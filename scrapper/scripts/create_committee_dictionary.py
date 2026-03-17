"""
Script to scrape the European Parliament committee list page and save
a committee dictionary as CSV and JSON.
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.create_committee_dictionary import build_committee_dictionary

# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, 'bld')


def main():
    df = build_committee_dictionary()
    print(f"Scraped {len(df)} committee rows")

    output_csv = os.path.join(BLD, 'committee_dictionary.csv')
    df.to_csv(output_csv, index=False)
    print(f"Saved CSV to {output_csv}")

    output_json = os.path.join(BLD, 'committee_dictionary.json')
    df.to_json(output_json, orient='records', indent=2)
    print(f"Saved JSON to {output_json}")


if __name__ == "__main__":
    main()