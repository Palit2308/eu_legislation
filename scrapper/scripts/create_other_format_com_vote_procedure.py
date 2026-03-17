"""
Script to build the long-format procedure table for 'other format'
committee-report procedures from PDFs, and save it as CSV and JSON.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from functions.create_other_format_com_vote_procedure import build_other_format_com_vote_procedure_table

# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, 'bld')


def main():
    vote_info_csv = os.path.join(BLD, 'committee_vote_info.csv')
    timeline_csv = os.path.join(BLD, 'timeline_table.csv')
    dict_csv = os.path.join(BLD, 'committee_dictionary.csv')

    df_vote_info = pd.read_csv(vote_info_csv)
    print(f"Read {len(df_vote_info)} rows from {vote_info_csv}")

    df_timeline = pd.read_csv(timeline_csv)
    print(f"Read {len(df_timeline)} rows from {timeline_csv}")

    df_dict = pd.read_csv(dict_csv)
    print(f"Read {len(df_dict)} rows from {dict_csv}")

    df_out = build_other_format_com_vote_procedure_table(
        df_vote_info=df_vote_info,
        df_timeline=df_timeline,
        df_dict=df_dict,
    )
    print(f"Built other-format procedure table with {len(df_out)} rows")

    output_csv = os.path.join(BLD, 'committee_other_format_procedure_table.csv')
    df_out.to_csv(output_csv, index=False)
    print(f"Saved CSV to {output_csv}")

    output_json = os.path.join(BLD, 'committee_other_format_procedure_table.json')
    df_out.to_json(output_json, orient='records', indent=2, force_ascii=False)
    print(f"Saved JSON to {output_json}")


if __name__ == "__main__":
    main()