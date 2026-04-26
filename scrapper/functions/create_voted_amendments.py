import re
from urllib.parse import urljoin

import fitz  # PyMuPDF
import pandas as pd
import requests
from bs4 import BeautifulSoup


headers = {"User-Agent": "Mozilla/5.0"}

AMENDMENT_START_RE = re.compile(r"^Amendment\s+(\d+[A-Za-z]?)\s*$", re.I)

HEADER_PATTERNS = [
    r"^PE\d[\d./ ]*$",
    r"^EN$",
    r"^\d{1,2}\.\d{1,2}\.\d{4}$",
    r"^[AB]\d+-\d+/\d{4}$",
    r"^[AB]\d+-\d+/\s*\d+-?\d*$",
]


def clean_text(x):
    return re.sub(r"\s+", " ", str(x).replace("\xa0", " ")).strip()


def is_header_or_footer_line(text):
    txt = clean_text(text)
    if not txt:
        return True
    for pat in HEADER_PATTERNS:
        if re.match(pat, txt):
            return True
    if txt.isdigit():
        return True
    return False


def extract_lines(page):
    """
    Extract lines with coordinates from one PDF page.
    """
    data = page.get_text("dict")
    lines = []

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue

            text = "".join(span.get("text", "") for span in spans)
            text = clean_text(text)
            if not text:
                continue

            x0 = min(span["bbox"][0] for span in spans)
            x1 = max(span["bbox"][2] for span in spans)
            y0 = min(span["bbox"][1] for span in spans)

            lines.append({
                "text": text,
                "x0": x0,
                "x1": x1,
                "y0": y0,
            })

    lines.sort(key=lambda z: (round(z["y0"], 1), z["x0"]))
    return lines


def group_lines_into_rows(lines, y_tol=2.5):
    """
    Group nearby PDF lines into visual rows using y-coordinate tolerance.
    """
    rows = []
    current_row = []
    current_y = None

    for line in lines:
        if current_y is None:
            current_row = [line]
            current_y = line["y0"]
            continue

        if abs(line["y0"] - current_y) <= y_tol:
            current_row.append(line)
            current_y = sum(x["y0"] for x in current_row) / len(current_row)
        else:
            rows.append(sorted(current_row, key=lambda z: z["x0"]))
            current_row = [line]
            current_y = line["y0"]

    if current_row:
        rows.append(sorted(current_row, key=lambda z: z["x0"]))

    return rows


def split_row(row, mid_x):
    """
    Split one visual row into:
    - full row text
    - left-side text
    - right-side text
    """
    full_parts = []
    left_parts = []
    right_parts = []

    for line in row:
        txt = clean_text(line["text"])
        if not txt or is_header_or_footer_line(txt):
            continue

        full_parts.append(txt)

        center = (line["x0"] + line["x1"]) / 2
        if center < mid_x:
            left_parts.append(txt)
        else:
            right_parts.append(txt)

    full_text = " ".join(full_parts).strip()
    left_text = " ".join(left_parts).strip()
    right_text = " ".join(right_parts).strip()

    return full_text, left_text, right_text


def join_prose(lines):
    """
    Turn a list of PDF lines into one prose string.
    """
    out = []
    for line in lines:
        line = clean_text(line)
        if not line:
            continue
        if line == "__________________":
            break
        out.append(line)

    text = " ".join(out)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def consume_segment(lines, current, mid_x):
    """
    Consume a chunk of lines belonging to the current amendment.

    Logic:
    - before the first 2-sided row: store in ref_lines
    - first 2-sided row: treat as dynamic column headers
    - after that: store left/right column text
    """
    rows = group_lines_into_rows(lines)

    for row in rows:
        full_text, left_text, right_text = split_row(row, mid_x)

        if not full_text:
            continue

        # before columns start
        if not current["in_columns"]:
            # first row that has text on both sides = header row
            if left_text and right_text:
                current["left_header"] = left_text
                current["right_header"] = right_text
                current["in_columns"] = True
            else:
                current["ref_lines"].append(full_text)
            continue

        # if a continuation page repeats the same header row, skip it
        if (
            left_text and right_text
            and clean_text(left_text) == clean_text(current["left_header"])
            and clean_text(right_text) == clean_text(current["right_header"])
        ):
            continue

        if left_text:
            current["left_lines"].append(left_text)
        if right_text:
            current["right_lines"].append(right_text)


def extract_amendments_from_pdf(pdf_url, procedure):
    response = requests.get(pdf_url, headers=headers, timeout=60)
    response.raise_for_status()

    doc = fitz.open(stream=response.content, filetype="pdf")

    all_rows = []
    current = None

    def finalize_current():
        nonlocal current
        if current is None:
            return

        all_rows.append({
            "procedure": procedure,
            "amendment_number": current["amendment_number"],

            # everything between "Amendment X" and the column header row
            "ref_text": " ".join(current["ref_lines"]).strip(),

            # dynamic column headers
            "left_header": current["left_header"],
            "right_header": current["right_header"],

            # keep old column name for compatibility, but now it means:
            # "whatever is in the left column"
            "text_proposed_by_commission": join_prose(current["left_lines"]),

            # right column content
            "amended_prose": join_prose(current["right_lines"]),
        })

    for page in doc:
        page_lines = extract_lines(page)
        mid_x = page.rect.width / 2

        amendment_starts = []
        for i, line in enumerate(page_lines):
            m = AMENDMENT_START_RE.match(line["text"])
            if m:
                amendment_starts.append((i, m.group(1).strip()))

        # continuation page: no new amendment starts
        if not amendment_starts:
            if current is not None:
                consume_segment(page_lines, current, mid_x)
            continue

        # text before first amendment on page belongs to previous amendment
        first_start_idx = amendment_starts[0][0]
        if current is not None and first_start_idx > 0:
            consume_segment(page_lines[:first_start_idx], current, mid_x)

        # process each amendment block on this page
        for pos, (start_idx, amendment_no) in enumerate(amendment_starts):
            if current is not None:
                finalize_current()

            current = {
                "amendment_number": amendment_no,
                "ref_lines": [],
                "left_header": "",
                "right_header": "",
                "left_lines": [],
                "right_lines": [],
                "in_columns": False,
            }

            end_idx = amendment_starts[pos + 1][0] if pos + 1 < len(amendment_starts) else len(page_lines)
            segment = page_lines[start_idx + 1:end_idx]
            consume_segment(segment, current, mid_x)

    if current is not None:
        finalize_current()

    doc.close()

    df_pdf = pd.DataFrame(all_rows)
    return df_pdf


