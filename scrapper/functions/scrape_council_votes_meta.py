"""
Functions for scraping Council of the EU voting-result search pages from Consilium.

Intent
------
This module takes the search-results page for Council voting results, walks through
all paginated result pages, parses each result block plus its corresponding vote block,
and returns two pandas DataFrames:

1. df_votes
   The main result table, one row per voting-result entry, with the same structure
   you validated in Jupyter.

2. df_meta
   A small per-page metadata table with:
   - page
   - rows
   - url

Design choices
--------------
- The output column names are kept exactly as in your working notebook version.
- The scraper first parses page 1 to infer:
  - expected total result count
  - total number of pages
  - the Session -> council configuration lookup
- The parser assumes the result HTML alternates between:
  - info section
  - votes section
  inside the main results container.

Fallbacks and diagnostics
-------------------------
- Retries are built into page fetching.
- A "browser check" page is explicitly detected and raised as an error.
- Missing sections do not crash the whole run; they produce warnings and blank fields.
- Page-level row counts are logged for quick diagnostics.
- A duplicate diagnostic is printed on the final combined dataframe.

Typical use
-----------
from functions.scrape_council_votes_meta import scrape_council_votes, save_council_vote_outputs

df_votes, df_meta = scrape_council_votes()
save_council_vote_outputs(df_votes, df_meta, output_dir="bld")
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


DEFAULT_SEARCH_URL = (
    "https://www.consilium.europa.eu/en/general-secretariat/"
    "corporate-policies/transparency/voting-results/"
    "?ActType=0&ActNumber=&DocNumber=&InterinstNumber=&Title="
    "&DateFrom=1960%2F01%2F01&DateTo=&Session=0&CouncilAction=0"
    "&VotingRule=0&VotingProcedure=0&PolicyArea=0&Country=0"
    "&VoteFor=on&VoteAgainst=on&VoteAbstain=on&VoteNotParticipating=on&page=1"
)

DEFAULT_HEADERS = {
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

VOTE_OUTPUT_COLUMNS = [
    "doc_number",
    "doc_link",
    "procedure",
    "date",
    "meeting_number",
    "council_configuration",
    "policy_area",
    "legislative_procedure",
    "voting_rule",
    "action_by_council",
    "act_type",
    "status",
    "status_detail",
    "title",
    "votes_in_favour",
    "votes_against",
    "abstentions",
    "not_participating",
    "total_votes",
    "countries_in_favour",
    "countries_against",
    "countries_abstentions",
    "countries_not_participating",
    "source_page",
    "result_rank_on_page",
    "search_url",
]

META_OUTPUT_COLUMNS = ["page", "rows", "url"]


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------
def clean_text(text: Optional[str]) -> str:
    """Collapse whitespace and return a safe string."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def normalize_procedure(text: Optional[str]) -> str:
    """
    Normalize procedure text.

    Example:
    '2024/0318 (COD)' -> '2024/0318(COD)'
    """
    text = clean_text(text)
    text = re.sub(r"\s+\(", "(", text)
    return text


def to_int(text: Optional[str]) -> Optional[int]:
    """Extract the first integer found in a string."""
    text = clean_text(text)
    if not text:
        return None
    match = re.search(r"\d+", text.replace(",", ""))
    return int(match.group()) if match else None


def set_page_in_url(url: str, page_num: int) -> str:
    """Return the same URL with the page query parameter replaced."""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page_num)
    new_query = urlencode(query, doseq=True)
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment)
    )


def get_total_results_from_soup(soup: BeautifulSoup) -> Optional[int]:
    """Parse the '1718 result(s) found.' number from the page."""
    p = soup.find("p", class_="gsc-heading--lg")
    if p is None:
        print("[WARN] Could not find total-results paragraph.")
        return None

    txt = clean_text(p.get_text(" ", strip=True))
    match = re.search(r"(\d[\d,]*)", txt)
    if not match:
        print(f"[WARN] Could not parse total results from text: {txt}")
        return None

    return int(match.group(1).replace(",", ""))


def get_total_pages_from_soup(soup: BeautifulSoup) -> int:
    """
    Infer the number of pages from the pagination block.

    Falls back to 1 when pagination is missing.
    """
    nav = soup.find("nav", class_="gsc-pagination")
    if nav is None:
        print("[INFO] No pagination nav found. Assuming only 1 page.")
        return 1

    page_numbers: List[int] = []

    current = nav.select_one(".gsc-pagination__page--current span")
    if current:
        txt = clean_text(current.get_text(" ", strip=True))
        if txt.isdigit():
            page_numbers.append(int(txt))

    for a in nav.find_all("a", href=True):
        txt = clean_text(a.get_text(" ", strip=True))
        if txt.isdigit():
            page_numbers.append(int(txt))

        href = a["href"]
        match = re.search(r"[?&]page=(\d+)", href)
        if match:
            page_numbers.append(int(match.group(1)))

    if not page_numbers:
        print("[WARN] Pagination nav found, but no page numbers parsed. Assuming 1 page.")
        return 1

    return max(page_numbers)


