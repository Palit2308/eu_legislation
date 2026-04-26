import re
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup


headers = {"User-Agent": "Mozilla/5.0"}


# ----------------------------
# Helper functions
# ----------------------------
def clean_text(x):
    return re.sub(r"\s+", " ", str(x)).strip()


def parse_small_table(tbl):
    """
    Convert the small tables below the main vote table into readable text.
    """
    lines = []

    for tr in tbl.find_all("tr"):
        cells = []
        for cell in tr.find_all(["td", "th"]):
            txt = clean_text(" ".join(cell.stripped_strings))
            if txt:
                cells.append(txt)

        if not cells:
            continue

        deduped = []
        for c in cells:
            if not deduped or c != deduped[-1]:
                deduped.append(c)
        cells = deduped

        if len(cells) == 1:
            lines.append(cells[0])
        elif len(cells) == 2:
            left, right = cells
            if left in ["First part", "Second part", "Third part", "Fourth part"]:
                lines.append(f"{left}: {right}")
            else:
                lines.append(f"{left} {right}")
        else:
            lines.append(" | ".join(cells))

    return "\n".join(lines)


def extract_vote_section(vote_row, df, headers):
    """
    Extract the vote table + additional remarks for one row of df1.
    Returns a cleaned DataFrame for that vote row.
    """
    procedure_id = vote_row["procedure"]
    vote_event_id = vote_row["event_id"]
    vote_url = vote_row["hyperlink"]

    # ----------------------------
    # Find report reference from df
    # ----------------------------
    mask_report = (
        (df["procedure"] == procedure_id) &
        (
            df["event"]
            .astype(str)
            .str.strip()
            .eq("Committee report tabled for plenary, 1st reading")
        )
    )

    report_ref = (
        df.loc[mask_report, "reference"]
          .dropna()
          .astype(str)
          .str.strip()
          .iloc[0]
    )

    # ----------------------------
    # Download page
    # ----------------------------
    response = requests.get(vote_url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # ----------------------------
    # Find the exact section containing the report reference
    # ----------------------------
    report_link = soup.find("a", string=lambda s: s and report_ref in s)

    if report_link is None:
        raise ValueError(f"Could not find report reference {report_ref} on the page.")

    section = report_link.find_parent("tr", class_="contents")
    if section is None:
        raise ValueError(f"Could not find enclosing section for {report_ref}.")

    # ----------------------------
    # Get all tables in this section
    # ----------------------------
    tables = section.find_all("table")
    if not tables:
        raise ValueError("No tables found in the section.")

    # ----------------------------
    # Identify the main vote table by header names
    # ----------------------------
    main_table = None
    main_table_index = None

    for i, tbl in enumerate(tables):
        header_text = clean_text(" ".join(tbl.stripped_strings)).lower()

        if (
            "subject" in header_text and
            "am no" in header_text and
            "author" in header_text and
            "vote" in header_text
        ):
            main_table = tbl
            main_table_index = i
            break

    if main_table is None:
        raise ValueError("Could not identify the main vote table.")

    # ----------------------------
    # Parse main vote table
    # ----------------------------
    df_section = pd.read_html(StringIO(str(main_table)))[0]

    # Flatten MultiIndex columns if needed
    if isinstance(df_section.columns, pd.MultiIndex):
        df_section.columns = [
            " ".join([str(x) for x in col if str(x) != "nan"]).strip()
            for col in df_section.columns
        ]

    df_section.columns = [clean_text(c) for c in df_section.columns]

    rename_map = {}
    for c in df_section.columns:
        cl = str(c).lower()
        if "subject" in cl:
            rename_map[c] = "Subject"
        elif "am no" in cl or "amendment" in cl:
            rename_map[c] = "Am No"
        elif "author" in cl:
            rename_map[c] = "Author"
        elif "rcv" in cl and "etc" in cl:
            rename_map[c] = "RCV etc."
        elif cl == "vote" or " vote" in cl or cl.endswith("vote"):
            rename_map[c] = "Vote"
        elif "remarks" in cl or "rcv/ev" in cl:
            rename_map[c] = "RCV/EV – remarks"

    df_section = df_section.rename(columns=rename_map)

    wanted_cols = [
        "Subject",
        "Am No",
        "Author",
        "RCV etc.",
        "Vote",
        "RCV/EV – remarks",
    ]

    for col in wanted_cols:
        if col not in df_section.columns:
            df_section[col] = pd.NA

    other_cols = [c for c in df_section.columns if c not in wanted_cols]
    df_section = df_section[wanted_cols + other_cols]

    # ----------------------------
    # CLEANUP: merge accidental numeric columns like 0,1,2,...
    # ----------------------------
    spill_cols = [c for c in df_section.columns if str(c).isdigit()]

    if spill_cols:
        spill_cols = sorted(spill_cols, key=lambda x: int(str(x)))

        for i, spill_col in enumerate(spill_cols[:len(wanted_cols)]):
            target_col = wanted_cols[i]

            df_section[target_col] = df_section[target_col].where(
                df_section[target_col].notna() &
                (df_section[target_col].astype(str).str.strip() != ""),
                df_section[spill_col]
            )

        df_section = df_section.drop(columns=spill_cols)

    # Keep only target columns
    df_section = df_section[wanted_cols].copy()

    # Remove duplicated header rows inside body
    header_values = wanted_cols.copy()

    def is_duplicate_header_row(row):
        vals = [str(row[col]).strip() for col in wanted_cols]
        return vals == header_values

    df_section = df_section[~df_section.apply(is_duplicate_header_row, axis=1)].copy()

    # Drop fully empty rows
    df_section = df_section.dropna(how="all", subset=wanted_cols).copy()
    df_section = df_section.reset_index(drop=True)

    # ----------------------------
    # Parse all following tables as additional remarks
    # ----------------------------
    extra_tables = tables[main_table_index + 1:]

    additional_blocks = []
    for tbl in extra_tables:
        txt = parse_small_table(tbl)
        if txt:
            additional_blocks.append(txt)

    additional_remarks = "\n\n".join(additional_blocks)

    # ----------------------------
    # Add tracking columns
    # ----------------------------
    df_section.insert(0, "event_id", vote_event_id)
    df_section.insert(0, "procedure", procedure_id)
    df_section["additional remarks"] = additional_remarks

    return df_section


def build_ep_final_vote_results(input_csv, verbose=True):
    """
    Build the final EP vote-results dataframe from the timeline table.

    Parameters
    ----------
    input_csv : str
        Path to bld/timeline_table.csv.

    verbose : bool
        Whether to print progress messages.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        final_votes_df, failed_rows_df
    """
    df = pd.read_csv(input_csv)

    df1 = df[
        df["event"].str.contains("Results of vote in Parliament", case=False, na=False) &
        df["institution"].str.contains("European Parliament", case=False, na=False)
    ].copy()

    all_results = []
    failed_rows = []

    for idx, vote_row in df1.iterrows():
        try:
            result = extract_vote_section(vote_row, df, headers)
            all_results.append(result)

            if verbose:
                print(
                    f"Done: index={idx}, "
                    f"procedure={vote_row['procedure']}, "
                    f"event_id={vote_row['event_id']}"
                )

        except Exception as e:
            failed_rows.append({
                "df1_index": idx,
                "procedure": vote_row.get("procedure"),
                "event_id": vote_row.get("event_id"),
                "hyperlink": vote_row.get("hyperlink"),
                "error": str(e),
            })

            if verbose:
                print(
                    f"Failed: index={idx}, "
                    f"procedure={vote_row.get('procedure')}, "
                    f"event_id={vote_row.get('event_id')} -> {e}"
                )

    # ----------------------------
    # Combine all extracted tables
    # ----------------------------
    if all_results:
        final_votes_df = pd.concat(all_results, ignore_index=True)
    else:
        final_votes_df = pd.DataFrame()

    failed_rows_df = pd.DataFrame(failed_rows)

    if verbose:
        print("\nCombined extracted table:\n")
        print(final_votes_df)

        print("\nFailed rows:\n")
        print(failed_rows_df)

    return final_votes_df, failed_rows_df