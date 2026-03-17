"""
Script to read the extracted-text CSV for 'other format' committee reports,
expand the procedural information into a long-format table, and save the
resulting CSV and JSON files.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from functions.create_other_format_com_vote_procedure import expand_other_format_committee_procedure

# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, 'bld')


def main():
    input_csv = os.path.join(BLD, 'beta_test_procedures_committee_other_format_text.csv')

    df = pd.read_csv(input_csv)
    print(f"Read {len(df)} rows from {input_csv}")

    df_long = expand_other_format_committee_procedure(df)
    print(f"Expanded to {len(df_long)} rows")

    output_csv = os.path.join(BLD, 'test_procedures_committee_other_format_procedure_table.csv')
    df_long.to_csv(output_csv, index=False)
    print(f"Saved CSV to {output_csv}")

    output_json = os.path.join(BLD, 'test_procedures_committee_other_format_procedure_table.json')
    df_long.to_json(output_json, orient='records', indent=2, force_ascii=False)
    print(f"Saved JSON to {output_json}")


if __name__ == '__main__':
    main()
