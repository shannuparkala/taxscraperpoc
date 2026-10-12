# Dead Code Audit Report

Generated: 2026-09-22  
Scope: `backend/app/` and `backend/tests/`, `frontend/src/`  
Exclusions: `legacy/`, `data/`, `Files/`, `taxfiles/`, `generated_output/`

## Summary

- **Backend modules examined:** 70+ Python files across app/api, app/core, app/models, app/schemas, app/repositories, app/services, app/tax_knowledge
- **Frontend examined:** 20+ TypeScript/React files
- **Unused dependencies found:** 3 (pypdf, xlrd, alembic)
- **Transitive dependencies (likely needed):** 3 (multipart, lxml, tenacity)
- **Dead routes/services:** 0
- **Potentially unused methods:** <10 (mostly false positives; all appear to be callable via route handlers or service methods)

---

## Unused Dependencies

| Package | Declared In | Evidence It Is Unused | Notes | Risk |
|---------|-------------|----------------------|-------|------|
| `pypdf>=5.1.0` | backend/requirements.txt | Never imported; grep for `pypdf`, `PdfReader`, `PdfWriter` returns nothing | Comment says "PDF metadata / merge / split" but code uses PyMuPDF (fitz) instead for all PDF operations | Low — not used in code path but adds minimal weight |
| `xlrd>=2.0.1` | backend/requirements.txt | Never imported; `.xls` extension recognized in ingestion_service but never processed | Was intended for legacy .xls file reading; openpyxl handles .xlsx | Low — feature not implemented |
| `alembic>=1.14.0` | backend/requirements.txt | Never imported; no `alembic/` folder; no migrations exist | SQLAlchemy migration tool but not used; schema is created at runtime | Medium — suggests no migration strategy; could cause issues on schema changes |

---

## Frontend Dependencies — All Used

| Package | Evidence of Use |
|---------|-----------------|
| `@types/d3-geo` | Imported in StateMap.tsx for type definitions |
| `@types/topojson-client` | Imported in StateMap.tsx for type definitions |
| `d3-geo` | Used in StateMap.tsx (`geoAlbersUsa`, `geoPath`) |
| `lucide-react` | Used in Composer, StateMap, StatePanel for icons |
| `react` | Core dependency, used in all files |
| `react-dom` | Core dependency, used in main.tsx |
| `react-markdown` | Used in Markdown.tsx for rendering markdown |
| `react-router-dom` | Used in App.tsx, main.tsx, DashboardPage.tsx for routing |
| `remark-gfm` | Used in Markdown.tsx for GitHub-flavored markdown |
| `topojson-client` | Used in StateMap.tsx (`feature` function) |
| `us-atlas` | Used in StateMap.tsx for US state topology data |

---

## Transitive Dependencies (Likely Needed)

These packages are declared but not directly imported in application code. They are likely transitive dependencies of other packages:

| Package | Likely Pulled By | Use Case |
|---------|------------------|----------|
| `multipart>=0.0.17` | FastAPI, starlette | Multipart form-data handling for file uploads |
| `lxml>=5.3.0` | beautifulsoup4 | XML/HTML parsing used by source_ingestion_service |
| `tenacity>=9.0.0` | httpx or google-genai | Retry logic for network calls |
| `truststore>=0.9.0` | httpx | OS trust store for TLS verification (used in config) |

---

## Code Quality Observations

### No dead routes
All FastAPI route handlers registered in `app/main.py` are used:
- `routes_auth`, `routes_dashboard`, `routes_files`, `routes_workflows`, `routes_review`, `routes_audit`, `routes_settings`, `routes_chat`

### Database models — all referenced
All 21 SQLAlchemy ORM models in `app/models/database_models.py` have at least one import or query reference across the codebase.

### Enum members — all used
Spot-check: `FilingType.PARTNERSHIP`, `FilingType.TRUST_ESTATE`, `FilingType.PAYROLL`, `FilingType.SALES_TAX`, `FilingType.STATE_LOCAL` all appear in dashboard label mappings.

### Environment variables
**Config keys read by settings:** 60+  
**Documented in .env.example:** 60+  
**No mismatch detected**

---

## Recommendations

1. **Remove `pypdf`** — Not used; all PDF operations handled by PyMuPDF. Clean removal, no code changes needed.
2. **Remove `xlrd`** — Not used; .xls handling not implemented. If legacy Excel support is planned, revisit; otherwise remove.
3. **Review `alembic`** — If the product scales and requires schema evolution, add a migrations folder. For now, it's unused but not harmful since it only adds dependency weight. Consider removing if zero-downtime deployments are never needed.

---

## Notes

- **SECURITY-marked code:** No SECURITY comments found on any of the unused items. All marked SECURITY code remains active and referenced.
- **Dynamic references:** Checked for dynamic corpus assembly, state_profiles usage, enum member lookups, prompt field names, route paths, and config keys — no dead code patterns detected.
- **Staleness:** Most active modules were touched 11 days ago in commit `54f294e`. No orphaned files found.
