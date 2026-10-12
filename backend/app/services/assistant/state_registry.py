"""Every jurisdiction the assistant accepts, and where its tax law is published.

This is structured input, not knowledge. It does three jobs:

* **Validates.** ``selected_state`` on a request must be a code in this table
  or the request is rejected. The model never infers the jurisdiction.
* **Routes.** Each entry names the agencies that administer the state's taxes
  and their domains, so prompts and search queries can point at the state's
  own publications rather than at whatever ranks first.
* **Reminds.** A few structural features - no tax on wages, community
  property, local income taxes, a gross receipts tax instead of a sales tax -
  are listed so the answer cannot quietly omit them. They are *hints to
  verify*, handed to the model as such and never as citable authority.

What is deliberately absent: rates, brackets, thresholds, deadlines, dollar
amounts. Those change every year, and a stale figure stated confidently is the
failure this assistant exists to avoid. Every figure in an answer comes from
Google Search grounding, with its source.

Adding a field: ask whether it would be wrong twelve months from now. If yes,
it does not belong here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Feature(str, Enum):
    """Structural features an answer about the state must not omit."""

    NO_WAGE_INCOME_TAX = "no_wage_income_tax"
    NO_STATEWIDE_SALES_TAX = "no_statewide_sales_tax"
    LOCAL_SALES_TAX = "local_sales_tax"
    LOCAL_INCOME_TAX = "local_income_tax"
    COMMUNITY_PROPERTY = "community_property"
    ELECTIVE_COMMUNITY_PROPERTY = "elective_community_property"
    GROSS_RECEIPTS_TAX = "gross_receipts_tax"
    OWN_TAX_SYSTEM = "own_tax_system"


FEATURE_LABELS: dict[Feature, str] = {
    Feature.NO_WAGE_INCOME_TAX: "No individual income tax on wages",
    Feature.NO_STATEWIDE_SALES_TAX: "No statewide sales tax",
    Feature.LOCAL_SALES_TAX: "Local sales taxes on top of (or instead of) a state rate",
    Feature.LOCAL_INCOME_TAX: "Local (city, county or school district) income taxes",
    Feature.COMMUNITY_PROPERTY: "Community property state",
    Feature.ELECTIVE_COMMUNITY_PROPERTY: "Elective (opt-in) community property",
    Feature.GROSS_RECEIPTS_TAX: "Taxes business gross receipts",
    Feature.OWN_TAX_SYSTEM: "Territory with its own income tax system",
}


@dataclass(frozen=True, slots=True)
class Agency:
    name: str
    url: str
    #: What this agency administers, when a state splits the work.
    administers: str = ""


@dataclass(frozen=True, slots=True)
class Jurisdiction:
    code: str
    name: str
    #: "state", "district" or "territory".
    kind: str
    #: Primary agency first.
    agencies: tuple[Agency, ...]
    #: Where the primary agency publishes news and notices.
    updates_url: str
    #: Official hostnames for this jurisdiction's tax administration.
    domains: tuple[str, ...]
    features: frozenset[Feature] = frozenset()
    #: Name of the gross receipts / margin tax, when there is one.
    business_tax: str = ""
    #: Short structural reminders. Never figures.
    hints: tuple[str, ...] = field(default_factory=tuple)

    @property
    def agency(self) -> Agency:
        return self.agencies[0]

    @property
    def taxes_wage_income(self) -> bool:
        return Feature.NO_WAGE_INCOME_TAX not in self.features

    @property
    def has_statewide_sales_tax(self) -> bool:
        return Feature.NO_STATEWIDE_SALES_TAX not in self.features

    @property
    def feature_labels(self) -> list[str]:
        labels = [FEATURE_LABELS[f] for f in Feature if f in self.features]
        if self.business_tax:
            labels = [
                f"{FEATURE_LABELS[Feature.GROSS_RECEIPTS_TAX]} ({self.business_tax})"
                if label == FEATURE_LABELS[Feature.GROSS_RECEIPTS_TAX]
                else label
                for label in labels
            ]
        return labels


_F = Feature
_NO_WAGE = _F.NO_WAGE_INCOME_TAX
_NO_SALES = _F.NO_STATEWIDE_SALES_TAX
_LOCAL_SALES = _F.LOCAL_SALES_TAX
_LOCAL_INCOME = _F.LOCAL_INCOME_TAX
_CP = _F.COMMUNITY_PROPERTY
_ECP = _F.ELECTIVE_COMMUNITY_PROPERTY
_GRT = _F.GROSS_RECEIPTS_TAX


def _j(
    code: str,
    name: str,
    agency: str,
    url: str,
    updates: str,
    domains: tuple[str, ...],
    features: tuple[Feature, ...] = (),
    *,
    kind: str = "state",
    extra_agencies: tuple[Agency, ...] = (),
    business_tax: str = "",
    hints: tuple[str, ...] = (),
) -> Jurisdiction:
    return Jurisdiction(
        code=code,
        name=name,
        kind=kind,
        agencies=(Agency(agency, url), *extra_agencies),
        updates_url=updates,
        domains=domains,
        features=frozenset(features) | (frozenset({_GRT}) if business_tax else frozenset()),
        business_tax=business_tax,
        hints=hints,
    )


#: Ordered by code so the selector, the map and any diff read the same way.
JURISDICTIONS: tuple[Jurisdiction, ...] = (
    _j("AK", "Alaska", "Alaska Department of Revenue, Tax Division",
       "https://tax.alaska.gov/", "https://tax.alaska.gov/news/",
       ("tax.alaska.gov",), (_NO_WAGE, _NO_SALES, _LOCAL_SALES, _ECP),
       hints=(("No state sales tax, but many boroughs and cities levy one; remote "
              "sellers deal with the Alaska Remote Seller Sales Tax Commission."),)),
    _j("AL", "Alabama", "Alabama Department of Revenue",
       "https://www.revenue.alabama.gov/", "https://www.revenue.alabama.gov/news/",
       ("revenue.alabama.gov", "www.revenue.alabama.gov"), (_LOCAL_SALES, _LOCAL_INCOME),
       hints=("Some Alabama cities and counties levy occupational (wage) taxes.",)),
    _j("AR", "Arkansas", "Arkansas Department of Finance and Administration",
       "https://www.dfa.arkansas.gov/", "https://www.dfa.arkansas.gov/news/",
       ("dfa.arkansas.gov", "www.dfa.arkansas.gov"), (_LOCAL_SALES,)),
    _j("AZ", "Arizona", "Arizona Department of Revenue",
       "https://azdor.gov/", "https://azdor.gov/news-notices",
       ("azdor.gov", "www.azdor.gov"), (_LOCAL_SALES, _CP),
       hints=("Arizona's sales tax is a Transaction Privilege Tax levied on the seller.",)),
    _j("CA", "California", "California Franchise Tax Board",
       "https://www.ftb.ca.gov/", "https://www.cdtfa.ca.gov/news/",
       ("ftb.ca.gov", "www.ftb.ca.gov", "cdtfa.ca.gov", "www.cdtfa.ca.gov",
        "edd.ca.gov", "www.edd.ca.gov"),
       (_LOCAL_SALES, _CP),
       extra_agencies=(
           Agency("California Department of Tax and Fee Administration",
                  "https://www.cdtfa.ca.gov/", "sales and use tax"),
           Agency("California Employment Development Department",
                  "https://edd.ca.gov/", "payroll taxes"),
       ),
       hints=(("Income and franchise tax: Franchise Tax Board. Sales and use tax: "
              "CDTFA. Payroll tax: EDD. Name the right one."),)),
    _j("CO", "Colorado", "Colorado Department of Revenue",
       "https://tax.colorado.gov/", "https://tax.colorado.gov/news",
       ("tax.colorado.gov", "cdor.colorado.gov"), (_LOCAL_SALES,),
       hints=("Home-rule cities administer their own sales tax.",)),
    _j("CT", "Connecticut", "Connecticut Department of Revenue Services",
       "https://portal.ct.gov/DRS", "https://portal.ct.gov/DRS/Press-Room/Press-Releases",
       ("portal.ct.gov",)),
    _j("DC", "District of Columbia", "DC Office of Tax and Revenue",
       "https://otr.cfo.dc.gov/", "https://otr.cfo.dc.gov/page/otr-newsroom",
       ("otr.cfo.dc.gov",), kind="district"),
    _j("DE", "Delaware", "Delaware Division of Revenue",
       "https://revenue.delaware.gov/", "https://revenue.delaware.gov/tax-updates/",
       ("revenue.delaware.gov", "revenuefiles.delaware.gov"), (_NO_SALES, _LOCAL_INCOME),
       business_tax="Delaware gross receipts tax",
       hints=("No sales tax at any level. The City of Wilmington levies a wage tax.",)),
    _j("FL", "Florida", "Florida Department of Revenue",
       "https://floridarevenue.com/", "https://floridarevenue.com/taxes/tips/Pages/default.aspx",
       ("floridarevenue.com", "www.floridarevenue.com"), (_NO_WAGE, _LOCAL_SALES, _ECP),
       hints=("No individual income tax, but a corporate income tax applies.",)),
    _j("GA", "Georgia", "Georgia Department of Revenue",
       "https://dor.georgia.gov/", "https://dor.georgia.gov/press-releases",
       ("dor.georgia.gov",), (_LOCAL_SALES,)),
    _j("HI", "Hawaii", "Hawaii Department of Taxation",
       "https://tax.hawaii.gov/", "https://tax.hawaii.gov/news/",
       ("tax.hawaii.gov",), (_LOCAL_SALES,), business_tax="Hawaii general excise tax",
       hints=(("The General Excise Tax is levied on the seller and reaches most "
              "business income, including services; it is not a sales tax."),)),
    _j("IA", "Iowa", "Iowa Department of Revenue",
       "https://revenue.iowa.gov/", "https://revenue.iowa.gov/newsroom",
       ("revenue.iowa.gov", "tax.iowa.gov"), (_LOCAL_SALES, _LOCAL_INCOME),
       hints=("Many school districts levy an income surtax.",)),
    _j("ID", "Idaho", "Idaho State Tax Commission",
       "https://tax.idaho.gov/", "https://tax.idaho.gov/news/",
       ("tax.idaho.gov",), (_LOCAL_SALES, _CP)),
    _j("IL", "Illinois", "Illinois Department of Revenue",
       "https://tax.illinois.gov/", "https://tax.illinois.gov/research/legalinformation.html",
       ("tax.illinois.gov", "www2.illinois.gov"), (_LOCAL_SALES,)),
    _j("IN", "Indiana", "Indiana Department of Revenue",
       "https://www.in.gov/dor/", "https://www.in.gov/dor/news-media-and-publications/",
       ("in.gov", "www.in.gov"), (_LOCAL_INCOME,),
       hints=("Every Indiana county levies a local income tax.",)),
    _j("KS", "Kansas", "Kansas Department of Revenue",
       "https://www.ksrevenue.gov/", "https://www.ksrevenue.gov/prnotices.html",
       ("ksrevenue.gov", "www.ksrevenue.gov"), (_LOCAL_SALES,)),
    _j("KY", "Kentucky", "Kentucky Department of Revenue",
       "https://revenue.ky.gov/", "https://revenue.ky.gov/News/Pages/default.aspx",
       ("revenue.ky.gov",), (_LOCAL_INCOME, _ECP),
       hints=("Many Kentucky cities and counties levy occupational license taxes on wages.",)),
    _j("LA", "Louisiana", "Louisiana Department of Revenue",
       "https://revenue.louisiana.gov/", "https://revenue.louisiana.gov/NewsAndPublications",
       ("revenue.louisiana.gov",), (_LOCAL_SALES, _CP),
       hints=("Parish sales taxes are administered separately from the state's.",)),
    _j("MA", "Massachusetts", "Massachusetts Department of Revenue",
       "https://www.mass.gov/orgs/massachusetts-department-of-revenue",
       "https://www.mass.gov/lists/dor-news-and-press-releases",
       ("mass.gov", "www.mass.gov")),
    _j("MD", "Maryland", "Comptroller of Maryland",
       "https://www.marylandtaxes.gov/", "https://www.marylandtaxes.gov/news/index.php",
       ("marylandtaxes.gov", "www.marylandtaxes.gov"), (_LOCAL_INCOME,),
       hints=(("Counties and Baltimore City levy a local income tax collected on the "
              "state return."),)),
    _j("ME", "Maine", "Maine Revenue Services",
       "https://www.maine.gov/revenue/", "https://www.maine.gov/revenue/news",
       ("maine.gov", "www.maine.gov")),
    _j("MI", "Michigan", "Michigan Department of Treasury",
       "https://www.michigan.gov/taxes", "https://www.michigan.gov/taxes/news",
       ("michigan.gov", "www.michigan.gov"), (_LOCAL_INCOME,),
       hints=("A number of Michigan cities, Detroit among them, levy a city income tax.",)),
    _j("MN", "Minnesota", "Minnesota Department of Revenue",
       "https://www.revenue.state.mn.us/", "https://www.revenue.state.mn.us/news-and-legal",
       ("revenue.state.mn.us", "www.revenue.state.mn.us"), (_LOCAL_SALES,)),
    _j("MO", "Missouri", "Missouri Department of Revenue",
       "https://dor.mo.gov/", "https://dor.mo.gov/news/",
       ("dor.mo.gov",), (_LOCAL_SALES, _LOCAL_INCOME),
       hints=("Kansas City and St. Louis levy an earnings tax.",)),
    _j("MS", "Mississippi", "Mississippi Department of Revenue",
       "https://www.dor.ms.gov/", "https://www.dor.ms.gov/news",
       ("dor.ms.gov", "www.dor.ms.gov"), (_LOCAL_SALES,)),
    _j("MT", "Montana", "Montana Department of Revenue",
       "https://mtrevenue.gov/", "https://mtrevenue.gov/news/",
       ("mtrevenue.gov",), (_NO_SALES,),
       hints=("No general sales tax; some resort communities levy a local option tax.",)),
    _j("NC", "North Carolina", "North Carolina Department of Revenue",
       "https://www.ncdor.gov/", "https://www.ncdor.gov/news",
       ("ncdor.gov", "www.ncdor.gov"), (_LOCAL_SALES,)),
    _j("ND", "North Dakota", "North Dakota Office of State Tax Commissioner",
       "https://www.tax.nd.gov/", "https://www.tax.nd.gov/news",
       ("tax.nd.gov", "www.tax.nd.gov"), (_LOCAL_SALES,)),
    _j("NE", "Nebraska", "Nebraska Department of Revenue",
       "https://revenue.nebraska.gov/", "https://revenue.nebraska.gov/news",
       ("revenue.nebraska.gov",), (_LOCAL_SALES,)),
    _j("NH", "New Hampshire", "New Hampshire Department of Revenue Administration",
       "https://www.revenue.nh.gov/", "https://www.revenue.nh.gov/news-and-media",
       ("revenue.nh.gov", "www.revenue.nh.gov"), (_NO_WAGE, _NO_SALES),
       hints=(("No tax on wages. The Interest and Dividends Tax was repealed for "
               "recent periods but applies to earlier years - check the year."),
              "Business Profits Tax and Business Enterprise Tax reach business activity.")),
    _j("NJ", "New Jersey", "New Jersey Division of Taxation",
       "https://www.nj.gov/treasury/taxation/", "https://www.nj.gov/treasury/taxation/news.shtml",
       ("nj.gov", "www.nj.gov")),
    _j("NM", "New Mexico", "New Mexico Taxation and Revenue Department",
       "https://www.tax.newmexico.gov/", "https://www.tax.newmexico.gov/news-alerts/",
       ("tax.newmexico.gov", "www.tax.newmexico.gov"), (_LOCAL_SALES, _CP),
       business_tax="New Mexico gross receipts tax",
       hints=("The Gross Receipts Tax replaces a sales tax and reaches services broadly.",)),
    _j("NV", "Nevada", "Nevada Department of Taxation",
       "https://tax.nv.gov/", "https://tax.nv.gov/news/",
       ("tax.nv.gov",), (_NO_WAGE, _LOCAL_SALES, _CP), business_tax="Nevada commerce tax",
       hints=("Payroll is separately subject to the Modified Business Tax.",)),
    _j("NY", "New York", "New York State Department of Taxation and Finance",
       "https://www.tax.ny.gov/", "https://www.tax.ny.gov/press/",
       ("tax.ny.gov", "www.tax.ny.gov"), (_LOCAL_SALES, _LOCAL_INCOME),
       hints=(("New York City and Yonkers levy their own income taxes, collected on "
              "the state return."),)),
    _j("OH", "Ohio", "Ohio Department of Taxation",
       "https://tax.ohio.gov/", "https://tax.ohio.gov/researcher/tax-alerts",
       ("tax.ohio.gov",), (_LOCAL_SALES, _LOCAL_INCOME),
       business_tax="Ohio commercial activity tax",
       hints=(("Most Ohio municipalities levy an income tax, and many school "
              "districts levy one too."),)),
    _j("OK", "Oklahoma", "Oklahoma Tax Commission",
       "https://oklahoma.gov/tax.html", "https://oklahoma.gov/tax/about-us/newsroom.html",
       ("oklahoma.gov",), (_LOCAL_SALES,)),
    _j("OR", "Oregon", "Oregon Department of Revenue",
       "https://www.oregon.gov/dor/", "https://www.oregon.gov/dor/pages/news.aspx",
       ("oregon.gov", "www.oregon.gov"), (_NO_SALES, _LOCAL_INCOME),
       business_tax="Oregon corporate activity tax",
       hints=(("Portland-area residents and workers can owe regional and county "
              "income taxes."),)),
    _j("PA", "Pennsylvania", "Pennsylvania Department of Revenue",
       "https://www.revenue.pa.gov/",
       "https://www.revenue.pa.gov/GeneralTaxInformation/News%20and%20Statistics/Pages/default.aspx",
       ("revenue.pa.gov", "www.revenue.pa.gov"), (_LOCAL_SALES, _LOCAL_INCOME),
       hints=(("Most municipalities and school districts levy a local earned income "
              "tax; Philadelphia levies its own wage tax."),)),
    _j("PR", "Puerto Rico", "Departamento de Hacienda de Puerto Rico",
       "https://hacienda.pr.gov/", "https://hacienda.pr.gov/sala-de-prensa",
       ("hacienda.pr.gov",), (_LOCAL_SALES, _F.OWN_TAX_SYSTEM), kind="territory",
       hints=(("Federal rules for bona fide residents of Puerto Rico differ "
              "substantially from those for the fifty states."),)),
    _j("RI", "Rhode Island", "Rhode Island Division of Taxation",
       "https://tax.ri.gov/", "https://tax.ri.gov/media-center", ("tax.ri.gov",)),
    _j("SC", "South Carolina", "South Carolina Department of Revenue",
       "https://dor.sc.gov/", "https://dor.sc.gov/communications",
       ("dor.sc.gov",), (_LOCAL_SALES,)),
    _j("SD", "South Dakota", "South Dakota Department of Revenue",
       "https://dor.sd.gov/", "https://dor.sd.gov/newsroom/",
       ("dor.sd.gov",), (_NO_WAGE, _LOCAL_SALES, _ECP)),
    _j("TN", "Tennessee", "Tennessee Department of Revenue",
       "https://www.tn.gov/revenue.html", "https://www.tn.gov/revenue/news.html",
       ("tn.gov", "www.tn.gov"), (_NO_WAGE, _LOCAL_SALES, _ECP),
       hints=("Franchise and excise tax reaches businesses operating in the state.",)),
    _j("TX", "Texas", "Texas Comptroller of Public Accounts",
       "https://comptroller.texas.gov/taxes/", "https://comptroller.texas.gov/about/media-center/news/",
       ("comptroller.texas.gov",), (_NO_WAGE, _LOCAL_SALES, _CP),
       business_tax="Texas franchise (margin) tax",
       hints=(("A question about owing Texas tax is usually about franchise tax or "
              "sales tax, not income tax."),)),
    _j("UT", "Utah", "Utah State Tax Commission",
       "https://tax.utah.gov/", "https://tax.utah.gov/announcements",
       ("tax.utah.gov",), (_LOCAL_SALES,)),
    _j("VA", "Virginia", "Virginia Department of Taxation",
       "https://www.tax.virginia.gov/", "https://www.tax.virginia.gov/news",
       ("tax.virginia.gov", "www.tax.virginia.gov"), (_LOCAL_SALES,)),
    _j("VT", "Vermont", "Vermont Department of Taxes",
       "https://tax.vermont.gov/", "https://tax.vermont.gov/media-room",
       ("tax.vermont.gov",), (_LOCAL_SALES,)),
    _j("WA", "Washington", "Washington Department of Revenue",
       "https://dor.wa.gov/", "https://dor.wa.gov/about/news-releases",
       ("dor.wa.gov",), (_NO_WAGE, _LOCAL_SALES, _CP),
       business_tax="Washington business and occupation (B&O) tax",
       hints=(("No tax on wages, but a separate capital gains excise tax reaches "
              "certain long-term gains of individuals."),)),
    _j("WI", "Wisconsin", "Wisconsin Department of Revenue",
       "https://www.revenue.wi.gov/", "https://www.revenue.wi.gov/Pages/News/Home.aspx",
       ("revenue.wi.gov", "www.revenue.wi.gov"), (_LOCAL_SALES, _CP),
       hints=("Wisconsin's marital property law is a community property system.",)),
    _j("WV", "West Virginia", "West Virginia Tax Division",
       "https://tax.wv.gov/", "https://tax.wv.gov/Pages/TaxNews.aspx",
       ("tax.wv.gov",), (_LOCAL_SALES,)),
    _j("WY", "Wyoming", "Wyoming Department of Revenue",
       "https://revenue.wyo.gov/", "https://revenue.wyo.gov/news",
       ("revenue.wyo.gov",), (_NO_WAGE, _LOCAL_SALES)),
)

_BY_CODE: dict[str, Jurisdiction] = {j.code: j for j in JURISDICTIONS}

#: The request allow-list. Anything else is rejected at the API boundary.
ALLOWED_CODES: frozenset[str] = frozenset(_BY_CODE)


def get(code: str | None) -> Jurisdiction | None:
    if not code:
        return None
    return _BY_CODE.get(code.strip().upper())


def require(code: str) -> Jurisdiction:
    found = get(code)
    if found is None:
        raise KeyError(code)
    return found


# ---------------------------------------------------------------------------
# Finding states named in text
# ---------------------------------------------------------------------------

#: Two-letter codes that are also common English words or abbreviations. In
#: free text "IN", "OR" and "ME" are far more often words than states, "LA"
#: is usually the city and "CO" a company, so a bare code is only read as a
#: state when it is not one of these. Full names are always read.
#: A false positive is worse than a miss: it obliges the answer to cover a
#: state nobody asked about, which forces a regeneration and then a fallback.
#: So tax vocabulary counts as ambiguous too - "AR" is accounts receivable,
#: "DC" a defined contribution plan, "VA" Veterans Affairs.
_AMBIGUOUS_CODES: frozenset[str] = frozenset(
    {"IN", "OR", "ME", "OK", "HI", "OH", "ID", "LA", "CO", "AL", "DE", "MA",
     "MD", "PA", "GA", "MO", "ND", "NE", "SD", "SC", "MS", "MT", "VA", "PR",
     "AR", "CT", "DC", "NM"}
)

#: Alternative spellings that name a jurisdiction. Matched before the plain
#: names, so "Washington, D.C." is DC and never Washington state.
_ALIASES: tuple[tuple[str, str], ...] = (
    ("washington, d.c.", "DC"),
    ("washington d.c.", "DC"),
    ("washington, dc", "DC"),
    ("washington dc", "DC"),
    ("district of columbia", "DC"),
    ("d.c.", "DC"),
    ("new york city", "NY"),
    ("nyc", "NY"),
)

_NAME_PATTERN = re.compile(
    "|".join(
        sorted(
            (re.escape(j.name.lower()) for j in JURISDICTIONS),
            key=len,
            reverse=True,
        )
    )
)
_ALIAS_PATTERN = re.compile(
    "|".join(
        rf"(?<![a-z]){re.escape(alias)}(?![a-z])"
        for alias, _ in sorted(_ALIASES, key=lambda a: len(a[0]), reverse=True)
    )
)
_ALIAS_CODES = dict(_ALIASES)
_CODE_PATTERN = re.compile(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])")


def find_states(text: str) -> list[str]:
    """Codes of every jurisdiction named in ``text``, in order of first mention.

    Reads full names ("West Virginia" before "Virginia", "Arkansas" never as
    "Kansas"), a few aliases, and upper-case two-letter codes that are not
    ordinary words. Case-insensitive for names.
    """
    if not text:
        return []
    lowered = text.lower()
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < e and s < end for s, e in taken)

    for match in _ALIAS_PATTERN.finditer(lowered):
        found.append((match.start(), _ALIAS_CODES[match.group()]))
        taken.append(match.span())

    for match in re.finditer(rf"(?<![a-z])(?:{_NAME_PATTERN.pattern})(?![a-z])", lowered):
        if overlaps(*match.span()):
            continue
        name = match.group()
        code = next(j.code for j in JURISDICTIONS if j.name.lower() == name)
        found.append((match.start(), code))
        taken.append(match.span())

    for match in _CODE_PATTERN.finditer(text):
        code = match.group(1)
        if code in _BY_CODE and code not in _AMBIGUOUS_CODES and not overlaps(*match.span()):
            found.append((match.start(), code))

    ordered: list[str] = []
    for _, code in sorted(found):
        if code not in ordered:
            ordered.append(code)
    return ordered
