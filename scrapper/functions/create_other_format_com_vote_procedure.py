"""
Functions to build the long-format procedure table for 'other format'
committee-report procedures from PDF documents.

Pipeline:
1. Identify 'other format' procedures from committee_vote_info + timeline_table
2. Revisit the plenary page and download the PDF
3. Build df_page_text (one row per PDF page)
4. Extract first-page metadata
5. Parse contents page into contents_df
6. Build df_committees
7. Parse:
   - old/prose "PROCEDURAL PAGE" universe
   - structured "PROCEDURE" / "PROCEDURE - COMMITTEE RESPONSIBLE" universe
8. Concatenate both into the final long table:
   procedure, committee, designation, head, value
"""

import ast
import io
import re
import unicodedata
from typing import Dict, List, Optional
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


# ============================================================
# shared constants
# ============================================================
EU_LANG_CODES = {
    "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FI", "FR", "GA",
    "HR", "HU", "IT", "LT", "LV", "MT", "NL", "PL", "PT", "RO", "SK",
    "SL", "SV"
}

MONTH_MAP = {
    "january": "January",
    "february": "February",
    "march": "March",
    "april": "April",
    "may": "May",
    "june": "June",
    "july": "July",
    "august": "August",
    "september": "September",
    "october": "October",
    "november": "November",
    "december": "December",
}
MONTH_PATTERN = r"(January|February|March|April|May|June|July|August|September|October|November|December)"

