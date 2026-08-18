import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import requests
from bs4 import BeautifulSoup
import json

from functions.create_meta_table import (
    extract_basic_info,
    extract_key_players_long,
    extract_mandatory_consultation,
)


# Path to the scrapper directory (project root)
SCRAPPER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Path to the bld directory inside scrapper
BLD = os.path.join(SCRAPPER_DIR, "bld")

# Create bld folder if it does not exist
os.makedirs(BLD, exist_ok=True)


def split_reference(ref):
    """
    Split a procedure reference like '2021/0366(COD)'
    into year and policy_number.

    Returns
    -------
    tuple
        (year, policy_number) as strings.

    policy_number includes everything after the first slash,
    e.g. '0366(COD)'.
    """
    if '/' not in ref:
        return None, ref

    year, policy_number = ref.split('/', 1)

    if year.isdigit():
        return year, policy_number
    else:
        return None, ref


# Input file
csv_path = os.path.join(BLD, "oeil_cod_procedures.csv")

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
]


# List to hold individual DataFrames
all_dfs = []

# Optional: keep track of policies/sections that failed
errors = []


for ref in df_landing['reference'].values.tolist():
    print(f"\nProcessing {ref} ...")

    # ---------------------------------------------------------
    # Find matching policy in landing-page CSV
    # ---------------------------------------------------------
    match = df_landing.loc[df_landing['reference'] == ref]

    if match.empty:
        print(f"  WARNING: Reference {ref} not found in CSV. Skipping.")
        continue

    # Get URL
    url = match.iloc[0]['url']

    # ---------------------------------------------------------
    # Download HTML
    # ---------------------------------------------------------
    try:
        response = requests.get(
            url,
            timeout=30
        )
        response.raise_for_status()
        html = response.text

    except Exception as e:
        print(
            f"  ERROR downloading {ref}: "
            f"{type(e).__name__}: {e}"
        )

        errors.append({
            "procedure": ref,
            "section": "download",
            "error": f"{type(e).__name__}: {e}",
        })

        # Skip this policy entirely
        continue

    # ---------------------------------------------------------
    # Parse HTML
    # ---------------------------------------------------------
    try:
        soup = BeautifulSoup(html, 'html.parser')

    except Exception as e:
        print(
            f"  ERROR parsing HTML for {ref}: "
            f"{type(e).__name__}: {e}"
        )

        errors.append({
            "procedure": ref,
            "section": "html_parsing",
            "error": f"{type(e).__name__}: {e}",
        })

        continue

    # ---------------------------------------------------------
    # Extract BASIC INFO
    # ---------------------------------------------------------
    try:
        basic_rows = extract_basic_info(soup)

    except Exception as e:
        print(
            f"  ERROR extracting basic info for {ref}: "
            f"{type(e).__name__}: {e}"
        )

        basic_rows = []

        errors.append({
            "procedure": ref,
            "section": "basic_info",
            "error": f"{type(e).__name__}: {e}",
        })

    # ---------------------------------------------------------
    # Extract KEY PLAYERS
    # ---------------------------------------------------------
    try:
        key_rows = extract_key_players_long(soup)

    except Exception as e:
        print(
            f"  ERROR extracting key players for {ref}: "
            f"{type(e).__name__}: {e}"
        )

        key_rows = []

        errors.append({
            "procedure": ref,
            "section": "key_players",
            "error": f"{type(e).__name__}: {e}",
        })

    # ---------------------------------------------------------
    # Extract MANDATORY CONSULTATION
    # ---------------------------------------------------------
    try:
        tech_rows = extract_mandatory_consultation(soup)

    except Exception as e:
        print(
            f"  ERROR extracting mandatory consultation for {ref}: "
            f"{type(e).__name__}: {e}"
        )

        tech_rows = []

        errors.append({
            "procedure": ref,
            "section": "mandatory_consultation",
            "error": f"{type(e).__name__}: {e}",
        })

    # ---------------------------------------------------------
    # Combine successfully extracted sections
    # ---------------------------------------------------------
    all_rows = basic_rows + key_rows + tech_rows

    if not all_rows:
        print(f"  No data extracted for {ref}. Skipping.")
        continue

    # ---------------------------------------------------------
    # Convert to DataFrame
    # ---------------------------------------------------------
    try:
        df_temp = pd.DataFrame(all_rows)

        # Add year, policy number and procedure
        year, policy_number = split_reference(ref)

        df_temp['year'] = year
        df_temp['policy_number'] = policy_number
        df_temp['procedure'] = ref

        # Reorder columns
        df_temp = df_temp[
            [
                'year',
                'policy_number',
                'procedure',
                'meta_column',
                'value',
            ]
        ]

    except Exception as e:
        print(
            f"  ERROR creating DataFrame for {ref}: "
            f"{type(e).__name__}: {e}"
        )

        errors.append({
            "procedure": ref,
            "section": "dataframe_creation",
            "error": f"{type(e).__name__}: {e}",
        })

        continue

    # Add successful policy to master list
    all_dfs.append(df_temp)

    print(f"  Extracted {len(df_temp)} rows.")


# -------------------------------------------------------------
# Combine all procedures into one DataFrame
# -------------------------------------------------------------
if all_dfs:

    df_final = pd.concat(
        all_dfs,
        ignore_index=True
    )

    print("\nFinal DataFrame shape:", df_final.shape)
    print(df_final.head(30))

else:

    df_final = pd.DataFrame(
        columns=[
            'year',
            'policy_number',
            'procedure',
            'meta_column',
            'value',
        ]
    )

    print("No data extracted.")


# -------------------------------------------------------------
# Save main output
# -------------------------------------------------------------

output_csv = os.path.join(
    BLD,
    "meta_table.csv"
)

df_final.to_csv(
    output_csv,
    index=False
)

print(f"\nSaved CSV to {output_csv}")


output_json = os.path.join(
    BLD,
    "meta_table.json"
)

df_final.to_json(
    output_json,
    orient="records",
    indent=2
)

print(f"Saved JSON to {output_json}")


# -------------------------------------------------------------
# Save extraction errors
# -------------------------------------------------------------
if errors:

    df_errors = pd.DataFrame(errors)

    error_csv = os.path.join(
        BLD,
        "meta_table_errors.csv"
    )

    df_errors.to_csv(
        error_csv,
        index=False
    )

    print(
        f"\nCompleted with {len(errors)} extraction error(s)."
    )

    print(f"Error log saved to {error_csv}")

    print("\nErrors encountered:")
    print(df_errors)

else:
    print("\nCompleted without extraction errors.")