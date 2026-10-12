---
name: research-tax-rule
description: Research a US federal, state or multi-state tax rule, form line, worksheet or constant from official sources and cache it with citations. Use before implementing or changing any tax calculation, threshold, or form line.
argument-hint: "[topic, e.g. 'Schedule A line 5e SALT cap 2025']"
context: fork
agent: tax-researcher
background: false
---

Research: $ARGUMENTS

1. **Cache check first.** Search `docs/tax-research/` for an existing note. If
   one answers the question, return its summary and stop - no web calls. If one
   covers the topic partially, extend it rather than writing a second note.

2. **Sources.** Use the authority tier the product itself may cite:
   `ALLOWLIST_DOMAINS` in `backend/app/services/tax_research_crawler.py`. Read
   that list rather than recalling it. Order: IRS instructions and publications,
   Revenue Procedures and notices, the Code, public laws, then the state agency
   from `state_profiles`. No blogs, no vendor sites, no preparer marketing.

3. **Fetch narrowly** - the section that answers the question, not the whole
   publication.

4. **Write `docs/tax-research/<kebab-topic>.md`** containing:
   - the rule in plain terms
   - exact figures by filing status, with the tax year
   - line-by-line logic if it is a form or worksheet
   - edge cases, and interactions with other lines
   - a citation (URL plus section) for **every** figure
   - `figures_as_of:` the date you recorded them, and `figures_source_url:`
   - `status: confirmed | verify` - use `verify` when sources conflict, when
     the guidance is not final, or when a 2025 figure might be superseded

5. **For 2025, check both layers.** Rev. Proc. 2024-40 set the inflation
   adjustments in October 2024; the One Big Beautiful Bill Act (Pub. L. 119-21,
   4 July 2025) then superseded several of them. A note giving one without
   checking the other looks settled and is not.

6. **If the figure belongs in the engine**, propose the `Constant` entry for
   `backend/app/services/tax_engine/tax_authority.py` - value, `Authority`
   (citation, URL, kind), and `verified=False` until a human confirms the
   pairing against primary text. Do not edit that file from here.

7. **Do not write into `backend/app/tax_knowledge/`.** Those corpora are what
   the assistant quotes to users; adding to them changes what the product cites
   and is a reviewed code change, not a research artifact.

Return 12 lines or fewer: key figures, citations, the note path, open questions.
