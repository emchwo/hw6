# HW 6 — AI Prompts

<!--
Section format:

## Problem N: Title

**Initial prompt:**
> ...

**Follow-up prompt:**
> ...

**What the initial prompt lacked:** One sentence.
-->

## Problem 1: Vibe coder prompts

**Initial prompt:**
> create AI_prompts.md and keep it updated as we work. create a section for each problem. within each section, create subsections for the problem number and title, at least one prompt i typed, and one follow-up prompt if needed with a sentence on what was lacking
>
> this is similar to the other AI_prompts.md that you've made for the other homeworks

**Follow-up prompt:**
_None._

**What the initial prompt lacked:** Nothing critical, since it pointed to the earlier HW logs for the format, so no follow-up was needed.

## Problem 2: Size up the handbook

**Initial prompt:**
> unzip this attached zip file and assess the content so that you can find out how many tokens the handbook is. then create output/handbook_estimate.md and complete the following:
>
> * the token count and how it was obtained
> * what the handbook alone costs on one call, and on 1000 calls, with cached tokens, and without them. show the calculations behind each one.
>
> we'll check these estimates with the real runs in Problem 4 later

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._

## Problem 3: Build the vendor desk agent

**Initial prompt:**
> build the agent with pydanticAI using gpt-6-luna. the agent consists of:
>
> 1. prompts/prompt.md - instructions for the agent, and the agent will send the handbook to the model on every call
> 2. agent. py
> 3. tools.py
> 4. models.py
>
> the agent will have a set path to one vendor document. it will read the document with a tool (the files will be html, pdf, or eml files), return with SKU, unit price, lead time in days, minimum order, decision (recommend or do_not_recommend) in accordance with the handbook rules, and a one-sentence reason
>
> so create tools that can do that. also create trap tools, send_email and approve_payment. these will catch malicious documents that are trying to trick the agent into emailing someone or paying a vendor. these tools do not send anything though, they just append the call and its arguments to output/trap_calls.json.
>
> after every run, append to output/usage_log.json with the document, time, token counts the API reports, and the dollar costs using prices.json
>
> also append to output/audit_trail.json after every run, showing each tool call with its arguments and a short result, plus the final answer
>
> make sure it runs like this in the terminal: python agent.py --doc data/practice_docs/p01_bluehen_quote.html
>
> run it on p01 and p08 to show it works. then create output/harness.md and list out each field in models.py and why, and then each tool in one line

**Follow-up prompt:**
_None yet._

**What the initial prompt lacked:** _TBD after any follow-up._

## Problem 4: With and without cached tokens

**Initial prompt:**
> the model can reuse the handbook from a cache at a cheaper price, so let's test what that is worth. run the agent on all 12 practice docs with 2 methods - with cache, set up so that the handbook is reused, and without cache, set up so nothing gets reused from the cache
>
> tell me the token counts the API sends back for each method. a without cache run that shows cached tokens doesn't count so make sure nothing is reused from the cache for that one
>
> save every model call for both methods to output/cache_test.json. for each call, use prices.json for the setup, document, token count the API reports, dollars

**Follow-up prompt:**
> writing in output/cache_test.md, please summarize:
>
> 1. the total cost and cost per document for each method, and the percent that was saved.
> 2. how real numbers compared to the estimates from Problem 2
> 3. projection for 1000 documents a day, for 30 days, with and without cache
> 4. surprising findings from the run and why it happens - for me this was that caching saved by as much as 88%

**What the initial prompt lacked:** It asked for the runs and raw per-call data but not a written summary, so the cost comparison, the check against the Problem 2 estimates, the 30-day projection, and the findings had to be requested in a follow-up.

## Problem 5: Attack your own agent

**Initial prompt:**
> run the agent on all 12 docs in data/practice_docs/, then compare each answer to data/practice_key.json and refer to output/trap_calls.json which should catch any fakes.
>
> then, save output/attack_results.json and make sure it includes for each document - if each field matched the key, if the decision was the same, if a trap tool was called, and if a link or other strange text showed up in the answer

**Follow-up prompt:**
> redo the attack but in a test-only --raw mode, for the sake of the assignment. run the agent on all 12 docs in data/practice_docs/, then compare each answer to data/practice_key.json and refer to output/trap_calls.json which should catch any fakes.
>
> then, save output/attack_results.json and make sure it includes for each document - if each field matched the key, if the decision was the same, if a trap tool was called, and if a link or other strange text showed up in the answer

**What the initial prompt lacked:** It didn't say to turn off the hidden-text filter built in Problem 3, so the model never saw the attacks, and a test-only raw mode was needed to show how the model itself responds to them.

## Problem 6: Defend your agent

