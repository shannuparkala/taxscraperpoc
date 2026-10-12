"""
Redact all occurrences of the name 'Kyle' (and associated last name, email patterns)
from input.pdf by drawing black boxes over matching text regions.

This ensures PII is visually masked before sharing the PDF with external AI tools.
"""

import fitz  # PyMuPDF
import os

INPUT_PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input.pdf")
OUTPUT_PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input_redacted.pdf")

# Patterns to search for and redact (case-insensitive search handled by searching multiple variants)
SEARCH_TERMS = [
    # Full name variations
    "Kyle Fiebelkorn",
    "KYLE FIEBELKORN",
    "Kyle M. Fiebelkorn",
    "KYLE M. FIEBELKORN",
    "Kyle M Fiebelkorn",
    "KYLE M FIEBELKORN",
    # First name alone
    "Kyle",
    "KYLE",
    "kyle",
    # Last name alone
    "Fiebelkorn",
    "FIEBELKORN",
    "fiebelkorn",
    # Email patterns
    "kyle.fiebelkorn",
    "KYLE.FIEBELKORN",
    "kfiebelkorn",
    "KFIEBELKORN",
]


def redact_pdf(input_path: str, output_path: str):
    """Find and redact all name occurrences with solid black rectangles."""
    doc = fitz.open(input_path)
    total_redactions = 0

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_redactions = 0

        for term in SEARCH_TERMS:
            instances = page.search_for(term)
            for inst in instances:
                # Add a redaction annotation with black fill and no replacement text
                annot = page.add_redact_annot(
                    inst,
                    text="",           # No replacement text
                    fill=(0, 0, 0),    # Black fill to mask the area
                )
                page_redactions += 1

        # Apply all redactions on this page (permanently removes underlying text)
        if page_redactions > 0:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            total_redactions += page_redactions
            print(f"  Page {page_num + 1}: {page_redactions} redactions applied")

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()

    print(f"\nTotal redactions: {total_redactions}")
    print(f"Redacted PDF saved to: {output_path}")


if __name__ == "__main__":
    if not os.path.exists(INPUT_PDF):
        print(f"ERROR: Input file not found: {INPUT_PDF}")
        exit(1)

    print(f"Redacting name from: {INPUT_PDF}")
    print(f"Searching for {len(SEARCH_TERMS)} patterns...\n")
    redact_pdf(INPUT_PDF, OUTPUT_PDF)
