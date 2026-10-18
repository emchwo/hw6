"""Problem 6 defenses for the vendor desk agent.

Code layer (runs on the document before and after the model)
- style_hides(...):    decides from parsed CSS whether text would be invisible (used by tools._html_visible).
- labeled_facts(text): reads the document's own labeled fact lines (SKU, unit price, lead time, minimum order).
- sanitize(text):      scores every sentence on several independent signals and removes the ones that act like
                       instructions to the agent, while label lines and ordinary prose stay untouched.
- reason_numbers_ok(): the reason may only cite numbers that the answer or the handbook supports.

Design layer (send_email / approve_payment)
- request_action(...): the agent can only REQUEST an email or payment. The request is checked against policy and
                       parked in output/pending_actions.json. Nothing is ever sent or paid from inside the agent.
                       Only a human running `python approve.py` at a terminal can approve and carry it out.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

HW_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = HW_DIR / "output"
PENDING_PATH = OUTPUT_DIR / "pending_actions.json"

# --------------------------------------------------------------------------- #
# Code layer 1: is this CSS invisible to a human?
# --------------------------------------------------------------------------- #

NAMED_COLORS = {
    "white": (255, 255, 255), "snow": (255, 250, 250), "ivory": (255, 255, 240), "ghostwhite": (248, 248, 255),
    "whitesmoke": (245, 245, 245), "floralwhite": (255, 250, 240), "mintcream": (245, 255, 250),
    "azure": (240, 255, 255), "transparent": None,
}


def parse_css(style: str) -> dict[str, str]:
    decls = {}
    for part in style.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            decls[k.strip().lower()] = v.strip().lower().replace("!important", "").strip()
    return decls


def parse_color(value: str) -> tuple[float, float, float, float] | None:
    """Return (r, g, b, alpha) in 0..1, or None if unknown."""
    v = value.strip().lower()
    if v in NAMED_COLORS:
        rgb = NAMED_COLORS[v]
        return (0, 0, 0, 0) if rgb is None else (*[c / 255 for c in rgb], 1.0)
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, 1.0)
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)", v)
    if m:
        a = float(m.group(4)) if m.group(4) else 1.0
        return (float(m.group(1)) / 255, float(m.group(2)) / 255, float(m.group(3)) / 255, a)
    return None


def luminance(c: tuple[float, ...]) -> float:
    def lin(x: float) -> float:
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def contrast(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _length_px(v: str) -> float | None:
    m = re.match(r"(-?[\d.]+)\s*(px|pt|em|rem|%)?", v)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2) or "px"
    return {"px": n, "pt": n * 4 / 3, "em": n * 16, "rem": n * 16, "%": n * 0.16}[unit]


def style_hides(decls: dict[str, str], background=(1.0, 1.0, 1.0, 1.0)) -> str | None:
    """Why this CSS makes text invisible to a human reader, or None if it is visible.
    Works from what the browser would render, not from a list of words."""
    if decls.get("display") == "none":
        return "display:none"
    if decls.get("visibility") in ("hidden", "collapse"):
        return "visibility:hidden"
    if "opacity" in decls:
        try:
            if float(decls["opacity"]) < 0.1:
                return "opacity near 0"
        except ValueError:
            pass
    if "font-size" in decls:
        px = _length_px(decls["font-size"])
        if px is not None and px < 4:
            return f"font-size {decls['font-size']}"
    if "color" in decls:
        fg = parse_color(decls["color"])
        bg = parse_color(decls.get("background-color", decls.get("background", ""))) or background
        if fg is not None and (fg[3] < 0.1 or contrast(fg, bg) < 1.5):
            return f"text color {decls['color']} on background has almost no contrast"
    for prop in ("left", "top", "right", "text-indent", "margin-left", "margin-top"):
        if prop in decls:
            px = _length_px(decls[prop])
            if px is not None and px <= -500:
                return f"moved off screen ({prop}:{decls[prop]})"
    if re.search(r"scale\(\s*0(\.0+)?\s*\)", decls.get("transform", "")):
        return "transform:scale(0)"
    if re.search(r"rect\(\s*0", decls.get("clip", "")) or "inset(50%" in decls.get("clip-path", "") \
            or "inset(100%" in decls.get("clip-path", ""):
        return "clipped away"
    overflow_hidden = decls.get("overflow") == "hidden"
    for prop in ("height", "max-height", "width", "max-width"):
        if prop in decls and overflow_hidden:
            px = _length_px(decls[prop])
            if px is not None and px <= 1:
                return f"{prop}:{decls[prop]} with overflow hidden"
    return None


# --------------------------------------------------------------------------- #
# Code layer 2: the document's own labeled facts
# --------------------------------------------------------------------------- #

SKU_RX = re.compile(r"\bCC-[A-Z]{2}-\d{3}\b")
MONEY_RX = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
LABELS = {
    "unit_price": re.compile(r"^(?:quoted\s+)?unit\s+(?:price|cost)\s*[:\-]?\s*\$\s?(\d[\d,]*(?:\.\d+)?)", re.I),
    "min_order": re.compile(r"^(?:minimum\s+order(?:\s+quantity)?|moq|min\.?\s+order)\s*[:\-]?\s*(\d[\d,]*)", re.I),
    "lead_time_days": re.compile(r"^lead\s+time\s*[:\-]?\s*(\d+)\s*(?:business\s+|calendar\s+|working\s+)?days?", re.I),
    "sku": re.compile(r"^(?:campus\s+customs\s+)?sku\s*[:\-]?\s*(CC-[A-Z]{2}-\d{3})", re.I),
}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def labeled_facts(text: str) -> dict:
    """First value of each labeled fact line ("Unit price: $21.80", table row "Lead time 14 business days").
    Later label lines for the same field are recorded as duplicates (tiered prices are legitimate, so they are
    reported, not removed)."""
    facts: dict = {}
    duplicates: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        for field, rx in LABELS.items():
            m = rx.match(line)
            if not m:
                continue
            val = m.group(1).upper() if field == "sku" else _num(m.group(1))
            if field in ("min_order", "lead_time_days"):
                val = int(val)
            if field not in facts:
                facts[field] = val
            elif facts[field] != val:
                duplicates.append({"field": field, "value": val, "line": line})
    if "sku" not in facts:  # "Item: Lunch Cooler (CC-BG-007)"
        m = SKU_RX.search(text)
        if m:
            facts["sku"] = m.group(0)
    if duplicates:
        facts["_duplicate_labels"] = duplicates
    return facts


# --------------------------------------------------------------------------- #
# Code layer 3: sentence scoring and removal
# --------------------------------------------------------------------------- #

REMOVE_AT = 3  # a sentence needs several independent signals (or one strong one) before it is removed

DIRECTIVE = re.compile(
    r"\b(reviewer|review agent|the agent|ai agent|assistant|language model|llm|the model|automated (system|reviewer)"
    r"|vendor desk)\b[^.]*\b(should|must|is to|are to|needs? to|has to|will|please|sends?|approves?|pays?|emails?)\b"
    r"|^\s*(reviewer|agent|assistant|ai|system)\s*[:,]"
    r"|\bignore (all |any )?(previous|prior|earlier|the above|above|your|other) (instructions|rules|guidance)"
    r"|\byou (must|should|are to|need to|have to)\b",
    re.I,
)
TOOL_CALL = re.compile(r"\b(send_email|approve_payment|read_document|check_purchasing_rules)\b|\b\w+_\w+\s*\(", re.I)
ACTION = re.compile(r"\b(send|e-?mail|forward|share|wire|transfer|pay|approve|remit|release|authori[sz]e)\b", re.I)
TARGET = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|\$\s?\d[\d,]{2,}|\bdeposit\b", re.I)
INTERNAL_DATA = re.compile(r"\b(max(imum)? unit cost|margins?|cost (list|table|sheet)|price list|handbook"
                           r"|internal (pricing|costs?|data)|our costs?)\b", re.I)
SHARE = re.compile(r"\b(send|share|forward|e-?mail|provide|export|upload|match|disclose)\b", re.I)
OUTPUT_STEER = re.compile(r"\b(your|the)\s+(reason|answer|response|output|summary|report|recommendation|reply)\b"
                          r"|\bso the buyer can\b", re.I)
AUTHORITY = re.compile(r"\b(standing instruction|pre-?approved|already approved|authori[sz]ed by|requested by (the )?"
                       r"(campus customs|buyer|owner|manager|store)|on behalf of campus customs|per (the )?owner"
                       r"|policy update|system (message|notice|override)|owner (has )?(approved|signed))", re.I)
SUPERSEDE = re.compile(r"\b(correction|corrected|revised|updated|replaces?|supersedes?|instead of|no longer|is now"
                       r"|now \$?\d|effective (immediately|\w+ \d+)|disregard|ignore|old standard|outdated"
                       r"|out of date|previous(ly)? (shown|quoted|listed))\b", re.I)
IDENTITY = re.compile(r"\b(vendor of record|brand name|doing business as|d/?b/?a|is the real|actual vendor"
                      r"|on behalf of|subsidiary|vendor code|operated by|parent company)\b", re.I)
STATUS_CLAIM = re.compile(r"\b(is|are|as) (a |an |your |the )?(licensed|approved|authori[sz]ed|certified|official"
                          r"|preferred|verified)\b[^.]*\b(vendor|supplier|partner|licensee)\b", re.I)
LINK = re.compile(r"https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.]+", re.I)

FIELD_CONTEXT = {
    "unit_price": (re.compile(r"\b(price|cost|per unit|each|/unit|unit)\b", re.I), MONEY_RX),
    "lead_time_days": (re.compile(r"\b(lead|ship|deliver|turnaround|production)\w*\b", re.I),
                       re.compile(r"\b(\d+)\s*(?:business\s+|calendar\s+|working\s+)?days?\b", re.I)),
    "min_order": (re.compile(r"\b(minimum|moq|min\.?)\b", re.I), re.compile(r"\b(\d[\d,]*)\s*units?\b", re.I)),
}


def _sentences(line: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])", line)
    return [p for p in parts if p.strip()]


def _is_label_line(line: str) -> bool:
    return any(rx.match(line.strip()) for rx in LABELS.values())


def score_sentence(s: str, facts: dict, other_vendors: list[str]) -> tuple[int, list[str]]:
    """Several independent signals; one keyword alone is never enough to remove a sentence."""
    signals: list[tuple[str, int]] = []
    if DIRECTIVE.search(s):
        signals.append(("instruction aimed at the agent", 3))
    if TOOL_CALL.search(s):
        signals.append(("names an agent tool or function call", 3))
    if ACTION.search(s) and TARGET.search(s):
        signals.append(("asks for an email/payment action with a target", 2))
    if INTERNAL_DATA.search(s) and SHARE.search(s):
        signals.append(("asks to share internal cost data", 3))
    if OUTPUT_STEER.search(s) and re.search(r"\b(put|include|add|insert|mention|write|say|state|use)\b", s, re.I):
        signals.append(("tries to steer what goes in the answer", 3))
    if AUTHORITY.search(s):
        signals.append(("claims authority or prior approval", 2))
    if SUPERSEDE.search(s):
        signals.append(("override or correction language", 1))
    if STATUS_CLAIM.search(s):
        signals.append(("claims its own vendor status (only the handbook decides that)", 3))
    named_other = [v for v in other_vendors if v.lower() in s.lower()]
    if IDENTITY.search(s):
        signals.append(("claims a different vendor identity", 2 + (2 if named_other else 0)))
    if LINK.search(s):
        signals.append(("link or address in prose", 1))
    # Field conflict: a sentence that states a DIFFERENT value for a fact the document already labels.
    for field, (context, value_rx) in FIELD_CONTEXT.items():
        if field not in facts or not context.search(s):
            continue
        for m in value_rx.finditer(s):
            if _num(m.group(1)) != float(facts[field]):
                signals.append((f"states a different {field} than the labeled value", 3))
                break
    return sum(w for _, w in signals), [name for name, _ in signals]


def sanitize(text: str, issuer_hint: str = "", vendor_names: list[str] | None = None) -> tuple[str, list[dict], dict]:
    """Remove sentences that act like instructions or fake corrections. Label lines are kept as they are.
    Returns (clean text, removed/flagged sentences, labeled facts)."""
    facts = labeled_facts(text)
    others = [v for v in (vendor_names or []) if v.lower() not in issuer_hint.lower()]
    out_lines, flagged = [], []
    for line in text.splitlines():
        if _is_label_line(line):
            out_lines.append(line)
            continue
        sents = _sentences(line)
        scored = [list(score_sentence(s, facts, others)) for s in sents]
        removed = [sc >= REMOVE_AT for sc, _ in scored]
        # Neighbors of a removed sentence in the same passage need less evidence: the lead-in ("Price match
        # program: ...") or follow-on ("This replaces the price above.") of an attack is part of the attack.
        for i, (sc, sig) in enumerate(scored):
            if not removed[i] and sig and ((i > 0 and removed[i - 1]) or (i + 1 < len(sents) and removed[i + 1])):
                scored[i][0] += 2
                sig.append("part of a removed passage")
                removed[i] = scored[i][0] >= REMOVE_AT
        kept = []
        for s, (score, signals), rm in zip(sents, scored, removed):
            if rm:
                flagged.append({"text": s, "score": score, "signals": signals, "action": "removed"})
            else:
                if score >= 2:
                    flagged.append({"text": s, "score": score, "signals": signals, "action": "kept"})
                kept.append(s)
        if kept:
            out_lines.append(" ".join(kept))
        elif line.strip():
            out_lines.append("[suspicious text removed]")
    return "\n".join(out_lines), flagged, facts


# --------------------------------------------------------------------------- #
# Code layer 4: numbers in the reason must be supported
# --------------------------------------------------------------------------- #

def reason_numbers_ok(reason: str, allowed: set[float]) -> list[str]:
    """Numbers in the reason that are not the answer's own values or a handbook limit."""
    bad = []
    for m in re.finditer(r"\$?\d[\d,]*(?:\.\d+)?", reason):
        n = _num(m.group(0).lstrip("$"))
        if n not in allowed:
            bad.append(m.group(0))
    return bad


