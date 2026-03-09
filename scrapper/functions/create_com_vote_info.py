import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from typing import List, Optional, Union, Tuple

# ---------- existing functions (unchanged, kept for reference) ----------
def fetch_html(url: str) -> str:
    response = requests.get(url)
    response.raise_for_status()
    return response.text

def find_sections_by_header(soup: BeautifulSoup, header_text: str) -> List[BeautifulSoup]:
    sections = []
    pattern = re.compile(re.escape(header_text), re.IGNORECASE)
    for elem in soup.find_all(string=pattern):
        parent = elem.parent
        while parent and parent.name not in ['h1','h2','h3','h4','h5','h6','p','div','section']:
            parent = parent.parent
        if not parent:
            parent = elem.parent
        next_div = parent.find_next('div', class_='table-responsive')
        if next_div and next_div not in sections:
            sections.append(next_div)
    return sections

def extract_committee_from_table(procedure_div: BeautifulSoup, label_texts: Union[str, List[str]]) -> Optional[str]:
    if isinstance(label_texts, str):
        label_texts = [label_texts]
    table = procedure_div.find('table')
    if not table:
        return None
    rows = table.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        if any(lt.lower() in label.lower() for lt in label_texts):
            p = cells[1].find('p')
            if p:
                return p.get_text(strip=True)
            return cells[1].get_text(strip=True)
    return None

def count_rollcall_sections(soup: BeautifulSoup, header_text: str) -> int:
    pattern = re.compile(re.escape(header_text), re.IGNORECASE)
    return len(list(soup.find_all(string=pattern)))

# ---------- new helper functions ----------
def find_all_divs_after_header(soup: BeautifulSoup, header_text: str, class_name: str = 'table-responsive') -> List[BeautifulSoup]:
    """
    Find all divs with class `class_name` that appear after an element containing header_text.
    Returns a list of those divs.
    """
    divs = []
    pattern = re.compile(re.escape(header_text), re.IGNORECASE)
    for elem in soup.find_all(string=pattern):
        parent = elem.parent
        while parent and parent.name not in ['h1','h2','h3','h4','h5','h6','p','div','section']:
            parent = parent.parent
        if not parent:
            parent = elem.parent
        # find all following divs with the given class
        for sibling in parent.find_all_next('div', class_=class_name):
            # stop if we hit another header? For simplicity we collect all until end of section.
            # But the page structure is consistent: all such divs under the same heading belong to it.
            if sibling not in divs:
                divs.append(sibling)
    return divs

def extract_committees_from_table(procedure_div: BeautifulSoup, label_texts: Union[str, List[str]]) -> List[str]:
    """
    Extract all committee codes from a procedure table.
    Finds the row whose first cell contains any of the label_texts (case‑insensitive),
    then collects the text from all subsequent cells (or their first paragraphs).
    Returns a list of committee codes.
    """
    if isinstance(label_texts, str):
        label_texts = [label_texts]
    table = procedure_div.find('table')
    if not table:
        return []
    rows = table.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        if any(lt.lower() in label.lower() for lt in label_texts):
            committees = []
            # start from cell 1 (index 1) because cell 0 is the label
            for cell in cells[1:]:
                # committee code is usually in the first paragraph, otherwise whole cell text
                p = cell.find('p')
                text = p.get_text(strip=True) if p else cell.get_text(strip=True)
                if text:  # ignore empty cells
                    committees.append(text)
            return committees
    return []

