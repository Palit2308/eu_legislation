"""
Script to read the committee vote info CSV, expand the procedure table HTML,
and save the resulting long-format table as CSV and JSON.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from functions.create_com_vote_procedure import expand_committee_procedure

# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, 'bld')

def main():
    # Input file
    input_csv = os.path.join(BLD, 'committee_vote_info.csv')
    
    # Read the data
    df = pd.read_csv(input_csv)
    print(f"Read {len(df)} rows from {input_csv}")
    
    # Expand the procedure table HTML into long format
    df_long = expand_committee_procedure(df)
    print(f"Expanded to {len(df_long)} rows")
    
    # Save as CSV
    output_csv = os.path.join(BLD, 'committee_vote_procedure_table.csv')
    df_long.to_csv(output_csv, index=False)
    print(f"Saved CSV to {output_csv}")
    
    # Save as JSON
    output_json = os.path.join(BLD, 'committee_vote_procedure_table.json')
    df_long.to_json(output_json, orient='records', indent=2)
    print(f"Saved JSON to {output_json}")

if __name__ == "__main__":
    main()