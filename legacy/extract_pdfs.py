"""
Extract text from input.pdf and output.pdf in chunks of 20 pages each.
Saves full text to .txt files for analysis.
"""

import PyPDF2
import os

CHUNK_SIZE = 20  # pages per chunk


def extract_pdf_in_chunks(pdf_path, output_txt_path):
    """Extract all text from a PDF in chunks and save to a text file."""
    reader = PyPDF2.PdfReader(pdf_path)
    total_pages = len(reader.pages)
    print(f"\n{'='*60}")
    print(f"Processing: {pdf_path}")
    print(f"Total pages: {total_pages}")
    print(f"{'='*60}")

    all_text = []

    for start in range(0, total_pages, CHUNK_SIZE):
        end = min(start + CHUNK_SIZE, total_pages)
        chunk_text = []
        for page_num in range(start, end):
            page = reader.pages[page_num]
            text = page.extract_text()
            if text:
                chunk_text.append(f"\n{'='*40} PAGE {page_num + 1} {'='*40}\n")
                chunk_text.append(text)
            else:
                chunk_text.append(f"\n{'='*40} PAGE {page_num + 1} (NO TEXT EXTRACTED) {'='*40}\n")

        chunk_content = "\n".join(chunk_text)
        all_text.append(chunk_content)
        print(f"  Extracted chunk: pages {start + 1} to {end} ({end - start} pages)")

    # Write full content to text file
    full_text = "\n".join(all_text)
    with open(output_txt_path, "w", encoding="utf-8") as f:
        f.write(full_text)

    print(f"\nSaved to: {output_txt_path}")
    print(f"Total characters extracted: {len(full_text)}")
    return full_text


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Extract input.pdf
    input_pdf = os.path.join(base_dir, "input.pdf")
    input_txt = os.path.join(base_dir, "input_extracted.txt")
    input_text = extract_pdf_in_chunks(input_pdf, input_txt)

    # Extract output.pdf
    output_pdf = os.path.join(base_dir, "output.pdf")
    output_txt = os.path.join(base_dir, "output_extracted.txt")
    output_text = extract_pdf_in_chunks(output_pdf, output_txt)

    print(f"\n\n{'='*60}")
    print("EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Input PDF text saved to: {input_txt}")
    print(f"Output PDF text saved to: {output_txt}")
