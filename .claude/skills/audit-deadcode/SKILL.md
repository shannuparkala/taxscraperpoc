---
name: audit-deadcode
description: Find unused files, functions, routes, dependencies and env vars across the backend and frontend. Read-only; produces a report and deletes nothing.
disable-model-invocation: true
context: fork
agent: code-auditor
allowed-tools: Read, Grep, Glob, Bash(git *), Bash(npx *), Bash(npm ls *), Bash(python -m *), Bash(pip show *)
---

Audit this codebase for dead code. Do not modify source files.

## Scope

- `backend/app/` and `backend/tests/`
- `frontend/src/`

Excluded, and not findings: `legacy/` (kept as reference on purpose), `data/`,
`Files/`, `taxfiles/`, `generated_output/`, anything gitignored.

## Gather evidence with tools, not by reading everything

- Python: `python -m vulture app` and `python -m deptry .` from `backend/`, if
  installed; otherwise fall back to import grep plus `git log`.
- Frontend: `npx knip` or `npx ts-prune` from `frontend/`.
- Staleness: `git log -1 --format=%cr -- <path>`.
- Declared-but-unused dependencies, in both `backend/requirements.txt` and
  `frontend/package.json`. Note that there is more than one virtualenv here and
  the server runs from `.venv` - a package missing from the venv that serves is
  a *different* finding from one nothing imports. See trap 16 in `CLAUDE.md`.
- Env vars: every key read in `backend/app/core/config.py` against
  `.env.example`. Report both directions - documented but unread, and read but
  undocumented.

## Before calling anything unused

Grep for dynamic references. This codebase has several kinds that no import
graph will show:

- `app/tax_knowledge/` corpora, assembled rather than imported by name.
- `state_profiles` entries, consumed as data by the map, the panel, the crawler
  allow-list and jurisdiction routing.
- Enum members, and `ALL_TABLES` in `models/database_models.py`.
- Field-name strings shared between an extraction prompt and the engine.
- Route paths and config keys reached by string.

Anything marked `# SECURITY:` is never a deletion candidate. If it looks
unreferenced, that goes in the escalation table with the invariant quoted.

## Output

Write `docs/deadcode-report.md`:

| Item | Type | Evidence it is unused | Dynamic-reference check | Risk |

Then two further tables: **Keep - human review** for anything referenced
dynamically or by a prompt, and **Escalate** for anything `# SECURITY:`-marked
or touching the four zones.

Never put a taxpayer value in the report. Return a 5-line summary: counts by
type and risk, plus the report path.
