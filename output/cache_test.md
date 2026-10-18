# Problem 4: With and Without Cached Tokens

All 12 practice docs were run under each setup with `gpt-6-luna`. That's 3 model calls per document, so 36 calls per setup and 72 in total. Raw per-call data is in `output/cache_test.json`. Prices come from `data/prices.json` (per 1M tokens: input $0.10, cached input $0.01, cache write $0.125, output $0.50).

- **Without cache:** every call starts with a random request id, so no two prompts share a prefix and nothing can be reused. The API reported **0 cached tokens on all 36 calls**.
- **With cache:** the instructions (prompt + handbook) are identical on every call, with a stable `prompt_cache_key` and a cache breakpoint right after the handbook. All 36 calls read the handbook from the cache.
- **Portkey's response cache was bypassed on every call**, so these are real model calls and not replays. All 72 response ids are unique.
- Both setups returned the same answers, **12/12 matching `practice_key.json`**.

## 1. Cost per method

| | Without cache | With cache |
|---|---|---|
| Input tokens | 406,026 | 405,285 |
| Cached input tokens | 0 | 396,742 |
| Cache-write tokens | 401,490 | 4,007 |
| Plain (uncached) input tokens | 4,536 | 4,536 |
| Output tokens | 2,151 | 2,231 |
| **Total cost (12 docs)** | **$0.05172** | **$0.00604** |
| **Cost per document** | **$0.00431** | **$0.00050** |

**Saved: $0.04568, which is 88.3%.**
```
($0.05171538 - $0.00603741) / $0.05171538 = 88.33%
```

The no-cache total prices the cache-write tokens at the $0.125 cache-write rate, because that's what the API reported (see finding 3). If those tokens were billed as plain input at $0.10, the no-cache total would be $0.04168 ($0.00347 per document), and caching would still save **85.5%**.

## 2. Real numbers vs. the Problem 2 estimates

| | Problem 2 estimate | Real run | Why they differ |
|---|---|---|---|
| Handbook tokens | 10,058 (tiktoken `o200k_base`) | ~10,954 cached prefix per call | The real prefix also holds `prompt.md` (610 tokens), the tool and answer schemas, and message framing. Prompt + handbook alone counts 10,674 with tiktoken, so the handbook count itself held up. |
| Input tokens per call | 10,058 (handbook only) | 11,080–11,473 | Each call adds the user prompt (~126 tokens), and later calls add earlier tool results. |
| Calls per document | 1 | **3** | Read the document, check the rules, return the answer. The handbook is sent again on every call. |
| One uncached call | $0.00101 | $0.00144 avg | ~12% more tokens, billed at the $0.125 write rate instead of $0.10, plus output tokens. |
| One cached call | $0.00010 | $0.00017 avg | The handbook part matched (~11k × $0.01/1M = $0.00011). The rest is output (~$0.00004), the new cache write on calls 2–3, and the 126 uncached tokens. |
| 1,000 calls, no cache | $1.0058 | $1.44 | Same reasons as one uncached call. |
| 1,000 calls, cached | $0.1017 | $0.168 | Same reasons as one cached call. |
| **Savings from caching** | **~89.9%** | **88.3%** | Very close. Output tokens and cache writes can't be cached, which takes about 1.6 points off. |

**Takeaway:** the handbook token count and the savings percentage were both accurate. The estimate missed two things: the agent makes **3 calls per document, not 1**, and every call carries more than the handbook. Real cost per *document* is about 4× the per-call estimate without cache, and about 5× with it.

## 3. Projection: 1,000 documents a day for 30 days (30,000 documents)

These projections use the measured cost per document.

| | Per day (1,000 docs) | 30 days (30,000 docs) |
|---|---|---|
| Without cache | 1,000 × $0.00430962 = **$4.31** | 30,000 × $0.00430962 = **$129.29** |
| With cache | 1,000 × $0.00050312 = **$0.50** | 30,000 × $0.00050312 = **$15.09** |
| Saved | $3.81 | **$114.19** (88.3%) |

If the no-cache writes were billed as plain input instead, no cache would cost $3.47 a day and $104.20 for 30 days. Caching would still save $89.10 (85.5%).

**Assumption: the cache stays warm.** 1,000 documents a day is about 2 a minute over an 8-hour day. That's well inside the cache's ~30-minute lifetime, so the handbook rarely needs to be rewritten. Each time the cache does go cold, the next call rewrites ~11k tokens, which costs about $0.0014. Even a few cold starts a day add only pennies over the month.

## 4. Surprising findings and why they happen

1. **Caching saved 88%, even though only the input gets cheaper.**
   - **Why:** almost all of the cost is the handbook, not the work. About 98% of each call's input is the same static ~11k-token prefix (prompt + handbook). Only ~126 tokens of a call are new to that call, plus any earlier tool results. Output is tiny, about 60 tokens per call. Cached tokens cost 10× less than plain input, so the bill drops to just over a tenth.
   - **Pattern:** a big fixed prompt with small, varied questions is the best case for caching.

2. **The handbook is sent 3 times per document.**
   - **Why:** an agent loop resends the whole conversation on every step. The steps are: call 1 asks for `read_document`, call 2 asks for `check_purchasing_rules`, and call 3 returns the final answer.
   - **Effect:** each step pays for the handbook again. Caching matters more for agents than for single-call apps. Cutting a step would also save money (for example, returning the answer right after the rule check).

3. **"No cache" still reported cache writes, and writes cost more than plain input.**
   - **Why:** the provider writes the prompt to the cache automatically. Asking for explicit-only caching didn't stop it, and every no-cache call reported ~11k cache-write tokens. Because the request id changes every call, those writes are never read back.
   - **Effect:** they're billed at $0.125/1M instead of $0.10/1M, so turning caching off cost about 24% *more* than a plain uncached estimate, on top of losing the 90% discount.

4. **Portkey was replaying identical requests.**
   - **What happened:** the Portkey key has a response cache. The first call of every document is byte-for-byte identical (same instructions, same user prompt; the document only arrives later in a tool result). So Portkey returned the earlier response, with the same response id, timestamp and token counts, without calling the model.
   - **Effect:** that's why Problem 3's logs showed the first call of each document as a fresh cache write. Every call now sends `x-portkey-cache-force-refresh: true`, so every logged token count comes from a real model call.

5. **Exactly 126 tokens were uncached on every single call, in both setups.**
   - **Why (likely):** the provider caches whole blocks of tokens, so the last partial block of each prompt is always billed at the full price. The tail is the same size on every call because the end of the prompt ends the same way each time.

6. **The cache was already warm at the start.**
   - **Why:** the first cached call reported 10,954 cached tokens and 0 written. Test calls a few minutes earlier had already stored the handbook, and the cache lasts about 30 minutes.
   - **Effect:** the cached total doesn't include the one-time ~$0.0014 cold-start write. That doesn't meaningfully change the 88% figure.
