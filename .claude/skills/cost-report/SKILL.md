---
name: cost-report
description: Summarize LLM spend per return and per chat session from the llm_calls ledger - per-return averages, cost per page, split by stage and model - and rank ways to cut it without hurting accuracy.
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
---

Report on LLM spend. Run the script; do not read raw logs or the database into
context.

```
cd backend && python -m scripts.cost_report --json            # all time
cd backend && python -m scripts.cost_report --json --days 30  # a window
```

Pass `$ARGUMENTS` through as `--days N` when it is a number.

## Where the numbers come from

- `llm_calls` - one row per model call, written by `GeminiService` through
  `llm_meter.DbLlmMeter`. Model, tier, task, stage, workflow id or chat session
  id, and the API's own usage fields: input (which *includes* cached), output,
  cached and thinking tokens. `cost_usd` is fixed at call time from
  `backend/app/llm_prices.json`; `prices_as_of` says which version.
- `app/llm_prices.json` - the only place a rate lives. Cite its `source` and
  `page_updated` beside every dollar figure. If a rate looks stale, say so and
  point at the file; never correct a rate from memory.
- A row with `cost_usd` null is **unpriced** - the price file has no rate for
  that model. Report the count; never fold it in as zero or estimate it.
- `Workflow.llm_usage` and `WorkflowStageRun.detail` still carry the older
  per-run token totals. They predate the ledger and cover extraction only; use
  the ledger, and mention the older fields only if the ledger is empty for the
  window asked about.

## Report, in this order

1. **Stub and failure rate first.** A non-zero stub count on a deployment with
   `GEMINI_ENABLED=true` is a configuration failure, not a cost story.
   Unattributed calls (no workflow, no chat) mean a caller skipped
   `metered(...)` or `meter_scope=` - name the stage they carry.
2. **Per return:** cost, calls, input and output tokens - mean, median, p90,
   max - and cost per page.
3. **Per chat session:** cost distribution.
4. **Split** by stage, model and tier.
5. **Savings**, as the script ranks them by the share of spend each touches,
   each with its accuracy risk. Add your own only if the numbers support it, and
   say which number.

Never print a taxpayer value. Identify runs by workflow id.
