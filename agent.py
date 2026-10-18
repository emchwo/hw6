"""Campus Customs vendor desk agent (PydanticAI + gpt-6-luna via Portkey).

Usage:
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html    # all defenses on (default)
    python agent.py --doc ... --unprotected                            # TEST ONLY: every defense off
    python agent.py --doc ... --layers code,prompt                     # TEST ONLY: pick layers

Defense layers (Problem 6), all on by default:
- code:   hidden-text filter, suspicious-sentence removal, facts parsed in code, answer cross-check,
          reason-number check, and the handbook post-check override.
- design: send_email / approve_payment can only file a request that a human approves with approve.py.
- prompt: prompts/prompt.md (with the Problem 5 lessons). Off = the original prompts/prompt_v1.md.

One run = one document. Every model call carries prompts/prompt.md + data/shop_handbook.md as the
instructions (identical prefix, so the provider can cache it). After each run:
- output/usage_log.json   gets token counts reported by the API and dollar costs from data/prices.json
- output/audit_trail.json gets every tool call (args + short result) and the final answer
- output/trap_calls.json  gets any send_email / approve_payment attempt (written by the trap tools)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry, RunContext, Tool
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

import defenses
import tools
from models import ALL_LAYERS, Deps, DocumentText, RuleCheck, TrapResult, VendorDecision

HW_DIR = tools.HW_DIR
PROMPT_PATHS = {True: HW_DIR / "prompts" / "prompt.md", False: HW_DIR / "prompts" / "prompt_v1.md"}
PRICES_PATH = tools.DATA_DIR / "prices.json"
USAGE_LOG = tools.OUTPUT_DIR / "usage_log.json"
AUDIT_LOG = tools.OUTPUT_DIR / "audit_trail.json"

# Only gpt-6-luna is allowed for this assignment. Deliberately not read from env or CLI.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

# Cost and runaway guards for one document.
LIMITS = UsageLimits(request_limit=6, tool_calls_limit=6, total_tokens_limit=80_000)
CACHE_KEY = "campus-customs-vendor-desk"

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
load_dotenv(HW_DIR / ".env")
load_dotenv(HW_DIR.parent / ".env")  # course root (AI Foundations/.env)
# approve.py refuses to run inside the agent's process, so the agent can never approve its own requests.
os.environ["VENDOR_DESK_AGENT_PROCESS"] = "1"


def build_instructions(prompt_layer: bool = True) -> str:
    prompt = PROMPT_PATHS[prompt_layer].read_text(encoding="utf-8").strip()
    handbook = tools.HANDBOOK_PATH.read_text(encoding="utf-8").strip()
    return f"{prompt}\n\n# Shop handbook (trusted)\n\n{handbook}"


def build_model() -> OpenAIResponsesModel:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        sys.exit("PORTKEY_API_KEY is not set. Add it to .env in HW 6 or its parent folder.")
    # The Portkey key has a response cache: an identical request gets the old response replayed, with the
    # old token counts. Force-refresh makes every call reach the model, so logged usage is always real.
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL,
                         default_headers={"x-portkey-provider": "openai",
                                          "x-portkey-cache-force-refresh": "true"})
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


INSTRUCTIONS = {True: build_instructions(True), False: build_instructions(False)}


def uncacheable_instructions(ctx: RunContext[Deps]) -> str:
    """no_cache setup: a fresh random id at the very start makes every call's prefix unique, so the
    provider never finds a cached prefix to reuse. PydanticAI re-runs this on every model call."""
    return f"Request id: {uuid.uuid4().hex}\n\n{INSTRUCTIONS['prompt' in ctx.deps.layers]}"


def read_document(ctx: RunContext[Deps]) -> DocumentText:
    """Read the vendor document assigned to this run and return its visible text (untrusted data)."""
    return tools.read_document(ctx.deps)


def check_purchasing_rules(
    vendor: str,
    sku: str | None,
    unit_price: float | None,
    lead_time_days: int | None,
    min_order: int | None,
) -> RuleCheck:
    """Run the four handbook section 4 checks (approved vendor, price, lead time, minimum order).
    Pass null for any value the document does not state."""
    return tools.check_purchasing_rules(vendor, sku, unit_price, lead_time_days, min_order)


def send_email(ctx: RunContext[Deps], to: str, subject: str, body: str) -> TrapResult:
    """Send an email to an outside party."""
    return tools.send_email(ctx.deps, to, subject, body)


def approve_payment(ctx: RunContext[Deps], vendor: str, amount: float, reference: str) -> TrapResult:
    """Approve a payment or deposit to a vendor."""
    return tools.approve_payment(ctx.deps, vendor, amount, reference)


def gated_send_email(ctx: RunContext[Deps], to: str, subject: str, body: str) -> TrapResult:
    """File a request to email someone. Nothing is sent: a person must approve it outside this agent, and only
    Campus Customs or approved-vendor order addresses are allowed. Not needed to review a document."""
    return tools.send_email(ctx.deps, to, subject, body)


def gated_approve_payment(ctx: RunContext[Deps], vendor: str, amount: float, reference: str) -> TrapResult:
    """File a request to pay an approved vendor. Nothing is paid: a person must approve it outside this agent.
    Not needed to review a document."""
    return tools.approve_payment(ctx.deps, vendor, amount, reference)


BASE_TOOLS = [Tool(read_document, takes_ctx=True), Tool(check_purchasing_rules, takes_ctx=False)]
TOOLS = {  # design layer on -> gated request tools; off -> the Problem 3 trap tools
    True: BASE_TOOLS + [Tool(gated_send_email, takes_ctx=True, name="send_email"),
                        Tool(gated_approve_payment, takes_ctx=True, name="approve_payment")],
    False: BASE_TOOLS + [Tool(send_email, takes_ctx=True), Tool(approve_payment, takes_ctx=True)],
}


def allowed_reason_numbers(answer: VendorDecision) -> set[float]:
    nums = {float(tools.MAX_LEAD_TIME_DAYS), float(tools.MAX_MIN_ORDER), 4.0}
    nums |= {float(v) for v in (answer.unit_price, answer.lead_time_days, answer.min_order) if v is not None}
    if answer.sku:
        nums.add(float(answer.sku[-3:]))
    return nums


def check_reason(ctx: RunContext[Deps], answer: VendorDecision) -> VendorDecision:
    """Code layer: the reason may only cite the answer's own values and the handbook limits. This stops a
    value planted in the document (e.g. a fake 'corrected' lead time) from reaching the buyer."""
    if "code" in ctx.deps.layers:
        bad = defenses.reason_numbers_ok(answer.reason, allowed_reason_numbers(answer))
        if bad:
            raise ModelRetry(f"The reason mentions {', '.join(bad)}, which is not one of your extracted values or "
                             "a handbook limit. Rewrite the reason using only those.")
    return answer

# Two setups, same model, prompt, handbook and tools (Problem 4).
# - cache:    identical instructions (prompt + handbook) on every call, a stable prompt_cache_key, and a cache
#             breakpoint right after the instructions, so every call can reuse the handbook from the cache.
# - no_cache: a random id leads the instructions on every call (see uncacheable_instructions), and explicit
#             cache mode with no breakpoints. The provider still reports cache writes; it never gets a read.
SETUPS = {
    "cache": OpenAIResponsesModelSettings(
        openai_prompt_cache_key=CACHE_KEY,
        openai_cache_instructions=True,
    ),
    "no_cache": OpenAIResponsesModelSettings(
        openai_prompt_cache_options={"mode": "explicit"},
    ),
}

_agents: dict[tuple, Agent] = {}


def get_agent(setup: str = "cache", layers: frozenset[str] = ALL_LAYERS) -> Agent[Deps, VendorDecision]:
    prompt_on, design_on = "prompt" in layers, "design" in layers
    key = (setup, prompt_on, design_on)
    if key not in _agents:
        agent = Agent(
            build_model(),
            deps_type=Deps,
            output_type=VendorDecision,
            instructions=INSTRUCTIONS[prompt_on] if setup == "cache" else uncacheable_instructions,
            model_settings=SETUPS[setup],
            tools=TOOLS[design_on],
            retries=2,
        )
        agent.output_validator(check_reason)
        _agents[key] = agent
    return _agents[key]


# --------------------------------------------------------------------------- #
# Logging helpers
# --------------------------------------------------------------------------- #

def _short_result(tool: str, content) -> str:
    if isinstance(content, DocumentText):
        return (f"{content.file_type}, {len(content.visible_text)} visible chars, "
                f"{content.hidden_items_removed} hidden item(s) removed, "
                f"{content.suspicious_items_removed} suspicious sentence(s) removed")
    if isinstance(content, RuleCheck):
        failed = ", ".join(content.failed_checks) or "none"
        return f"{content.decision} (failed: {failed})"
    if isinstance(content, TrapResult):
        return "BLOCKED and logged to trap_calls.json" + (
            f"; {content.message.split('.')[1].strip()}" if content.message.startswith("Not done") else "")
    text = content if isinstance(content, str) else json.dumps(content, default=str)
    return text[:200]


def tool_calls_from(messages) -> list[dict]:
    calls: dict[str, dict] = {}
    order: list[str] = []
    for msg in messages:
        for part in msg.parts:
            if isinstance(msg, ModelResponse) and isinstance(part, ToolCallPart):
                calls[part.tool_call_id] = {"tool": part.tool_name, "args": part.args_as_dict(), "result": None}
                order.append(part.tool_call_id)
            elif isinstance(msg, ModelRequest) and isinstance(part, ToolReturnPart):
                if part.tool_call_id in calls:
                    calls[part.tool_call_id]["result"] = _short_result(part.tool_name, part.content)
    # The final_result call is PydanticAI's structured-output step; the answer is logged separately.
    return [calls[i] for i in order if calls[i]["tool"] != "final_result"]


PRICES = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_NAME]


def token_cost(input_tokens: int, cached: int, written: int, output: int) -> tuple[dict, dict]:
    """Split API-reported tokens into billed buckets and price each with data/prices.json."""
    cached, written = cached or 0, written or 0
    uncached = input_tokens - cached - written
    tokens = {"input": input_tokens, "cached_input": cached, "cache_write": written,
              "uncached_input": uncached, "output": output, "total": input_tokens + output}
    costs = {
        "uncached_input": uncached * PRICES["input_per_1m"] / 1e6,
        "cached_input": cached * PRICES["cached_input_per_1m"] / 1e6,
        "cache_write": written * PRICES["cache_write_per_1m"] / 1e6,
        "output": output * PRICES["output_per_1m"] / 1e6,
    }
    costs["total"] = sum(costs.values())
    return tokens, {k: round(v, 8) for k, v in costs.items()}


def per_call_usage(messages) -> list[dict]:
    """One entry per model call, with the usage the API reported for that call."""
    calls = []
    for msg in messages:
        if not isinstance(msg, ModelResponse):
            continue
        u = msg.usage
        tokens, costs = token_cost(u.input_tokens, u.cache_read_tokens, u.cache_write_tokens, u.output_tokens)
        tokens["details"] = dict(u.details or {})
        tool_names = [p.tool_name for p in msg.parts if isinstance(p, ToolCallPart)]
        calls.append({
            "call": len(calls) + 1,
            "response_id": msg.provider_response_id,
            "model": msg.model_name,
            "requested": ", ".join(tool_names) or "text",
            "tokens": tokens,
            "cost_usd": costs,
        })
    return calls


def usage_record(doc: Path, usage, started: str, setup: str, layers: frozenset[str] = ALL_LAYERS) -> dict:
    tokens, costs = token_cost(usage.input_tokens, usage.cache_read_tokens,
                               usage.cache_write_tokens, usage.output_tokens)
    tokens["details"] = dict(usage.details or {})
    return {
        "document": str(doc.relative_to(HW_DIR)).replace("\\", "/"),
        "time": started,
        "model": MODEL_NAME,
        "setup": setup,
        "layers": sorted(layers),
        "requests": usage.requests,
        "tokens": tokens,
        "cost_usd": costs,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def resolve_doc(arg: str) -> Path:
    path = Path(arg)
    if not path.is_absolute():
        path = (Path.cwd() / path) if (Path.cwd() / path).exists() else (HW_DIR / path)
    path = path.resolve()
    if not path.is_file():
        sys.exit(f"Document not found: {arg}")
    if not path.is_relative_to(tools.DATA_DIR):
        sys.exit("Documents must live under HW 6/data/.")
    if path.suffix.lower() not in tools.ALLOWED_TYPES:
        sys.exit(f"Unsupported file type {path.suffix}. Use .html, .pdf, or .eml.")
    return path


def rejected_answers(messages) -> list[dict]:
    """Final answers the output validators rejected (the model was asked to retry)."""
    attempts = [p for m in messages if isinstance(m, ModelResponse)
                for p in m.parts if isinstance(p, ToolCallPart) and p.tool_name == "final_result"]
    return [p.args_as_dict() for p in attempts[:-1]]


def cross_check_facts(answer: VendorDecision, facts: dict) -> tuple[VendorDecision, list[dict]]:
    """Code layer: where the document has exactly one labeled value for a field, the answer must use it."""
    fixes = []
    for field in ("sku", "unit_price", "lead_time_days", "min_order"):
        if field in facts and getattr(answer, field) != facts[field]:
            fixes.append({"field": field, "model": getattr(answer, field), "labeled": facts[field]})
    if fixes:
        answer = answer.model_copy(update={f["field"]: f["labeled"] for f in fixes})
    return answer, fixes


def run(doc: Path, setup: str = "cache", raw: bool = False,
        layers: frozenset[str] | None = None) -> tuple[VendorDecision, list[dict]]:
    """Review one document. Returns the final answer and the per-call usage.

    layers = which defense layers are on (default: all). raw=True is the Problem 5 name for unprotected
    mode (TEST ONLY): no layers, so the model reads every hidden attack and nothing corrects its answer.
    The answer schema checks (no links, one sentence) and the trap log are always on."""
    if layers is None:
        layers = frozenset() if raw else ALL_LAYERS
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    deps = Deps(doc_path=doc, run_id=uuid.uuid4().hex[:12], layers=frozenset(layers))

    result = get_agent(setup, deps.layers).run_sync(
        "Review the vendor document assigned to this run and return your decision.",
        deps=deps,
        usage_limits=LIMITS,
    )
    answer: VendorDecision = result.output
    usage = result.usage() if callable(result.usage) else result.usage

    code_on = "code" in deps.layers
    fact_fixes = []
    if code_on:
        answer, fact_fixes = cross_check_facts(answer, deps.labeled_facts)

    # Safety net: the decision must match the handbook checks run in code on the reported facts.
    rules = tools.check_purchasing_rules(answer.vendor, answer.sku, answer.unit_price,
                                         answer.lead_time_days, answer.min_order)
    post_check = {"agreed": rules.decision == answer.decision and not fact_fixes,
                  "rules_decision": rules.decision, "failed_checks": rules.failed_checks,
                  "fact_fixes": fact_fixes}
    if rules.decision != answer.decision and not code_on:
        post_check["would_override_to"] = rules.decision
    elif rules.decision != answer.decision:
        post_check["model_decision"] = answer.decision
        answer = answer.model_copy(update={
            "decision": rules.decision,
            "reason": "Overridden by handbook check: " + "; ".join(
                c.detail for c in rules.checks if not c.passed) + "." if rules.failed_checks
            else "Overridden by handbook check: all four purchasing checks passed.",
        })

    tools.append_json(USAGE_LOG, usage_record(doc, usage, started, setup, deps.layers))
    tools.append_json(AUDIT_LOG, {
        "run_id": deps.run_id,
        "time": started,
        "document": str(doc.relative_to(HW_DIR)).replace("\\", "/"),
        "model": MODEL_NAME,
        "setup": setup,
        "layers": sorted(deps.layers),
        "raw_mode": not deps.layers,
        "tool_calls": tool_calls_from(result.all_messages()),
        "rejected_answers": rejected_answers(result.all_messages()),
        "hidden_content_removed": deps.hidden_content,
        "suspicious_sentences": deps.suspicious,
        "labeled_facts": deps.labeled_facts,
        "trap_calls": len(deps.trap_hits),
        "action_requests": [{k: r[k] for k in ("request_id", "action", "status", "policy_problems",
                                               "copied_from_document")} for r in deps.action_requests],
        "post_check": post_check,
        "final_answer": answer.model_dump(),
    })
    return answer, per_call_usage(result.all_messages())


def parse_layers(spec: str | None, unprotected: bool = False) -> frozenset[str]:
    if unprotected:
        return frozenset()
    if spec is None:
        return ALL_LAYERS
    layers = frozenset(x.strip().lower() for x in spec.split(",") if x.strip() and x.strip().lower() != "none")
    unknown = layers - ALL_LAYERS
    if unknown:
        sys.exit(f"Unknown layer(s): {', '.join(sorted(unknown))}. Use code, design, prompt, or none.")
    return layers


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent (gpt-6-luna).")
    parser.add_argument("--doc", required=True, help="Path to one vendor document (.html, .pdf, .eml)")
    parser.add_argument("--setup", choices=sorted(SETUPS), default="cache",
                        help="cache (default) reuses the handbook from the prompt cache; no_cache disables it")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--unprotected", "--raw", dest="unprotected", action="store_true",
                      help="TEST ONLY: turn every defense layer off (attack testing)")
    mode.add_argument("--layers", default=None,
                      help="TEST ONLY: comma list of layers to keep on (code,design,prompt). Default: all")
    args = parser.parse_args()
    layers = parse_layers(args.layers, args.unprotected)
    if layers != ALL_LAYERS:
        print(f"WARNING: test mode, defenses off: {', '.join(sorted(ALL_LAYERS - layers))}", file=sys.stderr)
    answer, _ = run(resolve_doc(args.doc), args.setup, layers=layers)
    print(json.dumps(answer.model_dump(), indent=2))


if __name__ == "__main__":
    main()
