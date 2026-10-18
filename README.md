# HW 6 — Campus Customs Vendor Desk Agent

An AI agent (PydanticAI + `gpt-6-luna` via Portkey) that reads one vendor document at a time (HTML quote, PDF quote, catalog page, or `.eml` supplier email), pulls out the SKU, unit price, lead time and minimum order, and decides **recommend** or **do_not_recommend** using the rules in `data/shop_handbook.md`. It is built for low cost (prompt caching) and safety (three defense layers against booby-trapped documents).

## Results page

**Download `output/hw6_report.html` and open it in a browser. GitHub shows it as code.**

It's a single self-contained file. It works offline and needs no other files.

## Setup

Requires Python 3.11+ and a Portkey API key.

```bash
git clone <this repo URL>
cd <repo folder>
python -m venv .venv
```

Activate the virtual environment:
- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (Git Bash): `source .venv/Scripts/activate`
- macOS / Linux: `source .venv/bin/activate`

Then install the packages and add your key:

```bash
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and replace the placeholder with your own `PORTKEY_API_KEY`. The agent only ever uses `gpt-6-luna`.

## Run the agent

One run reviews one document and prints the answer as JSON:

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

Example output:

```json
{
  "vendor": "Blue Hen Apparel",
  "sku": "CC-HD-006",
  "unit_price": 21.8,
  "lead_time_days": 14,
  "min_order": 240,
  "decision": "recommend",
  "reason": "All four purchasing checks passed."
}
```

`--doc` accepts any `.html`, `.pdf` or `.eml` file under `data/`. For example:

```bash
python agent.py --doc data/exam_docs/e05_quote.pdf
python agent.py --doc data/practice_docs/p09_westville_email.eml
python agent.py --doc data/my_attacks/spanish_instruction_quote.html
```

### Options

| Flag | What it does |
|---|---|
| *(none)* | All three defense layers on (code, design, prompt) and prompt caching on. This is the normal mode. |
| `--unprotected` | **Test only.** Turns every defense layer off, to see what an attack does to an unprotected agent. `--raw` means the same. |
| `--layers code,prompt` | **Test only.** Keeps just the layers you list (`code`, `design`, `prompt`). |
| `--setup no_cache` | Turns prompt caching off (used for the Problem 4 cost comparison). |

### What every run writes

| File | Contents |
|---|---|
| `output/usage_log.json` | Token counts the API reported (input, cached, cache write, output) and dollar cost from `data/prices.json` |
| `output/audit_trail.json` | Every tool call with its arguments and a short result, any hidden or suspicious text removed, and the final answer |
| `output/trap_calls.json` | Any call to `send_email` or `approve_payment`. Nothing is ever really sent or paid. |

## Reproduce each problem's results

Each script calls the model and adds to the logs above.

| Command | Problem | Writes |
|---|---|---|
| `python cache_test.py` | 4: with vs without caching (24 runs) | `output/cache_test.json` |
| `python attack_test.py --raw` | 5: attacks on the unprotected agent (12 runs) | `output/attack_results.json` |
| `python defense_test.py` | 6: all defenses on (12 runs) | `output/defense_results.json` |
| `python red_team_test.py` | 7: the two red-team documents, unprotected and defended (4 runs) | `output/red_team_results.json` |
| `python exam_test.py` | 8: all 10 exam documents (10 runs) | `output/exam_results.json` |
| `python make_report.py` | 9: rebuild the results page from the JSON files (no model calls) | `output/hw6_report.html` |

`python defense_test.py --offline-only` runs the code-layer and design-layer checks with no model calls.

## Human approval desk

The agent can never send an email or make a payment. With the design layer on, `send_email` and `approve_payment` only file a request in `output/pending_actions.json`. A person approves or denies it at a terminal:

```bash
python approve.py list
python approve.py approve <request_id>
```

Approving is simulated: the result is written to `output/outbox.json` or `output/payments.json`, and nothing leaves the machine.

## Files

| Path | Purpose |
|---|---|
| `agent.py` | The agent, command-line options, logging, and post-run checks |
| `tools.py` | Document readers (HTML/PDF/EML), handbook rule checks, gated email/payment tools |
| `models.py` | Output schema (`VendorDecision`) and tool/run data shapes |
| `defenses.py` | Code-layer filters and design-layer request policy |
| `approve.py` | Human-only approval desk |
| `prompts/prompt.md` | Agent instructions, with safety rules. The handbook is appended on every call. |
| `prompts/prompt_v1.md` | The original prompt, used when the prompt layer is off |
| `data/` | Handbook, prices, practice docs + answer key, exam docs, and `my_attacks/` (the two red-team documents) |
| `output/` | All results and write-ups (`harness.md` explains the design and the Safety layers) |
| `AI_prompts.md` | The prompts used for each problem |