NUMBER_WORDS = {
    "none": 0,
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

STRUCTURED_HARD_ASSERT = False


# ============================================================
# generic helpers
# ============================================================
def as_text(x):
    if pd.isna(x):
        return ""
    return str(x).replace("\xa0", " ")


def strip_ornaments(text):
    text = as_text(text)
    text = re.sub(r"[╔╗║╚╝═]", " ", text)
    text = re.sub(r"[★☆■□▪▫◆◇•·]+", " ", text)
    return text


def norm_space(text):
    return re.sub(r"\s+", " ", strip_ornaments(text)).strip()


def normalize_for_match(text):
    text = strip_ornaments(text)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text


def ascii_fold(text):
    text = unicodedata.normalize("NFKD", as_text(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def flatten_text(text):
    text = strip_ornaments(text)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def split_sentences(text):
    flat = flatten_text(text)
    if not flat:
        return []
    parts = re.split(r"(?<=[\.\?!])\s+", flat)
    return [part.strip() for part in parts if part.strip()]


def add_row(rows, procedure, committee, designation, head, value):
    if pd.isna(value):
        return
    value = norm_space(value)
    if not value:
        return
    rows.append(
        {
            "procedure": procedure,
            "committee": committee,
            "designation": designation,
            "head": head,
            "value": value,
        }
    )


# ============================================================
# step 1: build df_page_text
# ============================================================
def fetch_html(url: str, timeout: int = 30) -> str:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def clean_text_block(text: Optional[str]) -> str:
    if text is None:
        return ""

    text = str(text).replace("\xa0", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def get_other_format_links(procedure_url: str) -> Dict[str, Optional[str]]:
    html = fetch_html(procedure_url)
    soup = BeautifulSoup(html, "html.parser")

    links = {"pdf": None, "word": None}

    for a in soup.find_all("a", href=True):
        href = urljoin(procedure_url, a["href"])
        href_l = href.lower()

        text_l = a.get_text(" ", strip=True).lower()
        title_l = (a.get("title") or "").lower()

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
            or text_l == "doc"
            or text_l == "docx"
            or "word" in text_l
            or "doc" in title_l
        )

        if is_pdf and links["pdf"] is None:
            links["pdf"] = href

        if is_word and links["word"] is None:
            links["word"] = href

    return links


def extract_pdf_pages_from_url(
    pdf_url: str,
    procedure: str,
    reference: str
) -> List[Dict[str, object]]:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(pdf_url, headers=headers, timeout=120)
    response.raise_for_status()

    reader = PdfReader(io.BytesIO(response.content))
    rows: List[Dict[str, object]] = []

    for page_number, page in enumerate(reader.pages, start=1):
        raw_text = page.extract_text() or ""
        page_text = clean_text_block(raw_text)

        rows.append({
            "procedure": procedure,
            "reference": reference,
            "format": "pdf",
            "page": page_number,
            "text": page_text,
        })

    return rows


def build_other_format_page_table(
    df_vote_info: pd.DataFrame,
    df_timeline: pd.DataFrame
) -> pd.DataFrame:
    committee_series = df_vote_info.get("committee", pd.Series(dtype="object")).fillna("").astype(str).str.strip().str.lower()
    designation_series = df_vote_info.get("designation", pd.Series(dtype="object")).fillna("").astype(str).str.strip().str.lower()

    other_format_procedures = (
        df_vote_info.loc[
            (committee_series.eq("other format")) | (designation_series.eq("other format")),
            "procedure"
        ]
        .dropna()
        .drop_duplicates()
    )

    if other_format_procedures.empty:
        return pd.DataFrame(columns=["procedure", "reference", "format", "page", "text"])

    df_timeline_filtered = df_timeline.loc[
        df_timeline["event"].eq("Committee report tabled for plenary, 1st reading")
    ].copy()

    df_target = df_timeline_filtered[
        df_timeline_filtered["procedure"].isin(other_format_procedures)
    ].copy()

    if df_target.empty:
        return pd.DataFrame(columns=["procedure", "reference", "format", "page", "text"])

    keep_cols = [c for c in ["procedure", "reference", "hyperlink"] if c in df_target.columns]
    df_target = df_target[keep_cols].drop_duplicates(subset=["procedure"])

    rows: List[Dict[str, object]] = []

    for _, row in df_target.iterrows():
        procedure = row["procedure"]
        reference = row.get("reference", "")
        procedure_url = row.get("hyperlink", "")

        if pd.isna(procedure_url) or not str(procedure_url).strip():
            rows.append({
                "procedure": procedure,
                "reference": reference,
                "format": "",
                "page": pd.NA,
                "text": "",
            })
            continue

        try:
            links = get_other_format_links(procedure_url)
            pdf_url = links.get("pdf")
            word_url = links.get("word")

            if pdf_url:
                page_rows = extract_pdf_pages_from_url(
                    pdf_url=pdf_url,
                    procedure=procedure,
                    reference=reference
                )
                rows.extend(page_rows)

            elif word_url:
                rows.append({
                    "procedure": procedure,
                    "reference": reference,
                    "format": "word",
                    "page": pd.NA,
                    "text": "",
                })

            else:
                rows.append({
                    "procedure": procedure,
                    "reference": reference,
                    "format": "",
                    "page": pd.NA,
                    "text": "",
                })

        except Exception as e:
            rows.append({
                "procedure": procedure,
                "reference": reference,
                "format": "",
                "page": pd.NA,
                "text": f"Failed to process procedure page: {e}",
            })

    df_out = pd.DataFrame(rows, columns=["procedure", "reference", "format", "page", "text"])

    if not df_out.empty:
        df_out["page"] = df_out["page"].astype("Int64")

    return df_out


# ============================================================
# step 2: first-page metadata
# ============================================================
def norm_dashes(text):
    return re.sub(r"[–—−]", "-", as_text(text))


def clean_line(line):
    return re.sub(r"\s+", " ", strip_ornaments(line)).strip()


def extract_language_flag(text):
    text = strip_ornaments(text)
    tokens = re.findall(r"\b[A-Za-z]{2}\b", text)
    codes = [tok.upper() for tok in tokens if tok.upper() in EU_LANG_CODES]

    if not codes:
        return pd.NA

    return pd.Series(codes).value_counts().idxmax()


def extract_pe_ref(text):
    text = strip_ornaments(text)
    pattern = r"\bPE\s*\d[\d\.]*(?:v\d{2}-\d{2})?(?:/[A-Za-z0-9.\-]+)?"
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return pd.NA
    return re.sub(r"\s+", " ", m.group(0)).strip()


def extract_rr_ref(text):
    text = strip_ornaments(text)
    m = re.search(r"RR\\\d+[A-Z]{2}\.doc\b", text)
    if not m:
        return pd.NA
    return m.group(0).strip()


def has_contents_page(page_texts):
    pattern = re.compile(
        r"(^|\n)\s*(?:CONTENTS|C\s*O\s*N\s*T\s*E\s*N\s*T\s*S)\s*(\n|$)",
        flags=re.IGNORECASE
    )
    for txt in page_texts:
        if pattern.search(strip_ornaments(txt)):
            return True
    return False


def extract_doc_date(text):
    text = strip_ornaments(text)

    patterns = [
        r"\b\d{1,2}\s+[A-Z][a-z]+\s+\d{4}\b",
        r"\b\d{1,2}\.\d{1,2}\.\d{4}\b",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0).strip()

    return pd.NA


def extract_stage(text):
    for raw_line in as_text(text).splitlines():
        line = clean_line(raw_line)
        line = re.sub(r"[^*IVX]", "", line.upper())

        if line in {"***III", "***II", "***I", "***", "**II", "**I", "*"}:
            return line

    return pd.NA


def extract_title(text):
    flat = norm_space(strip_ornaments(text))

    patterns = [
        r"REPORT\s+on\s+the\s+proposal\s+for\s+a\s+European\s+Parliament\s+and\s+Council\s+Directive\s+on\s+(.*?)\s+\(\s*COM",
        r"REPORT\s+on\s+the\s+proposal\s+for\s+a\s+European\s+Parliament\s+and\s+Council\s+directive\s+on\s+(.*?)\s+\(\s*COM",
        r"REPORT\s+on\s+the\s+proposal\s+for\s+a\s+directive\s+of\s+the\s+European\s+Parliament\s+and\s+of\s+the\s+Council\s+on\s+(.*?)\s+\(\s*COM",
    ]

    for pat in patterns:
        m = re.search(pat, flat, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return pd.NA


def extract_ref_block(text):
    text = strip_ornaments(text)

    start = re.search(r"\(COM", text, flags=re.IGNORECASE)
    if not start:
        return pd.NA

    tail = text[start.start():]

    stop = re.search(r"\bCommittee\s+on\b", tail, flags=re.IGNORECASE)
    if stop:
        candidate = tail[:stop.start()]
    else:
        candidate = tail

    candidate = candidate.strip()

    if candidate.startswith("("):
        candidate = candidate[1:]
    candidate = candidate.strip()
    if candidate.endswith(")"):
        candidate = candidate[:-1]

    candidate = re.sub(r"\s+", " ", candidate).strip(" -–—")
    return candidate if candidate else pd.NA


def split_ref_block(ref_block):
    if pd.isna(ref_block):
        return []

    block = norm_dashes(ref_block)

    parts = [
        part.strip()
        for part in re.split(r"(?<!C\d)\s*-\s*", block, flags=re.IGNORECASE)
        if part.strip()
    ]
    return parts


def extract_committee(text):
    text = strip_ornaments(text)
    m = re.search(r"(?mi)^\s*Committee\s+on\s+.+$", text)
    if not m:
        return pd.NA
    return norm_space(m.group(0))


def extract_rapporteur(text):
    text = strip_ornaments(text)
    m = re.search(r"(?mi)^\s*Rapporteur\s*:\s*(.+)$", text)
    if not m:
        return pd.NA
    return norm_space(m.group(1))


def build_first_page_meta(df_page_text):
    df = df_page_text.copy()

    ref_col = "reference" if "reference" in df.columns else "web_reference"
    fmt_col = "format" if "format" in df.columns else None

    df["page"] = pd.to_numeric(df["page"], errors="coerce")

    rows = []

    group_cols = ["procedure", ref_col]
    if fmt_col is not None:
        group_cols.append(fmt_col)

    for keys, g in df.groupby(group_cols, dropna=False):
        if len(group_cols) == 3:
            procedure, web_reference, fmt = keys
        else:
            procedure, web_reference = keys
            fmt = pd.NA

        g = g.sort_values("page").copy()

        first_page = g[g["page"] == 1]
        if not first_page.empty:
            first_text = as_text(first_page.iloc[0]["text"])
        else:
            first_text = as_text(g.iloc[0]["text"])

        all_texts = g["text"].fillna("").astype(str).tolist()
        full_doc_text = "\n".join(all_texts)

        language = extract_language_flag(first_text)
        if pd.isna(language):
            language = extract_language_flag(full_doc_text)

        pe_ref = extract_pe_ref(first_text)
        if pd.isna(pe_ref):
            pe_ref = extract_pe_ref(full_doc_text)

        rr_ref = extract_rr_ref(first_text)
        if pd.isna(rr_ref):
            rr_ref = extract_rr_ref(full_doc_text)

        ref_block = extract_ref_block(first_text)
        ref_i = split_ref_block(ref_block)

        rows.append(
            {
                "procedure": procedure,
                "web_reference": web_reference,
                "format": fmt,
                "language": language,
                "pe_ref": pe_ref,
                "rr_ref": rr_ref,
                "contents": has_contents_page(all_texts),
                "doc_date": extract_doc_date(first_text),
                "stage": extract_stage(first_text),
                "title": extract_title(first_text),
                "references": ref_i,
                "committee": extract_committee(first_text),
                "designation": "lead",
                "rapporteur": extract_rapporteur(first_text),
            }
        )

    out = pd.DataFrame(rows)

    out = out[
        [
            "procedure",
            "web_reference",
            "format",
            "language",
            "pe_ref",
            "rr_ref",
            "contents",
            "doc_date",
            "stage",
            "title",
            "references",
            "committee",
            "designation",
            "rapporteur",
        ]
    ].sort_values(["procedure", "web_reference"], kind="stable").reset_index(drop=True)

    return out


# ============================================================
# step 3: contents_df and df_committees
# ============================================================
def looks_like_furniture(line):
    raw = clean_line(line)
    if not raw:
        return True

    norm = normalize_for_match(raw)

    if norm in {"PAGE"}:
        return True

    if norm in EU_LANG_CODES:
        return True

    if re.match(r"^-?\s*\d+\s*-?\s*PE\b", raw, flags=re.IGNORECASE):
        return True

    if re.search(r"RR\\\d+[A-Z]{2}\.doc", raw):
        return True

    if re.search(r"\bPE\s*\d", raw, flags=re.IGNORECASE):
        if re.search(r"\b\d+\s*/\s*\d+\b", raw) or re.search(r"\bEN\b", raw):
            return True
        if len(raw) < 40:
            return True

    return False


def is_contents_heading(line):
    norm = normalize_for_match(line)
    norm_no_space = re.sub(r"\s+", "", norm)
    return norm == "CONTENTS" or norm_no_space == "CONTENTS"


def find_contents_page(group_df):
    for _, row in group_df.sort_values("page").iterrows():
        txt = as_text(row["text"])
        for line in txt.splitlines():
            if is_contents_heading(line):
                return row["page"], txt
    return pd.NA, ""


def parse_contents_items(contents_text):
    lines = [clean_line(line) for line in as_text(contents_text).splitlines()]

    start_idx = None
    for i, line in enumerate(lines):
        if is_contents_heading(line):
            start_idx = i + 1
            break

    if start_idx is None:
        return []

    lines = lines[start_idx:]

    entries = []
    buffer = []

    for line in lines:
        if looks_like_furniture(line):
            continue

        if not line:
            continue

        m = re.match(r"^(.*?)(?:\.{2,}|…{2,})\s*(\d+)\s*$", line)
        if m:
            item_piece = m.group(1).strip(" -")
            page_number = int(m.group(2))

            parts = buffer + ([item_piece] if item_piece else [])
            item = " ".join(parts)
            item = re.sub(r"\s+,", ",", item)
            item = norm_space(item)

            if item:
                entries.append((item, page_number))

            buffer = []
        else:
            buffer.append(line)

    return entries


def build_contents_df(df_page_text, dff_first_page_meta):
    page_ref_col = "reference" if "reference" in df_page_text.columns else "web_reference"
    meta_ref_col = "web_reference" if "web_reference" in dff_first_page_meta.columns else "reference"

    rows = []

    meta_contents = dff_first_page_meta.loc[dff_first_page_meta["contents"] == True].copy()

    for _, meta_row in meta_contents.iterrows():
        procedure = meta_row["procedure"]
        web_reference = meta_row[meta_ref_col]

        g = df_page_text.loc[
            (df_page_text["procedure"] == procedure)
            & (df_page_text[page_ref_col] == web_reference)
        ].copy()

        if g.empty:
            continue

        contents_page, contents_text = find_contents_page(g)
        if not contents_text:
            continue

        items = parse_contents_items(contents_text)

        for item, page_number in items:
            rows.append({
                "procedure": procedure,
                "item": item,
                "page_number": page_number,
            })

    return pd.DataFrame(rows, columns=["procedure", "item", "page_number"])


def build_df_committees(contents_df, dff_first_page_meta):
    rows = []

    for _, meta_row in dff_first_page_meta.iterrows():
        procedure = meta_row["procedure"]
        lead_committee = meta_row.get("committee", pd.NA)

        cdf = contents_df.loc[contents_df["procedure"] == procedure].copy()
        if cdf.empty:
            continue

        has_procedural_page = cdf["item"].apply(
            lambda x: (
                normalize_for_match(x).startswith("PROCEDURAL PAGE")
                or normalize_for_match(x).startswith("PROCEDURE - COMMITTEE RESPONSIBLE")
            )
        ).any()

        if has_procedural_page and pd.notna(lead_committee) and str(lead_committee).strip():
            rows.append({
                "procedure": procedure,
                "committee": lead_committee,
                "designation": "lead",
            })

        prefix = "OPINION OF THE "

        for item in cdf["item"]:
            item_norm = normalize_for_match(item)

            if item_norm.startswith(prefix):
                committee = norm_space(item[len(prefix):])
                if committee:
                    rows.append({
                        "procedure": procedure,
                        "committee": committee,
                        "designation": "opinion",
                    })

    out = pd.DataFrame(rows, columns=["procedure", "committee", "designation"])

    if not out.empty:
        out = (
            out.assign(
                _committee_norm=out["committee"].map(normalize_for_match),
                _designation_norm=out["designation"].str.lower()
            )
            .drop_duplicates(subset=["procedure", "_committee_norm", "_designation_norm"])
            .drop(columns=["_committee_norm", "_designation_norm"])
            .sort_values(["procedure", "designation", "committee"], kind="stable")
            .reset_index(drop=True)
        )

    return out


# ============================================================
# step 4: prose / PROCEDURAL PAGE universe
# ============================================================
def strip_honorifics(name):
    name = norm_space(name)
    name = re.sub(
        r"^(Mr|Mrs|Ms|Miss|Mme|M\.|Sir|Dr|Professor|Prof\.)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    return norm_space(name)


def parse_references_field(x):
    if isinstance(x, (list, tuple)):
        return [norm_space(v) for v in x if norm_space(v)]

    s = as_text(x).strip()
    if not s:
        return []

    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return [norm_space(v) for v in parsed if norm_space(v)]
        except Exception:
            pass

    return [norm_space(s)]


def lead_page_score(text):
    s = ascii_fold(flatten_text(text)).lower()
    score = 0

    if "procedural page" in s:
        score += 100
    if "appointed" in s and "rapporteur" in s:
        score += 30
    if "considered the commission proposal" in s:
        score += 30
    if "adopted the draft legislative resolution" in s:
        score += 30
    if "the following were present for the vote:" in s:
        score += 20
    if "the following took part in the vote/were present for the vote:" in s:
        score += 20
    if "the opinions of" in s:
        score += 10

    return score


def opinion_start_page_score(text, committee_name):
    s = ascii_fold(flatten_text(text)).lower()
    c = ascii_fold(committee_name).lower()
    score = 0

    if "opinion of the committee on" in s and c in s:
        score += 120
    if c in s:
        score += 60
    if "draftsman" in s:
        score += 25
    if re.search(r"\bprocedure\b", s):
        score += 15
    if "considered the draft opinion" in s:
        score += 20
    if "appointed" in s and "draftsman" in s:
        score += 20
    if "the following were present for the vote:" in s:
        score += 10
    if "the following took part in the vote:" in s:
        score += 10

    return score


def locate_page_with_window(proc_pages, target_page, score_func):
    candidate_pages = proc_pages.loc[
        proc_pages["page"].between(target_page - 1, target_page + 1, inclusive="both")
    ].copy()

    if candidate_pages.empty:
        return pd.NA, ""

    candidate_pages["score"] = candidate_pages["text"].map(score_func)
    candidate_pages["distance"] = (candidate_pages["page"] - target_page).abs()

    candidate_pages = candidate_pages.sort_values(
        ["score", "distance", "page"],
        ascending=[False, True, True],
        kind="stable"
    )

    best = candidate_pages.iloc[0]
    if best["score"] <= 0:
        return pd.NA, ""

    return int(best["page"]), as_text(best["text"])


def locate_lead_procedural_page(proc_pages, target_page):
    return locate_page_with_window(proc_pages, target_page, lead_page_score)


def locate_opinion_start_page(proc_pages, target_page, committee_name):
    return locate_page_with_window(
        proc_pages,
        target_page,
        lambda text: opinion_start_page_score(text, committee_name)
    )


def find_procedure_subsection_in_page(text):
    lines = as_text(text).splitlines()
    for i, line in enumerate(lines):
        if normalize_for_match(line) == "PROCEDURE":
            return "\n".join(lines[i:]).strip()
    return ""


def build_page_lookup(proc_pages):
    return {
        int(row["page"]): as_text(row["text"])
        for _, row in proc_pages.iterrows()
        if pd.notna(row["page"])
    }


def locate_opinion_procedure_section(proc_pages, start_page):
    page_lookup = build_page_lookup(proc_pages)

    for p in range(start_page, start_page + 3):
        txt = page_lookup.get(p, "")
        subsection = find_procedure_subsection_in_page(txt)
        if subsection:
            return p, subsection, True

    txt = page_lookup.get(start_page, "")
    if txt:
        return start_page, txt, False

    return pd.NA, "", False


def fix_ocr_day_zeroes(text):
    text = as_text(text)
    text = re.sub(
        rf"\b(\d)O(?=\s+{MONTH_PATTERN}\b)",
        lambda m: f"{m.group(1)}0",
        text,
        flags=re.IGNORECASE,
    )
    return text


def canonical_date(day, month, year):
    return f"{int(day)} {MONTH_MAP[month.lower()]} {int(year)}"


def parse_date_string_to_ts(date_str):
    return pd.to_datetime(date_str, dayfirst=True, errors="coerce")


def extract_dates_from_sentence(text):
    text = fix_ocr_day_zeroes(text)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = norm_space(text)

    base_year_match = re.findall(r"\b((?:19|20)\d{2})\b", text)
    base_year = base_year_match[-1] if base_year_match else None

    results = []

    pattern = re.compile(
        rf"""
        (\b\d{{1,2}}\s*-\s*\d{{1,2}}\s+{MONTH_PATTERN}(?:\s+(?:19|20)\d{{2}})?\b)
        |
        (\b\d{{1,2}}\s+{MONTH_PATTERN}(?:\s+(?:19|20)\d{{2}})?\b)
        """,
        flags=re.IGNORECASE | re.VERBOSE,
    )

    for m in pattern.finditer(text):
        frag = m.group(0).strip()

        range_match = re.match(
            rf"^\b(\d{{1,2}})\s*-\s*(\d{{1,2}})\s+{MONTH_PATTERN}(?:\s+((?:19|20)\d{{2}}))?\b$",
            frag,
            flags=re.IGNORECASE,
        )
        if range_match:
            start_day = int(range_match.group(1))
            end_day = int(range_match.group(2))
            month = range_match.group(3)
            year = range_match.group(4) or base_year
            if year:
                for day in range(start_day, end_day + 1):
                    results.append(canonical_date(day, month, year))
            continue

        single_match = re.match(
            rf"^\b(\d{{1,2}})\s+{MONTH_PATTERN}(?:\s+((?:19|20)\d{{2}}))?\b$",
            frag,
            flags=re.IGNORECASE,
        )
        if single_match:
            day = int(single_match.group(1))
            month = single_match.group(2)
            year = single_match.group(3) or base_year
            if year:
                results.append(canonical_date(day, month, year))

    deduped = []
    seen = set()
    for d in results:
        if d not in seen:
            seen.add(d)
            deduped.append(d)

    return deduped


def person_name_variants(name):
    clean = strip_honorifics(name)
    if not clean:
        return []

    full = ascii_fold(clean).lower()
    parts = clean.split()
    surname = ascii_fold(parts[-1]).lower() if parts else ""

    variants = [full]
    if surname and surname not in variants:
        variants.append(surname)

    return variants


def extract_role_holder_from_label(text, role_word):
    flat = flatten_text(text)
    m = re.search(
        rf"\b{role_word}\s*:\s*(.+?)(?=At its meeting of|At its meetings of|The Committee on|$)",
        flat,
        flags=re.IGNORECASE,
    )
    if not m:
        return pd.NA
    return strip_honorifics(m.group(1))


def extract_role_holder_and_date(section_text, role_word, known_name=pd.NA):
    role_word = role_word.lower()
    label_name = extract_role_holder_from_label(section_text, role_word) if role_word == "draftsman" else pd.NA
    chosen_name = strip_honorifics(known_name) if pd.notna(known_name) else pd.NA

    if pd.isna(chosen_name) and pd.notna(label_name):
        chosen_name = label_name

    variants = person_name_variants(chosen_name) if pd.notna(chosen_name) else []

    for sent in split_sentences(section_text):
        sent_fold = ascii_fold(sent).lower()
        if "appoint" not in sent_fold or role_word not in sent_fold:
            continue

        if variants and not any(v in sent_fold for v in variants):
            continue

        if pd.isna(chosen_name):
            m = re.search(
                rf"appointed\s+(.+?)\s+{role_word}\b",
                sent,
                flags=re.IGNORECASE,
            )
            if m:
                chosen_name = strip_honorifics(m.group(1))

        dates = extract_dates_from_sentence(sent)
        if dates:
            return chosen_name, dates[0]

    return chosen_name, pd.NA


def sentence_is_discussion_sentence(sent):
    s = ascii_fold(sent).lower()

    if "considered" not in s:
        return False

    discussion_markers = [
        "commission proposal",
        "draft report",
        "draft opinion",
        "draft opinions",
    ]

    return any(marker in s for marker in discussion_markers)


def extract_discussed_dates(section_text):
    results = []

    for sent in split_sentences(section_text):
        if not sentence_is_discussion_sentence(sent):
            continue
        results.extend(extract_dates_from_sentence(sent))

    deduped = []
    seen = set()
    for d in results:
        if d not in seen:
            seen.add(d)
            deduped.append(d)

    return deduped


def normalize_number_token(tok):
    tok = as_text(tok).strip().lower()
    if tok.isdigit():
        return str(int(tok))
    if tok in NUMBER_WORDS:
        return str(NUMBER_WORDS[tok])
    return tok


def parse_vote_rows_from_sentence(sent):
    s = ascii_fold(sent).lower()

    if "unanimously" in s:
        return [("Result of the vote", "unanimous")]

    sent_clean = fix_ocr_day_zeroes(sent)
    sent_clean = sent_clean.replace("–", "-").replace("—", "-").replace("−", "-")
    num = r"(\d+|none|zero|one|two|three|four|five|six|seven|eight|nine|ten)"

    patterns = [
        rf"by\s+{num}\s+votes?\s+to\s*{num}\s*,?\s*with\s+{num}\s+abstentions?",
        rf"by\s+{num}\s+votes?\s+to\s*{num}",
        rf"by\s+{num}\s+votes?\s*,?\s*with\s+{num}\s+abstentions?",
    ]

    for pat in patterns:
        m = re.search(pat, sent_clean, flags=re.IGNORECASE)
        if not m:
            continue

        groups = [normalize_number_token(g) for g in m.groups()]

        if len(groups) == 3:
            return [
                ("Result of final vote +", groups[0]),
                ("Result of final vote –", groups[1]),
                ("Result of final vote 0", groups[2]),
            ]
        if len(groups) == 2 and "to" in m.group(0).lower():
            return [
                ("Result of final vote +", groups[0]),
                ("Result of final vote –", groups[1]),
            ]
        if len(groups) == 2:
            return [
                ("Result of final vote +", groups[0]),
                ("Result of final vote 0", groups[1]),
            ]

    return []


def sentence_is_adoption_sentence(sent, designation):
    s = ascii_fold(sent).lower()

    if "adopt" not in s:
        return False

    if designation == "lead":
        return "adopted the draft legislative resolution" in s

    opinion_markers = [
        "adopted the conclusions",
        "adopted the amendments below",
        "adopted the draft opinion",
    ]
    return any(marker in s for marker in opinion_markers)


def extract_vote_and_adoption(section_text, discussed_dates, designation):
    adoption_found = False
    adopted_date = pd.NA
    vote_rows = []

    for sent in split_sentences(section_text):
        if not sentence_is_adoption_sentence(sent, designation):
            continue

        adoption_found = True

        if discussed_dates:
            parsed = [(d, parse_date_string_to_ts(d)) for d in discussed_dates]
            parsed = [(d, ts) for d, ts in parsed if pd.notna(ts)]
            if parsed:
                adopted_date = max(parsed, key=lambda x: x[1])[0]

        vote_rows = parse_vote_rows_from_sentence(sent)
        return adoption_found, adopted_date, vote_rows

    return adoption_found, adopted_date, vote_rows


def extract_members_present(section_text):
    flat = flatten_text(section_text)

    patterns = [
        r"The following took part in the vote/were present for the vote:\s*(.*?)(?=The opinions of|The report was tabled on|The deadline for tabling amendments|AMENDMENTS|SHORT JUSTIFICATION|Commission proposal|POSITION OF THE COMMISSION|$)",
        r"The following were present for the vote:\s*(.*?)(?=The opinions of|The report was tabled on|The deadline for tabling amendments|AMENDMENTS|SHORT JUSTIFICATION|Commission proposal|POSITION OF THE COMMISSION|$)",
        r"The following took part in the vote:\s*(.*?)(?=The opinions of|The report was tabled on|The deadline for tabling amendments|AMENDMENTS|SHORT JUSTIFICATION|Commission proposal|POSITION OF THE COMMISSION|$)",
    ]

    for pat in patterns:
        m = re.search(pat, flat, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return norm_space(m.group(1))

    return pd.NA


def find_opinion_contents_row(proc_contents, committee_name):
    target = normalize_for_match(committee_name)

    opinion_rows = proc_contents.loc[
        proc_contents["item"].map(normalize_for_match).str.startswith("OPINION OF THE ")
    ].copy()

    if opinion_rows.empty:
        return pd.DataFrame()

    opinion_rows["committee_extracted"] = opinion_rows["item"].map(
        lambda x: normalize_for_match(re.sub(r"^OPINION OF THE\s+", "", normalize_for_match(x)))
    )

    matched = opinion_rows.loc[opinion_rows["committee_extracted"] == target].copy()
    return matched


def build_lead_rows_from_first_page_meta(rows, procedure, meta_row):
    committee = meta_row.get("committee", pd.NA)
    designation = "lead"

    add_row(rows, procedure, committee, designation, "Title", meta_row.get("title", pd.NA))

    references = parse_references_field(meta_row.get("references", []))
    for ref in references:
        add_row(rows, procedure, committee, designation, "References", ref)

    rapporteur_clean = strip_honorifics(meta_row.get("rapporteur", pd.NA))
    add_row(rows, procedure, committee, designation, "Rapporteurs", rapporteur_clean)
    add_row(rows, procedure, committee, designation, "Committee responsible", committee)

    return rapporteur_clean


def parse_committee_section(rows, procedure, committee, designation, section_text, known_person_name=pd.NA):
    role_word = "rapporteur" if designation == "lead" else "draftsman"

    person_name, date_appointed = extract_role_holder_and_date(
        section_text=section_text,
        role_word=role_word,
        known_name=known_person_name,
    )

    add_row(rows, procedure, committee, designation, "Rapporteurs", person_name)
    add_row(rows, procedure, committee, designation, "Date appointed", date_appointed)

    discussed_dates = extract_discussed_dates(section_text)
    for d in discussed_dates:
        add_row(rows, procedure, committee, designation, "Discussed in committee", d)

    adoption_found, adopted_date, vote_rows = extract_vote_and_adoption(
        section_text=section_text,
        discussed_dates=discussed_dates,
        designation=designation,
    )

    if adoption_found:
        add_row(rows, procedure, committee, designation, "Date adopted", adopted_date)
        for head, value in vote_rows:
            add_row(rows, procedure, committee, designation, head, value)

    members_present = extract_members_present(section_text)
    add_row(rows, procedure, committee, designation, "Members present for the final vote", members_present)


def build_committee_meta_long_procedural_universe(
    df_page_text,
    contents_df,
    dff_first_page_meta,
    df_committees,
):
    page_ref_col = "reference" if "reference" in df_page_text.columns else "web_reference"
    meta_ref_col = "web_reference" if "web_reference" in dff_first_page_meta.columns else "reference"

    eligible_contents = contents_df.loc[
        contents_df["item"].map(normalize_for_match).str.startswith("PROCEDURAL PAGE")
    ].copy()

    eligible_procedures = set(eligible_contents["procedure"].dropna().unique())

    rows = []

    for procedure in eligible_procedures:
        proc_contents = contents_df.loc[contents_df["procedure"] == procedure].copy()
        meta_match = dff_first_page_meta.loc[dff_first_page_meta["procedure"] == procedure].copy()

        if meta_match.empty:
            continue

        meta_row = meta_match.iloc[0]
        web_reference = meta_row[meta_ref_col]

        proc_pages = df_page_text.loc[
            (df_page_text["procedure"] == procedure)
            & (df_page_text[page_ref_col] == web_reference)
        ].copy()

        if proc_pages.empty:
            proc_pages = df_page_text.loc[df_page_text["procedure"] == procedure].copy()

        if proc_pages.empty:
            continue

        proc_pages["page"] = pd.to_numeric(proc_pages["page"], errors="coerce")
        proc_pages = proc_pages.dropna(subset=["page"]).copy()

        lead_contents = proc_contents.loc[
            proc_contents["item"].map(normalize_for_match).str.startswith("PROCEDURAL PAGE")
        ].copy()

        if not lead_contents.empty:
            lead_target_page = int(lead_contents["page_number"].iloc[0])
            located_page, lead_text = locate_lead_procedural_page(proc_pages, lead_target_page)

            if pd.notna(located_page) and lead_text:
                print(f"located for lead committee in procedure == {procedure}")

                lead_committee = meta_row.get("committee", pd.NA)
                known_rapporteur = build_lead_rows_from_first_page_meta(rows, procedure, meta_row)

                parse_committee_section(
                    rows=rows,
                    procedure=procedure,
                    committee=lead_committee,
                    designation="lead",
                    section_text=lead_text,
                    known_person_name=known_rapporteur,
                )

        proc_committees = df_committees.loc[
            (df_committees["procedure"] == procedure)
            & (df_committees["designation"].str.lower() == "opinion")
        ].copy()

        if proc_committees.empty:
            continue

        for _, c_row in proc_committees.iterrows():
            opinion_committee = c_row["committee"]

            matched_contents = find_opinion_contents_row(proc_contents, opinion_committee)
            if matched_contents.empty:
                continue

            opinion_target_page = int(matched_contents["page_number"].iloc[0])

            opinion_start_page, opinion_start_text = locate_opinion_start_page(
                proc_pages=proc_pages,
                target_page=opinion_target_page,
                committee_name=opinion_committee,
            )

            if pd.isna(opinion_start_page) or not opinion_start_text:
                continue

            section_page, opinion_section_text, explicit_procedure_heading = locate_opinion_procedure_section(
                proc_pages=proc_pages,
                start_page=opinion_start_page,
            )

            if pd.isna(section_page) or not opinion_section_text:
                continue

            print(f"found opinion section for committee == {opinion_committee} in procedure == {procedure}")

            parse_committee_section(
                rows=rows,
                procedure=procedure,
                committee=opinion_committee,
                designation="opinion",
                section_text=opinion_section_text,
                known_person_name=pd.NA,
            )

    out = pd.DataFrame(rows, columns=["procedure", "committee", "designation", "head", "value"])

    if not out.empty:
        out = out.drop_duplicates().reset_index(drop=True)

    return out


# ============================================================
# step 5: structured table universe
# ============================================================
def st_as_text(x):
    if pd.isna(x):
        return ""
    return str(x).replace("\xa0", " ")


def st_strip_ornaments(text):
    text = st_as_text(text)
    text = re.sub(r"[╔╗║╚╝═]", " ", text)
    text = re.sub(r"[★☆■□▪▫◆◇•·]+", " ", text)
    return text


def st_norm_space(text):
    return re.sub(r"\s+", " ", st_strip_ornaments(text)).strip()


def st_normalize_for_match(text):
    text = st_strip_ornaments(text)
    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("’", "'")
        .replace("‘", "'")
    )
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text


def st_ascii_fold(text):
    text = unicodedata.normalize("NFKD", st_as_text(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def st_flatten_text(text):
    text = st_strip_ornaments(text)
    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
        .replace("’", "'")
        .replace("‘", "'")
    )
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def st_add_row(rows, procedure, committee, designation, head, value):
    if pd.isna(value):
        return
    value = st_norm_space(value)
    if not value:
        return
    rows.append(
        {
            "procedure": procedure,
            "committee": committee,
            "designation": designation,
            "head": head,
            "value": value,
        }
    )


def st_build_committee_code_lookup(df_dict):
    out = {}
    for _, row in df_dict.iterrows():
        code = st_norm_space(row.get("committee_code", "")).upper()
        committee = st_norm_space(row.get("committee", ""))
        if code:
            out[code] = committee
    return out


def st_normalize_committee_name_for_compare(text):
    s = st_ascii_fold(st_as_text(text)).lower()
    s = s.replace("&", " and ")
    s = s.replace("’", "'").replace("‘", "'")
    s = re.sub(r"^annex:\s*", "", s)
    s = re.sub(r"^opinion of the\s+", "", s)
    s = re.sub(r"^committee on the\s+", "", s)
    s = re.sub(r"^committee on\s+", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def st_committee_code_matches_expected(expected_committee, code, committee_code_lookup):
    code = st_norm_space(code).upper()
    mapped = committee_code_lookup.get(code, "")

    if not mapped:
        return False, ""

    exp_norm = st_normalize_committee_name_for_compare(expected_committee)
    map_norm = st_normalize_committee_name_for_compare(mapped)

    if exp_norm == map_norm or exp_norm in map_norm or map_norm in exp_norm:
        return True, mapped

    stop = {"and", "the", "of", "on", "for", "in", "to"}
    exp_tokens = {t for t in exp_norm.split() if t not in stop}
    map_tokens = {t for t in map_norm.split() if t not in stop}

    overlap = len(exp_tokens & map_tokens)
    if overlap >= 2:
        return True, mapped

    return False, mapped


def st_assert_or_warn_committee_match(
    procedure,
    designation,
    expected_committee,
    code,
    committee_code_lookup,
):
    ok, mapped = st_committee_code_matches_expected(
        expected_committee=expected_committee,
        code=code,
        committee_code_lookup=committee_code_lookup,
    )

    if ok:
        return True

    msg = (
        f"[structured-parser] committee-code mismatch in procedure {procedure} "
        f"({designation}). code={code!r}, df_dict={mapped!r}, expected outer committee={expected_committee!r}"
    )

    if STRUCTURED_HARD_ASSERT:
        raise AssertionError(msg)

    print(msg)
    return False


def st_structured_table_page_score(text):
    s = st_ascii_fold(st_flatten_text(text)).lower()
    score = 0

    if "procedure - committee responsible" in s:
        score += 120
    if re.search(r"\bprocedure\b", s):
        score += 80
    if "title " in s:
        score += 20
    if "references " in s:
        score += 20
    if "date adopted" in s:
        score += 10
    if "result of final vote" in s:
        score += 20
    if "members present for the final vote" in s:
        score += 20
    if "committee responsible" in s:
        score += 10

    return score


def st_build_page_lookup(proc_pages):
    out = {}
    for _, row in proc_pages.iterrows():
        if pd.notna(row["page"]):
            out[int(row["page"])] = st_as_text(row["text"])
    return out


def st_locate_lead_structured_page(proc_pages, target_page):
    cand = proc_pages.loc[
        proc_pages["page"].between(target_page - 1, target_page + 1, inclusive="both")
    ].copy()

    if cand.empty:
        return pd.NA, ""

    cand["score"] = cand["text"].map(st_structured_table_page_score)
    cand["distance"] = (cand["page"] - target_page).abs()

    cand = cand.sort_values(
        ["score", "distance", "page"],
        ascending=[False, True, True],
        kind="stable",
    )

    best = cand.iloc[0]
    if best["score"] <= 0:
        return pd.NA, ""

    return int(best["page"]), st_as_text(best["text"])


def st_locate_opinion_structured_page(proc_pages, section_start_page, section_end_page):
    page_lookup = st_build_page_lookup(proc_pages)

    candidates = []
    for p in range(section_end_page, section_start_page - 1, -1):
        txt = page_lookup.get(p, "")
        if not txt:
            continue
        score = st_structured_table_page_score(txt)
        if score > 0:
            candidates.append((p, score, txt))

    if not candidates:
        return pd.NA, ""

    candidates = sorted(candidates, key=lambda x: (x[0], x[1]), reverse=True)
    page, _, txt = candidates[0]
    return page, txt


def st_find_lead_procedure_contents_row(proc_contents):
    cdf = proc_contents.copy()
    cdf["item_norm"] = cdf["item"].map(st_normalize_for_match)

    preferred = cdf.loc[cdf["item_norm"].str.startswith("PROCEDURE - COMMITTEE RESPONSIBLE")]
    if not preferred.empty:
        preferred = preferred.sort_values("page_number", ascending=False, kind="stable")
        return preferred.iloc[[0]]

    fallback = cdf.loc[cdf["item_norm"].eq("PROCEDURE")]
    if not fallback.empty:
        fallback = fallback.sort_values("page_number", ascending=False, kind="stable")
        return fallback.iloc[[0]]

    return pd.DataFrame(columns=proc_contents.columns)


def st_find_opinion_contents_row(proc_contents, committee_name):
    cdf = proc_contents.copy()
    cdf = cdf.loc[cdf["item"].map(st_normalize_for_match).str.startswith("OPINION OF THE")].copy()
    if cdf.empty:
        return pd.DataFrame(columns=proc_contents.columns)

    expected = st_normalize_committee_name_for_compare(committee_name)

    def score_item(item):
        item_norm = st_normalize_committee_name_for_compare(item)
        score = 0
        if expected == item_norm:
            score += 100
        if expected in item_norm or item_norm in expected:
            score += 80

        exp_tokens = set(expected.split())
        item_tokens = set(item_norm.split())
        score += len(exp_tokens & item_tokens)

        if st_normalize_for_match(item).startswith("OPINION OF THE"):
            score += 10

        return score

    cdf["score"] = cdf["item"].map(score_item)
    cdf = cdf.sort_values(["score", "page_number"], ascending=[False, True], kind="stable")

    best = cdf.iloc[0]
    if best["score"] <= 0:
        return pd.DataFrame(columns=proc_contents.columns)

    return cdf.iloc[[0]]


def st_get_section_end_page(proc_contents_sorted, current_page):
    later = proc_contents_sorted.loc[proc_contents_sorted["page_number"] > current_page].copy()
    if later.empty:
        return current_page
    return int(later["page_number"].iloc[0]) - 1


STRUCTURED_HEAD_SPECS = [
    ("Title", "simple_text", re.compile(r"^(Title)\b\s*(.*)$", flags=re.IGNORECASE)),
    ("References", "simple_text", re.compile(r"^(References)\b\s*(.*)$", flags=re.IGNORECASE)),
    (
        "Date submitted to Parliament",
        "simple_text",
        re.compile(r"^(Date submitted to Parliament)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Committee responsible",
        "paired",
        re.compile(r"^(Committee responsible)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    ("Opinion by", "paired", re.compile(r"^(Opinion by)\b\s*(.*)$", flags=re.IGNORECASE)),
    (
        "Committees asked for opinions",
        "paired",
        re.compile(
            r"^(Committees asked for opinions|Committee\(s\) asked for opinion\(s\))\b\s*(.*)$",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "Associated committees",
        "paired",
        re.compile(r"^(Associated committees)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Not delivering opinions",
        "paired",
        re.compile(r"^(Not delivering opinions)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Rapporteur",
        "paired",
        re.compile(r"^(Rapporteurs?|Draftsman|Drafts\(wo\)man)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Discussed in committee",
        "date_list",
        re.compile(r"^(Discussed in committee)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Date adopted",
        "simple_text",
        re.compile(r"^(Date adopted)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Result of final vote",
        "vote",
        re.compile(r"^(Result of final vote)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Members present for the final vote",
        "list_block",
        re.compile(r"^(Members present for the final vote)\b\s*(.*)$", flags=re.IGNORECASE),
    ),
    (
        "Substitutes present for the final vote",
        "list_block",
        re.compile(
            r"^(Substitutes present for the final vote|Substitute\(s\) present for the final vote)\b\s*(.*)$",
            flags=re.IGNORECASE,
        ),
    ),
    (
        "Substitutes under Rule present for the final vote",
        "list_block",
        re.compile(
            r"^(Substitutes under Rule .*?present(?: for)? the final vote|Substitute\(s\) under Rule .*?present(?: for)? the final vote)\b\s*(.*)$",
            flags=re.IGNORECASE,
        ),
    ),
    ("Date tabled", "simple_text", re.compile(r"^(Date tabled)\b\s*(.*)$", flags=re.IGNORECASE)),
]


def st_detect_structured_head(line):
    line = st_norm_space(line)
    for _, kind, pat in STRUCTURED_HEAD_SPECS:
        m = pat.match(line)
        if m:
            display_head = st_norm_space(m.group(1))
            remainder = st_norm_space(m.group(2))
            return {
                "display_head": display_head,
                "kind": kind,
                "remainder": remainder,
            }
    return None


def st_make_logical_lines(page_text):
    raw_lines = [line.strip() for line in st_as_text(page_text).splitlines()]
    raw_lines = [line for line in raw_lines if line]

    start_idx = None
    for i, line in enumerate(raw_lines):
        if st_normalize_for_match(line).startswith("PROCEDURE"):
            start_idx = i
            break

    if start_idx is None:
        return []

    body = raw_lines[start_idx + 1:]
    logical = []

    i = 0
    while i < len(body):
        line = body[i].strip()
        if not line:
            i += 1
            continue

        if st_detect_structured_head(line) is None and i + 1 < len(body):
            combined = f"{line} {body[i + 1].strip()}"
            if st_detect_structured_head(combined) is not None:
                logical.append(combined)
                i += 2
                continue

        logical.append(line)
        i += 1

    return logical


def st_extract_structured_blocks(page_text):
    lines = st_make_logical_lines(page_text)
    blocks = []

    i = 0
    while i < len(lines):
        detected = st_detect_structured_head(lines[i])
        if detected is None:
            i += 1
            continue

        block = {
            "display_head": detected["display_head"],
            "kind": detected["kind"],
            "content_lines": [],
        }

        if detected["remainder"]:
            block["content_lines"].append(detected["remainder"])

        i += 1
        while i < len(lines):
            if st_detect_structured_head(lines[i]) is not None:
                break
            block["content_lines"].append(st_norm_space(lines[i]))
            i += 1

        blocks.append(block)

    return blocks


def st_extract_dot_dates(text):
    return re.findall(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b", st_as_text(text))


def st_parse_vote_block(display_head, content_lines):
    items = []
    symbols = []
    numbers = []

    sym_map = {"+": "+", "-": "–", "–": "–", "0": "0"}

    for line in content_lines:
        for part in [p.strip() for p in re.split(r"\s+", st_as_text(line)) if p.strip()]:
            part_clean = part.rstrip(":")
            if part_clean in sym_map and part.endswith(":"):
                symbols.append(sym_map[part_clean])
            elif re.fullmatch(r"\d+", part_clean):
                numbers.append(part_clean)

    for sym, num in zip(symbols, numbers):
        items.append({"head": f"{display_head} {sym}", "value": num})

    return items


def st_parse_paired_block(display_head, content_lines):
    items = []
    content_lines = [st_norm_space(x) for x in content_lines if st_norm_space(x)]
    if not content_lines:
        return items

    subhead = None
    first = st_normalize_for_match(content_lines[0])

    if first in {"DATE ANNOUNCED IN PLENARY", "DATE OF DECISION", "DATE APPOINTED"}:
        subhead = st_norm_space(content_lines[0])
        content_lines = content_lines[1:]

    if not content_lines:
        return items

    if subhead:
        idx = 0
        while idx < len(content_lines):
            items.append({"head": display_head, "value": content_lines[idx]})
            if idx + 1 < len(content_lines):
                items.append({"head": subhead, "value": content_lines[idx + 1]})
            idx += 2
    else:
        for val in content_lines:
            items.append({"head": display_head, "value": val})

    return items


def st_parse_structured_block(block):
    display_head = block["display_head"]
    kind = block["kind"]
    content_lines = [st_norm_space(x) for x in block["content_lines"] if st_norm_space(x)]

    items = []

    if kind == "simple_text":
        value = st_norm_space(" ".join(content_lines))
        if value:
            items.append({"head": display_head, "value": value})
        return items

    if kind == "date_list":
        joined = st_norm_space(" ".join(content_lines))
        dates = st_extract_dot_dates(joined)
        if dates:
            for d in dates:
                items.append({"head": display_head, "value": d})
        elif joined:
            items.append({"head": display_head, "value": joined})
        return items

    if kind == "vote":
        return st_parse_vote_block(display_head, content_lines)

    if kind == "list_block":
        value = st_norm_space(" ".join(content_lines))
        if value:
            items.append({"head": display_head, "value": value})
        return items

    if kind == "paired":
        return st_parse_paired_block(display_head, content_lines)

    return items


def st_parse_structured_procedure_page(page_text):
    blocks = st_extract_structured_blocks(page_text)
    extracted = []

    for block in blocks:
        extracted.extend(st_parse_structured_block(block))

    return extracted


def build_structured_committee_meta_long_pdf(
    df_page_text,
    contents_df,
    df_committees,
    df_dict,
):
    committee_code_lookup = st_build_committee_code_lookup(df_dict)

    proc_contents_all = contents_df.copy()
    proc_contents_all["page_number"] = pd.to_numeric(proc_contents_all["page_number"], errors="coerce")
    proc_contents_all = proc_contents_all.dropna(subset=["page_number"]).copy()

    structured_contents_mask = proc_contents_all["item"].map(st_normalize_for_match).apply(
        lambda x: x == "PROCEDURE" or x.startswith("PROCEDURE - COMMITTEE RESPONSIBLE")
    )
    structured_procedures = proc_contents_all.loc[structured_contents_mask, "procedure"].dropna().unique().tolist()

    rows = []

    for procedure in structured_procedures:
        proc_contents = (
            proc_contents_all.loc[proc_contents_all["procedure"] == procedure]
            .sort_values("page_number", kind="stable")
            .copy()
        )

        proc_pages = df_page_text.loc[df_page_text["procedure"] == procedure].copy()
        if proc_pages.empty:
            continue

        proc_pages["page"] = pd.to_numeric(proc_pages["page"], errors="coerce")
        proc_pages = proc_pages.dropna(subset=["page"]).copy()

        lead_rows = df_committees.loc[
            (df_committees["procedure"] == procedure)
            & (df_committees["designation"].str.lower() == "lead")
        ].copy()

        if not lead_rows.empty:
            expected_lead_committee = st_norm_space(lead_rows.iloc[0]["committee"])

            lead_contents_row = st_find_lead_procedure_contents_row(proc_contents)
            if not lead_contents_row.empty:
                target_page = int(lead_contents_row.iloc[0]["page_number"])

                located_page, lead_text = st_locate_lead_structured_page(proc_pages, target_page)
                if pd.notna(located_page) and lead_text:
                    print(f"found structured lead table in procedure == {procedure} on page == {located_page}")

                    extracted = st_parse_structured_procedure_page(lead_text)
                    extracted_df = pd.DataFrame(extracted)

                    if not extracted_df.empty:
                        lead_code_rows = extracted_df.loc[
                            extracted_df["head"].map(st_normalize_for_match) == "COMMITTEE RESPONSIBLE"
                        ]
                        if not lead_code_rows.empty:
                            lead_code = st_norm_space(lead_code_rows.iloc[0]["value"]).upper()
                            st_assert_or_warn_committee_match(
                                procedure=procedure,
                                designation="lead",
                                expected_committee=expected_lead_committee,
                                code=lead_code,
                                committee_code_lookup=committee_code_lookup,
                            )

                        for item in extracted:
                            st_add_row(
                                rows=rows,
                                procedure=procedure,
                                committee=expected_lead_committee,
                                designation="lead",
                                head=item["head"],
                                value=item["value"],
                            )

        opinion_rows = df_committees.loc[
            (df_committees["procedure"] == procedure)
            & (df_committees["designation"].str.lower() == "opinion")
        ].copy()

        if opinion_rows.empty:
            continue

        for _, c_row in opinion_rows.iterrows():
            expected_opinion_committee = st_norm_space(c_row["committee"])

            opinion_contents_row = st_find_opinion_contents_row(proc_contents, expected_opinion_committee)
            if opinion_contents_row.empty:
                print(
                    f"[structured-parser] could not match opinion contents row for committee == {expected_opinion_committee} "
                    f"in procedure == {procedure}"
                )
                continue

            section_start_page = int(opinion_contents_row.iloc[0]["page_number"])
            section_end_page = st_get_section_end_page(proc_contents, section_start_page)

            located_page, opinion_text = st_locate_opinion_structured_page(
                proc_pages=proc_pages,
                section_start_page=section_start_page,
                section_end_page=section_end_page,
            )

            if pd.isna(located_page) or not opinion_text:
                print(
                    f"[structured-parser] could not locate structured opinion PROCEDURE table "
                    f"for committee == {expected_opinion_committee} in procedure == {procedure}"
                )
                continue

            print(
                f"found structured opinion table for committee == {expected_opinion_committee} "
                f"in procedure == {procedure} on page == {located_page}"
            )

            extracted = st_parse_structured_procedure_page(opinion_text)
            extracted_df = pd.DataFrame(extracted)

            if not extracted_df.empty:
                opinion_code_rows = extracted_df.loc[
                    extracted_df["head"].map(st_normalize_for_match) == "OPINION BY"
                ]
                if not opinion_code_rows.empty:
                    opinion_code = st_norm_space(opinion_code_rows.iloc[0]["value"]).upper()
                    st_assert_or_warn_committee_match(
                        procedure=procedure,
                        designation="opinion",
                        expected_committee=expected_opinion_committee,
                        code=opinion_code,
                        committee_code_lookup=committee_code_lookup,
                    )

                for item in extracted:
                    st_add_row(
                        rows=rows,
                        procedure=procedure,
                        committee=expected_opinion_committee,
                        designation="opinion",
                        head=item["head"],
                        value=item["value"],
                    )

    out = pd.DataFrame(rows, columns=["procedure", "committee", "designation", "head", "value"])
    if not out.empty:
        out = out.drop_duplicates().reset_index(drop=True)

    return out


# ============================================================
# top-level pipeline
# ============================================================
def build_other_format_com_vote_procedure_table(
    df_vote_info: pd.DataFrame,
    df_timeline: pd.DataFrame,
    df_dict: pd.DataFrame,
    return_intermediates: bool = False,
):
    """
    Full end-to-end builder.

    Parameters
    ----------
    df_vote_info : pd.DataFrame
    df_timeline : pd.DataFrame
    df_dict : pd.DataFrame
        Committee dictionary with committee_code and committee columns.
    return_intermediates : bool
        If True, returns a dict with intermediate tables too.

    Returns
    -------
    pd.DataFrame or dict
        Final long-format procedure table, or a dict containing all stages.
    """
    df_page_text = build_other_format_page_table(df_vote_info, df_timeline)
    dff_first_page_meta = build_first_page_meta(df_page_text)
    contents_df = build_contents_df(df_page_text, dff_first_page_meta)
    df_committees = build_df_committees(contents_df, dff_first_page_meta)

    df_committee_meta_long_prose = build_committee_meta_long_procedural_universe(
        df_page_text=df_page_text,
        contents_df=contents_df,
        dff_first_page_meta=dff_first_page_meta,
        df_committees=df_committees,
    )

    df_committee_meta_long_structured = build_structured_committee_meta_long_pdf(
        df_page_text=df_page_text,
        contents_df=contents_df,
        df_committees=df_committees,
        df_dict=df_dict,
    )

    df_committee_meta_long = (
        pd.concat(
            [df_committee_meta_long_prose, df_committee_meta_long_structured],
            ignore_index=True
        )
        .drop_duplicates()
        .reset_index(drop=True)
    )

    if return_intermediates:
        return {
            "df_page_text": df_page_text,
            "dff_first_page_meta": dff_first_page_meta,
            "contents_df": contents_df,
            "df_committees": df_committees,
            "df_committee_meta_long_prose": df_committee_meta_long_prose,
            "df_committee_meta_long_structured": df_committee_meta_long_structured,
            "df_committee_meta_long": df_committee_meta_long,
        }

    return df_committee_meta_long