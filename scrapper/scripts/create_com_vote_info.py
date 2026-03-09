import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
from functions.create_com_vote_info import get_committee_votes

# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # go up one level
BLD = os.path.join(project_root, 'bld')

def main():
    # Path to the input CSV
    input_csv = os.path.join(BLD, 'test_procedures_timeline.csv')
    
    # Read the timeline data
    df_timeline = pd.read_csv(input_csv)
    
    # Filter rows where event is "Committee report tabled for plenary, 1st reading"
    mask = df_timeline['event'] == "Committee report tabled for plenary, 1st reading"
    df_filtered = df_timeline[mask].copy()
    
    if df_filtered.empty:
        print("No matching events found.")
        return
    
    # Prepare list to collect DataFrames
    all_dfs = []
    
    # Iterate over each filtered row
    for idx, row in df_filtered.iterrows():
        procedure = row['procedure']
        hyperlink = row['hyperlink']
        
        # Skip if hyperlink is missing or NaN
        if pd.isna(hyperlink) or not hyperlink:
            print(f"Skipping procedure {procedure}: no hyperlink")
            continue
        
        print(f"Processing {procedure} -> {hyperlink}")
        
        try:
            df_committees = get_committee_votes(hyperlink)
            # Add the procedure column
            df_committees['procedure'] = procedure
            all_dfs.append(df_committees)
        except Exception as e:
            print(f"Error processing {hyperlink}: {e}")
            # Optionally add a row with error info? For now just skip.
            continue
    
    if not all_dfs:
        print("No data collected.")
        return
    
    # Concatenate all results
    df_final = pd.concat(all_dfs, ignore_index=True)
    
    # Reorder columns to put 'procedure' first (optional)
    cols = ['procedure'] + [c for c in df_final.columns if c != 'procedure']
    df_final = df_final[cols]
    
    # Save output
    output_csv = os.path.join(BLD, 'test_procedures_committee_vote_info.csv')
    df_final.to_csv(output_csv, index=False)
    print(f"Saved {len(df_final)} rows to {output_csv}")

if __name__ == "__main__":
    main()