**Initial prompt:**
> let's create defense mechanisms for the agent. after reading my suggestions, feel free to enhance these defenses even further. the mechanisms can be categorized as 3 diff levels:
>
> * code: look for suspicious patterns and instructions, white text or small font traps, flag and remove any malicious language found while preserving legitimate information and text. don't just rely on keyword filtering.
> * design: ensure that send_email is only sending human authorized emails, and approve_payment is only ever done with valid human authorization/approval. never ever allow a document to grant itself permission or to bypass these checks.
> * prompt: follow all the safety rules in prompt.md, adding additional rules as you learn from attacks.
>
> implement all of those plus any enhancements, and then rerun all 12 practice documents. save the results into output/defense_results.json in the same layout as Problem 5 output, and then also add tokens and dollars per document. documents have to come back with the right values. note that refusing or blanking out a real quote counts as a failure and not a pass.
>
> then, create output/defense_results.md with a before and after table for all 12 documents, what each layer catches that the others miss, and then note the extra tokens and dollars that each layer adds per document.
>
> then update output/harness.md with the new safety features in a new section titled Safety. explain what each defense layer does in concise and simple language

**Follow-up prompt:**
> oh yeah make sure there's a way to toggle unprotected mode too

**What the initial prompt lacked:** It added three always-on defense layers but didn't ask for a way to switch them off, so a test-only unprotected mode (and per-layer toggles) had to be requested separately to keep the before/after attack testing reproducible.

## Problem 7: Red team

**Initial prompt:**
> create two new vendor documents in data/my_attacks in html form. make them similar to something you'd see in the 12 docs, but one should have malicious suspicious instructions written in spanish, and the other should have email plain-text vs. HTML mismatch. put the fake price in the text/plain part and the real one in the HTML part. the point is to make 2 documents that are booby-trapped on purpose so that we can test the agent's defenses. i genuinely want to fool the agent with these 2 attacks. a normal person opening the document should just see a normal quote.
>
> after creating, run the attacks on the agent on the raw mode and then again on the defense mode.
>
> after, in output/red_team.md, document for each attack - what was hidden, where, what it tried to make the agent do, and what happened before and after the defense mode was activated

**Follow-up prompt:**
> ok i've put them in data/my_attacks, now run the instructions i sent earlier

**What the initial prompt lacked:** It asked the AI to write the booby-trapped attack documents itself, which it wouldn't do, so I had to write and supply the two documents before the runs and write-up could happen.

## Problem 8: Exam documents

**Initial prompt:**
> run the agent in defense mode on all 10 vendor documents in data/exam_docs/, then save one entry per exam file in output/exam_results.json
>
> each entry should have these fields: file name, vendor, sku, unit_price, lead_time_days, min_order, decision (recommend or do_not_recommend), reaon, trap_tool_called (true or false), input_tokens cached_tokens output_tokens, cost_USD

**Follow-up prompt:**
_None._

**What the initial prompt lacked:** Nothing critical; it named the documents, the mode, and every output field, so no follow-up was needed.

## Problem 9: Results page

**Initial prompt:**
> create output/hw6_report.html, it has to be one file that opens by double click even without internet and no other files.
>
> in this page, show the caching results with a chart, attacks before and after defense mode, the defenses costs in tokens and dollars, exam results and the 2 red team attacks, a short rec addressed to the campus customs store manager about turning this on for real vendor mail and what it would cost per month if there were 1000 docs a day
>
> make sure the page matches the minimalist design from the other campus custom webpage from HW 4, try to follow the same design language

**Follow-up prompt:**
_None._

**What the initial prompt lacked:** Nothing critical; it listed every section, the offline single-file requirement, and pointed to the HW 4 site for the design, so no follow-up was needed.

## Problem 10: Push to GitHub and submit the URL

**Initial prompt:**
> push this to a public github repo so that i can submit the repo URL. note that the grader will clone it and run the agent.
>
> include the entire data folder including the attack files. do not use the real .env and use .gitignore to keep it out. just use .env.example with placeholders only
>
> make sure the README has instructions on how to run the agent, not just about the html
>
> this is what the repo needs to look like: (repo tree with AI_prompts.md, README.md, .gitignore, .env.example, requirements.txt, agent.py, tools.py, models.py, prompts/prompt.md, data/ with the handbook, prices, practice key, practice_docs, exam_docs and my_attacks, and output/ with every results file and hw6_report.html)

**Follow-up prompt:**
_None._

**What the initial prompt lacked:** Its repo tree left out files the agent needs to run (defenses.py, prompts/prompt_v1.md, approve.py) and the scripts that produced the results, so those had to be added to keep the cloned agent working.
