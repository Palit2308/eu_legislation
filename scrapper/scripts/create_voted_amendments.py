"""
Run the voted amendments extraction pipeline.

This script mirrors the structure of the user's existing project scripts:
- resolve the project root relative to the scripts folder,
- import the reusable builder function from the functions package,
- run the pipeline,
- save the final amendments dataframe.
"""

import os
import sys

# Make the project root importable so ``functions`` can be imported when this
# script is executed directly from the shell.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from functions.create_voted_amendments import build_voted_amendments


# Determine the project root (the parent of the 'scripts' folder).
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, "bld")

# Input file.
INPUT_CSV = os.path.join(BLD, "timeline_table.csv")

# Output files.
OUTPUT_CSV = os.path.join(BLD, "voted_amendments_all.csv")
FAILED_ROWS_CSV = os.path.join(BLD, "failed_voted_amendments.csv")


def main() -> None:
    """Run the pipeline and save the final amendments dataframe."""
    # Ensure the build directory exists before writing any outputs.
    os.makedirs(BLD, exist_ok=True)

    print("=" * 80)
    print("Running scripts/create_voted_amendments.py")
    print(f"Script directory: {script_dir}")
    print(f"Project root: {project_root}")
    print(f"BLD directory: {BLD}")
    print(f"Input CSV: {INPUT_CSV}")
    print(f"Output CSV: {OUTPUT_CSV}")
    print("=" * 80)

    # Run the reusable pipeline function.
    df_all_amendments, failed_rows_df = build_voted_amendments(
        input_csv=INPUT_CSV,
        verbose=True,
    )

    print(f"[Save] Final dataframe has {len(df_all_amendments)} row(s).")

    # Save final amendments output.
    df_all_amendments.to_csv(OUTPUT_CSV, index=False)
    print(f"[Save] Saved CSV to {OUTPUT_CSV}")

    # Save failed rows separately for debugging.
    failed_rows_df.to_csv(FAILED_ROWS_CSV, index=False)
    print(f"[Save] Saved failed rows CSV to {FAILED_ROWS_CSV}")


if __name__ == "__main__":
    main()