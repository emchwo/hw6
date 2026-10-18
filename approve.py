"""Human approval desk for email and payment requests (design layer, Problem 6).

The agent can only FILE requests (output/pending_actions.json). This script is the only way to approve one,
and it only works for a person at a terminal:

    python approve.py list
    python approve.py show <request_id>
    python approve.py approve <request_id>
    python approve.py deny <request_id>

Approving re-checks the policy, checks the request was not edited since it was filed, warns if the request's
values were copied out of the vendor document, and asks the person to type the request id and their name.
"Carrying out" an approved request is simulated: it is written to output/outbox.json or output/payments.json.
Nothing is ever emailed or paid for real.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import defenses
import tools

OUTBOX = tools.OUTPUT_DIR / "outbox.json"
PAYMENTS = tools.OUTPUT_DIR / "payments.json"


class ApprovalRefused(Exception):
    pass


def _load() -> list[dict]:
    p = defenses.PENDING_PATH
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _save(data: list[dict]) -> None:
    defenses.PENDING_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _find(data: list[dict], request_id: str) -> dict:
    for r in data:
        if r["request_id"] == request_id:
            return r
    raise ApprovalRefused(f"No request {request_id}.")


def require_human() -> None:
    """The agent can never reach this: it has no tool that runs it, and it is refused inside the agent's process
    or without an interactive terminal."""
    if os.environ.get("VENDOR_DESK_AGENT_PROCESS") == "1":
        raise ApprovalRefused("Approvals cannot run inside the agent process.")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ApprovalRefused("Approvals need a person at an interactive terminal.")


def verify(req: dict) -> list[str]:
    """Everything that must be true before a human's yes counts."""
    problems = []
    if req["status"] != "awaiting_human_approval":
        problems.append(f"status is {req['status']}")
    if defenses.request_digest(req["action"], req["args"]) != req["digest"]:
        problems.append("request was edited after it was filed")
    problems += defenses.policy_problems(req["action"], req["args"], tools.handbook_rules())
    return problems


def show(req: dict) -> None:
    print(json.dumps({k: req[k] for k in ("request_id", "created", "action", "args", "document", "run_id",
                                          "copied_from_document", "policy_problems", "status")}, indent=2))


def approve(request_id: str) -> None:
    require_human()
    data = _load()
    req = _find(data, request_id)
    show(req)
    problems = verify(req)
    if problems:
        raise ApprovalRefused("Cannot approve: " + "; ".join(problems))
    if req["copied_from_document"]:
        print(f"\nWARNING: {', '.join(req['copied_from_document'])} came from the vendor document itself. "
              "Documents asking for emails or payments are a known attack. Confirm with the vendor by phone first.")
    typed = input(f"\nType the request id ({request_id}) to approve: ").strip()
    name = input("Your name: ").strip()
    if typed != request_id or not name:
        raise ApprovalRefused("Confirmation did not match. Nothing was approved.")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    req.update(status="executed_simulated", approved_by=name, approved_at=now)
    _save(data)
    record = {"request_id": request_id, "approved_by": name, "time": now, **req["args"],
              "note": "SIMULATED: nothing was actually sent or paid."}
    tools.append_json(OUTBOX if req["action"] == "send_email" else PAYMENTS, record)
    print(f"Approved by {name}. Recorded (simulated) in {(OUTBOX if req['action'] == 'send_email' else PAYMENTS).name}.")


def deny(request_id: str) -> None:
    require_human()
    data = _load()
    req = _find(data, request_id)
    req.update(status="denied_by_human", denied_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    _save(data)
    print(f"Denied {request_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Human approval desk for vendor desk requests.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("show", "approve", "deny"):
        sub.add_parser(name).add_argument("request_id")
    args = parser.parse_args()
    try:
        if args.cmd == "list":
            for r in _load():
                print(f"{r['request_id']}  {r['status']:24} {r['action']:16} {r['document']}  "
                      f"{'; '.join(r['policy_problems'])}")
        elif args.cmd == "show":
            show(_find(_load(), args.request_id))
        elif args.cmd == "approve":
            approve(args.request_id)
        else:
            deny(args.request_id)
    except ApprovalRefused as e:
        sys.exit(f"REFUSED: {e}")


if __name__ == "__main__":
    main()
