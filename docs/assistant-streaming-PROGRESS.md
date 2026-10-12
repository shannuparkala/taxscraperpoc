# Assistant speed and quality rework - progress log

Persisted incrementally so an interrupted run can resume. Branch
`assistant-streaming-quality`, started 2026-10-09 from `cf3fdfa`.

## Owner decisions (2026-10-09)

1. **Streaming Option A**: one grounded streaming call writes the answer;
   checks run when the stream ends; a failing draft is withdrawn (`replace`
   event) and regenerated, then replaced by the fallback.
2. **Masking is opt-in with `/mask`.** Without it the question is sent as
   typed; the egress guard still blocks SSN/EIN/ITIN, card/account numbers and
   emails (phones and street addresses are advisory-only in the guard and are
   sent, like names).
3. Owner's uncommitted dashboard work committed first (`cf3fdfa`).
4. Cost-efficient without lowering quality.
5. No domain blocklist: source origin does not matter as long as answers are
   genuine (citations only from grounding, hypotheticals never cited).

## Commits, in order

- [x] 1 masking - `db58181` /mask opt-in, precise chat masking (12/12 offline cases, was 9/12)
- [x] 2 eval harness - `e4c19df` TTFT, total, words, cost, citation validity, rubric; 51 cases
- [x] `5c01ae6` top-bar badge says "Masking on request" on the assistant
- [x] 3 streaming - `582f978` one grounded streamed markdown call, checked at the end
- [x] 4 router - `65176dc` answer types + policies, selected state only for state questions
- [x] harness fix - `9a6b991` meter eval calls (cost was 0), keep markers with their sentence
- [x] 5 sources - `964acf2` flag unsourced figures [?], drop markers naming no source
- [x] 6a cache - `4cfe47b` same-day replay of general first-turn questions
- [x] 4b - `773aacc` jurisdiction federal/state/both; missing tax year flagged, not regenerated
- [x] `c389448` no false [?] on "U.S." or calculation lines
- [x] 6b - `d61c160` thinking level low (A/B: same correctness, half the wait)

## Findings worth keeping

- Grounding metadata (queries, sources, supports) arrives **only on the last
  stream chunk**; nothing to gate on earlier. Support offsets are byte offsets
  into the *whole* streamed text, so `extract_grounding(full_text=...)`.
- Probe, one question: default thinking -> first text 13.5 s (1,266 thinking
  tokens); `thinking_level=low` -> 3.7 s, no thinking tokens, same answer.
- Baseline (old two-call pipeline) per case: 40-85 s, 700-1,000+ words even
  for "what is the standard deduction", 4-5 follow-ups, markers inside
  hypothetical examples.
- First live run of the streaming pipeline (DE selected, standard deduction):
  first text 12.5 s, total 14.8 s (baseline 40 s for the same question).

## Eval runs

Runs are saved under `evals/assistant/runs/<label>.json` (gitignored);
compare with `python -m evals.assistant.run_eval --compare A B`.

| Label | Code | Notes |
| --- | --- | --- |
| baseline | `cf3fdfa` (+ harness) | old two-call pipeline |
| step3-streaming | `582f978` | streaming, general policy, old jurisdiction |
| step5 | `884fde7` | router + policies + flags (+ cache, which an eval cannot hit) |
| ab-thinking-default | `b894a3b` | A/B arm, run concurrently with the next |
| ab-thinking-low | `b894a3b` + `ASSISTANT_THINKING_LEVEL=low` | = final behaviour (`d61c160`) |

## Results (2026-10-09, all runs the same day)

| Metric | baseline | step3 | step5 | final (low) |
| --- | --- | --- | --- | --- |
| Cases passed | 3/51 | 40/51 | 42/51 | 50/51 |
| First text, median / p90 (s) | 61.3 / 81.7 | 13.7 / 17.9 | 19.9 / 34.4 | 9.2 / 11.7 |
| Total, median / p90 (s) | 61.3 / 81.7 | 16.9 / 32.2 | 23.9 / 59.2 | 12.4 / 16.3 |
| Words, median | 1024 | 176 | 198 | 198 |
| Within length budget | 0/48 | 39/47 | 42/46 | 46/47 |
| State-correct | 43/46 | 43/46 | 43/46 | 45/45 |
| Hypotheticals uncited | 8/50 | 50/50 | 50/50 | 50/50 |
| Uncited figure sentences | 110 | 9 | 10 | 6 |
| At most 2 follow-ups | 8/50 | 50/50 | 50/50 | 50/50 |
| Drafts withdrawn | - | 6 | 11 | 0 |
| Thinking tokens / case | n/a | 1,364 | 1,852 | 0 |

step5 was slower than step3: regenerations for a missing tax year (fixed in
`773aacc`) and more skipped searches; the thinking A/B then removed both.

Baseline tokens were not recorded (the harness did not meter until `9a6b991`).
