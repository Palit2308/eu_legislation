"""
Build a participant-level dataframe for Council / Presidency / Conclusions PDFs.

This module is a script-friendly packaging of the user's notebook pipeline.
The goal here is not to change the underlying logic, but to move the same
sequence of notebook cells into reusable Python functions that can be imported
from a runner script.

The pipeline does the following, in the same order as the notebook:

1. Load ``bld/pres_con_links.csv``.
2. Download each PDF whose ``document_found`` is ``True``.
3. Extract page-wise text with ``pdfplumber``.
4. Repair a specific broken heading encoding seen in some older PDFs.
5. Clean page text and extract the "PARTICIPANTS" section per procedure.
6. Parse the extracted section into a participant-level dataframe with the
   columns: ``procedure``, ``group``, ``participant``, ``role``.

The notebook redefined some helper names in later cells. To preserve the same
behaviour in a normal Python module, this file keeps the two relevant helper
sets separate:

- one set for participants-section extraction (notebook cells 5-6)
- one set for participant-row extraction (notebook cells 7-8)

This keeps the effective execution order aligned with the notebook.
"""

from __future__ import annotations

import os
import re
import unicodedata
from difflib import get_close_matches
from io import BytesIO
from typing import List, Dict, Optional

import pandas as pd
import pdfplumber
import requests


# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------
# Resolve the path of this file first.
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# The project root is the parent directory of the functions folder.
PROJECT_ROOT = os.path.dirname(MODULE_DIR)

# Build directory used throughout the project.
BLD = os.path.join(PROJECT_ROOT, "bld")

# Default input file produced by the earlier PDF-link pipeline.
DEFAULT_INPUT_CSV = os.path.join(BLD, "pres_con_links.csv")


# -----------------------------------------------------------------------------
# HTTP session
# -----------------------------------------------------------------------------
# In the original notebook, the extraction cell referenced an existing
# ``session`` object. In a standalone module we define it explicitly so the
# code can run from a fresh Python process.
session = requests.Session()


# -----------------------------------------------------------------------------
# Notebook cell 2: extract PDF pages with pdfplumber
# -----------------------------------------------------------------------------
def extract_pdf_pages(procedure: str, link: str, timeout: int = 40) -> List[Dict[str, object]]:
    """
    Download a PDF and return one row per page.

    Parameters
    ----------
    procedure:
        The legislative procedure identifier associated with the PDF.
    link:
        Direct URL to the PDF file.
    timeout:
        HTTP timeout in seconds.

    Returns
    -------
    list[dict]
        Each dictionary contains ``procedure``, ``link``, ``page_num``, and
        ``content`` exactly as in the notebook pipeline.
    """
    rows: List[Dict[str, object]] = []

    # Keep the notebook behaviour: missing links simply produce no rows.
    if pd.isna(link):
        return rows

    try:
        # Download the PDF bytes.
        resp = session.get(link, timeout=timeout)
        resp.raise_for_status()

        # Wrap the response bytes in an in-memory file object so pdfplumber can
        # read it without touching disk.
        pdf_file = BytesIO(resp.content)

        # Open the PDF and extract text page by page.
        with pdfplumber.open(pdf_file) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    # ``layout=True`` keeps more of the original page structure,
                    # which was the chosen notebook setting.
                    text = page.extract_text(layout=True)
                except Exception:
                    # Preserve notebook behaviour: if one page fails, store an
                    # empty string for that page instead of crashing.
                    text = ""

                rows.append(
                    {
                        "procedure": procedure,
                        "link": link,
                        "page_num": i,
                        "content": text if text is not None else "",
                    }
                )

    except Exception as e:
        # Preserve notebook behaviour: if PDF extraction fails at the document
        # level, emit one failure row for that procedure.
        rows.append(
            {
                "procedure": procedure,
                "link": link,
                "page_num": pd.NA,
                "content": f"[PDF_EXTRACTION_FAILED] {e}",
            }
        )

    return rows


