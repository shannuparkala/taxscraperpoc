"""Run the assistant eval set against the live Gemini API and score it.

    python -m evals.assistant.run_eval --label baseline       # every case
    python -m evals.assistant.run_eval --case ca-rates        # one case (repeatable)
    python -m evals.assistant.run_eval --group multi-state
    python -m evals.assistant.run_eval --masking-only         # offline, no API
    python -m evals.assistant.run_eval --compare baseline after-streaming

Needs GEMINI_API_KEY (read from backend/.env like the server). Each case is
asked through ``AssistantService.answer_events`` exactly as the streaming API
asks it - masking, grounding, validation, regeneration and all - against a
throwaway SQLite database under ``data/evals/assistant``.

Per case it records:

* **time to first token** - seconds until the first ``delta`` event (answer
  text on screen). A pipeline that streams no text scores its ``final``
  time, which is when the reader first saw anything;
* **total time**, **words** in the displayed answer, and **cost** (the LLM
  meter's own ``llm_calls`` rows for the conversation);
* **citation validity** - every ``[n]`` in the displayed text names a listed
  source; no marker sits inside a hypothetical example;
* **uncited figures** - sentences stating a dollar amount, percentage or
  date with no source marker (reported, not failed: some are the user's
  own numbers);
* **correctness rubric** - ``must_mention`` groups (any phrase of a group
  must appear), ``must_not_mention``, the expected status and states, a
  stated tax year, the answer type's length budget, and at most two
  follow-up questions.

The ``masking_cases`` run offline through ``QuestionMasker`` - what ``/mask``
must replace and what it must leave alone.

Writes ``evals/assistant/runs/<label>.json``, ``REPORT.md`` and
``last_run.json``. Exit status is 1 if any case failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
HERE = Path(__file__).resolve().parent
EVAL_SET = HERE / "eval_set.json"
REPORT = HERE / "REPORT.md"
LAST = HERE / "last_run.json"
RUNS = HERE / "runs"
EVAL_DATA = ROOT / "data" / "evals" / "assistant"

_YEAR = re.compile(r"(?<!\d)(19|20)\d\d(?!\d)")
_MARKER = re.compile(r"\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
_SENTENCES = re.compile(r"(?<=[.!?])[ \t]+(?!\[(?:\d|\?))|(?<=\d\]|\?\])[ \t]+(?=\S)|\n+")
_FIGURE = re.compile(
    r"\$\s?\d|\d(?:\.\d+)?\s?%|\b(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{1,2}\b"
)
#: A heading line naming an example: "### Hypothetical example", "**Example**".
_EXAMPLE_HEADING = re.compile(
    r"^\s*(?:#+[ \t]*[^\n]*\bexample\b|\*\*[^*\n]*\bexample\b[^*\n]*\*\*)", re.IGNORECASE
)
_HEADING = re.compile(r"^\s*(?:#+\s+\S|\*\*[^*\n]+\*\*\s*$)")

#: Word budget per answer type. Generous on purpose: this flags padding, not
#: a terse writer.
WORD_BUDGET = {
    "fact": 160,
    "how_to": 320,
    "dispute": 380,
    "scenario": 420,
    "case_news": 320,
    "multi_state": 480,
    "clarify": 80,
    "out_of_scope": 80,
    "declined": 260,
}


def _bootstrap(database: str = "eval.db") -> None:
    EVAL_DATA.mkdir(parents=True, exist_ok=True)
    os.environ["DATA_DIR"] = str(EVAL_DATA)
    for zone in ("raw", "masked", "output", "tmp", "vector"):
        (EVAL_DATA / zone).mkdir(exist_ok=True)
        os.environ[f"{zone.upper()}_ZONE_DIR" if zone != "vector" else "VECTOR_STORE_DIR"] = str(
            EVAL_DATA / zone
        )
    os.environ["DATABASE_URL"] = f"sqlite:///{(EVAL_DATA / database).as_posix()}"
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", action="append", default=[], help="Run only this case id")
    parser.add_argument("--group", action="append", default=[], help="Run only this group")
    parser.add_argument("--label", default="", help="Save the run as runs/<label>.json")
    parser.add_argument("--pause", type=float, default=0.0, help="Seconds between cases")
    parser.add_argument("--masking-only", action="store_true", help="Offline masking cases only")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="Compare two saved runs")
    args = parser.parse_args(argv)

    if args.compare:
        print(_comparison(*(_load_run(label) for label in args.compare), labels=args.compare))
        return 0

    # Offline masking runs get their own database so they never contend with
    # a live run's SQLite write lock.
    _bootstrap("masking.db" if args.masking_only else "eval.db")
    from app.core.config import get_settings
    from app.core.db import init_database, session_scope

    settings = get_settings()
    init_database()
    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))

    with session_scope() as session:
        masking = _run_masking(data.get("masking_cases", []), session)
    print(f"Masking cases: {sum(m['passed'] for m in masking)}/{len(masking)} passed")
    for item in masking:
        if not item["passed"]:
            print(f"    FAIL {item['text'][:70]!r}: {'; '.join(item['failures'])}")
    if args.masking_only:
        return 0 if all(m["passed"] for m in masking) else 1

    from app.schemas.api import AssistantAnswerOut, AssistantQueryRequest
    from app.services.assistant.assistant_service import AssistantService
    from app.services.gemini_service import GeminiService

    if not (settings.gemini_enabled and settings.gemini_api_key):
        print("GEMINI_API_KEY is not set (or GEMINI_ENABLED=false); nothing to evaluate.")
        return 2

    cases = data["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    if args.group:
        cases = [c for c in cases if c.get("group") in args.group]

    results: list[dict[str, Any]] = []
    for number, case in enumerate(cases, start=1):
        print(f"[{number}/{len(cases)}] {case['id']} ...", flush=True)
        started = time.monotonic()
        try:
            result = _run_case(case, AssistantService, GeminiService, AssistantQueryRequest,
                               AssistantAnswerOut, session_scope, settings)
        except Exception as exc:  # noqa: BLE001 - a crashing case is a failed case
            result = {"id": case["id"], "group": case.get("group"), "type": case.get("type"),
                      "passed": False, "failures": [f"crashed: {type(exc).__name__}: {exc}"],
                      "checks": {}}
        result.setdefault("seconds", round(time.monotonic() - started, 1))
        results.append(result)
        print(
            f"    {'PASS' if result['passed'] else 'FAIL'} "
            f"ttft={result.get('ttft')}s total={result.get('seconds')}s "
            f"words={result.get('words')} {'; '.join(result['failures'])}",
            flush=True,
        )
        if args.pause:
            time.sleep(args.pause)

    run = {
        "label": args.label or "unlabelled",
        "model": settings.assistant_model,
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "results": results,
        "masking": masking,
    }
    _write(run)
    return 0 if all(r["passed"] for r in results) else 1


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _run_masking(cases: list[dict[str, Any]], session: Any) -> list[dict[str, Any]]:
    from app.services.assistant.masking import QuestionMasker

    masker = QuestionMasker(session)
    out = []
    for case in cases:
        failures = []
        try:
            masked = masker.mask(case["text"]).text
        except Exception as exc:  # noqa: BLE001
            masked = ""
            failures.append(f"crashed: {type(exc).__name__}")
        for value in case.get("keep", []):
            if value not in masked:
                failures.append(f"replaced {value!r}")
        for value in case.get("mask", []):
            if value in masked:
                failures.append(f"left {value!r} unmasked")
        out.append({"text": case["text"], "passed": not failures, "failures": failures})
    return out


def _run_case(case, AssistantService, GeminiService, AssistantQueryRequest,
              AssistantAnswerOut, session_scope, settings) -> dict[str, Any]:
    expect = case["expect"]
    kind = case.get("type", "")
    checks: dict[str, bool | None] = {}
    failures: list[str] = []
    base = {"id": case["id"], "group": case.get("group"), "type": kind}

    # Request validation is the first gate, exactly as at the API.
    try:
        request = AssistantQueryRequest(
            question=case["question"], selected_state=case.get("selected_state")
        )
    except ValidationError:
        rejected = True
    else:
        rejected = False
    if expect.get("rejected"):
        checks["state_correct"] = rejected
        if not rejected:
            failures.append("invalid selected_state was accepted")
        return {**base, "passed": not failures, "failures": failures, "checks": checks,
                "status": "rejected" if rejected else "accepted"}
    if rejected:
        return {**base, "passed": False, "failures": ["valid request was rejected"], "checks": {}}

    timings: dict[str, float] = {}
    with session_scope() as session:
        from app.services.llm_meter import DbLlmMeter

        # Metered as the API route meters it (deps.get_gemini_service), so
        # cost per case comes from the same llm_calls rows production writes.
        service = AssistantService(
            session, gemini=GeminiService(meter=DbLlmMeter(session)), settings=settings
        )
        session_id = None
        for turn in case.get("turns", []):
            prior = service.answer(question=turn["question"], selected_state=turn.get("selected_state"),
                                   session_id=session_id)
            session_id = prior["session_id"]
        started = time.monotonic()
        answer: dict[str, Any] | None = None
        withdrawn = 0
        for event in service.answer_events(
            question=request.question, selected_state=request.selected_state, session_id=session_id
        ):
            elapsed = time.monotonic() - started
            kind_of_event = event.get("type")
            if kind_of_event == "delta":
                timings.setdefault("ttft", elapsed)
            elif kind_of_event == "replace":
                withdrawn += 1
            elif kind_of_event == "final":
                timings["final"] = elapsed
                answer = event["answer"]
            elif kind_of_event == "error":
                raise RuntimeError(event.get("message", "error event"))
        assert answer is not None, "no final event"
        conversation = answer.get("session_id")

    usage = _cost(session_scope, conversation)

    try:
        AssistantAnswerOut.model_validate(answer)
        schema_ok = "schema_invalid" not in answer.get("validation_issues", [])
    except ValidationError:
        schema_ok = False
    checks["schema_valid"] = schema_ok
    if not schema_ok:
        failures.append("schema invalid")

    status = answer["status"]
    if status not in expect.get("status", [status]):
        failures.append(f"status {status}, expected {expect['status']}")

    answered = status in ("answered", "declined")
    states = sorted(s["code"] for s in answer.get("states", []))
    if "states" in expect and status == "answered":
        ok = states == sorted(expect["states"])
        if expect.get("spans_states"):
            ok = ok and bool(answer.get("spans_states"))
        if expect.get("state_change_notice"):
            ok = ok and bool(answer.get("state_change_notice"))
        checks["state_correct"] = ok
        if not ok:
            failures.append(f"states {states}, expected {sorted(expect['states'])}")
    elif "states" in expect and not (status == "clarify" and "clarify" in expect.get("status", [])):
        checks["state_correct"] = False
        failures.append(f"not answered ({status}); state correctness unscored")

    text = _display_text(answer)
    body, example = _split_example(answer, text)
    words = len(re.findall(r"\b\w[\w'’.-]*\b", text))
    citations = answer.get("citations", [])

    if status == "answered":
        cited = len(citations) > 0
        checks["cited"] = cited
        if not cited:
            failures.append("no citations")
        # The product rule (validators.check_tax_year): an answer that states
        # a figure says which tax year it applies to. A procedure with no
        # figure ("how do I get my transcript") is not made to invent one.
        if _FIGURE.search(_display_text(answer)):
            has_year = bool(_YEAR.search(answer.get("tax_year", "")))
            checks["tax_year"] = has_year
            if not has_year:
                failures.append("no tax year")
        wanted = expect.get("tax_year_contains")
        if wanted and wanted not in answer.get("tax_year", ""):
            failures.append(f"tax year {answer.get('tax_year')!r}, expected {wanted}")

    markers = {int(n) for group in _MARKER.findall(text) for n in group.split(",")}
    valid = markers <= set(range(1, len(citations) + 1))
    checks["citations_valid"] = valid
    if not valid:
        failures.append(f"markers {sorted(markers)} but {len(citations)} sources")
    hypothetical_cited = bool(_MARKER.search(example))
    checks["hypothetical_uncited"] = not hypothetical_cited
    if hypothetical_cited:
        failures.append("hypothetical example carries source markers")

    # A marker sits after its sentence's full stop ("taxable. [1] Next"), so a
    # sentence boundary is never placed before a marker. A sentence flagged
    # [?] (no source passage) counts as uncited: it is.
    uncited_figures = sum(
        1 for sentence in _SENTENCES.split(body)
        if _FIGURE.search(sentence) and not _MARKER.search(sentence)
    )

    follow_ups = len(answer.get("follow_up_questions", []))
    checks["follow_ups_ok"] = follow_ups <= 2
    if follow_ups > 2:
        failures.append(f"{follow_ups} follow-up questions")
    if expect.get("needs_follow_up") and answered and not follow_ups:
        failures.append("did not ask which state")

    budget = WORD_BUDGET.get(kind)
    if budget and status in ("answered", "declined", "clarify"):
        checks["length_ok"] = words <= budget
        if words > budget:
            failures.append(f"{words} words, budget {budget} for {kind}")

    lowered = text.lower()
    correct = True
    for group in expect.get("must_mention", []):
        if not any(phrase.lower() in lowered for phrase in group):
            correct = False
            failures.append(f"mentions none of {group}")
    for phrase in expect.get("must_not_mention", []):
        if phrase.lower() in lowered:
            correct = False
            failures.append(f"mentions {phrase!r}")
    for phrase in expect.get("quick_answer_must_not_contain", []):
        if phrase.lower() in answer.get("quick_answer", "").lower():
            correct = False
            failures.append(f"quick answer contains {phrase!r}")
    if expect.get("needs_next_steps") and answered and not (
        answer.get("next_steps") or re.search(r"(?m)^\s*(?:\d+\.|[-*])\s", answer.get("answer_markdown", ""))
    ):
        correct = False
        failures.append("no next steps for a dispute")
    checks["correct"] = correct
    if expect.get("was_masked") and not answer.get("was_masked"):
        failures.append("identifier was not masked")

    return {
        **base,
        "passed": not failures,
        "failures": failures,
        "checks": checks,
        "status": status,
        "states": states,
        "tax_year": answer.get("tax_year", ""),
        "answer_type": answer.get("answer_type", ""),
        "citations": [c["domain"] for c in citations],
        "attempts": answer.get("attempts"),
        "withdrawn": withdrawn,
        "validation_issues": answer.get("validation_issues", []),
        "ttft": round(timings.get("ttft", timings["final"]), 1),
        "seconds": round(timings["final"], 1),
        "words": words,
        "uncited_figures": uncited_figures,
        "follow_ups": follow_ups,
        **usage,
        "text": text,
    }


def _cost(session_scope, conversation: str | None) -> dict[str, Any]:
    """What the conversation cost, from the meter's ``llm_calls`` rows.

    Tokens are always known; USD only for models priced in llm_prices.json
    (a model missing there is reported as unpriced, never estimated).
    """
    usage = {"cost_usd": 0.0, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0,
             "thinking_tokens": 0, "unpriced_calls": 0}
    if not conversation:
        return usage
    from sqlalchemy import text as sql

    with session_scope() as session:
        row = session.execute(
            sql("SELECT COALESCE(SUM(CAST(cost_usd AS REAL)), 0), COUNT(*), "
                "COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
                "COALESCE(SUM(thinking_tokens), 0), "
                "COALESCE(SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END), 0) "
                "FROM llm_calls WHERE chat_session_id = :sid"),
            {"sid": conversation},
        ).one()
    return {"cost_usd": round(float(row[0] or 0), 5), "llm_calls": int(row[1] or 0),
            "input_tokens": int(row[2]), "output_tokens": int(row[3]),
            "thinking_tokens": int(row[4]), "unpriced_calls": int(row[5])}


def _display_text(answer: dict[str, Any]) -> str:
    """Everything the reader sees as the answer, minus sources and disclaimer."""
    if answer.get("answer_markdown"):
        return str(answer["answer_markdown"])
    parts: list[str] = [answer.get("quick_answer", ""), answer.get("why", "")]
    parts += [s.get("content", "") for s in answer.get("state_sections", [])]
    parts.append(answer.get("example", ""))
    parts += answer.get("facts_relied_on", []) + answer.get("assumptions", [])
    parts += [s.get("action", "") for s in answer.get("next_steps", [])]
    parts += [f"{r.get('label', '')} {r.get('description', '')}" for r in answer.get("references", [])]
    parts += answer.get("considerations", []) + answer.get("recent_or_pending_changes", [])
    parts += answer.get("unverified_points", []) + answer.get("follow_up_questions", [])
    parts.append((answer.get("professional_help") or {}).get("reason", ""))
    return "\n".join(p for p in parts if p)


def _split_example(answer: dict[str, Any], text: str) -> tuple[str, str]:
    """(text outside any example, the example text)."""
    if not answer.get("answer_markdown"):
        example = answer.get("example", "")
        return text.replace(example, "") if example else text, example
    body: list[str] = []
    example: list[str] = []
    inside = False
    for line in text.splitlines():
        if _HEADING.match(line) or _EXAMPLE_HEADING.match(line):
            inside = bool(_EXAMPLE_HEADING.match(line))
        (example if inside else body).append(line)
    return "\n".join(body), "\n".join(example)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    results = [r for r in run["results"] if r.get("status") not in (None, "rejected")]
    timed = [r for r in results if r.get("seconds") is not None]

    def pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)

    def rate(key: str) -> str:
        scored = [r["checks"][key] for r in run["results"] if r.get("checks", {}).get(key) is not None]
        return f"{sum(1 for s in scored if s)}/{len(scored)}" if scored else "n/a"

    ttft = [r["ttft"] for r in timed]
    total = [r["seconds"] for r in timed]
    words = [r["words"] for r in results if r.get("status") in ("answered", "clarify")]
    costs = [r.get("cost_usd", 0.0) for r in results]
    masking = run.get("masking", [])
    return {
        "Cases passed": f"{sum(1 for r in run['results'] if r['passed'])}/{len(run['results'])}",
        "Time to first token, median (s)": round(statistics.median(ttft), 1) if ttft else None,
        "Time to first token, p90 (s)": pct(ttft, 0.9),
        "Total time, median (s)": round(statistics.median(total), 1) if total else None,
        "Total time, p90 (s)": pct(total, 0.9),
        "Words, median (answered)": int(statistics.median(words)) if words else None,
        "Within length budget": rate("length_ok"),
        "Correctness rubric": rate("correct"),
        "State-correct": rate("state_correct"),
        "Citation present (answered)": rate("cited"),
        "Citation markers valid": rate("citations_valid"),
        "Hypotheticals uncited": rate("hypothetical_uncited"),
        "Uncited figure sentences (total)": sum(r.get("uncited_figures", 0) for r in results),
        "At most 2 follow-ups": rate("follow_ups_ok"),
        "Tax year stated (answered)": rate("tax_year"),
        "Drafts withdrawn": sum(r.get("withdrawn", 0) for r in results),
        "Cost, total (USD, priced models only)": round(sum(costs), 4),
        "Unpriced calls": sum(r.get("unpriced_calls", 0) for r in results),
        "LLM calls (total)": sum(r.get("llm_calls", 0) for r in results),
        "Input tokens per case, mean": _mean(results, "input_tokens"),
        "Output tokens per case, mean": _mean(results, "output_tokens"),
        "Thinking tokens per case, mean": _mean(results, "thinking_tokens"),
        "Masking cases (offline)": f"{sum(m['passed'] for m in masking)}/{len(masking)}" if masking else "n/a",
    }


def _mean(results: list[dict[str, Any]], key: str) -> int | None:
    values = [r[key] for r in results if r.get("llm_calls")]
    return int(sum(values) / len(values)) if values else None


def _write(run: dict[str, Any]) -> None:
    RUNS.mkdir(exist_ok=True)
    payload = json.dumps(run, indent=2, ensure_ascii=False)
    LAST.write_text(payload, encoding="utf-8")
    if run["label"] != "unlabelled":
        (RUNS / f"{run['label']}.json").write_text(payload, encoding="utf-8")
    results = run["results"]
    summary = _summary(run)
    lines = [
        "# Assistant evaluation",
        "",
        f"Run `{run['label']}` at {run['ran_at']} against `{run['model']}` with Google Search grounding.",
        "",
        "| Metric | Result |",
        "| --- | --- |",
        *[f"| {key} | {value} |" for key, value in summary.items()],
        "",
        "| Case | Type | Result | Status | States | Year | TTFT | Total | Words | Tokens out | Failures |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['id']} | {r.get('type', '')} | {'PASS' if r['passed'] else 'FAIL'} | "
            f"{r.get('status', '')} | {', '.join(r.get('states', []))} | {r.get('tax_year', '')} | "
            f"{r.get('ttft', '')} | {r.get('seconds', '')} | {r.get('words', '')} | "
            f"{r.get('output_tokens', '')} | {'; '.join(r['failures'])} |"
        )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{len(results)} passed. Report: {REPORT}")
    for key, value in summary.items():
        print(f"  {key}: {value}")


def _load_run(label: str) -> dict[str, Any]:
    path = Path(label) if label.endswith(".json") else RUNS / f"{label}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _comparison(before: dict[str, Any], after: dict[str, Any], *, labels: list[str]) -> str:
    a, b = _summary(before), _summary(after)
    lines = [f"| Metric | {labels[0]} | {labels[1]} |", "| --- | --- | --- |"]
    lines += [f"| {key} | {a.get(key)} | {b.get(key)} |" for key in a]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
