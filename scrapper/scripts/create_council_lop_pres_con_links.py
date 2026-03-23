import os
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag
from urllib.parse import urljoin, urlparse, parse_qs


# Resolve project root and bld directory once
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, ".."))
BLD = os.path.join(project_root, "bld")
output_path = os.path.join(project_root, "bld", "pres_con_links.csv")

# Create bld folder if it does not exist
os.makedirs(BLD, exist_ok=True)


# -----------------------------
# Patterns
# -----------------------------
COUNCIL_HEADER_PATTERN = re.compile(
    r"""
    (
        Adoption\s+of\s+common\s+position\s+by\s+Council
        |
        Approval\s+of\s+the\s+EP'?s\s+
        (first|second|third)\s+reading\s+position\s+by\s+the\s+Council
        |
        Council\s+agreement
        |
        Discussions\s+within\s+the\s+Council\s+or\s+its\s+preparatory\s+bodies
    )
    """,
    re.I | re.X,
)

# matches PRES anywhere in the visible text, including CS-PRES
PRES_PATTERN = re.compile(r"PRES", re.I)


# -----------------------------
# Sessions
# -----------------------------
# Session for Eur-Lex page scraping (first block in your notebook/code)
session_scrape = requests.Session()
session_scrape.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
)

# Session for PDF checks (second block in your notebook/code)
session_pdf = requests.Session()
session_pdf.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": "https://www.consilium.europa.eu/en/",
        "Upgrade-Insecure-Requests": "1",
        "DNT": "1",
    }
)


# -----------------------------
# Council / PRES extraction logic
# -----------------------------
def find_pres_link_in_container(container, base_url):
    """Return (press_exists, pres_link) from a BS4 container."""
    if container is None:
        return "no", pd.NA

    pres_a = container.find(
        lambda tag: isinstance(tag, Tag)
        and tag.name == "a"
        and PRES_PATTERN.search(tag.get_text(" ", strip=True) or "")
    )

    if pres_a and pres_a.get("href"):
        return "yes", urljoin(base_url, pres_a["href"])

    return "no", pd.NA


def extract_council_adoption_info(url):
    result = {
        "council_adoption_exists": "no",
        "press_exists": "no",
        "pres_link": pd.NA,
    }

    print(f"[Council scan] Checking Eur-Lex URL: {url}")

    try:
        resp = session_scrape.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1) First check literal tables
        target_table = None
        for table in soup.find_all("table"):
            table_text = table.get_text(" ", strip=True)
            if COUNCIL_HEADER_PATTERN.search(table_text):
                target_table = table
                break

        if target_table is not None:
            result["council_adoption_exists"] = "yes"
            result["press_exists"], result["pres_link"] = find_pres_link_in_container(
                target_table, resp.url
            )
            print(
                "[Council scan] Match found in table -> "
                f"council_adoption_exists={result['council_adoption_exists']}, "
                f"press_exists={result['press_exists']}, pres_link={result['pres_link']}"
            )
            return pd.Series(result)

        # 2) Fallback: look for a section/header/block containing the text
        header_tag = soup.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name
            in [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "summary",
                "button",
                "div",
                "span",
                "li",
                "td",
                "th",
            ]
            and COUNCIL_HEADER_PATTERN.search(tag.get_text(" ", strip=True) or "")
        )

        if header_tag is None:
            print("[Council scan] No council adoption section found.")
            return pd.Series(result)

        result["council_adoption_exists"] = "yes"

        candidates = []

        if isinstance(header_tag.parent, Tag):
            candidates.append(header_tag.parent)

        sibling_html = []
        for sib in header_tag.next_siblings:
            if isinstance(sib, Tag) and sib.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                break
            sibling_html.append(str(sib))

        if sibling_html:
            sibling_container = BeautifulSoup("".join(sibling_html), "html.parser")
            candidates.append(sibling_container)

        candidates.append(header_tag)

        for candidate in candidates:
            press_exists, pres_link = find_pres_link_in_container(candidate, resp.url)
            if press_exists == "yes":
                result["press_exists"] = "yes"
                result["pres_link"] = pres_link
                break

        print(
            "[Council scan] Section-based result -> "
            f"council_adoption_exists={result['council_adoption_exists']}, "
            f"press_exists={result['press_exists']}, pres_link={result['pres_link']}"
        )
        return pd.Series(result)

    except requests.RequestException as e:
        print(f"[Council scan] Request failed for {url}: {e}")
        return pd.Series(result)
    except Exception as e:
        print(f"[Council scan] Unexpected error for {url}: {e}")
        return pd.Series(result)


