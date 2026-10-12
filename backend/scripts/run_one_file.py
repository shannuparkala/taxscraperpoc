"""Run the pipeline over a single workpaper and print the result.

    cd backend && python -m scripts.run_one_file "..\\Files\\Basic 5 Workpapers.pdf"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.batch_run import run_one


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1]).resolve()
    if not path.is_file():
        print(f"Not a file: {path}")
        return 2

    print(f"Processing {path.name} ...", flush=True)
    record = run_one(path)
    print(json.dumps(record, indent=2, default=str))
    return 0 if record.get("computed_return") else 1


if __name__ == "__main__":
    raise SystemExit(main())
