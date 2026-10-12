"""Pull Pub. 946 Appendix A tables out of the PDF with PyMuPDF find_tables."""
import json
import re
import sys

import pymupdf

doc = pymupdf.open(sys.argv[1])
out = {}


def nums(cell):
    if cell is None:
        return []
    return [float(x.rstrip('%')) for x in cell.replace('%', '').split('\n') if re.fullmatch(r"[0-9.]+", x.strip())]


for pno in range(69, 86):
    page = doc[pno]
    text = page.get_text()
    heads = re.findall(r"^(Table A-[0-9a-z]+\.)", text, flags=re.M)
    tabs = page.find_tables().tables
    print("page", pno, heads, [ (len(t.extract()), len(t.extract()[0])) for t in tabs], file=sys.stderr)
    for idx, t in enumerate(tabs):
        rows = t.extract()
        out[f"p{pno}_t{idx}"] = rows

json.dump(out, open(sys.argv[2], "w"), indent=1)
