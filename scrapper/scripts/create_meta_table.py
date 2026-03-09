import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import requests
from bs4 import BeautifulSoup
import json
from functions.create_meta_table import extract_basic_info, extract_key_players_long, extract_mandatory_consultation

# Path to the scrapper directory (project root)
SCRAPPER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Path to the bld directory inside scrapper
BLD = os.path.join(SCRAPPER_DIR, "bld")

# Create bld folder if it does not exist
os.makedirs(BLD, exist_ok=True)

def split_reference(ref):
    """
    Split a procedure reference like '2021/0366(COD)' into year and policy_number.
    Returns (year, policy_number) as strings.
    policy_number includes everything after the first slash, e.g., '0366(COD)'.
    """
    if '/' not in ref:
        return None, ref
    year, policy_number = ref.split('/', 1)
    # year should be digits; if not, fallback
    if year.isdigit():
        return year, policy_number
    else:
        return None, ref

# Path to your CSV file
csv_path = f'{BLD}\\oeil_all_procedures_landing_page.csv'

# Read the CSV once
df_landing = pd.read_csv(csv_path)

# List of procedure references to process
procedures = [
    '2021/0366(COD)',
    '2014/0011(COD)',
    '2012/0364(COD)',
    '2010/0380(COD)',
    '2010/0377(COD)',
    '2007/0295(COD)',
    '2000/0073(COD)',
    '1994/0272(COD)',
    '2011/0465(COD)',
    '2011/0439(COD)',
    '2012/0358(COD)',
    '2013/0303(COD)',
    '2014/0213(COD)',
    '2014/0091(COD)',
    '2015/0284(COD)',
    '2015/0287(COD)',
    '2016/0414(COD)',
    '2016/0224B(COD)',
    '2017/0354(COD)',
    '2014/0004(COD)',
    '2018/0298(COD)',
    '2019/0002(COD)',
    '2020/0347(COD)',
    '2020/0262(COD)',
    # Add more references as needed
]

# List to hold individual DataFrames
all_dfs = []

for ref in procedures:
    print(f"Processing {ref} ...")
    # Find the row with this reference
    match = df_landing.loc[df_landing['reference'] == ref]
    if match.empty:
        print(f"  WARNING: Reference {ref} not found in CSV. Skipping.")
        continue

    # Get the URL (assuming column name is 'url')
    url = match.iloc[0]['url']

    # Download HTML
    try:
        response = requests.get(url)
        response.raise_for_status()
        html = response.text
    except Exception as e:
        print(f"  ERROR downloading {url}: {e}")
        continue

    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # Extract all sections
    basic_rows = extract_basic_info(soup)
    key_rows = extract_key_players_long(soup)
    tech_rows = extract_mandatory_consultation(soup)

    # Combine
    all_rows = basic_rows + key_rows + tech_rows

    if not all_rows:
        print(f"  No data extracted for {ref}.")
        continue

    # Convert to DataFrame
    df_temp = pd.DataFrame(all_rows)

    # Add year, policy_number, and full procedure columns
    year, policy_number = split_reference(ref)
    df_temp['year'] = year
    df_temp['policy_number'] = policy_number
    df_temp['procedure'] = ref  # keep the original full reference

    # Reorder columns: year, policy_number, procedure, meta_column, value
    df_temp = df_temp[['year', 'policy_number', 'procedure', 'meta_column', 'value']]

    all_dfs.append(df_temp)
    print(f"  Extracted {len(df_temp)} rows.")

# Combine all procedures into one DataFrame
if all_dfs:
    df_final = pd.concat(all_dfs, ignore_index=True)
    print("\nFinal DataFrame shape:", df_final.shape)
    print(df_final.head(20))
else:
    df_final = pd.DataFrame(columns=['year', 'policy_number', 'procedure', 'meta_column', 'value'])
    print("No data extracted.")

# Save to CSV and JSON
df_final.to_csv(f'{BLD}\\test_procedures_meta.csv', index=False)
df_final.to_json(f'{BLD}\\test_procedures_meta.json', orient='records', indent=2)