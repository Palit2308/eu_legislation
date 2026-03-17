import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
import sys

# Add parent directory to path so that functions module is found
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.create_timeline_table import (
    extract_key_events_detailed,
    extract_documentation_gateway,
    create_timeline_simple
)

# --- Configuration ---
# Determine the project root (parent of the 'scripts' folder)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # go up one level
BLD = os.path.join(project_root, 'bld')

# Path to the CSV with all procedure references and URLs
LANDING_CSV = os.path.join(BLD, 'oeil_cod_procedures.csv')

# List of procedures to process (add as many as needed)
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

# --- Read landing CSV ---
df_landing = pd.read_csv(LANDING_CSV)

# --- Loop over procedures and build timeline ---
all_timelines = []

for ref in procedures:
    print(f"Processing {ref} ...")
    # Find the URL
    match = df_landing.loc[df_landing['reference'] == ref]
    if match.empty:
        print(f"  WARNING: Procedure {ref} not found in landing CSV. Skipping.")
        continue
    url = match.iloc[0]['url']
    print(f"  URL: {url}")

    # Fetch and parse
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}")
        continue

    # Extract events and documents
    events = extract_key_events_detailed(soup, ref, url)
    docs = extract_documentation_gateway(soup, url)

    if not events and not docs:
        print(f"  No data extracted for {ref}.")
        continue

    df_events = pd.DataFrame(events)
    df_docs = pd.DataFrame(docs)

    # Create timeline for this procedure
    df_timeline = create_timeline_simple(df_events, df_docs)

    # Add procedure column
    df_timeline.insert(0, 'procedure', ref)

    all_timelines.append(df_timeline)
    print(f"  Extracted {len(df_timeline)} timeline rows.")

# --- Combine all procedures ---
if all_timelines:
    df_combined = pd.concat(all_timelines, ignore_index=True)
    print(f"\nFinal combined timeline: {len(df_combined)} rows.")

    # Save to CSV and JSON
    df_combined.to_csv(os.path.join(BLD, 'timeline_table.csv'), index=False)
    df_combined.to_json(os.path.join(BLD, 'timeline_table.json'), orient='records', indent=2)
    print("Saved timeline_table.csv and timeline_table.json")
else:
    print("No data extracted for any procedure.")