# -----------------------------
# PDF link logic
# -----------------------------
def normalize_url(url):
    if pd.isna(url):
        return pd.NA
    return str(url).strip().replace("http://", "https://")


def is_pdf_response(resp):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    final_url = resp.url.lower()
    return "application/pdf" in ctype or final_url.endswith(".pdf") or "/pdf" in final_url


# ---------------------------------------------------
# EUROPA logic
# ---------------------------------------------------
def get_presscorner_slug(url):
    url = normalize_url(url)

    # New Press Corner detail URL
    m = re.search(r"/detail/[a-z]{2}/([a-z-]+_\d+_\d+)$", url, re.I)
    if m:
        return m.group(1).lower()

    # Old rapid URL
    parsed = urlparse(url)
    ref = parse_qs(parsed.query).get("reference", [None])[0]

    if ref:
        m = re.match(r"([A-Z-]+)/(\d+)/(\d+)", ref, re.I)
        if m:
            prefix = m.group(1).lower()
            yy = m.group(2)
            num = m.group(3)
            return f"{prefix}_{yy}_{num}"

    return None


def build_presscorner_pdf_url(url):
    slug = get_presscorner_slug(url)
    if not slug:
        return None
    return f"https://ec.europa.eu/commission/presscorner/api/files/document/print/en/{slug}/{slug.upper()}_EN.pdf"


def get_europa_pdf_link(url):
    pdf_url = build_presscorner_pdf_url(url)
    if not pdf_url:
        print(f"[PDF check][EUROPA] Could not build PDF URL from: {url}")
        return False, pd.NA

    print(f"[PDF check][EUROPA] Trying: {pdf_url}")
    try:
        resp = session_pdf.get(pdf_url, timeout=30, allow_redirects=True, stream=True)
        resp.raise_for_status()
        if is_pdf_response(resp):
            print(f"[PDF check][EUROPA] PDF found: {resp.url}")
            return True, resp.url
    except Exception as e:
        print(f"[PDF check][EUROPA] Failed for {url}: {e}")

    print(f"[PDF check][EUROPA] No PDF found for: {url}")
    return False, pd.NA


# ---------------------------------------------------
# CONSILIUM logic
# ---------------------------------------------------
def two_digit_year_to_four_digit(yy):
    """
    13 -> 2013
    96 -> 1996
    Assumes:
    00-59 => 2000-2059
    60-99 => 1960-1999
    """
    yy = int(yy)
    return 2000 + yy if yy < 60 else 1900 + yy


def extract_docnum_and_year_from_press_link(url):
    """
    From:
    ...ff_COTE_DOCUMENT=10457/13|10457/*/13...
    extract:
      doc_number = '10457'
      yy = '13'
      year = 2013
    """
    url = normalize_url(url)
    if pd.isna(url):
        return pd.NA, pd.NA, pd.NA

    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    cote = params.get("ff_COTE_DOCUMENT", [None])[0]
    if not cote:
        return pd.NA, pd.NA, pd.NA

    first_part = cote.split("|")[0].strip()

    m = re.match(r"(\d+)/(\d{2})$", first_part)
    if not m:
        return pd.NA, pd.NA, pd.NA

    doc_number = m.group(1)
    yy = m.group(2)
    year = two_digit_year_to_four_digit(yy)

    return doc_number, yy, year


def build_consilium_pdf_candidates(doc_number, year, max_rev=8):
    """
    Example:
    https://data.consilium.europa.eu/doc/document/ST-10457-2013-REV-1/en/pdf
    """
    if pd.isna(doc_number) or pd.isna(year):
        return []

    base = f"https://data.consilium.europa.eu/doc/document/ST-{doc_number}-{year}"
    candidates = []

    # Common variants
    candidates.append(f"{base}-INIT/en/pdf")

    for rev in range(1, max_rev + 1):
        candidates.append(f"{base}-REV-{rev}/en/pdf")

    # Optional extra variants
    for add in range(1, 6):
        candidates.append(f"{base}-ADD-{add}/en/pdf")

    for cor in range(1, 4):
        candidates.append(f"{base}-COR-{cor}/en/pdf")

    for rev in range(1, max_rev + 1):
        for add in range(1, 4):
            candidates.append(f"{base}-REV-{rev}-ADD-{add}/en/pdf")
        for cor in range(1, 3):
            candidates.append(f"{base}-REV-{rev}-COR-{cor}/en/pdf")

    return candidates


