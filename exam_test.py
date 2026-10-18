"""Problem 8: run the agent (all defenses on) on every exam document.

Usage:
    python exam_test.py

Writes output/exam_results.json: one entry per exam file.
"""

from __future__ import annotations

import json

import agent
import tools

EXAM_DIR = tools.DATA_DIR / "exam_docs"
OUT_PATH = tools.OUTPUT_DIR / "exam_results.json"


def main() -> None:
    entries = []
    for doc in sorted(EXAM_DIR.iterdir()):
        answer, calls = agent.run(doc, "cache")  # default: all defense layers on
        run_id = json.loads(agent.AUDIT_LOG.read_text(encoding="utf-8"))[-1]["run_id"]
        traps = [t for t in json.loads(tools.TRAP_LOG.read_text(encoding="utf-8")) if t["run_id"] == run_id]
        entries.append({
            "file": doc.name,
            **answer.model_dump(include={"vendor", "sku", "unit_price", "lead_time_days", "min_order",
                                         "decision", "reason"}),
            "trap_tool_called": bool(traps),
            "input_tokens": sum(c["tokens"]["input"] for c in calls),
            "cached_tokens": sum(c["tokens"]["cached_input"] for c in calls),
            "output_tokens": sum(c["tokens"]["output"] for c in calls),
            "cost_usd": round(sum(c["cost_usd"]["total"] for c in calls), 8),
        })
        e = entries[-1]
        print(f"{e['file']:18} {e['vendor']:26} {e['sku']} ${e['unit_price']} {e['lead_time_days']}d "
              f"{e['min_order']}u {e['decision']:17} trap={e['trap_tool_called']} ${e['cost_usd']:.6f} | {e['reason']}")
    OUT_PATH.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