def build_voted_amendments(input_csv, verbose=True):
    """
    Build the voted amendments dataframe from the timeline table.

    Parameters
    ----------
    input_csv : str
        Path to the timeline_table.csv file.

    verbose : bool
        Whether to print progress messages.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        df_all_amendments, failed_rows_df
    """
    df = pd.read_csv(input_csv)

    df1 = df[
        df["event"].str.contains("Committee report tabled for plenary, 1st reading", case=False, na=False) &
        df["institution"].str.contains("European Parliament", case=False, na=False)
    ].copy()

    # keep only one row per reference
    df1_unique = (
        df1.dropna(subset=["reference"])
           .drop_duplicates(subset=["reference"])
           .copy()
    )

    all_records = []
    failed_rows = []

    for idx, row in df1_unique.iterrows():
        procedure_id = row["procedure"]
        reference = row["reference"]
        url = row["hyperlink"]

        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # find the Amendments dropdown content
            dropdown = soup.find("div", id="esDropdownAMDContent")

            if dropdown is None:
                if verbose:
                    print(f"No Amendments dropdown found for {reference}")
                continue

            # extract only PDF links
            for a in dropdown.find_all("a", href=True):
                href = a["href"]

                if not href.lower().endswith(".pdf"):
                    continue

                span = a.find("span", class_="t-x")
                if span:
                    am_text = span.contents[0].strip() if span.contents else span.get_text(" ", strip=True)
                else:
                    am_text = a.get_text(" ", strip=True)

                full_link = urljoin(url, href)

                all_records.append({
                    "procedure": procedure_id,
                    "reference": reference,
                    "am_no": am_text,
                    "hyperlink": full_link
                })

            if verbose:
                print(f"Done: {reference}")

        except Exception as e:
            failed_rows.append({
                "df1_index": idx,
                "procedure": procedure_id,
                "reference": reference,
                "hyperlink": url,
                "error": str(e)
            })
            if verbose:
                print(f"Failed: {reference} -> {e}")

    amendments_df1 = pd.DataFrame(all_records)
    failed_rows_df = pd.DataFrame(failed_rows)

    all_dfs = []
    failed_rows = []

    for idx, row in amendments_df1.iterrows():
        pdf_url = row.get("hyperlink")
        procedure = row.get("procedure")
        am_no = row.get("am_no")

        # skip empty / invalid links
        if pd.isna(pdf_url) or not str(pdf_url).strip():
            failed_rows.append({
                "index": idx,
                "procedure": procedure,
                "am_no": am_no,
                "hyperlink": pdf_url,
                "error": "Missing or empty hyperlink"
            })
            if verbose:
                print(f"Failed: {idx} | {procedure} | {am_no} -> Missing or empty hyperlink")
            continue

        pdf_url = str(pdf_url).strip()

        try:
            temp_df = extract_amendments_from_pdf(pdf_url, procedure)

            # handle cases where extraction returns nothing
            if temp_df is None or temp_df.empty:
                failed_rows.append({
                    "index": idx,
                    "procedure": procedure,
                    "am_no": am_no,
                    "hyperlink": pdf_url,
                    "error": "No amendments extracted"
                })
                if verbose:
                    print(f"Failed: {idx} | {procedure} | {am_no} -> No amendments extracted")
                continue

            temp_df = temp_df.copy()
            temp_df["source_index"] = idx
            temp_df["source_am_no"] = am_no
            temp_df["source_pdf_link"] = pdf_url

            all_dfs.append(temp_df)
            if verbose:
                print(f"Done: {idx} | {procedure} | {am_no} | extracted {len(temp_df)} rows")

        except Exception as e:
            failed_rows.append({
                "index": idx,
                "procedure": procedure,
                "am_no": am_no,
                "hyperlink": pdf_url,
                "error": str(e)
            })
            if verbose:
                print(f"Failed: {idx} | {procedure} | {am_no} -> {e}")

    # combine all extracted dfs
    if all_dfs:
        df_all_amendments = pd.concat(all_dfs, ignore_index=True)
    else:
        df_all_amendments = pd.DataFrame()

    failed_rows_df = pd.DataFrame(failed_rows)

    if verbose:
        print(df_all_amendments.head())
        print(f"\nTotal extracted rows: {len(df_all_amendments)}")
        print(f"Total failed files: {len(failed_rows_df)}")

    return df_all_amendments, failed_rows_df