# -----------------------------------------------------------------------------
# Notebook cell 3: repair a specific broken heading encoding
# -----------------------------------------------------------------------------
COUNTRY_HEADINGS = {
    "BELGIUM",
    "DENMARK",
    "GERMANY",
    "GREECE",
    "SPAIN",
    "FRANCE",
    "IRELAND",
    "ITALY",
    "LUXEMBOURG",
    "NETHERLANDS",
    "AUSTRIA",
    "PORTUGAL",
    "FINLAND",
    "SWEDEN",
    "UNITED KINGDOM",
}

SECTION_HEADINGS = {
    "PARTICIPANTS",
    "COMMISSION",
    "OTHER PARTICIPANTS",
}

ALL_KNOWN_HEADINGS = COUNTRY_HEADINGS | SECTION_HEADINGS


def decode_shift29(text: str) -> str:
    """
    Repair a specific character-shift pattern observed in some older PDFs.

    The notebook used a heuristic where certain printable characters are shifted
    by +29 ASCII code points when a line appears to be encoded incorrectly.
    """
    out: List[str] = []
    for ch in text:
        if ch.isspace():
            out.append(ch)
        else:
            code = ord(ch)
            # This reproduces the notebook condition exactly.
            if 33 <= code <= 97:
                out.append(chr(code + 29))
            else:
                out.append(ch)
    return "".join(out)



def normalize_heading(text: str) -> str:
    """Normalize a potential heading for comparison."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = re.sub(r"[^A-Za-z ]+", "", text)
    return text.upper().strip()



def maybe_decode_line(line: object) -> object:
    """
    Decode a line only when it appears to match the broken-encoding pattern.

    This mirrors the notebook logic exactly.
    """
    if not isinstance(line, str) or not line.strip():
        return line

    decoded = decode_shift29(line)

    orig_norm = normalize_heading(line)
    dec_norm = normalize_heading(decoded)

    # If the decoded line becomes a known heading, accept it immediately.
    if dec_norm in ALL_KNOWN_HEADINGS:
        return decoded

    # Otherwise, use the same heuristic from the notebook: lines with many odd
    # symbols that become much more alphabetic after decoding are accepted.
    weird_chars = sum(ch in r"""%$&'()*+,./0123456789:;<=>?@[\]^_`""" for ch in line)
    orig_alpha = sum(ch.isalpha() for ch in line)
    dec_alpha = sum(ch.isalpha() for ch in decoded)

    if weird_chars >= 2 and dec_alpha >= orig_alpha + 3:
        return decoded

    return line



def repair_pdf_text(text: object) -> object:
    """Apply line-wise repair to a whole page of extracted PDF text."""
    if pd.isna(text):
        return text
    return "\n".join(maybe_decode_line(line) for line in str(text).splitlines())


# -----------------------------------------------------------------------------
# Notebook cells 5-6: participants-section extraction helpers
# -----------------------------------------------------------------------------
# These helpers intentionally correspond to the versions that existed before the
# notebook later redefined similar helper names in cell 7.
INTRO_SENTENCE_SECTION = (
    "The Governments of the Member States and the European Commission "
    "were represented as follows"
)

HEADING_MAP_SECTION = {
    "BELGIUM": "Belgium",
    "BULGARIA": "Bulgaria",
    "CZECH REPUBLIC": "Czech Republic",
    "DENMARK": "Denmark",
    "GERMANY": "Germany",
    "ESTONIA": "Estonia",
    "IRELAND": "Ireland",
    "GREECE": "Greece",
    "SPAIN": "Spain",
    "FRANCE": "France",
    "CROATIA": "Croatia",
    "ITALY": "Italy",
    "CYPRUS": "Cyprus",
    "LATVIA": "Latvia",
    "LITHUANIA": "Lithuania",
    "LUXEMBOURG": "Luxembourg",
    "HUNGARY": "Hungary",
    "MALTA": "Malta",
    "NETHERLANDS": "Netherlands",
    "AUSTRIA": "Austria",
    "POLAND": "Poland",
    "PORTUGAL": "Portugal",
    "ROMANIA": "Romania",
    "SLOVENIA": "Slovenia",
    "SLOVAKIA": "Slovakia",
    "FINLAND": "Finland",
    "SWEDEN": "Sweden",
    "UNITED KINGDOM": "United Kingdom",
    "COMMISSION": "Commission",
    "OTHER PARTICIPANTS": "Other participants",
    "HIGH REPRESENTATIVE": "High Representative",
}

