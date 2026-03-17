import io
import re
from urllib.parse import urljoin
from typing import Optional, Dict, List

import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


# ---------------------------------------------------------------------
# basic helpers
# ---------------------------------------------------------------------
def fetch_html(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def clean_text(text: str) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def extract_pdf_text_from_url(pdf_url: str) -> str:
    """
    Download a PDF and extract all text with pypdf.
    """
    response = requests.get(pdf_url, timeout=60)
    response.raise_for_status()

    reader = PdfReader(io.BytesIO(response.content))
    pages = []

    for page in reader.pages:
        txt = page.extract_text() or ""
        txt = clean_text(txt)
        if txt:
            pages.append(txt)

    return "\n\n".join(pages)


# ---------------------------------------------------------------------
# find available downloadable formats on an "other format" procedure page
# ---------------------------------------------------------------------
def get_other_format_links(procedure_url: str) -> Dict[str, Optional[str]]:
    """
    Return available download links from a procedure page.

    Output:
        {
            "pdf": "...",
            "word": "..."
        }

    Prefers links found near the 'not available in HTML' placeholder,
    but falls back to searching the full page.
    """
    html = fetch_html(procedure_url)
    soup = BeautifulSoup(html, "html.parser")

    links = {"pdf": None, "word": None}

    # Try to detect the "other formats" message
    placeholder = soup.find(
        string=re.compile(
            r"This document does not exist in HTML but is available in the following formats:",
            re.IGNORECASE
        )
    )

    if placeholder:
        container = placeholder.parent
        while container and container.name not in ["div", "section", "article", "body"]:
            container = container.parent
        search_root = container if container else soup
    else:
        search_root = soup

    anchors = search_root.find_all("a", href=True)

    for a in anchors:
        href = urljoin(procedure_url, a["href"])
        href_l = href.lower()
        text_l = clean_text(a.get_text(" ", strip=True)).lower()
        title_l = clean_text(a.get("title", "")).lower()

        is_pdf = (
            href_l.endswith(".pdf")
            or ".pdf" in href_l
            or text_l == "pdf"
            or " pdf" in text_l
            or title_l == "pdf"
            or "pdf" in title_l
        )

        is_word = (
            href_l.endswith(".doc")
            or href_l.endswith(".docx")
            or ".doc" in href_l
            or ".docx" in href_l
            or text_l == "word"
            or "word" in text_l
            or text_l == "doc"
            or text_l == "docx"
            or "word" in title_l
            or "doc" in title_l
        )

        if is_pdf and links["pdf"] is None:
            links["pdf"] = href

        if is_word and links["word"] is None:
            links["word"] = href

    return links


def extract_other_format_record(
    procedure: str,
    reference: str,
    procedure_url: str
) -> Dict[str, str]:
    """
    For one procedure page, detect available formats and extract PDF text if possible.

    Output columns:
        procedure, reference, format, extracted_text
    """
    links = get_other_format_links(procedure_url)

    pdf_url = links.get("pdf")
    word_url = links.get("word")

    if pdf_url:
        try:
            extracted_text = extract_pdf_text_from_url(pdf_url)
        except Exception as e:
            extracted_text = f"PDF extraction failed: {e}"
        return {
            "procedure": procedure,
            "reference": reference,
            "format": "pdf",
            "extracted_text": extracted_text,
        }

    if word_url:
        # Word fallback noted, but not extracted yet
        return {
            "procedure": procedure,
            "reference": reference,
            "format": "word",
            "extracted_text": "",
        }

    return {
        "procedure": procedure,
        "reference": reference,
        "format": "",
        "extracted_text": "",
    }


# ---------------------------------------------------------------------
# main dataframe builder
# ---------------------------------------------------------------------
def build_other_format_text_table(
    df_vote_info: pd.DataFrame,
    df_timeline: pd.DataFrame
) -> pd.DataFrame:
    """
    Use the committee vote info table to identify 'other format' procedures,
    then revisit the corresponding procedure pages from the timeline and
    extract whole-text PDFs when available.

    Required columns:
    - df_vote_info: procedure, committee, designation
    - df_timeline: procedure, event, hyperlink, reference
    """
    # Identify procedures marked as "other format"
    other_format_procedures = (
        df_vote_info.loc[
            (df_vote_info["committee"].eq("other format"))
            | (df_vote_info["designation"].eq("other format")),
            "procedure"
        ]
        .dropna()
        .drop_duplicates()
    )

    if other_format_procedures.empty:
        return pd.DataFrame(columns=["procedure", "reference", "format", "extracted_text"])

    # Match back to the same timeline event
    timeline_mask = df_timeline["event"].eq("Committee report tabled for plenary, 1st reading")
    df_timeline_filtered = df_timeline.loc[timeline_mask].copy()

    df_target = df_timeline_filtered[
        df_timeline_filtered["procedure"].isin(other_format_procedures)
    ].copy()

    if df_target.empty:
        return pd.DataFrame(columns=["procedure", "reference", "format", "extracted_text"])

    # Keep one row per procedure
    keep_cols = [c for c in ["procedure", "reference", "hyperlink"] if c in df_target.columns]
    df_target = df_target[keep_cols].drop_duplicates(subset=["procedure"])

    rows: List[Dict[str, str]] = []

    for _, row in df_target.iterrows():
        procedure = row["procedure"]
        reference = row.get("reference", "")
        hyperlink = row.get("hyperlink", "")

        if pd.isna(hyperlink) or not clean_text(hyperlink):
            rows.append({
                "procedure": procedure,
                "reference": reference,
                "format": "",
                "extracted_text": "",
            })
            continue

        try:
            record = extract_other_format_record(
                procedure=procedure,
                reference=reference,
                procedure_url=hyperlink,
            )
            rows.append(record)
        except Exception as e:
            rows.append({
                "procedure": procedure,
                "reference": reference,
                "format": "",
                "extracted_text": f"Failed to process procedure page: {e}",
            })

    return pd.DataFrame(rows, columns=["procedure", "reference", "format", "extracted_text"])