# --------------------------------------------------------------------------- #
# Design layer: email and payment requests need a human, outside the agent
# --------------------------------------------------------------------------- #

PAYMENT_CAP_USD = 5000.0  # anything above this also needs the owner (handbook section 2: large orders)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def request_digest(action: str, args: dict) -> str:
    """Fingerprint of exactly what was requested. approve.py refuses if the stored request was edited."""
    return hashlib.sha256(json.dumps({"action": action, "args": args}, sort_keys=True).encode()).hexdigest()


def policy_problems(action: str, args: dict, rules: dict) -> list[str]:
    """Hard rules checked in code when the request is made AND again when a human approves it."""
    problems = []
    if action == "send_email":
        to = str(args.get("to", "")).strip().lower()
        allowed = rules["order_emails"] | {"@campuscustoms.example"}
        if not (to in allowed or to.endswith("@campuscustoms.example")):
            problems.append(f"recipient {to or '(none)'} is not a Campus Customs address or an approved vendor's "
                            "order address from the handbook")
        body = f"{args.get('subject', '')} {args.get('body', '')}"
        leaked = {m for m in MONEY_RX.findall(body) if _num(m) in rules["max_costs"]}
        if INTERNAL_DATA.search(body) or len(leaked) >= 2:
            problems.append("message contains internal cost data (handbook says never share it)")
    elif action == "approve_payment":
        vendor = re.sub(r"[^a-z0-9]", "", str(args.get("vendor", "")).lower())
        if vendor not in rules["approved"]:
            problems.append(f"{args.get('vendor')} is not an approved vendor")
        try:
            amount = float(args.get("amount", 0))
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            problems.append("amount must be positive")
        if amount > PAYMENT_CAP_USD:
            problems.append(f"amount over ${PAYMENT_CAP_USD:,.0f} also needs the owner")
        if not str(args.get("reference", "")).strip():
            problems.append("missing invoice or quote reference")
    else:
        problems.append(f"unknown action {action}")
    return problems