HEADING_MAP_COMPACT_SECTION = {
    k.replace(" ", ""): v for k, v in HEADING_MAP_SECTION.items()
}

PERSON_PATTERN_SECTION = re.compile(r"^(Mr|Mrs|Ms|Mme|Miss|Sir|M)\.?\b", re.I)


def strip_accents_section(text: object) -> str:
    """Remove accents for more forgiving matching."""
    return (
        unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    )



def clean_pdf_line_section(line: object) -> str:
    """
    Clean one extracted line using the exact notebook cell-5 logic.

    This removes recurring pdfplumber garbage markers and normalizes whitespace.
    """
    if pd.isna(line):
        return ""

    line = str(line).replace("\xa0", " ")
    line = line.replace("EcidWPFEcidWOVF", "")
    line = line.replace("EcidWOVF", "")
    line = line.replace("EcidWPF", " ")
    line = re.sub(r"\bG\s+G\s+G\b", "***", line)
    line = re.sub(r"[ \t]+", " ", line).strip()
    return line



def clean_page_text(text: object) -> str:
    """Apply line cleaning to a whole page of repaired text."""
    if pd.isna(text):
        return ""
    return "\n".join(clean_pdf_line_section(line) for line in str(text).splitlines())



def heading_key_section(text: object) -> str:
    """Normalize a line so it can be compared to heading dictionaries."""
    text = clean_pdf_line_section(text)
    text = strip_accents_section(text)
    text = re.sub(r"[^A-Za-z ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text



def is_person_line_section(line: object) -> bool:
    """Return True when a line starts with a person title such as Mr or Ms."""
    line = clean_pdf_line_section(line)
    return bool(PERSON_PATTERN_SECTION.match(line))



def is_participants_heading_section(line: object) -> bool:
    """Check whether a line is exactly the PARTICIPANTS heading."""
    return heading_key_section(line) == "PARTICIPANTS"



def looks_like_contents_line_section(line: object) -> bool:
    """
    Identify lines that look like contents-page entries.

    This is used to avoid falsely extracting the contents page when it contains
    the word PARTICIPANTS.
    """
    raw = str(line)
    cl = clean_pdf_line_section(line)

    if not cl:
        return False

    return (
        bool(re.search(r"\.{3,}", raw))
        or bool(re.search(r"\b[IVXLC]+\s*$", cl))
        or bool(re.search(r"\b\d{1,3}\s*$", cl))
    )



def heading_from_line_section(line: object) -> Optional[str]:
    """
    Map a noisy heading line to a canonical group label.

    This includes exact matching and fuzzy matching so that lines such as a
    slightly corrupted country name can still be recognized.
    """
    cl = clean_pdf_line_section(line)
    key = heading_key_section(cl)

    if not key:
        return None

    if key in HEADING_MAP_SECTION:
        return HEADING_MAP_SECTION[key]

    compact = key.replace(" ", "")
    if compact in HEADING_MAP_COMPACT_SECTION:
        return HEADING_MAP_COMPACT_SECTION[compact]

    if is_person_line_section(cl) or len(key.split()) > 4:
        return None

    match = get_close_matches(key, list(HEADING_MAP_SECTION.keys()), n=1, cutoff=0.72)
    if match:
        return HEADING_MAP_SECTION[match[0]]

    match_compact = get_close_matches(
        compact, list(HEADING_MAP_COMPACT_SECTION.keys()), n=1, cutoff=0.72
    )
    if match_compact:
        return HEADING_MAP_COMPACT_SECTION[match_compact[0]]

    return None



def looks_like_page_noise_section(line: object) -> bool:
    """
    Identify recurring PDF page-marker noise.

    The notebook used this to avoid letting page headers / footers terminate or
    pollute the participants section.
    """
    cl = clean_pdf_line_section(line)

    if not cl:
        return False

    if cl in {"EN", "(1)", "( 1 )", "1"}:
        return True

    if "VPSOLOLNO" in cl or "NMKsKOMNO" in cl or "RSVSLMN" in cl:
        return True

    if "Emresse" in cl or "obs O" in cl:
        return True

    if "EcidW" in cl:
        return True

    letters_only = re.sub(r"[^A-Za-z]", "", strip_accents_section(cl))
    if len(letters_only) >= 8 and len(cl.split()) <= 6:
        vowels = sum(ch.lower() in "aeiou" for ch in letters_only)
        if vowels <= 2 and heading_from_line_section(cl) is None and not is_person_line_section(cl):
            return True

    return False



def find_participants_start(lines: List[str]) -> Optional[int]:
    """
    Find the first line index that appears to begin the real participants section.

    This reproduces the notebook logic that distinguished a true section from a
    contents-page mention of PARTICIPANTS.
    """
    cleaned = [clean_pdf_line_section(line) for line in lines]

    for i, line in enumerate(cleaned):
        if not line:
            continue

        candidate = is_participants_heading_section(line) or INTRO_SENTENCE_SECTION.lower() in line.lower()
        if not candidate:
            continue

        window = cleaned[i : i + 20]
        prev_window = cleaned[max(0, i - 5) : i + 5]

        has_intro = any(INTRO_SENTENCE_SECTION.lower() in x.lower() for x in window[:6])
        has_people = sum(is_person_line_section(x) for x in window[:15]) >= 2
        has_group_heading = sum(heading_from_line_section(x) is not None for x in window[:15]) >= 1

        near_contents = any(heading_key_section(x) == "CONTENTS" for x in prev_window)
        contents_like_count = sum(looks_like_contents_line_section(x) for x in window[:10])

        if near_contents and contents_like_count >= 3 and not has_intro:
            continue

        if has_intro or (has_people and has_group_heading):
            for j in range(max(0, i - 3), i):
                if is_participants_heading_section(cleaned[j]):
                    return j
            return i

    return None



def looks_like_strong_end_heading_section(line: object) -> bool:
    """
    Detect a strong non-participants heading that likely marks the end of the section.
    """
    cl = clean_pdf_line_section(line)

    if not cl:
        return False
    if looks_like_page_noise_section(cl):
        return False
    if is_participants_heading_section(cl):
        return False
    if INTRO_SENTENCE_SECTION.lower() in cl.lower():
        return False
    if heading_from_line_section(cl) is not None:
        return False
    if is_person_line_section(cl):
        return False
    if cl == "***":
        return False

    alpha = sum(ch.isalpha() for ch in cl)
    if alpha < 8:
        return False

    ascii_line = strip_accents_section(cl)
    if ascii_line == ascii_line.upper():
        return True

    return False



def extract_participants_section(full_text: object) -> object:
    """
    Extract the participants section from a procedure-level concatenated text blob.

    This corresponds to notebook cell 5 logic as finally refined.
    """
    if not isinstance(full_text, str) or not full_text.strip():
        return pd.NA

    raw_lines = full_text.splitlines()
    cleaned_lines = [clean_pdf_line_section(line) for line in raw_lines]

    start_idx = find_participants_start(cleaned_lines)
    if start_idx is None:
        return pd.NA

    collected: List[str] = []

    for i in range(start_idx, len(cleaned_lines)):
        line = cleaned_lines[i]

        if not line:
            collected.append("")
            continue

        # Keep page noise out of the extracted text, but do not let it end the section.
        if looks_like_page_noise_section(line):
            continue

        # Only end the section when a strong heading appears and there is no
        # more participant-like structure shortly afterwards.
        if i > start_idx and looks_like_strong_end_heading_section(line):
            next_window = cleaned_lines[i : i + 12]

            future_has_participants_structure = any(
                is_person_line_section(x) or heading_from_line_section(x) is not None
                for x in next_window[1:]
                if not looks_like_page_noise_section(x)
            )

            if not future_has_participants_structure:
                break

        collected.append(line)

    section = "\n".join(collected).strip()
    return section if section else pd.NA


# -----------------------------------------------------------------------------
# Notebook cells 7-8: participant-row extraction helpers
# -----------------------------------------------------------------------------
# These correspond to the later redefinitions in the notebook and are used only
# after the participants-section dataframe has already been built.
HEADING_MAP_ROWS = {
    "BELGIUM": "Belgium",
    "BULGARIA": "Bulgaria",
    "CZECH REPUBLIC": "Czech Republic",
    "DENMARK": "Denmark",
    "GERMANY": "Germany",
    "ESTONIA": "Estonia",
    "IRELAND": "Ireland",
    "GREECE": "Greece",
    "SPAIN": "Spain",
    "FRANCE": "France",
    "CROATIA": "Croatia",
    "ITALY": "Italy",
    "CYPRUS": "Cyprus",
    "LATVIA": "Latvia",
    "LITHUANIA": "Lithuania",
    "LUXEMBOURG": "Luxembourg",
    "HUNGARY": "Hungary",
    "MALTA": "Malta",
    "NETHERLANDS": "Netherlands",
    "AUSTRIA": "Austria",
    "POLAND": "Poland",
    "PORTUGAL": "Portugal",
    "ROMANIA": "Romania",
    "SLOVENIA": "Slovenia",
    "SLOVAKIA": "Slovakia",
    "FINLAND": "Finland",
    "SWEDEN": "Sweden",
    "UNITED KINGDOM": "United Kingdom",
    "COMMISSION": "Commission",
    "OTHER PARTICIPANTS": "Other participants",
    "HIGH REPRESENTATIVE": "High Representative",
}

HEADING_MAP_COMPACT_ROWS = {k.replace(" ", ""): v for k, v in HEADING_MAP_ROWS.items()}
PERSON_PATTERN_ROWS = re.compile(r"^(Mr|Mrs|Ms|Mme|Miss|Sir|M)\.?\b", re.I)

ROLE_STARTERS = {
    "minister",
    "deputy",
    "ambassador",
    "state",
    "permanent",
    "chairman",
    "member",
    "vice",
    "president",
    "vicepresident",
    "secretary",
    "federal",
    "head",
    "parliamentary",
    "special",
    "representative",
    "general",
    "prime",
    "chancellor",
    "tanaiste",
    "high",
    "commissioner",
    "justice",
}


def strip_accents_rows(text: object) -> str:
    """Row-extraction version of accent stripping."""
    return (
        unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    )



def clean_pdf_line_rows(line: object) -> str:
    """Row-extraction version of line cleaning, kept separate to preserve notebook ordering."""
    if pd.isna(line):
        return ""

    line = str(line).replace("\xa0", " ")
    line = line.replace("EcidWPFEcidWOVF", "")
    line = line.replace("EcidWOVF", "")
    line = line.replace("EcidWPF", " ")
    line = re.sub(r"\bG\s+G\s+G\b", "***", line)
    line = re.sub(r"[ \t]+", " ", line).strip()
    return line



def heading_key_rows(text: object) -> str:
    """Normalize a row-level line for heading matching."""
    text = clean_pdf_line_rows(text)
    text = strip_accents_rows(text)
    text = re.sub(r"[^A-Za-z ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text



def normalize_token(token: str) -> str:
    """Normalize one token when deciding where a role starts."""
    token = strip_accents_rows(token)
    token = re.sub(r"[^A-Za-z]", "", token)
    return token.lower()



def is_upper_name_token(token: str) -> bool:
    """
    Heuristic used by the notebook to detect surname-like uppercase tokens.

    This helps split a person line into a name part and a role part.
    """
    letters = re.sub(r"[^A-Za-z]", "", strip_accents_rows(token))
    return len(letters) >= 2 and letters == letters.upper()



def is_person_line_rows(line: object) -> bool:
    """Return True when a line starts with a person title such as Mr or Ms."""
    line = clean_pdf_line_rows(line)
    return bool(PERSON_PATTERN_ROWS.match(line))



def heading_from_line_rows(line: object) -> Optional[str]:
    """
    Map a line to a canonical group label for row extraction.

    This is the later notebook version used during participant-row extraction.
    """
    cl = clean_pdf_line_rows(line)
    key = heading_key_rows(cl)

    if not key:
        return None

    if key in HEADING_MAP_ROWS:
        return HEADING_MAP_ROWS[key]

    compact = key.replace(" ", "")
    if compact in HEADING_MAP_COMPACT_ROWS:
        return HEADING_MAP_COMPACT_ROWS[compact]

    match = get_close_matches(key, list(HEADING_MAP_ROWS.keys()), n=1, cutoff=0.72)
    if match:
        return HEADING_MAP_ROWS[match[0]]

    match_compact = get_close_matches(
        compact, list(HEADING_MAP_COMPACT_ROWS.keys()), n=1, cutoff=0.72
    )
    if match_compact:
        return HEADING_MAP_COMPACT_ROWS[match_compact[0]]

    return None



def is_intro_or_separator_rows(line: object) -> bool:
    """Skip section labels, intro lines, and separators during row extraction."""
    cl = clean_pdf_line_rows(line)
    key = heading_key_rows(cl)

    if not cl:
        return True

    if key == "PARTICIPANTS":
        return True

    if "THE GOVERNMENTS OF THE MEMBER STATES" in key:
        return True

    if "THE GOVERNMENT OF THE ACCEDING STATE" in key:
        return True

    if cl == "***":
        return True

    return False



def looks_like_page_noise_rows(line: object) -> bool:
    """Identify page-marker garbage during participant-row extraction."""
    cl = clean_pdf_line_rows(line)

    if not cl:
        return True

    if cl in {"EN", "(1)", "( 1 )", "(1", "1", "II", "III", "IV", "V"}:
        return True

    if "VPSOLOLNO" in cl or "NMKsKOMNO" in cl or "RSVSLMN" in cl:
        return True

    if "Emresse" in cl or "obs O" in cl:
        return True

    if "EcidW" in cl:
        return True

    letters_only = re.sub(r"[^A-Za-z]", "", strip_accents_rows(cl))
    if len(letters_only) >= 8 and len(cl.split()) <= 6:
        vowels = sum(ch.lower() in "aeiou" for ch in letters_only)
        if vowels <= 2 and heading_from_line_rows(cl) is None and not is_person_line_rows(cl):
            return True

    return False



def split_name_role(line: str) -> tuple[str, str]:
    """
    Split a person line into participant name and role.

    Example
    -------
    'Mr Didier REYNDERS Minister for Finance'
    -> ('Mr Didier REYNDERS', 'Minister for Finance')
    """
    line = clean_pdf_line_rows(line)
    tokens = line.split()

    if len(tokens) < 2:
        return line, ""

    seen_upper_surname = False

    for i in range(1, len(tokens)):
        tok_norm = normalize_token(tokens[i])

        if is_upper_name_token(tokens[i]):
            seen_upper_surname = True

        if tok_norm in ROLE_STARTERS and (seen_upper_surname or i >= 3):
            name = " ".join(tokens[:i]).strip()
            role = " ".join(tokens[i:]).strip()
            return name, role

    return line, ""



def looks_like_role_continuation(line: object) -> bool:
    """
    Decide whether a non-person line should be appended to the previous role.

    This catches wrapped role descriptions that continue onto the next line.
    """
    cl = clean_pdf_line_rows(line)

    if not cl:
        return False
    if is_person_line_rows(cl):
        return False
    if heading_from_line_rows(cl) is not None:
        return False
    if is_intro_or_separator_rows(cl):
        return False
    if looks_like_page_noise_rows(cl):
        return False

    if sum(ch.islower() for ch in cl) < 3:
        return False

    role_words = [
        "minister",
        "affairs",
        "representative",
        "department",
        "departments",
        "ministry",
        "policy",
        "trade",
        "culture",
        "science",
        "sport",
        "education",
        "industry",
        "transport",
        "energy",
        "agriculture",
        "communications",
        "research",
        "environment",
        "tourism",
        "innovation",
        "foreign",
        "economic",
        "social",
        "union",
        "budget",
        "finance",
        "attached",
        "responsibility",
        "president",
        "chairman",
        "member",
        "commission",
        "secretary",
        "federal",
    ]

    cl_low = cl.lower()
    return any(word in cl_low for word in role_words)



def extract_participant_rows(procedure: str, section_text: object) -> List[Dict[str, object]]:
    """
    Convert one participants section into participant-level rows.

    This preserves the notebook logic used to:
    - track the current country/group heading,
    - split a person line into ``participant`` and ``role``,
    - append wrapped role lines to the previous row.
    """
    rows: List[Dict[str, object]] = []

    if not isinstance(section_text, str) or not section_text.strip():
        return rows

    current_group: Optional[str] = None
    current_row_idx: Optional[int] = None

    for raw_line in section_text.splitlines():
        line = clean_pdf_line_rows(raw_line)

        if not line:
            continue

        if looks_like_page_noise_rows(line):
            continue

        if is_intro_or_separator_rows(line):
            continue

        group = heading_from_line_rows(line)
        if group is not None:
            current_group = group
            current_row_idx = None
            continue

        if is_person_line_rows(line):
            participant, role = split_name_role(line)

            rows.append(
                {
                    "procedure": procedure,
                    "group": current_group,
                    "participant": participant,
                    "role": role,
                }
            )
            current_row_idx = len(rows) - 1
            continue

        if current_row_idx is not None and looks_like_role_continuation(line):
            rows[current_row_idx]["role"] = (rows[current_row_idx]["role"] + " " + line).strip()
            continue

        # Any other line is ignored, matching the notebook behaviour.

    return rows


# -----------------------------------------------------------------------------
# Public pipeline function
# -----------------------------------------------------------------------------
def build_council_lop_pres_con(input_csv: Optional[str] = None, verbose: bool = True) -> pd.DataFrame:
    """
    Run the full notebook pipeline and return the final participant dataframe.

    Parameters
    ----------
    input_csv:
        Optional explicit path to ``pres_con_links.csv``. If omitted, the module
        uses ``bld/pres_con_links.csv`` relative to the project root.
    verbose:
        If True, print detailed progress messages for shell execution.

    Returns
    -------
    pandas.DataFrame
        Final participant-level dataframe with the columns:
        ``procedure``, ``group``, ``participant``, ``role``.
    """
    input_csv = input_csv or DEFAULT_INPUT_CSV

    if verbose:
        print("=" * 80)
        print("Starting council_lop_pres_con pipeline")
        print(f"Module directory: {MODULE_DIR}")
        print(f"Project root: {PROJECT_ROOT}")
        print(f"BLD directory: {BLD}")
        print(f"Input CSV: {input_csv}")
        print("=" * 80)

    # -----------------------------------------------------------------
    # Notebook cell 1
    # -----------------------------------------------------------------
    pdf_df = pd.read_csv(input_csv)

    if verbose:
        print(f"[Load] Loaded pres_con_links dataframe with {len(pdf_df)} rows.")
        if "document_found" in pdf_df.columns:
            print(f"[Load] Rows with document_found == True: {(pdf_df['document_found'] == True).sum()}")

    # -----------------------------------------------------------------
    # Notebook cell 2
    # -----------------------------------------------------------------
    if verbose:
        print("\n[Step 1] Downloading PDFs and extracting page-wise text with pdfplumber...")

    pdf_pages_rows: List[Dict[str, object]] = []

    docs_to_process = pdf_df.loc[
        pdf_df["document_found"] == True, ["procedure", "pdf_link"]
    ]

    total_docs = len(docs_to_process)
    for doc_num, (_, r) in enumerate(docs_to_process.iterrows(), start=1):
        procedure = r["procedure"]
        link = r["pdf_link"]

        if verbose:
            print(f"[Step 1] ({doc_num}/{total_docs}) Extracting pages for procedure {procedure}")

        rows = extract_pdf_pages(procedure=procedure, link=link)
        pdf_pages_rows.extend(rows)

        if verbose:
            page_count = sum(1 for row in rows if pd.notna(row["page_num"]))
            failed = any(str(row["content"]).startswith("[PDF_EXTRACTION_FAILED]") for row in rows)
            if failed:
                print(f"[Step 1]   Extraction failed for {procedure}")
            else:
                print(f"[Step 1]   Extracted {page_count} page(s) for {procedure}")

    pdf_pages_df = pd.DataFrame(
        pdf_pages_rows, columns=["procedure", "link", "page_num", "content"]
    )

    if verbose:
        print(f"[Step 1] Done. Built pdf_pages_df with {len(pdf_pages_df)} rows.")

    # -----------------------------------------------------------------
    # Notebook cells 3-4
    # -----------------------------------------------------------------
    if verbose:
        print("\n[Step 2] Repairing broken heading encodings in extracted PDF text...")

    pdf_pages_df["content_fixed"] = pdf_pages_df["content"].apply(repair_pdf_text)

    if verbose:
        print("[Step 2] Done. Added column: content_fixed")

    # -----------------------------------------------------------------
    # Notebook cells 5-6
    # -----------------------------------------------------------------
    if verbose:
        print("\n[Step 3] Cleaning repaired text and extracting participants sections...")

    pdf_pages_df["content_clean"] = pdf_pages_df["content_fixed"].apply(clean_page_text)

    procedure_text_df = (
        pdf_pages_df.sort_values(["procedure", "page_num"])
        .groupby("procedure", as_index=False)
        .agg(full_text=("content_clean", "\n".join))
    )

    procedure_text_df["participants_section"] = procedure_text_df["full_text"].apply(
        extract_participants_section
    )

    participants_section_df = procedure_text_df[["procedure", "participants_section"]].copy()

    if verbose:
        found_sections = participants_section_df["participants_section"].notna().sum()
        print(f"[Step 3] Done. Extracted participants sections for {found_sections} procedure(s).")

    # -----------------------------------------------------------------
    # Notebook cells 7-8
    # -----------------------------------------------------------------
    if verbose:
        print("\n[Step 4] Converting participants sections into participant rows...")

    participant_rows: List[Dict[str, object]] = []

    total_sections = len(participants_section_df)
    for idx, (_, row) in enumerate(participants_section_df.iterrows(), start=1):
        procedure = row["procedure"]

        if verbose:
            print(f"[Step 4] ({idx}/{total_sections}) Parsing participant rows for {procedure}")

        rows = extract_participant_rows(
            procedure=procedure,
            section_text=row["participants_section"],
        )
        participant_rows.extend(rows)

        if verbose:
            print(f"[Step 4]   Extracted {len(rows)} participant row(s) for {procedure}")

    participant_df = pd.DataFrame(
        participant_rows,
        columns=["procedure", "group", "participant", "role"],
    )

    if verbose:
        print(f"[Step 4] Done. Built participant_df with {len(participant_df)} rows.")
        print("=" * 80)
        print("Pipeline finished successfully.")
        print("=" * 80)

    return participant_df
