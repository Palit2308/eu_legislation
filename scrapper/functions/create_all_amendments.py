import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import fitz  # PyMuPDF
import pandas as pd
import requests
from bs4 import BeautifulSoup


# =========================================================
# 1. BASIC SETTINGS
# =========================================================

HEADERS = {"User-Agent": "Mozilla/5.0"}

TARGET_EVENTS = {
    "Committee draft report",
    "Amendments tabled in committee",
}

REQUEST_TIMEOUT = 60
SLEEP_BETWEEN_REQUESTS = 0.3

AMENDMENT_START_RE = re.compile(r"^Amendment\s+(\d+[A-Za-z]?)\s*$", re.I)
ORIGIN_RE = re.compile(r"^Or\.\s*[A-Za-z-]+\s*$", re.I)

HEADER_PATTERNS = [
    r"^EN$",
    r"^\d+/\d+$",
    r"^PE[\d.]+v\d{2}-\d{2}$",
    r"^(?:PR|AM)\\.*$",
    r"^PE[\d.]+v\d{2}-\d{2}\s+\d+/\d+\s+(?:PR|AM)\\.*$",
    r"^(?:PR|AM)\\.*\s+\d+/\d+\s+PE[\d.]+v\d{2}-\d{2}$",
    r"^United in diversity$",
    r"^EN\s+United in diversity\s+EN$",
]

CONTEXT_STARTERS = (
    "proposal for ",
    "draft legislative resolution",
    "draft european parliament legislative resolution",
    "motion for a resolution",
    "recommendation for second reading",
    "common position",
)


# =========================================================
# 2. SMALL HELPERS
# =========================================================

