"""
Generic PII Redactor: Automatically detects and redacts personal information
from any PDF without prior knowledge of whose data it contains.

Uses spaCy NER for name detection + regex for structured PII patterns.

Install dependencies:
    pip install PyMuPDF spacy
    python -m spacy download en_core_web_sm
"""

import fitz  # PyMuPDF
import spacy
import re
import os
import sys
from collections import defaultdict

# Load spaCy NER model
nlp = spacy.load("en_core_web_sm")

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# What entity types to redact (spaCy labels)
REDACT_ENTITIES = {"PERSON"}  # Add "ORG", "GPE" etc. if needed

# Regex patterns for structured PII
PII_PATTERNS = {
    "SSN": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
    "PHONE": r"\b(?:\+1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
    "DOB": r"\b(?:0[1-9]|1[0-2])[/\-](0[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b",
    "ACCOUNT_NUM": r"\b\d{8,17}\b",  # Bank/brokerage account numbers (8-17 digits)
    "ROUTING_NUM": r"\b\d{9}\b",      # Bank routing numbers (exactly 9 digits)
}

# Minimum name length to avoid false positives (single letters, "Mr", etc.)
MIN_NAME_LENGTH = 3

# Words that spaCy sometimes misclassifies as PERSON names (tax/form context)
FALSE_POSITIVE_NAMES = {
    # Months/days
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    # Business suffixes
    "irs", "llc", "inc", "corp", "ltd",
    # Tax form terms commonly misidentified
    "form", "schedule", "section", "standard", "itemized", "federal",
    "state", "total", "page", "box", "date", "email", "payer", "payee",
    "detail", "driver", "deemed", "backup", "withholding", "pub",
    "roth", "coverdell", "wash", "expenditures", "taxpayer",
    "cell", "phone", "trust", "revocable",
}


# ==============================================================================
# NER-BASED NAME DETECTION
# ==============================================================================

def extract_person_names(text: str) -> set:
    """Use spaCy NER to find all person names in text."""
    doc = nlp(text)
    names = set()

    for ent in doc.ents:
        if ent.label_ in REDACT_ENTITIES:
            name = ent.text.strip()
            # Filter out false positives
            if len(name) < MIN_NAME_LENGTH:
                continue
            if name.lower() in FALSE_POSITIVE_NAMES:
                continue
            # Skip if it's all digits or punctuation
            if not any(c.isalpha() for c in name):
                continue
            names.add(name)

    return names


def build_name_variants(names: set) -> set:
    """
    Given detected names, build variants to catch different casings
    and partial matches (first name, last name individually).
    """
    variants = set()

    for name in names:
        # Skip entities that are clearly not person names (contain digits, too many words)
        if any(c.isdigit() for c in name):
            continue
        if len(name.split()) > 4:
            continue

        variants.add(name)
        # Add individual parts (first name, last name)
        parts = name.split()
        for part in parts:
            # Strip punctuation for comparison
            clean = part.strip(".,()").lower()
            if len(clean) >= MIN_NAME_LENGTH and clean not in FALSE_POSITIVE_NAMES:
                variants.add(part.strip(".,()"))

    return variants


# ==============================================================================
# REGEX-BASED PII DETECTION
# ==============================================================================

def find_pii_matches(text: str) -> dict:
    """Find all regex-based PII matches in text. Returns {pattern_name: [matches]}."""
    matches = defaultdict(set)
    for pii_type, pattern in PII_PATTERNS.items():
        for m in re.finditer(pattern, text):
            match_text = m.group()
            # Extra validation to reduce false positives
            if pii_type == "ACCOUNT_NUM" and len(match_text) < 9:
                continue
            if pii_type == "ROUTING_NUM":
                # Routing numbers shouldn't overlap with years, zip codes etc.
                # Basic check: not a year (19xx, 20xx patterns as 9 digits is unlikely year)
                pass
            matches[pii_type].add(match_text)
    return matches


# ==============================================================================
# PDF REDACTION
# ==============================================================================

def redact_pdf(input_path: str, output_path: str, redact_names=True, redact_pii=True):
    """
    Generic PII redaction pipeline:
    1. Extract all text from PDF
    2. Run NER to detect person names
    3. Run regex to detect structured PII
    4. Redact all matches with black boxes
    """
    doc = fitz.open(input_path)

    # --- Phase 1: Extract full text for NER analysis ---
    print("Phase 1: Extracting text for NER analysis...")
    full_text = ""
    for page in doc:
        full_text += page.get_text("text") + "\n"

    # --- Phase 2: Detect names via NER ---
    detected_names = set()
    if redact_names:
        print("Phase 2: Running Named Entity Recognition...")
        detected_names = extract_person_names(full_text)
        name_variants = build_name_variants(detected_names)
        print(f"  Detected {len(detected_names)} unique person entities")
        print(f"  Expanded to {len(name_variants)} search variants")
        if detected_names:
            print(f"  Names found: {', '.join(sorted(detected_names))}")

    # --- Phase 3: Detect structured PII ---
    pii_matches = defaultdict(set)
    if redact_pii:
        print("Phase 3: Scanning for structured PII patterns...")
        pii_matches = find_pii_matches(full_text)
        for pii_type, matches in pii_matches.items():
            print(f"  {pii_type}: {len(matches)} matches")

    # --- Phase 4: Apply redactions ---
    print("Phase 4: Applying redactions...")
    total_redactions = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_redactions = 0

        # Redact name variants
        if redact_names:
            for name in name_variants:
                instances = page.search_for(name)
                for inst in instances:
                    page.add_redact_annot(inst, text="", fill=(0, 0, 0))
                    page_redactions += 1

        # Redact structured PII (SSN, email, phone, etc.)
        if redact_pii:
            for pii_type, matches in pii_matches.items():
                for match_text in matches:
                    instances = page.search_for(match_text)
                    for inst in instances:
                        page.add_redact_annot(inst, text="", fill=(0, 0, 0))
                        page_redactions += 1

        if page_redactions > 0:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            total_redactions += page_redactions
            print(f"  Page {page_num + 1}: {page_redactions} redactions")

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    print(f"\nDone! Total redactions: {total_redactions}")
    print(f"Output: {output_path}")
    return total_redactions


# ==============================================================================
# CLI
# ==============================================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input.pdf")

    if not os.path.exists(input_file):
        print(f"ERROR: File not found: {input_file}")
        sys.exit(1)

    base, ext = os.path.splitext(input_file)
    output_file = f"{base}_redacted{ext}"

    print(f"Input:  {input_file}")
    print(f"Output: {output_file}\n")

    redact_pdf(input_file, output_file)
