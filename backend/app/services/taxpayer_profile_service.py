"""Decide who the taxpayer is: filing status, ages, dependents.

Measured on nine real workpapers, this was the single largest source of error
after missing prior-year data. Filing status could not be determined on 7 of 7
cases and the engine fell back to Single; on one of them the accountant filed
married jointly with both spouses over 65, so the standard deduction was 15,750
against a correct 34,700. A wrong filing status invalidates the deduction, the
bracket table and every phase-out at once — it is not one wrong line, it is the
whole return.

The old logic read a single ``filing_status`` field and returned None if it was
absent, which it was on six of seven cases. It ignored the evidence that *was*
there: a spouse's name, a spouse's SSN, a spouse's date of birth.

Two things make this harder than reading a field:

**A workpaper contains other people's documents.** Partnership K-1s name other
partners, joint brokerage statements name co-owners, a dependent's 1098-T names
a student. One sample produced four different spouse names and two different
dates of birth. Candidates are therefore weighted by the document that stated
them: an organizer or a prior-year return describes *this* taxpayer; a K-1 does
not.

**Married does not say joint or separate.** The two differ by roughly half the
standard deduction. Joint is inferred because it is overwhelmingly the common
choice, but it is always flagged rather than assumed silently, because the
taxpayer's actual election is not derivable from the documents.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.services.tax_engine.tax_tables import FilingStatusTax

logger = get_logger(__name__)


#: How much a document's word is worth about *this* taxpayer's identity.
#: An organizer is filled in by the client about themselves; a K-1 arrives from
#: a partnership and may name anybody.
DOCUMENT_TRUST: dict[str, float] = {
    "client_organizer": 1.00,
    "prior_year_return": 0.95,
    "engagement_letter": 0.80,
    "consent_form": 0.80,
    "w2": 0.70,
    "1095": 0.60,
    "1098": 0.55,
    "irs_notice": 0.55,
    "correspondence": 0.40,
    "1099_int": 0.35,
    "1099_div": 0.35,
    "1099_b": 0.35,
    "1099_r": 0.35,
    "1099_misc": 0.35,
    "1099_nec": 0.35,
    "brokerage_statement": 0.30,
    "1098_t": 0.25,
    "k1": 0.20,
    "profit_and_loss": 0.20,
    "receipt": 0.10,
}
#: A spouse must be described by at least this many different fields before a
#: joint return is inferred. One name alone is the shape of somebody else.
_SPOUSE_CORROBORATING_FIELDS = 2

#: ...and the document saying so must be worth at least this much. Correspondence
#: (0.40) qualifies; a receipt (0.10) does not.
_SPOUSE_MIN_TRUST = 0.35

DEFAULT_TRUST = 0.30

#: Documents that describe the taxpayer's household, not just a transaction.
#:
#: Each of these has somewhere a spouse would appear — the organizer's spouse
#: box, the prior-year return's filing status line, the W-2's employee block —
#: so reading identity off one and finding no spouse is informative. A 1099-INT
#: names an account holder and tells you nothing about who they are married to,
#: which is why the brokerage forms are deliberately absent.
_STATUS_BEARING_DOCUMENTS: frozenset[str] = frozenset(
    {
        "client_organizer",
        "prior_year_return",
        "w2",
        "engagement_letter",
        "consent_form",
        "irs_notice",
    }
)

#: Below this, a resolved status still raises a review item. Every inference
#: that is not a stated status sits below it deliberately.
_RAISE_REVIEW_BELOW = 0.8

#: Single concluded from paperwork with no spouse box at all (1099s, K-1s, a
#: brokerage statement). Low on purpose: it must stay under
#: `_RAISE_REVIEW_BELOW` so the preparer is always asked to confirm it.
_WEAK_SINGLE_CONFIDENCE = 0.55

#: Single concluded *against* a signal pointing the other way — one
#: uncorroborated spouse name, or dependents that might make this head of
#: household. Lower again, because something in the documents disagrees.
#:
#: Single is the conservative direction in both cases: joint and head of
#: household each carry a larger standard deduction, so choosing single
#: overstates the tax rather than understating it, and an overstatement is
#: recoverable by amending. It is never chosen silently.
_FLAGGED_SINGLE_CONFIDENCE = 0.5

_FILING_STATUS_WORDS: dict[str, FilingStatusTax] = {
    "single": FilingStatusTax.SINGLE,
    "marriedfilingjointly": FilingStatusTax.MARRIED_JOINT,
    "marriedjoint": FilingStatusTax.MARRIED_JOINT,
    "joint": FilingStatusTax.MARRIED_JOINT,
    "mfj": FilingStatusTax.MARRIED_JOINT,
    "marriedfilingseparately": FilingStatusTax.MARRIED_SEPARATE,
    "marriedseparate": FilingStatusTax.MARRIED_SEPARATE,
    "mfs": FilingStatusTax.MARRIED_SEPARATE,
    "headofhousehold": FilingStatusTax.HEAD_OF_HOUSEHOLD,
    "hoh": FilingStatusTax.HEAD_OF_HOUSEHOLD,
    "qualifyingsurvivingspouse": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "qualifyingwidow": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "qss": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
    "widow": FilingStatusTax.QUALIFYING_SURVIVING_SPOUSE,
}

#: Placeholders the model returns instead of declining to answer.
_NON_VALUES = {
    "", "-", "n/a", "na", "none", "null", "unknown", "not provided",
    "on file", "xxx-xx-xxxx", "same", "see attached",
}

_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%y")


def _is_real(value: str | None) -> bool:
    if value is None:
        return False
    cleaned = str(value).strip().lower()
    return bool(cleaned) and cleaned not in _NON_VALUES


def _parse_date(value: str | None) -> date | None:
    from datetime import datetime

    if not _is_real(value):
        return None
    text = str(value).strip()
    for pattern in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, pattern).date()  # noqa: DTZ007
        except ValueError:
            continue
        # A two-digit year that lands in the future was meant to be last
        # century: "55" is 1955, not 2055.
        if parsed.year > date.today().year:  # noqa: DTZ011
            parsed = parsed.replace(year=parsed.year - 100)
        return parsed
    return None


#: Words that make a "spouse name" a business rather than a person. A workpaper
#: names the taxpayer's employers, brokers, trusts and partnerships throughout,
#: and one of them landed in the spouse box: on the CS 2 workpaper the entire
#: basis for filing a joint return was a spouse_name of "Harborview Solutions
#: LLC!", which cost that return the whole difference between the single and
#: joint standard deduction.
_ENTITY_WORDS: frozenset[str] = frozenset(
    {
        "llc", "llp", "inc", "incorporated", "corp", "corporation",
        "company", "ltd", "limited", "trust", "foundation", "partners",
        "partnership", "associates", "holdings", "group", "bank", "fund",
        "capital", "solutions", "services", "systems", "enterprises", "plc",
        "pllc",
        # "na", "co" and "pc" are deliberately absent: they are real surnames,
        # and rejecting a real spouse name leaves the status undetermined, which
        # falls back to single and understates a married couple's deduction by
        # half. A missed company name only costs a review item.
    }
)


def _looks_like_a_person(value: str | None) -> bool:
    """True when a name could be a human being rather than an organisation."""
    if not _is_real(value):
        return False
    text = str(value).strip()
    # Trailing punctuation is a transcription artefact, not part of a name.
    words = re.findall(r"[A-Za-z&]+", text)
    if not words:
        return False
    if "&" in text:
        return False
    return not any(word.lower().strip(".") in _ENTITY_WORDS for word in words)


@dataclass(frozen=True, slots=True)
class Candidate:
    value: str
    document_type: str

    @property
    def trust(self) -> float:
        return DOCUMENT_TRUST.get(self.document_type, DEFAULT_TRUST)


@dataclass(slots=True)
class Determination:
    """One resolved fact, with why it was chosen and how sure we are."""

    value: Any = None
    confidence: float = 0.0
    evidence: str = ""
    #: Distinct competing values, when the documents disagreed.
    conflicts: list[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.value is not None


@dataclass(slots=True)
class TaxpayerProfileResult:
    filing_status: Determination = field(default_factory=Determination)
    taxpayer_age_65: Determination = field(default_factory=Determination)
    spouse_age_65: Determination = field(default_factory=Determination)
    taxpayer_dob: date | None = None
    spouse_dob: date | None = None
    qualifying_children: int = 0
    other_dependents: int = 0
    #: Things a preparer must confirm before the return can be relied on.
    review_items: list[dict[str, str]] = field(default_factory=list)

    @property
    def seniors(self) -> int:
        """Senior additions this return is entitled to — not people over 65.

        The engine consumes this as `age_65_or_older` and adds one amount per
        count, so the spouse may only be counted on a return that actually has
        one. A spouse date of birth that failed to corroborate a married
        return would otherwise still buy a second addition on a single return:
        about 2,000 of deduction for a person who is not on it. Married filing
        separately is excluded too — each spouse takes their own — and so is
        qualifying surviving spouse, where the additional amount is the
        survivor's alone.
        """
        joint = self.filing_status.value is FilingStatusTax.MARRIED_JOINT
        return int(bool(self.taxpayer_age_65.value)) + int(
            joint and bool(self.spouse_age_65.value)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "filing_status": {
                "value": self.filing_status.value.value
                if isinstance(self.filing_status.value, FilingStatusTax)
                else self.filing_status.value,
                "confidence": self.filing_status.confidence,
                "evidence": self.filing_status.evidence,
                "conflicts": self.filing_status.conflicts,
            },
            "seniors": self.seniors,
            "taxpayer_age_65": self.taxpayer_age_65.evidence,
            "spouse_age_65": self.spouse_age_65.evidence,
            "qualifying_children": self.qualifying_children,
            "other_dependents": self.other_dependents,
            "review_items": self.review_items,
        }


class TaxpayerProfileService:
    """Resolves identity facts from competing extraction candidates."""

    def determine(
        self,
        *,
        normalized: dict[str, Any],
        candidates: dict[str, list[dict[str, str]]] | None,
        tax_year: int,
        prior_year_status: str | None = None,
    ) -> TaxpayerProfileResult:
        pools = self._pools(normalized, candidates or {})
        result = TaxpayerProfileResult()

        result.taxpayer_dob = self._best_date(pools.get("date_of_birth", []))
        result.spouse_dob = self._best_date(pools.get("spouse_date_of_birth", []))
        result.taxpayer_age_65 = self._age_65(result.taxpayer_dob, tax_year, "Taxpayer")
        result.spouse_age_65 = self._age_65(result.spouse_dob, tax_year, "Spouse")

        result.qualifying_children = self._count(normalized, "qualifying_children")
        result.other_dependents = self._count(normalized, "other_dependents")

        result.filing_status = self._filing_status(
            pools, result, prior_year_status, tax_year
        )
        self._raise_review_items(result, pools)
        return result

    # -- candidate handling ------------------------------------------------

    @staticmethod
    def _pools(
        normalized: dict[str, Any], candidates: dict[str, list[dict[str, str]]]
    ) -> dict[str, list[Candidate]]:
        pools: dict[str, list[Candidate]] = {}
        for field_name, entries in candidates.items():
            kept = [
                Candidate(str(e.get("value", "")), str(e.get("document_type", "")))
                for e in entries
                if _is_real(e.get("value"))
            ]
            if kept:
                pools[field_name] = kept
        # Anything the merge flattened but did not record a candidate for still
        # counts as evidence, at default trust.
        for field_name, value in normalized.items():
            if field_name not in pools and _is_real(value):
                pools[field_name] = [Candidate(str(value), "")]
        return pools

    @staticmethod
    def _best(pool: list[Candidate]) -> Candidate | None:
        """The candidate the most trustworthy documents agree on.

        Trust is summed per distinct value rather than taking the single most
        trusted document, so three 1099s naming the same spouse outweigh one
        K-1 naming somebody else.
        """
        if not pool:
            return None
        scores: Counter[str] = Counter()
        for candidate in pool:
            scores[candidate.value] += candidate.trust
        winner = scores.most_common(1)[0][0]
        return next(c for c in pool if c.value == winner)

    @staticmethod
    def _agreement_trust(pool: list[Candidate]) -> float:
        """Total trust behind the winning value, so corroboration counts.

        Counted once per document type. A long document is extracted in
        segments, so the same fact arrives several times from one source, and
        summing those made a single sighting look like independent
        corroboration: an ``unknown_workpaper`` worth 0.30 cleared a 0.5 bar by
        being seen twice.
        """
        if not pool:
            return 0.0
        scores: dict[str, dict[str, float]] = {}
        for candidate in pool:
            scores.setdefault(candidate.value, {})[candidate.document_type] = (
                candidate.trust
            )
        return max(sum(by_type.values()) for by_type in scores.values())

    def _best_date(self, pool: list[Candidate]) -> date | None:
        dated = [c for c in pool if _parse_date(c.value) is not None]
        best = self._best(dated)
        return _parse_date(best.value) if best else None

    @staticmethod
    def _count(normalized: dict[str, Any], key: str) -> int:
        raw = normalized.get(key)
        try:
            return max(0, int(str(raw).strip()))
        except (TypeError, ValueError):
            return 0

    # -- rules -------------------------------------------------------------

    @staticmethod
    def _age_65(born: date | None, tax_year: int, who: str) -> Determination:
        """65 or older is tested as born before January 2 of the following year."""
        if born is None:
            return Determination(
                value=False, confidence=0.0, evidence=f"{who} date of birth not found"
            )
        # Someone is treated as 65 on the day *before* their 65th birthday, so
        # for tax year 2025 the cutoff is being born before 2 January 1961 —
        # sixty-four years before the year after the tax year. Comparing
        # against January of the following year instead made every living
        # taxpayer a senior.
        qualifies = born < date(tax_year - 64, 1, 2)
        age = tax_year - born.year
        return Determination(
            value=qualifies,
            confidence=0.9,
            evidence=(
                f"{who} born {born:%d %b %Y}, age {age} at the end of {tax_year}"
                + (" — 65 or older" if qualifies else " — under 65")
            ),
        )

    def _filing_status(
        self,
        pools: dict[str, list[Candidate]],
        result: TaxpayerProfileResult,
        prior_year_status: str | None,
        tax_year: int,
    ) -> Determination:
        """Filing status, in descending order of how much the evidence is worth."""

        # 1. The documents say so outright.
        stated = self._best(pools.get("filing_status", []))
        if stated:
            key = re.sub(r"[^a-z0-9]+", "", stated.value.lower())
            mapped = _FILING_STATUS_WORDS.get(key)
            if mapped:
                return Determination(
                    value=mapped,
                    confidence=0.95,
                    evidence=f'Stated as "{stated.value}" on the {stated.document_type or "workpaper"}',
                )
            if key in {"married", "marriedfiling"}:
                # Deliberately unmapped: it does not distinguish joint from
                # separate, and the two differ by half the standard deduction.
                return self._married_but_unspecified(
                    f'The documents say "{stated.value}", which does not say joint or separate'
                )

        # 2. Last year's return, when this is a returning client.
        if prior_year_status:
            try:
                carried = FilingStatusTax(prior_year_status)
            except ValueError:
                carried = None
            if carried is not None:
                return Determination(
                    value=carried,
                    confidence=0.75,
                    evidence=(
                        f"Carried from the prior-year return ({carried.value}). "
                        "Confirm it has not changed."
                    ),
                )

        # 3. A spouse in the documents means a married return -- but only when
        #    the documents describe a person, and say more about them than a
        #    name. One bare spouse_name filed four of eight sample returns
        #    jointly that the accountant filed single, at a cost of the whole
        #    difference in the standard deduction each time. A workpaper is
        #    full of other people: an account holder, a partner, a dependent's
        #    parent, a name on page 49 of an organizer.
        spouse_signals = [
            name
            for name in ("spouse_ssn", "spouse_name", "spouse_date_of_birth", "spouse_wages")
            if pools.get(name)
        ]
        if "spouse_name" in spouse_signals and not any(
            _looks_like_a_person(c.value) for c in pools["spouse_name"]
        ):
            spouse_signals.remove("spouse_name")

        if spouse_signals:
            best_name = self._best(pools.get("spouse_name", []))
            # Trust is summed per distinct document type, so corroboration
            # counts but one document repeating itself does not.
            trust = max(
                (self._agreement_trust(pools[s]) for s in spouse_signals if pools.get(s)),
                default=0.0,
            )
            detail = ", ".join(s.replace("_", " ") for s in spouse_signals)
            # Two different facts about the same person -- a name and a date of
            # birth, a name and an SSN -- is what a spouse box on an organizer
            # looks like. A single stray field is what everybody else looks
            # like, however trusted the document carrying it.
            if len(spouse_signals) >= _SPOUSE_CORROBORATING_FIELDS and trust >= _SPOUSE_MIN_TRUST:
                return self._married_but_unspecified(
                    f"A spouse appears in the documents ({detail})"
                    + (f", named {best_name.value}" if best_name else "")
                )
            # One bare name is not the married return — measured, four of eight
            # sample returns. It is also not nothing, so this used to refuse
            # outright and Basic 9 produced no return at all on the strength of
            # a single name on a single page.
            #
            # Single is the answer that can be checked: it overstates the tax
            # rather than understating it, and a joint return could not be
            # filed from these documents anyway, because joint filing needs the
            # spouse's SSN and signature and neither is here. The name is
            # repeated in the evidence so the preparer can settle it at a
            # glance.
            return Determination(
                value=FilingStatusTax.SINGLE,
                confidence=_FLAGGED_SINGLE_CONFIDENCE,
                evidence=(
                    f"A spouse is mentioned ({detail})"
                    + (f", named {best_name.value}" if best_name else "")
                    + ", but nothing corroborates it: a workpaper names other "
                    "people throughout -- account holders, partners, a "
                    "dependant's parent -- and one stray name is not evidence "
                    "of a married return. Computed as single, which overstates "
                    "the tax rather than understating it. If that person is "
                    "the taxpayer's spouse, this return has to be prepared "
                    "jointly instead -- which also needs their SSN, and no "
                    "document here supplies one"
                ),
            )

        # 4. Unmarried with dependents may be head of household, but the
        #    support and household tests are not in the documents.
        #
        #    Head of household is not assumed, because its two tests — paying
        #    over half the cost of keeping up a home, and the qualifying person
        #    living there over half the year — are facts about the household
        #    that no form reports. Single is the fallback rather than a
        #    refusal: it is a valid status for a taxpayer with dependents who
        #    does not meet those tests, and head of household carries the
        #    larger standard deduction, so single overstates the tax. The
        #    review item names the test to ask about.
        if result.qualifying_children or result.other_dependents:
            count = result.qualifying_children + result.other_dependents
            return Determination(
                value=FilingStatusTax.SINGLE,
                confidence=_FLAGGED_SINGLE_CONFIDENCE,
                evidence=(
                    f"{count} dependent(s) are present and no spouse was found. "
                    "This may be head of household, which needs two facts no "
                    "document reports: whether the taxpayer paid over half the "
                    "cost of keeping up the home, and whether the qualifying "
                    "person lived there over half the year. Computed as single, "
                    "which takes the smaller standard deduction of the two -- "
                    "ask those two questions and reprocess as head of household "
                    "if the answer to both is yes"
                ),
            )

        # 5. No spouse and no dependents, on documents that would have said so.
        #
        #    This is a determination, not a failure to find one. The five
        #    statuses are not a menu: four of them require somebody else. Joint
        #    and separate need a spouse, surviving spouse needs a deceased one
        #    plus a dependent child, and head of household needs a qualifying
        #    person. With none of those present, single is what is left.
        #
        #    What makes the absence meaningful is *which* documents were read. A
        #    client organizer has a spouse box; a prior-year return states the
        #    status outright; a W-2 names the employee. If we successfully read
        #    identity off one of those and it described nobody but the taxpayer,
        #    that is evidence of absence rather than absence of evidence.
        #
        #    Treating this as undetermined instead refused to compute the sample
        #    return at all — a single filer with a full workpaper, where single
        #    was both the only available answer and the right one.
        identity_fields = ("taxpayer_name", "ssn", "date_of_birth", "filing_status")
        witnesses = sorted(
            {
                candidate.document_type
                for name in identity_fields
                for candidate in pools.get(name, [])
                if candidate.document_type in _STATUS_BEARING_DOCUMENTS
            }
        )
        if witnesses:
            described = ", ".join(w.replace("_", " ") for w in witnesses)
            return Determination(
                value=FilingStatusTax.SINGLE,
                confidence=0.70,
                evidence=(
                    f"No spouse and no dependents appear anywhere in the "
                    f"documents, and the taxpayer's own details were read from "
                    f"a {described}, which would have named a spouse if there "
                    f"were one. Single is the only status the remaining "
                    f"evidence supports — confirm it if the taxpayer married, "
                    f"separated or gained a dependent during the year."
                ),
            )

        # 5b. The same reasoning on weaker paperwork, at lower confidence.
        #
        #     Requiring one of the six status-bearing documents refused the
        #     return outright on workpapers that happen not to contain one.
        #     Measured across the sample corpus: Basic 4's identity came off
        #     1099s and CS 2 is an S-corp/K-1 case with no W-2 at all, so both
        #     produced no package — after OCR, classification and extraction had
        #     all succeeded. Most of the corpus failed this way.
        #
        #     A 1099 or a K-1 is genuinely weaker evidence of absence than an
        #     organizer: it names one account holder, and nothing on it has a
        #     spouse box. But the choice here is not between a safe answer and a
        #     risky one. It is between "single, at low confidence, with a review
        #     item a preparer must clear" and "no return at all" — and the
        #     preparer cannot check a return that does not exist. The review
        #     item is the mitigation, and it is the same one Basic 5 and CS 3
        #     already ship with.
        #
        #     SECURITY-of-the-numbers: this must never outrank a stated status
        #     (step 1), a carried prior-year status (step 2), any corroborated
        #     spouse (step 3) or a dependent (step 4). It is reached only when
        #     every one of those found nothing, and it never resolves above
        #     `_RAISE_REVIEW_BELOW`, so `_raise_review_items` always speaks.
        #
        #     The test is "is the taxpayer identified at all", not "which
        #     document identified them". A field that survived the merge
        #     without a recorded candidate carries no document type, and
        #     requiring one refused workpapers whose name and SSN had been read
        #     perfectly well — the same failure one level down.
        identified = sorted(
            {
                candidate.document_type
                for name in identity_fields
                for candidate in pools.get(name, [])
                if candidate.document_type
            }
        )
        if identified or any(pools.get(name) for name in identity_fields):
            described = (
                ", ".join(d.replace("_", " ") for d in identified)
                if identified
                else "workpaper with no organizer, W-2 or prior-year return in it"
            )
            return Determination(
                value=FilingStatusTax.SINGLE,
                confidence=_WEAK_SINGLE_CONFIDENCE,
                evidence=(
                    f"No filing status, no spouse and no dependents appear "
                    f"anywhere in the documents. The taxpayer was identified "
                    f"from a {described} — weaker evidence of a one-person "
                    f"household than an organizer, a W-2 or last year's return, "
                    f"because none of those documents has a spouse box. Single "
                    f"is what the remaining evidence supports and the return "
                    f"below is computed on it: confirm the status before "
                    f"filing, and reprocess with the organizer or last year's "
                    f"return if this taxpayer is married"
                ),
            )

        # 6. Nothing at all: no status, nobody else, and not one document that
        #    identified the taxpayer. There is nobody here to file for, so this
        #    is genuinely undetermined rather than conservatively refused.
        return Determination(
            value=None,
            confidence=0.0,
            evidence=(
                "No filing status stated, no spouse or dependents found, and no "
                "document identified the taxpayer by name, SSN or date of birth"
            ),
        )

    @staticmethod
    def _married_but_unspecified(evidence: str) -> Determination:
        """Married, but the documents do not say joint or separate.

        Joint is used because it is the overwhelmingly common election and
        separate is usually a deliberate, unusual choice. It is never silent:
        the caller always raises a review item, because this is the taxpayer's
        election and not a fact about their documents.
        """
        return Determination(
            value=FilingStatusTax.MARRIED_JOINT,
            confidence=0.55,
            evidence=(
                f"{evidence}. Assumed married filing jointly, which is the usual "
                "election — confirm it is not separate."
            ),
        )

    # -- review ------------------------------------------------------------

    def _raise_review_items(
        self, result: TaxpayerProfileResult, pools: dict[str, list[Candidate]]
    ) -> None:
        status = result.filing_status

        if not status.resolved:
            result.review_items.append(
                {
                    "field": "filing_status",
                    "title": "Filing status could not be determined",
                    "description": (
                        f"{status.evidence}. No return was computed, because "
                        "filing status sets the standard deduction, the "
                        "bracket table and most phase-outs — a return on an "
                        "assumed status foots perfectly and is wrong in all "
                        "three at once. Supply the status, or upload the "
                        "organizer or last year's return, and reprocess."
                    ),
                }
            )
        elif status.confidence < _RAISE_REVIEW_BELOW:
            result.review_items.append(
                {
                    "field": "filing_status",
                    "title": (
                        # A status inferred from paperwork with no spouse box is
                        # the weakest thing this service will still act on, so
                        # the title says out loud that it gates filing.
                        f"Confirm filing status before filing: {status.value.value}"
                        if status.confidence <= _WEAK_SINGLE_CONFIDENCE
                        else f"Confirm filing status: {status.value.value}"
                    ),
                    "description": status.evidence,
                }
            )

        # Conflicting identity across documents is worth saying out loud: it is
        # the signal that the workpaper contains somebody else's paperwork.
        for name, label in (
            ("date_of_birth", "date of birth"),
            ("spouse_date_of_birth", "spouse date of birth"),
            ("spouse_name", "spouse name"),
        ):
            distinct = {c.value for c in pools.get(name, [])}
            if len(distinct) > 1:
                chosen = (
                    f"{result.taxpayer_dob:%d %b %Y}"
                    if name == "date_of_birth" and result.taxpayer_dob
                    else f"{result.spouse_dob:%d %b %Y}"
                    if name == "spouse_date_of_birth" and result.spouse_dob
                    else "the most-corroborated value"
                )
                result.review_items.append(
                    {
                        "field": name,
                        "title": f"Documents disagree on the {label}",
                        "description": (
                            f"{len(distinct)} different values were found: "
                            f"{', '.join(sorted(distinct)[:6])}. "
                            f"Used {chosen}, chosen by which documents are about "
                            "this taxpayer rather than about other people named "
                            "in the workpaper. A workpaper often contains "
                            "partnership K-1s, joint statements or a dependent's "
                            "forms, so confirm the right person was used."
                        ),
                    }
                )

        if result.taxpayer_dob is None:
            result.review_items.append(
                {
                    "field": "date_of_birth",
                    "title": "Date of birth not found",
                    "description": (
                        "Age drives the larger standard deduction at 65 and the "
                        "Schedule 1-A senior deduction. Without it both are "
                        "omitted, understating deductions by up to 8,000 per "
                        "person."
                    ),
                }
            )
