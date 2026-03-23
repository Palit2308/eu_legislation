"""
Script entry point for scraping Council voting-result metadata.

What this script does
---------------------
- Adds the project root to sys.path so the local `functions` package is importable.
- Calls the scraper in `functions/scrape_council_votes_meta.py`.
- Saves the outputs into the project's `bld/` directory as:

    bld/council_votes.csv
    bld/council_votes.json
    bld/council_votes_meta.csv
    bld/council_votes_meta.json

Why this split exists
---------------------
- `functions/...` contains reusable logic.
- `scripts/...` is the thin runner you execute from the command line or IDE.

Usage
-----
From the project root, for example:

    python scripts/scrape_council_votes_meta.py
"""

import os
import sys

# Make project root importable so `functions/...` works when this script is run directly.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from functions.scrape_council_votes_meta import (
    scrape_council_votes,
    save_council_vote_outputs,
)


# Determine the project root (parent of the 'scripts' folder)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BLD = os.path.join(PROJECT_ROOT, "bld")


def main() -> None:
    os.makedirs(BLD, exist_ok=True)
    print(f"[INFO] Using output directory: {BLD}")

    df_votes, df_meta = scrape_council_votes()

    print(f"[INFO] Scraped {len(df_votes)} total vote rows.")
    print(f"[INFO] Collected {len(df_meta)} page-level metadata rows.")

    save_council_vote_outputs(
        df_votes=df_votes,
        df_meta=df_meta,
        output_dir=BLD,
    )

    print("[SUCCESS] Council vote scraping completed.")
    print(f"[INFO] Votes dataframe shape: {df_votes.shape}")
    print(f"[INFO] Meta dataframe shape: {df_meta.shape}")


if __name__ == "__main__":
    main()