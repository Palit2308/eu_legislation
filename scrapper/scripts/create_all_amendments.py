"""
Run the all-amendments extraction pipeline.

This script mirrors the structure of the user's existing project scripts:
- resolve the project root relative to the scripts folder,
- import the reusable builder function from the functions package,
- run the pipeline,
- save the final amendment-level dataframe and debugging outputs.
"""

import os
import sys

# Make the project root importable so ``functions`` can be imported when this
# script is executed directly from the shell.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from functions.create_all_amendments import build_all_amendments


# Determine the project root (the parent of the 'scripts' folder).
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, "bld")

# Input file.
INPUT_CSV = os.path.join(BLD, "timeline_table.csv")

# Output files.
OUTPUT_CSV = os.path.join(BLD, "proposed_amendments_all.csv")
DOC_LEVEL_CSV = os.path.join(BLD, "all_amendments_document_links.csv")
FAILED_PDF_TEXT_CSV = os.path.join(BLD, "failed_all_amendments_pdf_text.csv")
FAILED_AMENDMENT_DOCS_CSV = os.path.join(BLD, "failed_all_amendments_parsing.csv")


def main() -> None:
    """Run the pipeline and save the final amendment-level dataframe."""
    # Ensure the build directory exists before writing any outputs.
    os.makedirs(BLD, exist_ok=True)

    print("=" * 80)
    print("Running scripts/create_all_amendments.py")
    print(f"Script directory: {script_dir}")
    print(f"Project root: {project_root}")
    print(f"BLD directory: {BLD}")
    print(f"Input CSV: {INPUT_CSV}")
    print(f"Output CSV: {OUTPUT_CSV}")
    print("=" * 80)

    (
        amendment_level_df,
        final_docs_df,
        failed_pdf_text_rows_df,
        failed_amendment_docs_df,
    ) = build_all_amendments(
        input_csv=INPUT_CSV,
        verbose=True,
    )

    print(f"[Save] Final amendment-level dataframe has {len(amendment_level_df)} row(s).")

    # Save final amendment-level output.
    amendment_level_df.to_csv(OUTPUT_CSV, index=False)
    print(f"[Save] Saved amendment-level CSV to {OUTPUT_CSV}")

    # Save document-level PDF link dataframe for debugging/reuse.
    final_docs_df.to_csv(DOC_LEVEL_CSV, index=False)
    print(f"[Save] Saved document-level CSV to {DOC_LEVEL_CSV}")

    # Save failed rows from the PDF-link/text-extraction stage.
    failed_pdf_text_rows_df.to_csv(FAILED_PDF_TEXT_CSV, index=False)
    print(f"[Save] Saved failed PDF/text rows CSV to {FAILED_PDF_TEXT_CSV}")

    # Save failed rows from the amendment-parsing stage.
    failed_amendment_docs_df.to_csv(FAILED_AMENDMENT_DOCS_CSV, index=False)
    print(f"[Save] Saved failed amendment-parsing CSV to {FAILED_AMENDMENT_DOCS_CSV}")


if __name__ == "__main__":
    main()