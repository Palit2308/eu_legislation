"""
Run the Council / Presidency / Conclusions participant-extraction pipeline.

This script mirrors the structure of the user's existing project scripts:
- resolve the project root relative to the scripts folder,
- import the reusable builder function from the functions package,
- run the pipeline,
- save only the final participant dataframe as CSV and JSON.
"""

import sys
import os

# Make the project root importable so ``functions`` can be imported when this
# script is executed directly from the shell.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from functions.create_council_lop_pres_con import build_council_lop_pres_con


# Determine the project root (the parent of the 'scripts' folder).
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, "bld")

# Output files requested by the user.
OUTPUT_CSV = os.path.join(BLD, "council_lop_pres_con.csv")
OUTPUT_JSON = os.path.join(BLD, "council_lop_pres_con.json")


def main() -> None:
    """Run the pipeline and save the final participant dataframe."""
    # Ensure the build directory exists before writing any outputs.
    os.makedirs(BLD, exist_ok=True)

    print("=" * 80)
    print("Running scripts/create_council_lop_pres_con.py")
    print(f"Script directory: {script_dir}")
    print(f"Project root: {project_root}")
    print(f"BLD directory: {BLD}")
    print("=" * 80)

    # Run the reusable pipeline function. Verbose output is enabled so the user
    # can see what is happening while the script runs in the shell.
    participant_df = build_council_lop_pres_con(verbose=True)

    print(f"[Save] Final dataframe has {len(participant_df)} row(s).")

    # Save CSV output.
    participant_df.to_csv(OUTPUT_CSV, index=False)
    print(f"[Save] Saved CSV to {OUTPUT_CSV}")

    # Save JSON output.
    participant_df.to_json(OUTPUT_JSON, orient="records", indent=2)
    print(f"[Save] Saved JSON to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