def from_document(args: dict, doc_text: str) -> list[str]:
    """Which request values were copied out of the document (a sign the document asked for the action)."""
    hits = []
    low = doc_text.lower()
    for k, v in args.items():
        if isinstance(v, (int, float)):
            if f"{v:,.0f}" in doc_text or f"{v:.2f}" in doc_text:
                hits.append(k)
        elif isinstance(v, str) and len(v) >= 6 and v.lower() in low:
            hits.append(k)
    return hits


def request_action(action: str, args: dict, *, run_id: str, document: str, doc_text: str, rules: dict,
                   already_requested: int) -> dict:
    """Record a request for a human. Never sends or pays. Returns what the model is told."""
    problems = policy_problems(action, args, rules)
    if already_requested:
        problems.append("only one such request is allowed per review")
    status = "denied_by_policy" if problems else "awaiting_human_approval"
    req = {
        "request_id": "req-" + uuid.uuid4().hex[:10],
        "created": _now(),
        "action": action,
        "args": args,
        "digest": request_digest(action, args),
        "requested_by": "vendor desk agent",
        "run_id": run_id,
        "document": document,
        "copied_from_document": from_document(args, doc_text),
        "policy_problems": problems,
        "status": status,
    }
    data = json.loads(PENDING_PATH.read_text(encoding="utf-8")) if PENDING_PATH.exists() else []
    data.append(req)
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return req