def clean_text(text):
    """
    Normalize whitespace in extracted text.
    """
    if text is None:
        return ""
    text = str(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def make_absolute_url(base_url, maybe_relative_url):
    """
    Convert relative URL to absolute URL.
    """
    if not maybe_relative_url:
        return None
    return urljoin(base_url, maybe_relative_url)


def safe_get(row, candidates, default=None):
    """
    Return the first existing column value from a list of candidate column names.
    """
    for col in candidates:
        if col in row.index:
            return row[col]
    return default


def clean_join_space(lines):
    out = []
    for x in lines:
        x = clean_text(x)
        if not x:
            continue
        if set(x) == {"_"}:
            continue
        out.append(x)
    return clean_text(" ".join(out))


def clean_join_pipe(lines):
    out = []
    for x in lines:
        x = clean_text(x)
        if not x:
            continue
        out.append(x)
    return " | ".join(out)


def clean_join_semicolon(lines):
    out = []
    for x in lines:
        x = clean_text(x)
        if not x:
            continue
        out.append(x)
    return "; ".join(out)


def is_header_or_footer_line(text):
    txt = clean_text(text)
    if not txt:
        return True

    for pat in HEADER_PATTERNS:
        if re.match(pat, txt, flags=re.I):
            return True

    # Standalone page numbers
    if txt.isdigit():
        return True

    return False


def is_context_start(text):
    txt = clean_text(text).lower()
    if txt.startswith(CONTEXT_STARTERS):
        return True

    # A few additional common legislative heading patterns
    if "legislative resolution" in txt:
        return True

    return False


def looks_like_column_header(left_text, right_text):
    """
    Detect the row where the two columns actually begin.

    We key mostly off the right header being 'Amendment',
    because the left header is variable:
    - Text proposed by the Commission
    - Draft legislative resolution
    - etc.
    """
    left = clean_text(left_text).lower()
    right = clean_text(right_text).lower()

    if right == "amendment":
        return True

    if left == "text proposed by the commission" and "amendment" in right:
        return True

    return False


# =========================================================
# 3. EXTRACT PDF LINK FROM HTML PAGE
# =========================================================

def extract_pdf_link_from_html(html_url, session=None, verbose=False):
    """
    Open an HTML page and extract the best PDF link.

    Strategy:
    - if html_url already ends with .pdf, return it directly
    - otherwise parse HTML and collect all hrefs ending in .pdf
    - prefer English PDF (_EN.pdf) when available
    - otherwise return the first PDF link found
    """
    if not html_url or pd.isna(html_url):
        raise ValueError("HTML link is missing")

    html_url = str(html_url).strip()

    if html_url.lower().endswith(".pdf"):
        if verbose:
            print(f"   Direct PDF link already provided: {html_url}")
        return html_url

    sess = session or requests.Session()
    resp = sess.get(html_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    pdf_candidates = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if ".pdf" in href.lower():
            full_url = make_absolute_url(html_url, href)
            text = clean_text(a.get_text(" ", strip=True))
            aria = a.get("aria-label", "")
            pdf_candidates.append({
                "href": full_url,
                "text": text,
                "aria": aria,
            })

    # remove duplicates while preserving order
    seen = set()
    unique_candidates = []
    for c in pdf_candidates:
        if c["href"] not in seen:
            unique_candidates.append(c)
            seen.add(c["href"])

    if verbose:
        print(f"   Found {len(unique_candidates)} PDF candidate(s)")
        for j, c in enumerate(unique_candidates[:5], 1):
            print(f"      {j}. {c['href']} | text={c['text']} | aria={c['aria']}")

    if not unique_candidates:
        raise ValueError("No PDF link found on HTML page")

    # Prefer English pdf if available
    for c in unique_candidates:
        if re.search(r"_EN\.pdf$", c["href"], re.I):
            if verbose:
                print(f"   Selected EN PDF: {c['href']}")
            return c["href"]

    # Otherwise prefer one explicitly marked pdf
    for c in unique_candidates:
        if "pdf" in c["text"].lower() or str(c["aria"]).lower() == "pdf":
            if verbose:
                print(f"   Selected PDF by label: {c['href']}")
            return c["href"]

    # Fallback: first PDF
    if verbose:
        print(f"   Selected first PDF candidate: {unique_candidates[0]['href']}")
    return unique_candidates[0]["href"]


# =========================================================
# 4. EXTRACT TEXT FROM PDF URL
# =========================================================

def extract_text_from_pdf_url(pdf_url, session=None, verbose=False):
    """
    Download PDF and extract all text page by page using PyMuPDF.
    """
    if not pdf_url or pd.isna(pdf_url):
        raise ValueError("PDF link is missing")

    pdf_url = str(pdf_url).strip()
    sess = session or requests.Session()

    resp = sess.get(pdf_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    doc = fitz.open(stream=resp.content, filetype="pdf")

    if verbose:
        print(f"   PDF opened successfully | pages = {doc.page_count}")

    pages_text = []

    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        page_text = page.get_text("text")
        page_text = clean_text(page_text)

        if verbose and pno < 3:
            preview = page_text[:150].replace("\n", " ")
            print(f"      Page {pno + 1} preview: {preview}")

        if page_text:
            pages_text.append(page_text)

    doc.close()

    full_text = "\n\n".join(pages_text)
    full_text = clean_text(full_text)

    if verbose:
        print(f"   Extracted text length = {len(full_text):,} characters")

    return full_text


# =========================================================
# 5. BUILD DOCUMENT-LEVEL DATAFRAME
# =========================================================

def build_event_pdf_text_df(
    df,
    procedure_col="procedure",
    event_col="event",
    reference_col="reference",
    hyperlink_col="hyperlink",
    verbose=True,
):
    """
    Build final dataframe with columns:
    procedure, event, reference, link, extracted_text

    Rules:
    - Keep only target events
    - For 'Committee draft report': keep only one row per procedure
    - For 'Amendments tabled in committee': allow multiple occurrences
      but remove exact duplicate records if present

    Also returns failed_rows_df for debugging.
    """
    required_cols = [procedure_col, event_col, hyperlink_col]
    missing_required = [c for c in required_cols if c not in df.columns]
    if missing_required:
        raise KeyError(f"Missing required columns in df: {missing_required}")

    work_df = df.copy()

    if verbose:
        print("=" * 80)
        print("STEP 1: Initial dataframe check")
        print("=" * 80)
        print(f"Input rows: {len(work_df):,}")
        print(f"Columns: {list(work_df.columns)}")
        print()

    # Keep only target events
    work_df[event_col] = work_df[event_col].astype(str).str.strip()
    filtered_df = work_df[work_df[event_col].isin(TARGET_EVENTS)].copy()

    if verbose:
        print("=" * 80)
        print("STEP 2: Filter to target events")
        print("=" * 80)
        print(f"Rows after event filter: {len(filtered_df):,}")
        if not filtered_df.empty:
            print(filtered_df[event_col].value_counts(dropna=False))
        print()

    if filtered_df.empty:
        if verbose:
            print("No matching rows found for target events.")
        empty_out = pd.DataFrame(columns=["procedure", "event", "reference", "link", "extracted_text"])
        empty_fail = pd.DataFrame(columns=["procedure", "event", "reference", "html_link", "error"])
        return empty_out, empty_fail

    # ---------------------------------------------------
    # DUPLICATE HANDLING
    # ---------------------------------------------------
    # Rule:
    # 1. Committee draft report -> keep one per procedure
    # 2. Amendments tabled in committee -> allow multiple rows
    #    but remove exact duplicate documents if any
    # ---------------------------------------------------

    draft_mask = filtered_df[event_col] == "Committee draft report"
    amend_mask = filtered_df[event_col] == "Amendments tabled in committee"

    draft_df = filtered_df[draft_mask].copy()
    amend_df = filtered_df[amend_mask].copy()

    if verbose:
        print("=" * 80)
        print("STEP 3: Before duplicate cleanup")
        print("=" * 80)
        print(f"Committee draft report rows        : {len(draft_df):,}")
        print(f"Amendments tabled in committee rows: {len(amend_df):,}")
        print()

    # For draft reports: one per procedure
    draft_dups = draft_df[draft_df.duplicated(subset=[procedure_col], keep=False)].copy()

    if verbose:
        print("Duplicate Committee draft report rows by procedure:")
        print(f"{len(draft_dups):,}")
        if not draft_dups.empty:
            cols_to_show = [c for c in [procedure_col, event_col, hyperlink_col, reference_col] if c in draft_dups.columns]
            print(draft_dups[cols_to_show].head(10))
        print()

    draft_df = draft_df.drop_duplicates(subset=[procedure_col], keep="first").copy()

    # For amendments: keep multiple occurrences, remove only exact duplicates
    amend_subset = [procedure_col, event_col, hyperlink_col]
    if reference_col in amend_df.columns:
        amend_subset.append(reference_col)

    amend_dups = amend_df[amend_df.duplicated(subset=amend_subset, keep=False)].copy()

    if verbose:
        print("Exact duplicate amendment rows:")
        print(f"{len(amend_dups):,}")
        if not amend_dups.empty:
            cols_to_show = [c for c in [procedure_col, event_col, hyperlink_col, reference_col] if c in amend_dups.columns]
            print(amend_dups[cols_to_show].head(10))
        print()

    amend_df = amend_df.drop_duplicates(subset=amend_subset, keep="first").copy()

    # Put them back together
    filtered_df = pd.concat([draft_df, amend_df], ignore_index=True)

    # Optional sorting for readability
    filtered_df = filtered_df.sort_values(
        by=[procedure_col, event_col],
        kind="stable",
    ).reset_index(drop=True)

    if verbose:
        print("=" * 80)
        print("STEP 4: After duplicate cleanup")
        print("=" * 80)
        print(f"Rows kept for Committee draft report        : {len(draft_df):,}")
        print(f"Rows kept for Amendments tabled in committee: {len(amend_df):,}")
        print(f"Total rows to scrape                        : {len(filtered_df):,}")
        print()

    # Final extraction loop
    results = []
    failed_rows = []

    session = requests.Session()

    if verbose:
        print("=" * 80)
        print("STEP 5: Start scraping + PDF extraction")
        print("=" * 80)

    total = len(filtered_df)

    for i, (_, row) in enumerate(filtered_df.iterrows(), start=1):
        procedure = safe_get(row, [procedure_col], "")
        event = safe_get(row, [event_col], "")
        reference = safe_get(row, [reference_col], "") if reference_col in filtered_df.columns else ""
        html_link = safe_get(row, [hyperlink_col], "")

        print(f"[{i}/{total}] procedure={procedure} | event={event}")

        try:
            if pd.isna(html_link) or not str(html_link).strip():
                raise ValueError("Missing hyperlink")

            html_link = str(html_link).strip()
            print(f"   HTML link: {html_link}")

            pdf_link = extract_pdf_link_from_html(
                html_url=html_link,
                session=session,
                verbose=True,
            )

            extracted_text = extract_text_from_pdf_url(
                pdf_url=pdf_link,
                session=session,
                verbose=True,
            )

            results.append({
                "procedure": procedure,
                "event": event,
                "reference": reference,
                "link": pdf_link,
                "extracted_text": extracted_text,
            })

            print(f"   SUCCESS | stored row | text chars = {len(extracted_text):,}")
            print("-" * 80)

        except Exception as e:
            failed_rows.append({
                "procedure": procedure,
                "event": event,
                "reference": reference,
                "html_link": html_link,
                "error": str(e),
            })

            print(f"   FAILED | {e}")
            print("-" * 80)

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    final_df = pd.DataFrame(results)
    failed_rows_df = pd.DataFrame(failed_rows)

    if verbose:
        print()
        print("=" * 80)
        print("STEP 6: Final sanity checks")
        print("=" * 80)
        print(f"Final extracted rows: {len(final_df):,}")
        print(f"Failed rows         : {len(failed_rows_df):,}")

        if not final_df.empty:
            print("\nFinal dataframe columns:")
            print(list(final_df.columns))

            print("\nSample rows:")
            print(final_df[["procedure", "event", "reference", "link"]].head())

            print("\nExtracted text lengths:")
            temp = final_df.copy()
            temp["text_len"] = temp["extracted_text"].fillna("").str.len()
            print(temp[["procedure", "event", "text_len"]].head())

            print("\nRows per event in final_df:")
            print(final_df["event"].value_counts(dropna=False))

            print("\nAmendment rows per procedure:")
            amend_final = final_df[final_df["event"] == "Amendments tabled in committee"]
            if not amend_final.empty:
                print(amend_final.groupby("procedure").size().sort_values(ascending=False).head(20))

        if not failed_rows_df.empty:
            print("\nFailed rows preview:")
            print(failed_rows_df.head())

    return final_df, failed_rows_df


# =========================================================
# 6. PDF LOADING
# =========================================================

def load_pdf_bytes(pdf_source, session=None):
    """
    Supports:
    - http(s) URL
    - local file path
    """
    if pdf_source is None or pd.isna(pdf_source):
        raise ValueError("PDF source is missing")

    pdf_source = str(pdf_source).strip()
    parsed = urlparse(pdf_source)

    if parsed.scheme in {"http", "https"}:
        sess = session or requests.Session()
        resp = sess.get(pdf_source, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content

    # Local file path
    path = Path(pdf_source)
    if not path.exists():
        raise FileNotFoundError(f"Local file not found: {pdf_source}")

    return path.read_bytes()


# =========================================================
# 7. EXTRACT PDF LINES WITH COORDINATES
# =========================================================

def extract_lines_from_page(page):
    """
    Extract line-level text with coordinates from one page.
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
            y1 = max(span["bbox"][3] for span in spans)

            lines.append({
                "text": text,
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
            })

    lines.sort(key=lambda z: (round(z["y0"], 1), z["x0"]))
    return lines


def group_lines_into_rows(lines, y_tol=2.5):
    """
    Group nearby PDF lines into visual rows.
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
        if not txt:
            continue
        if is_header_or_footer_line(txt):
            continue

        full_parts.append(txt)

        center = (line["x0"] + line["x1"]) / 2
        if center < mid_x:
            left_parts.append(txt)
        else:
            right_parts.append(txt)

    full_text = clean_text(" ".join(full_parts))
    left_text = clean_text(" ".join(left_parts))
    right_text = clean_text(" ".join(right_parts))

    return full_text, left_text, right_text


# =========================================================
# 8. AMENDMENT STATE MACHINE
# =========================================================

def init_amendment_state(amendment_number, page_num):
    return {
        "amendment_number": amendment_number,
        "author_lines": [],
        "context_lines": [],
        "left_header": "",
        "right_header": "",
        "left_lines": [],
        "right_lines": [],
        "justification_lines": [],
        "origin_lines": [],
        "context_started": False,
        "in_columns": False,
        "in_justification": False,
        "source_page_start": page_num,
        "source_page_end": page_num,
    }


def finalize_amendment(current, procedure, event, reference, link):
    if current is None:
        return None

    return {
        "procedure": procedure,
        "event": event,
        "reference": reference,
        "link": link,
        "amendment_number": current["amendment_number"],
        "authors": clean_join_semicolon(current["author_lines"]),
        "ref_text": clean_join_pipe(current["context_lines"]),
        "left_header": clean_text(current["left_header"]),
        "right_header": clean_text(current["right_header"]),
        "text_proposed_by_commission": clean_join_space(current["left_lines"]),
        "amended_text": clean_join_space(current["right_lines"]),
        "justification": clean_join_space(current["justification_lines"]),
        "origin": clean_join_semicolon(current["origin_lines"]),
        "source_page_start": current["source_page_start"],
        "source_page_end": current["source_page_end"],
    }


def consume_rows(rows, current, mid_x, page_num):
    """
    Consume rows belonging to the current amendment.
    """
    for row in rows:
        full_text, left_text, right_text = split_row(row, mid_x)

        if not full_text:
            continue

        current["source_page_end"] = page_num

        # Origin line like "Or. en"
        if ORIGIN_RE.match(full_text):
            current["origin_lines"].append(full_text)
            continue

        # Start of justification block
        if clean_text(full_text).lower() == "justification":
            current["in_justification"] = True
            continue

        # Once in justification, everything until next amendment goes there
        if current["in_justification"]:
            current["justification_lines"].append(full_text)
            continue

        # Before columns start: collect authors + context lines
        if not current["in_columns"]:
            if left_text and right_text and looks_like_column_header(left_text, right_text):
                current["left_header"] = left_text
                current["right_header"] = right_text
                current["in_columns"] = True
                continue

            if not current["context_started"] and is_context_start(full_text):
                current["context_started"] = True
                current["context_lines"].append(full_text)
                continue

            if current["context_started"]:
                current["context_lines"].append(full_text)
            else:
                current["author_lines"].append(full_text)

            continue

        # In columns
        if (
            left_text and right_text
            and clean_text(left_text) == clean_text(current["left_header"])
            and clean_text(right_text) == clean_text(current["right_header"])
        ):
            continue

        # Skip decorative separator rows only
        if set(full_text) == {"_"}:
            continue

        if left_text:
            current["left_lines"].append(left_text)

        if right_text:
            current["right_lines"].append(right_text)


# =========================================================
# 9. PARSE ONE PDF INTO AMENDMENT-LEVEL ROWS
# =========================================================

def parse_amendments_from_pdf(
    pdf_source,
    procedure="",
    event="",
    reference="",
    link="",
    session=None,
    verbose=True,
):
    """
    Parse one amendments-style PDF into one row per amendment.
    """
    pdf_bytes = load_pdf_bytes(pdf_source, session=session)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if verbose:
        print("=" * 90)
        print("Parsing PDF for amendments")
        print(f"procedure = {procedure}")
        print(f"event     = {event}")
        print(f"reference = {reference}")
        print(f"source    = {pdf_source}")
        print(f"pages     = {doc.page_count}")
        print("=" * 90)

    all_rows = []
    current = None
    found_first_amendment = False

    def flush_current():
        nonlocal current
        if current is None:
            return
        row = finalize_amendment(
            current=current,
            procedure=procedure,
            event=event,
            reference=reference,
            link=link or pdf_source,
        )
        if row is not None:
            all_rows.append(row)
        current = None

    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        page_lines = extract_lines_from_page(page)
        page_rows = group_lines_into_rows(page_lines)
        mid_x = page.rect.width / 2

        amendment_starts = []
        for i, row in enumerate(page_rows):
            full_text, _, _ = split_row(row, mid_x)
            m = AMENDMENT_START_RE.match(full_text)
            if m:
                amendment_starts.append((i, m.group(1).strip()))

        if verbose:
            print(f"\nPage {pno + 1}: amendment starts found = {len(amendment_starts)}")
            if amendment_starts:
                print("   numbers =", [x[1] for x in amendment_starts[:10]])

        # No amendment start on this page
        if not amendment_starts:
            if current is not None:
                if verbose:
                    print("   continuation page for current amendment")
                consume_rows(page_rows, current, mid_x, pno + 1)
            else:
                if verbose and not found_first_amendment:
                    print("   pre-amendment page skipped")
            continue

        found_first_amendment = True

        # Any rows before the first amendment start belong to previous amendment
        first_start_idx = amendment_starts[0][0]
        if current is not None and first_start_idx > 0:
            if verbose:
                print("   rows before first start belong to previous amendment")
            consume_rows(page_rows[:first_start_idx], current, mid_x, pno + 1)

        # Process each amendment block on the page
        for pos, (start_idx, amendment_no) in enumerate(amendment_starts):
            if current is not None:
                flush_current()

            current = init_amendment_state(amendment_no, pno + 1)

            if verbose:
                print(f"   -> opened Amendment {amendment_no} on page {pno + 1}")

            end_idx = amendment_starts[pos + 1][0] if pos + 1 < len(amendment_starts) else len(page_rows)
            segment = page_rows[start_idx + 1:end_idx]
            consume_rows(segment, current, mid_x, pno + 1)

    if current is not None:
        flush_current()

    doc.close()

    df_out = pd.DataFrame(all_rows)

    if verbose:
        print("\n" + "=" * 90)
        print(f"Finished PDF: extracted amendment rows = {len(df_out)}")
        if not df_out.empty:
            print(df_out[[
                "amendment_number",
                "authors",
                "ref_text",
                "source_page_start",
                "source_page_end",
            ]].head(10))
        print("=" * 90)

    return df_out


# =========================================================
# 10. PARSE ALL ROWS IN final_docs_df
# =========================================================

def build_amendment_level_df(
    final_docs_df,
    procedure_col="procedure",
    event_col="event",
    reference_col="reference",
    link_col="link",
    allowed_events=None,
    verbose=True,
):
    """
    Takes document-level final_docs_df and returns amendment-level dataframe.

    Expected final_docs_df columns:
    - procedure
    - event
    - reference
    - link

    Returns:
    - amendments_df
    - failed_docs_df
    """
    required_cols = [procedure_col, event_col, link_col]
    missing = [c for c in required_cols if c not in final_docs_df.columns]
    if missing:
        raise KeyError(f"Missing required columns in final_docs_df: {missing}")

    work_df = final_docs_df.copy()

    if allowed_events is not None:
        work_df = work_df[work_df[event_col].isin(allowed_events)].copy()

    work_df = work_df.reset_index(drop=True)

    if verbose:
        print("\n" + "#" * 100)
        print("DOCUMENT-LEVEL INPUT CHECK")
        print("#" * 100)
        print(f"Rows to parse: {len(work_df)}")
        if not work_df.empty:
            print(work_df[[procedure_col, event_col, link_col]].head())
        print("#" * 100)

    all_dfs = []
    failed_docs = []

    session = requests.Session()

    for i, row in work_df.iterrows():
        procedure = row.get(procedure_col, "")
        event = row.get(event_col, "")
        reference = row.get(reference_col, "") if reference_col in work_df.columns else ""
        link = row.get(link_col, "")

        print("\n" + "-" * 100)
        print(f"[{i + 1}/{len(work_df)}] procedure={procedure} | event={event}")
        print(f"link={link}")

        try:
            if pd.isna(link) or not str(link).strip():
                raise ValueError("Missing PDF link")

            temp_df = parse_amendments_from_pdf(
                pdf_source=str(link).strip(),
                procedure=procedure,
                event=event,
                reference=reference,
                link=str(link).strip(),
                session=session,
                verbose=verbose,
            )

            if temp_df is None or temp_df.empty:
                failed_docs.append({
                    "procedure": procedure,
                    "event": event,
                    "reference": reference,
                    "link": link,
                    "error": "No amendments extracted from PDF",
                })
                print("No amendment rows extracted.")
            else:
                all_dfs.append(temp_df)
                print(f"SUCCESS: extracted {len(temp_df)} amendment rows")

        except Exception as e:
            failed_docs.append({
                "procedure": procedure,
                "event": event,
                "reference": reference,
                "link": link,
                "error": str(e),
            })
            print(f"FAILED: {e}")

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    amendments_df = pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()
    failed_docs_df = pd.DataFrame(failed_docs)

    if verbose:
        print("\n" + "#" * 100)
        print("FINAL SANITY CHECK")
        print("#" * 100)
        print(f"Extracted amendment rows: {len(amendments_df)}")
        print(f"Failed documents        : {len(failed_docs_df)}")

        if not amendments_df.empty:
            print("\nColumns:")
            print(list(amendments_df.columns))

            print("\nTop rows:")
            print(amendments_df[[
                "procedure",
                "event",
                "amendment_number",
                "authors",
                "ref_text",
                "source_page_start",
                "source_page_end",
            ]].head(15))

            print("\nRows by event:")
            print(amendments_df["event"].value_counts(dropna=False))

            print("\nAmendment count by procedure/event:")
            print(
                amendments_df
                .groupby(["procedure", "event"])
                .size()
                .reset_index(name="n_amendments")
                .head(20)
            )

        if not failed_docs_df.empty:
            print("\nFailed documents preview:")
            print(failed_docs_df.head())

    return amendments_df, failed_docs_df


# =========================================================
# 11. OPTIONAL: QUICK TEST ON LOCAL FILES
# =========================================================

def test_single_local_pdf(local_pdf_path, procedure="", event="", reference=""):
    df = parse_amendments_from_pdf(
        pdf_source=local_pdf_path,
        procedure=procedure,
        event=event,
        reference=reference,
        link=local_pdf_path,
        verbose=True,
    )
    print(df.head(10))
    return df


# =========================================================
# 12. MAIN REUSABLE BUILDER
# =========================================================

def build_all_amendments(input_csv, verbose=True):
    """
    Run the full all-amendments pipeline.

    Parameters
    ----------
    input_csv : str
        Path to bld/timeline_table.csv.

    verbose : bool
        Whether to print progress messages.

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]
        amendment_level_df,
        final_docs_df,
        failed_pdf_text_rows_df,
        failed_amendment_docs_df
    """
    df = pd.read_csv(input_csv)

    final_docs_df, failed_pdf_text_rows_df = build_event_pdf_text_df(
        df,
        verbose=verbose,
    )

    amendment_level_df, failed_amendment_docs_df = build_amendment_level_df(
        final_docs_df,
        allowed_events=[
            "Committee draft report",
            "Amendments tabled in committee",
        ],
        verbose=verbose,
    )

    return (
        amendment_level_df,
        final_docs_df,
        failed_pdf_text_rows_df,
        failed_amendment_docs_df,
    )