def url_is_pdf(url, timeout=20):
    try:
        resp = session_pdf.get(url, timeout=timeout, allow_redirects=True, stream=True)
        resp.raise_for_status()

        ctype = (resp.headers.get("Content-Type") or "").lower()
        final_url = resp.url.lower()

        is_pdf = "application/pdf" in ctype or final_url.endswith(".pdf") or "/pdf" in final_url

        resp.close()

        if is_pdf:
            return True, resp.url
        return False, pd.NA

    except Exception:
        return False, pd.NA


def get_consilium_pdf_link(url, max_rev=8, debug=False):
    """
    For register.consilium links:
    1) extract doc number + year from ff_COTE_DOCUMENT
    2) try likely direct EN PDF URLs
    3) return (document_found, pdf_link)
    """
    doc_number, yy, year = extract_docnum_and_year_from_press_link(url)

    if pd.isna(doc_number):
        print(f"[PDF check][CONSILIUM] No document number extracted from: {url}")
        return False, pd.NA

    print(
        f"[PDF check][CONSILIUM] Extracted doc_number={doc_number}, yy={yy}, year={year} from: {url}"
    )

    candidates = build_consilium_pdf_candidates(doc_number, year, max_rev=max_rev)

    for i, candidate in enumerate(candidates, start=1):
        found, final_url = url_is_pdf(candidate)

        if debug:
            print(f"[PDF check][CONSILIUM] Candidate {i}/{len(candidates)}: {candidate} -> {found}")

        if found:
            print(f"[PDF check][CONSILIUM] PDF found: {final_url}")
            return True, final_url

    print(f"[PDF check][CONSILIUM] No PDF found for: {url}")
    return False, pd.NA


# ---------------------------------------------------
# Dispatcher
# ---------------------------------------------------
def get_document_pdf_link(pres_link, debug=False):
    if pd.isna(pres_link):
        print("[PDF check] pres_link is missing.")
        return pd.Series({"document_found": False, "pdf_link": pd.NA})

    url = normalize_url(pres_link)
    low = url.lower()

    print(f"[PDF check] Processing pres_link: {url}")

    # check consilium FIRST
    if "register.consilium.europa.eu" in low or "consilium.europa.eu" in low:
        found, pdf_link = get_consilium_pdf_link(url, debug=debug)
        return pd.Series({"document_found": found, "pdf_link": pdf_link})

    # then europa / presscorner
    if "ec.europa.eu" in low or "europa.eu/rapid" in low or "commission/presscorner" in low:
        found, pdf_link = get_europa_pdf_link(url)
        return pd.Series({"document_found": found, "pdf_link": pdf_link})

    print(f"[PDF check] Unsupported domain for pres_link: {url}")
    return pd.Series({"document_found": False, "pdf_link": pd.NA})


# -----------------------------
# Main execution
# -----------------------------
# -----------------------------
# Main execution
# -----------------------------
def main():
    input_path = os.path.join(BLD, "timeline_table_checked.csv")

    print("=" * 80)
    print("Starting create_council_lop_pres_con_links.py")
    print(f"Script directory: {script_dir}")
    print(f"Project root: {project_root}")
    print(f"BLD directory: {BLD}")
    print(f"Input file: {input_path}")
    print(f"Output file: {output_path}")
    print("=" * 80)

    df = pd.read_csv(input_path)
    print(f"[Load] Loaded dataframe with {len(df)} rows and {len(df.columns)} columns.")

    print("\n[Step 1] Extracting council adoption / PRES link information...")
    df[["council_adoption_exists", "press_exists", "pres_link"]] = df["eurlex_url"].apply(
        extract_council_adoption_info
    )
    print("[Step 1] Done.")
    print(
        "[Step 1] Summary -> "
        f"council_adoption_exists=yes: {(df['council_adoption_exists'] == 'yes').sum()}, "
        f"press_exists=yes: {(df['press_exists'] == 'yes').sum()}, "
        f"pres_link notna: {df['pres_link'].notna().sum()}"
    )

    print("\n[Step 2] Building PDF link dataframe from rows with pres_link...")
    pdf_df = df.loc[df["pres_link"].notna(), ["procedure", "pres_link"]].copy()
    print(f"[Step 2] Rows to process for PDF lookup: {len(pdf_df)}")

    pdf_df[["document_found", "pdf_link"]] = pdf_df["pres_link"].apply(
        lambda x: get_document_pdf_link(x, debug=False)
    )

    print("[Step 2] Done.")
    print(
        "[Step 2] Summary -> "
        f"document_found=True: {pdf_df['document_found'].sum()} out of {len(pdf_df)}"
    )

    pdf_df.to_csv(output_path, index=False)
    print(f"\n[Save] Output written to: {output_path}")

    print("\n[Final] pdf_df preview:")
    print(pdf_df)

    return pdf_df


if __name__ == "__main__":
    main()
