"""
Script to identify 'other format' committee-report procedures, revisit their
procedure pages, extract whole-text PDFs where available, and save the result
as CSV.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from functions.create_com_other_format_text import build_other_format_text_table

# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, 'bld')


def main():
    vote_info_csv = os.path.join(BLD, 'committee_vote_info.csv')
    timeline_csv = os.path.join(BLD, 'timeline_table.csv')

    df_vote_info = pd.read_csv(vote_info_csv)
    print(f"Read {len(df_vote_info)} rows from {vote_info_csv}")

    df_timeline = pd.read_csv(timeline_csv)
    print(f"Read {len(df_timeline)} rows from {timeline_csv}")

    df_out = build_other_format_text_table(df_vote_info, df_timeline)
    print(f"Built other-format text table with {len(df_out)} rows")

    output_csv = os.path.join(BLD, 'committee_other_format_text.csv')
    df_out.to_csv(output_csv, index=False)
    print(f"Saved CSV to {output_csv}")


if __name__ == "__main__":
    main()