# ---------- new main function ----------
def get_committee_votes_with_html(url: str, procedure_number: str) -> pd.DataFrame:
    """
    Fetch the HTML from the given Europarl document URL and extract
    information about responsible and opinion committees, including the
    full HTML of the procedure and roll‑call tables.

    Parameters
    ----------
    url : str
        The URL of the document (e.g. https://www.europarl.europa.eu/doceo/document/...)
    procedure_number : str
        The procedure identifier, e.g. '2021/0366(COD)'

    Returns
    -------
    pd.DataFrame
        Columns: procedure, committee, designation, procedure_available,
                 rollcall_available, procedure_string, rollcall_string
    """
    html = fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')

    # ----- Check for "document not in HTML" placeholder -----
    placeholder = soup.select_one('div.card.mb-3 div.card-body p.bg-white.alert.alert-info.mb-3')
    if placeholder and "This document does not exist in HTML but is available in the following formats:" in placeholder.get_text():
        return pd.DataFrame([{
            'procedure': procedure_number,
            'committee': 'other format',
            'designation': 'other format',
            'procedure_available': False,
            'rollcall_available': False,
            'procedure_string': '',
            'rollcall_string': ''
        }])

    # ---- Collect responsible committee and its procedure table ----
    resp_procedure_div = None
    resp_committee = None

    # Try specific header first
    resp_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE RESPONSIBLE")
    for div in resp_sections:
        code = extract_committee_from_table(div, "Committee responsible")
        if code:
            resp_committee = code
            resp_procedure_div = div
            break

    # If not found, try generic "PROCEDURE"
    if not resp_committee:
        generic_sections = find_sections_by_header(soup, "PROCEDURE")
        for div in generic_sections:
            code = extract_committee_from_table(div, "Committee responsible")
            if code:
                resp_committee = code
                resp_procedure_div = div
                break

    # ---- Collect responsible roll‑call tables ----
    resp_rollcall_divs = find_all_divs_after_header(soup, "FINAL VOTE BY ROLL CALL IN COMMITTEE RESPONSIBLE")
    resp_rollcall_exists = len(resp_rollcall_divs) > 0

    # ---- Collect opinion committees with their source tables ----
    # We'll store tuples (committee_code, procedure_div)
    opinion_entries = []

    # 1. Sections with header "PROCEDURE – COMMITTEE ASKED FOR OPINION"
    opinion_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE ASKED FOR OPINION")
    for div in opinion_sections:
        codes = extract_committees_from_table(div, ["Opinion by", "Committee(s) asked for opinion(s)"])
        for code in codes:
            opinion_entries.append((code, div))

    # 2. Sections with header "OPINION"
    if not opinion_entries:
        opinion_headers_sections = find_sections_by_header(soup, "OPINION")
        for div in opinion_headers_sections:
            codes = extract_committees_from_table(div, ["Opinion by", "Committee(s) asked for opinion(s)"])
            for code in codes:
                opinion_entries.append((code, div))

    # 3. Generic "PROCEDURE" sections (only if we haven't found any yet, and avoid duplicates)
    if not opinion_entries:
        generic_sections = find_sections_by_header(soup, "PROCEDURE")
        existing = set()
        for div in generic_sections:
            codes = extract_committees_from_table(div, ["Opinion by", "Committee(s) asked for opinion(s)"])
            for code in codes:
                if code.upper() not in existing:
                    opinion_entries.append((code, div))
                    existing.add(code.upper())

    # ---- Collect opinion roll‑call tables ----
    opinion_rollcall_divs = find_all_divs_after_header(soup, "FINAL VOTE BY ROLL CALL IN COMMITTEE ASKED FOR OPINION")
    opinion_rollcall_count = len(opinion_rollcall_divs)

    # ---- Build rows ----
    rows = []

    # Responsible committee row
    if resp_committee:
        proc_html = str(resp_procedure_div) if resp_procedure_div else ''
        roll_html = ''.join(str(div) for div in resp_rollcall_divs) if resp_rollcall_exists else ''
        rows.append({
            'procedure': procedure_number,
            'committee': resp_committee,
            'designation': 'lead',
            'procedure_available': resp_procedure_div is not None,
            'rollcall_available': resp_rollcall_exists,
            'procedure_string': proc_html,
            'rollcall_string': roll_html
        })
    elif resp_sections:  # section exists but no committee code found
        proc_html = str(resp_sections[0]) if resp_sections else ''
        roll_html = ''.join(str(div) for div in resp_rollcall_divs) if resp_rollcall_exists else ''
        rows.append({
            'procedure': procedure_number,
            'committee': 'UNKNOWN',
            'designation': 'lead',
            'procedure_available': True,
            'rollcall_available': resp_rollcall_exists,
            'procedure_string': proc_html,
            'rollcall_string': roll_html
        })

    # Opinion committee rows
    for i, (comm, proc_div) in enumerate(opinion_entries):
        proc_html = str(proc_div) if proc_div else ''
        # rollcall available only for the first `opinion_rollcall_count` committees
        roll_avail = i < opinion_rollcall_count
        roll_html = ''.join(str(div) for div in opinion_rollcall_divs) if roll_avail else ''
        rows.append({
            'procedure': procedure_number,
            'committee': comm,
            'designation': 'opinion',
            'procedure_available': True,  # we have a procedure div
            'rollcall_available': roll_avail,
            'procedure_string': proc_html,
            'rollcall_string': roll_html
        })

    return pd.DataFrame(rows)