def build_session_lookup_from_soup(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Build a lookup from meeting number -> council configuration.

    Example:
    4159 -> Justice and Home Affairs
    """
    lookup: Dict[str, str] = {}

    session_select = soup.find("select", attrs={"name": "Session"})
    if session_select is None:
        print("[WARN] Could not find Session select; council_configuration mapping will be blank.")
        return lookup

    for opt in session_select.find_all("option"):
        value = clean_text(opt.get("value"))
        label = clean_text(opt.get_text(" ", strip=True))

        if not value or value == "0":
            continue

        if " - " in label:
            _, config = label.split(" - ", 1)
            lookup[value] = clean_text(config)
        else:
            lookup[value] = label

    print(f"[INFO] Built session lookup with {len(lookup)} mappings.")
    return lookup


def extract_country_codes(countries_div) -> str:
    """Extract country abbreviations from a vote-country container."""
    if countries_div is None:
        return ""
    codes = [clean_text(abbr.get_text(" ", strip=True)) for abbr in countries_div.find_all("abbr")]
    codes = [code for code in codes if code]
    return "|".join(codes)


# ---------------------------------------------------------------------
# Request / parsing infrastructure
# ---------------------------------------------------------------------
def build_session(headers: Optional[Dict[str, str]] = None) -> requests.Session:
    """Create a requests session with default or custom headers."""
    session = requests.Session()
    session.headers.update(headers or DEFAULT_HEADERS)
    return session


def fetch_response(
    session: requests.Session,
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_sleep_seconds: float = 2.0,
) -> requests.Response:
    """
    Fetch a page with retries and a browser-check guard.

    Raises
    ------
    RuntimeError
        When Consilium returns a Cloudflare/browser-check page.
    requests.RequestException
        After the final retry fails.
    """
    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()

            # Detect cloudflare / browser-check content explicitly.
            title_match = re.search(
                r"<title>\s*(.*?)\s*</title>",
                response.text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            page_title = clean_text(title_match.group(1)) if title_match else ""

            if "Browser check - Consilium" in page_title:
                raise RuntimeError(
                    "Received 'Browser check - Consilium' page instead of the real content."
                )

            return response

        except Exception as exc:  # intentional broad catch to retry browser-check failures too
            last_error = exc
            print(
                f"[WARN] Fetch failed for {url} "
                f"(attempt {attempt}/{max_retries}): {exc}"
            )

            if attempt < max_retries:
                sleep_time = retry_sleep_seconds * attempt
                print(f"[INFO] Sleeping {sleep_time:.1f}s before retry.")
                time.sleep(sleep_time)

    raise last_error


def fetch_soup(
    session: requests.Session,
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    retry_sleep_seconds: float = 2.0,
) -> Tuple[requests.Response, BeautifulSoup]:
    """Fetch a URL and parse it into BeautifulSoup."""
    response = fetch_response(
        session=session,
        url=url,
        timeout=timeout,
        max_retries=max_retries,
        retry_sleep_seconds=retry_sleep_seconds,
    )
    soup = BeautifulSoup(response.text, "html.parser")
    return response, soup


# ---------------------------------------------------------------------
# Per-result parsing
# ---------------------------------------------------------------------
def parse_info_section(
    info_sec,
    session_lookup: Dict[str, str],
    source_page: int,
    result_rank_on_page: int,
    search_url: str,
) -> Dict[str, object]:
    """
    Parse the 'info' half of a result pair.
    """
    row: Dict[str, object] = {
        "doc_number": "",
        "doc_link": "",
        "procedure": "",
        "date": "",
        "meeting_number": "",
        "council_configuration": "",
        "policy_area": "",
        "legislative_procedure": "",
        "voting_rule": "",
        "action_by_council": "",
        "act_type": "",
        "status": "",
        "status_detail": "",
        "title": "",
        "votes_in_favour": None,
        "votes_against": None,
        "abstentions": None,
        "not_participating": None,
        "total_votes": None,
        "countries_in_favour": "",
        "countries_against": "",
        "countries_abstentions": "",
        "countries_not_participating": "",
        "source_page": source_page,
        "result_rank_on_page": result_rank_on_page,
        "search_url": search_url,
    }

    title_el = info_sec.find("strong", class_="gsc-search-results__heading")
    if title_el is None:
        print(f"[WARN] Page {source_page}, rank {result_rank_on_page}: missing title element.")
    else:
        row["title"] = clean_text(title_el.get_text(" ", strip=True))

    meta_ul = info_sec.find("ul", class_="gsc-search-results__act-meta")
    if meta_ul is None:
        print(f"[WARN] Page {source_page}, rank {result_rank_on_page}: missing meta block.")
    else:
        for li in meta_ul.find_all("li", recursive=False):
            span = li.find("span")
            strong = li.find("strong")
            label = clean_text(span.get_text(" ", strip=True)).rstrip(":").lower() if span else ""
            value = clean_text(strong.get_text(" ", strip=True)) if strong else ""

            if label == "doc. no.":
                row["doc_number"] = value
                a = li.find("a", href=True)
                row["doc_link"] = urljoin(search_url, a["href"]) if a else ""

            elif label == "interinstitutional number":
                row["procedure"] = normalize_procedure(value)

            elif label == "date":
                row["date"] = value

    details_ul = info_sec.find("ul", class_="gsc-search-results__results")
    if details_ul is None:
        print(f"[WARN] Page {source_page}, rank {result_rank_on_page}: missing details block.")
    else:
        for li in details_ul.find_all("li", recursive=False):
            span = li.find("span")
            strong = li.find("strong")
            label = clean_text(span.get_text(" ", strip=True)).rstrip(":").lower() if span else ""
            value = clean_text(strong.get_text(" ", strip=True)) if strong else ""

            if label == "council":
                row["meeting_number"] = value
            elif label == "policy area":
                row["policy_area"] = value
            elif label == "legislative procedure":
                row["legislative_procedure"] = value
            elif label == "voting rule":
                row["voting_rule"] = value
            elif label == "action by the council":
                row["action_by_council"] = value
            elif label == "type of act":
                row["act_type"] = value

    if row["meeting_number"]:
        meeting_number = str(row["meeting_number"])
        row["council_configuration"] = session_lookup.get(meeting_number, "")
        if meeting_number != "0" and not row["council_configuration"]:
            print(
                f"[WARN] Page {source_page}, rank {result_rank_on_page}: "
                f"meeting_number={meeting_number} not found in Session lookup."
            )

    status_box = info_sec.find("div", class_="gsc-search-results__status")
    if status_box is None:
        print(f"[WARN] Page {source_page}, rank {result_rank_on_page}: missing status box.")
    else:
        status_strong = status_box.find("strong")
        status_p = status_box.find("p")
        row["status"] = clean_text(status_strong.get_text(" ", strip=True)) if status_strong else ""
        row["status_detail"] = clean_text(status_p.get_text(" ", strip=True)) if status_p else ""

    return row


def parse_votes_section(
    votes_sec,
    row: Dict[str, object],
    source_page: int,
    result_rank_on_page: int,
) -> Dict[str, object]:
    """
    Parse the 'votes' half of a result pair and update the row in place.
    """
    if votes_sec is None:
        print(f"[WARN] Page {source_page}, rank {result_rank_on_page}: missing votes section.")
        return row

    vote_labels = votes_sec.find_all("strong", class_="gsc-votes")
    vote_numbers = votes_sec.find_all("span", class_="gsc-votes__number")
    vote_country_divs = votes_sec.find_all("div", class_="gsc-votes__countries")

    if len(vote_labels) != 4:
        print(
            f"[WARN] Page {source_page}, rank {result_rank_on_page}: "
            f"expected 4 vote labels, found {len(vote_labels)}."
        )

    if len(vote_numbers) < 5:
        print(
            f"[WARN] Page {source_page}, rank {result_rank_on_page}: "
            f"expected at least 5 vote numbers (incl. total), found {len(vote_numbers)}."
        )

    if len(vote_country_divs) != 4:
        print(
            f"[WARN] Page {source_page}, rank {result_rank_on_page}: "
            f"expected 4 country-divs, found {len(vote_country_divs)}."
        )

    # HTML order observed from the results page:
    # 0 favour, 1 against, 2 abstentions, 3 not participating, 4 total
    if len(vote_numbers) >= 1:
        row["votes_in_favour"] = to_int(vote_numbers[0].get_text(" ", strip=True))
    if len(vote_numbers) >= 2:
        row["votes_against"] = to_int(vote_numbers[1].get_text(" ", strip=True))
    if len(vote_numbers) >= 3:
        row["abstentions"] = to_int(vote_numbers[2].get_text(" ", strip=True))
    if len(vote_numbers) >= 4:
        row["not_participating"] = to_int(vote_numbers[3].get_text(" ", strip=True))
    if len(vote_numbers) >= 5:
        row["total_votes"] = to_int(vote_numbers[4].get_text(" ", strip=True))

    if len(vote_country_divs) >= 1:
        row["countries_in_favour"] = extract_country_codes(vote_country_divs[0])
    if len(vote_country_divs) >= 2:
        row["countries_against"] = extract_country_codes(vote_country_divs[1])
    if len(vote_country_divs) >= 3:
        row["countries_abstentions"] = extract_country_codes(vote_country_divs[2])
    if len(vote_country_divs) >= 4:
        row["countries_not_participating"] = extract_country_codes(vote_country_divs[3])

    return row


def parse_page_to_df(
    soup: BeautifulSoup,
    source_page: int,
    search_url: str,
    session_lookup: Dict[str, str],
) -> pd.DataFrame:
    """
    Parse one search-results page into the final row structure.

    Notes
    -----
    The page structure alternates result blocks:
    - info section
    - votes section
    """
    acts_container = soup.find("section", class_="gsc-search-results__acts")
    if acts_container is None:
        print(f"[WARN] Page {source_page}: could not find acts container.")
        return pd.DataFrame(columns=VOTE_OUTPUT_COLUMNS)

    blocks = acts_container.find_all("section", recursive=False)
    if not blocks:
        print(f"[WARN] Page {source_page}: no direct section blocks found inside acts container.")
        return pd.DataFrame(columns=VOTE_OUTPUT_COLUMNS)

    if len(blocks) % 2 != 0:
        print(
            f"[WARN] Page {source_page}: expected alternating info/votes blocks, "
            f"but found odd number of sections = {len(blocks)}."
        )

    rows: List[Dict[str, object]] = []
    pair_count = len(blocks) // 2

    print(f"[INFO] Page {source_page}: found {len(blocks)} section blocks -> {pair_count} result pairs.")

    for i in range(pair_count):
        info_sec = blocks[2 * i]
        votes_sec = blocks[2 * i + 1]

        row = parse_info_section(
            info_sec=info_sec,
            session_lookup=session_lookup,
            source_page=source_page,
            result_rank_on_page=i + 1,
            search_url=search_url,
        )
        row = parse_votes_section(
            votes_sec=votes_sec,
            row=row,
            source_page=source_page,
            result_rank_on_page=i + 1,
        )
        rows.append(row)

    df = pd.DataFrame(rows)
    return df[VOTE_OUTPUT_COLUMNS]


# ---------------------------------------------------------------------
# Main scraping entry point
# ---------------------------------------------------------------------
def scrape_council_votes(
    search_url: str = DEFAULT_SEARCH_URL,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    delay_seconds: float = 1.0,
    max_retries: int = 3,
    retry_sleep_seconds: float = 2.0,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Scrape all pages of Council voting results for the given search URL.

    Parameters
    ----------
    search_url
        The page-1 search URL. Pagination is derived from this URL.
    headers
        Optional request headers. Defaults to DEFAULT_HEADERS.
    timeout
        Per-request timeout in seconds.
    delay_seconds
        Sleep time between successful page fetches.
    max_retries
        Number of retries per page fetch.
    retry_sleep_seconds
        Base wait time before retrying.

    Returns
    -------
    (df_votes, df_meta)
        df_votes: main row-level dataset
        df_meta: per-page metadata dataset
    """
    session = build_session(headers=headers)

    print("=" * 80)
    print("[STEP] Fetching page 1")
    response, soup = fetch_soup(
        session=session,
        url=search_url,
        timeout=timeout,
        max_retries=max_retries,
        retry_sleep_seconds=retry_sleep_seconds,
    )

    print(f"[INFO] status_code: {response.status_code}")
    print(f"[INFO] final_url: {response.url}")
    print(f"[INFO] title: {soup.title.get_text(strip=True) if soup.title else None}")

    h1 = soup.find("h1")
    print(f"[INFO] h1: {h1.get_text(' ', strip=True) if h1 else None}")

    results_p = soup.find("p", class_="gsc-heading--lg")
    print(f"[INFO] results_text: {results_p.get_text(' ', strip=True) if results_p else None}")

    page1_url = response.url

    print("=" * 80)
    print("[STEP] Inspecting pagination and metadata from page 1")

    expected_total_results = get_total_results_from_soup(soup)
    total_pages = get_total_pages_from_soup(soup)
    session_lookup = build_session_lookup_from_soup(soup)

    print(f"[INFO] Expected total results from page text: {expected_total_results}")
    print(f"[INFO] Total pages inferred from pagination: {total_pages}")
    print("=" * 80)

    all_dfs: List[pd.DataFrame] = []
    page_counts: List[Dict[str, object]] = []

    print("[STEP] Parsing page 1")
    df_page_1 = parse_page_to_df(
        soup=soup,
        source_page=1,
        search_url=page1_url,
        session_lookup=session_lookup,
    )
    print(f"[INFO] Page 1 parsed rows: {len(df_page_1)}")
    all_dfs.append(df_page_1)
    page_counts.append({"page": 1, "rows": len(df_page_1), "url": page1_url})

    for page_num in range(2, total_pages + 1):
        page_url = set_page_in_url(page1_url, page_num)

        print("=" * 80)
        print(f"[STEP] Fetching page {page_num}/{total_pages}")
        print(f"[INFO] URL: {page_url}")

        response_i, soup_i = fetch_soup(
            session=session,
            url=page_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_sleep_seconds=retry_sleep_seconds,
        )

        print(f"[INFO] HTTP status: {response_i.status_code}")
        print(f"[INFO] Title: {soup_i.title.get_text(strip=True) if soup_i.title else None}")

        results_text_el = soup_i.find("p", class_="gsc-heading--lg")
        results_text = clean_text(results_text_el.get_text(" ", strip=True)) if results_text_el else None
        print(f"[INFO] Results text: {results_text}")

        df_page = parse_page_to_df(
            soup=soup_i,
            source_page=page_num,
            search_url=response_i.url,
            session_lookup=session_lookup,
        )

        print(f"[INFO] Parsed rows on page {page_num}: {len(df_page)}")
        if len(df_page) == 0:
            print(f"[WARN] Page {page_num} produced 0 rows.")

        all_dfs.append(df_page)
        page_counts.append({"page": page_num, "rows": len(df_page), "url": response_i.url})

        time.sleep(delay_seconds)

    print("=" * 80)
    print("[STEP] Combining all parsed pages")

    df_all_pages = pd.concat(all_dfs, ignore_index=True)
    df_all_pages = df_all_pages[VOTE_OUTPUT_COLUMNS]

    page_counts_df = pd.DataFrame(page_counts)
    if not page_counts_df.empty:
        page_counts_df = page_counts_df[META_OUTPUT_COLUMNS]

    print(f"[INFO] Total parsed rows: {len(df_all_pages)}")
    if expected_total_results is not None:
        print(f"[INFO] Expected total rows from site: {expected_total_results}")
        if len(df_all_pages) == expected_total_results:
            print("[SUCCESS] Parsed row count matches expected total.")
        else:
            print("[WARN] Parsed row count DOES NOT match expected total.")

    dup_mask = df_all_pages.duplicated(
        subset=["doc_number", "procedure", "date", "title"],
        keep=False,
    )
    num_dup_rows = int(dup_mask.sum())
    print(f"[INFO] Potential duplicate rows on [doc_number, procedure, date, title]: {num_dup_rows}")

    print("[INFO] Final votes dataframe shape:", df_all_pages.shape)
    print("[INFO] Final meta dataframe shape:", page_counts_df.shape)

    return df_all_pages, page_counts_df


# ---------------------------------------------------------------------
# Saving helpers
# ---------------------------------------------------------------------
def save_dataframe_csv_json(
    df: pd.DataFrame,
    csv_path: Path | str,
    json_path: Path | str,
) -> None:
    """
    Save a dataframe as CSV and JSON records.

    JSON is written using Python's json module for stable pretty formatting.
    """
    csv_path = Path(csv_path)
    json_path = Path(json_path)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    df.to_csv(csv_path, index=False)
    print(f"[INFO] Saved CSV to {csv_path}")

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(df.to_dict(orient="records"), f, ensure_ascii=False, indent=2)
    print(f"[INFO] Saved JSON to {json_path}")


def save_council_vote_outputs(
    df_votes: pd.DataFrame,
    df_meta: pd.DataFrame,
    output_dir: Path | str,
) -> None:
    """
    Save the two expected outputs:

    - council_votes.csv
    - council_votes.json
    - council_votes_meta.csv
    - council_votes_meta.json
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    save_dataframe_csv_json(
        df=df_votes,
        csv_path=output_dir / "council_votes.csv",
        json_path=output_dir / "council_votes.json",
    )

    save_dataframe_csv_json(
        df=df_meta,
        csv_path=output_dir / "council_votes_meta.csv",
        json_path=output_dir / "council_votes_meta.json",
    )