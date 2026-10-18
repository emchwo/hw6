# Problem 2: Handbook Size and Cost Estimate

Source file: `data/shop_handbook.md` (29,241 bytes · 28,903 characters · 6,127 words · 338 lines)
Prices: `data/prices.json` for `gpt-6-luna`

## 1. Token count

**Estimated handbook size: 10,058 tokens**

How I got it:

- I tokenized the full file with OpenAI's `tiktoken` library (v0.14.0), using the `o200k_base` encoding. That's the tokenizer current OpenAI GPT models use. `tiktoken` has no mapping for `gpt-6-luna`, so I chose the encoding myself.
- Cross-checks:
  | Method | Tokens |
  |---|---|
  | `tiktoken` `o200k_base` (used) | **10,058** |
  | `tiktoken` `cl100k_base` (older GPT-4 tokenizer) | 10,184 |
  | Rule of thumb, characters ÷ 4 | ~7,226 |
- The rule of thumb comes in about 28% low. The handbook is heavy on Markdown tables, pipes, SKU codes and numbers, and those break into more tokens than plain prose does (about 2.9 characters per token here, not 4).
- This count is the handbook text only. The chat message wrapper adds a handful of tokens per message. Problem 4 will check the estimate against the `usage.prompt_tokens` that real `gpt-6-luna` calls report.

## 2. Prices used (`gpt-6-luna`, per 1M tokens)

| Token type | Price per 1M | Price per token |
|---|---|---|
| Input (uncached) | $0.10 | $0.0000001 |
| Cached input (cache hit) | $0.01 | $0.00000001 |
| Cache write | $0.125 | $0.000000125 |
| Output | $0.50 | not used here |

Only the handbook's **input** cost is counted. Output tokens depend on the agent's answers and aren't part of "the handbook alone."

## 3. Cost without caching

Every call pays the full input price for all 10,058 handbook tokens.

**One call**
```
10,058 tokens × $0.10 / 1,000,000 = $0.0010058   ≈ $0.0010 (about 1/10 of a cent)
```

**1,000 calls**
```
1,000 × $0.0010058 = $1.0058   ≈ $1.01
(= 10,058,000 tokens × $0.10 / 1,000,000)
```

## 4. Cost with caching

The handbook sits at the start of the prompt, identical on every call, so it can be cached. The first call **writes** the cache at $0.125/1M. Every later call within the cache window **reads** it at $0.01/1M.

**One call**
- First call (cache write, nothing cached yet):
  ```
  10,058 × $0.125 / 1,000,000 = $0.00125725   ≈ $0.0013
  ```
  This is about 25% *more* than one uncached call, so caching doesn't pay off for a single call.
- Any later call that hits the cache:
  ```
  10,058 × $0.01 / 1,000,000 = $0.00010058    ≈ $0.0001
  ```
  This is 90% cheaper than an uncached call.

**1,000 calls** (1 cache write + 999 cache hits)
```
Cache write:  1   × 10,058 × $0.125 / 1,000,000 = $0.00125725
Cache hits:   999 × 10,058 × $0.01  / 1,000,000 = $0.10047942
                                                ------------
Total                                           = $0.10173667  ≈ $0.10
```

## 5. Summary

| Scenario | 1 call | 1,000 calls |
|---|---|---|
| No caching | $0.0010058 | **$1.0058** |
| With caching | $0.00125725 (cache write) / $0.00010058 (cache hit) | **$0.1017** |
| Savings from caching | -25% on a lone first call / 90% per hit | **$0.904 saved (~89.9%)** |

## 6. Assumptions and caveats (to check in Problem 4)

- **Prefix must match exactly.** Caching only works if the handbook is the first thing in the prompt and stays byte-for-byte identical across calls. The vendor document and the question have to come *after* it.
- **Minimum size.** OpenAI only caches prompts of at least 1,024 tokens. At about 10k tokens, the handbook clears that easily.
- **Cache lifetime.** A cache entry expires after a few minutes of inactivity. The 1,000-call estimate assumes the calls run back to back. If they're spread out, each expiry adds another cache write (about $0.0011 extra each).
- **Cache granularity.** Providers cache in token blocks, so the cached portion reported by the API may be slightly under 10,058 tokens. Any leftover tokens are billed at the uncached rate. The effect on cost is tiny.
- **Tokenizer match.** If `gpt-6-luna` uses a different tokenizer than `o200k_base`, the real count will differ. Problem 4's real runs will show by how much.
