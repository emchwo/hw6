"""Problem 4: run all 12 practice docs with and without prompt caching, save every model call.

Usage:
    python cache_test.py

Writes output/cache_test.json: one record per model call (setup, document, API-reported tokens, dollars
from data/prices.json), plus totals per setup. Each run also lands in usage_log.json / audit_trail.json
like any other agent run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import agent
import tools

PRACTICE_DIR = tools.DATA_DIR / "practice_docs"
KEY_PATH = tools.DATA_DIR / "practice_key.json"
OUT_PATH = tools.OUTPUT_DIR / "cache_test.json"
FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")

SETUP_NOTES = {
    "no_cache": "Random request id at the start of the instructions on every call, so no two calls share a "
                "prefix; explicit cache mode with no breakpoints. Nothing can be read from the cache.",
    "cache": "Identical instructions (prompt.md + handbook) on every call, stable prompt_cache_key, and a cache "
             "breakpoint after the instructions, so the handbook is reused from the cache.",
}


def main() -> None:
    key = {k["file"]: k for k in json.loads(KEY_PATH.read_text(encoding="utf-8"))}
    docs = sorted(PRACTICE_DIR.iterdir())
    calls, runs = [], []

    for setup in ("no_cache", "cache"):
        for doc in docs:
            answer, doc_calls = agent.run(doc, setup)
            expected = key[doc.name]
            mismatched = [f for f in FIELDS if getattr(answer, f) != expected[f]]
            runs.append({"setup": setup, "document": doc.name, "decision": answer.decision,
                         "matches_key": not mismatched, "mismatched_fields": mismatched})
            for c in doc_calls:
                calls.append({"setup": setup, "document": doc.name, **c})
            print(f"{setup:8} {doc.name:32} {answer.decision:17} calls={len(doc_calls)} "
                  f"cached={sum(c['tokens']['cached_input'] for c in doc_calls):>6} "
                  f"${sum(c['cost_usd']['total'] for c in doc_calls):.6f}")

    summary = {}
    for setup in ("no_cache", "cache"):
        rows = [c for c in calls if c["setup"] == setup]
        tok = {k: sum(c["tokens"][k] for c in rows)
               for k in ("input", "cached_input", "cache_write", "uncached_input", "output", "total")}
        cost = {k: round(sum(c["cost_usd"][k] for c in rows), 8)
                for k in ("uncached_input", "cached_input", "cache_write", "output", "total")}
        summary[setup] = {
            "documents": len(docs),
            "model_calls": len(rows),
            "tokens": tok,
            "cost_usd": cost,
            "cost_per_document_usd": round(cost["total"] / len(docs), 8),
            "calls_with_cached_tokens": sum(1 for c in rows if c["tokens"]["cached_input"] > 0),
            "decisions_matching_key": sum(1 for r in runs if r["setup"] == setup and r["matches_key"]),
        }
    ids = [c["response_id"] for c in calls]
    nc, ca = summary["no_cache"]["cost_usd"]["total"], summary["cache"]["cost_usd"]["total"]
    summary["comparison"] = {
        "savings_usd": round(nc - ca, 8),
        "savings_pct": round(100 * (nc - ca) / nc, 2) if nc else None,
        "no_cache_valid": summary["no_cache"]["calls_with_cached_tokens"] == 0,
        "all_response_ids_unique": len(ids) == len(set(ids)),
    }

    OUT_PATH.write_text(json.dumps({
        "problem": "Problem 4: With and without cached tokens",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": agent.MODEL_NAME,
        "prices_per_1m": agent.PRICES,
        "setups": SETUP_NOTES,
        "portkey_response_cache": "bypassed on every call (x-portkey-cache-force-refresh), so each call is a "
                                  "real model call; all_response_ids_unique confirms no replays",
        "summary": summary,
        "runs": runs,
        "calls": calls,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
