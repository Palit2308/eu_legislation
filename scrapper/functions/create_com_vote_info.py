import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
from typing import List, Optional, Union

def fetch_html(url: str) -> str:
    """Fetch HTML content from a URL."""
    response = requests.get(url)
    response.raise_for_status()
    return response.text

def find_sections_by_header(soup: BeautifulSoup, header_text: str) -> List[BeautifulSoup]:
    """
    Find all div.table-responsive that appear after an element containing header_text (case-insensitive).
    Returns a list of those divs.
    """
    sections = []
    pattern = re.compile(re.escape(header_text), re.IGNORECASE)
    for elem in soup.find_all(string=pattern):
        parent = elem.parent
        # Climb up to a block-level element that likely contains the heading
        while parent and parent.name not in ['h1','h2','h3','h4','h5','h6','p','div','section']:
            parent = parent.parent
        if not parent:
            parent = elem.parent
        next_div = parent.find_next('div', class_='table-responsive')
        if next_div and next_div not in sections:
            sections.append(next_div)
    return sections

def extract_committee_from_table(procedure_div: BeautifulSoup, label_texts: Union[str, List[str]]) -> Optional[str]:
    """
    Extract committee code from a procedure table by looking for a row
    whose first cell contains any of the label_texts (case‑insensitive substring match).
    Returns the text from the first paragraph of the second cell, or the whole cell text if no paragraph.
    """
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
        # Check if any of the label texts appears in the label (case‑insensitive)
        if any(lt.lower() in label.lower() for lt in label_texts):
            # Committee code is in the second cell, usually the first paragraph
            p = cells[1].find('p')
            if p:
                return p.get_text(strip=True)
            return cells[1].get_text(strip=True)
    return None

def count_rollcall_sections(soup: BeautifulSoup, header_text: str) -> int:
    """Count how many elements contain header_text (case-insensitive)."""
    pattern = re.compile(re.escape(header_text), re.IGNORECASE)
    return len(list(soup.find_all(string=pattern)))

def get_committee_votes(url: str) -> pd.DataFrame:
    """
    Fetch the HTML from the given Europarl document URL and extract
    information about responsible and opinion committees.
    Returns a DataFrame with columns:
        committee, designation, procedure_available, rollcall_available
    """
    html = fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')

    # ----- Check for "document not in HTML" placeholder -----
    placeholder = soup.select_one('div.card.mb-3 div.card-body p.bg-white.alert.alert-info.mb-3')
    if placeholder and "This document does not exist in HTML but is available in the following formats:" in placeholder.get_text():
        # Return a single placeholder row
        return pd.DataFrame([{
            'committee': 'other format',
            'designation': 'other format',
            'procedure_available': 'other format',
            'rollcall_available': 'other format'
        }])

    # ---- Responsible committee ----
    resp_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE RESPONSIBLE")
    resp_committee = None
    for div in resp_sections:
        code = extract_committee_from_table(div, "Committee responsible")
        if code:
            resp_committee = code
            break

    generic_procedure_sections = []
    if not resp_committee:
        generic_sections = find_sections_by_header(soup, "PROCEDURE")
        generic_procedure_sections = generic_sections
        for div in generic_sections:
            code = extract_committee_from_table(div, "Committee responsible")
            if code:
                resp_committee = code
                if div not in resp_sections:
                    resp_sections.append(div)
                break
    else:
        generic_procedure_sections = find_sections_by_header(soup, "PROCEDURE")

    resp_rollcall_exists = count_rollcall_sections(soup, "FINAL VOTE BY ROLL CALL IN COMMITTEE RESPONSIBLE") > 0

    # ---- Opinion committees ----
    opinion_labels = ["Opinion by", "Committee(s) asked for opinion(s)"]

    opinion_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE ASKED FOR OPINION")
    opinion_committees = []
    for div in opinion_sections:
        code = extract_committee_from_table(div, opinion_labels)
        if code:
            opinion_committees.append(code)

    if not opinion_committees:
        opinion_headers_sections = find_sections_by_header(soup, "OPINION")
        for div in opinion_headers_sections:
            code = extract_committee_from_table(div, opinion_labels)
            if code:
                opinion_committees.append(code)

    if generic_procedure_sections:
        existing = {c.upper() for c in opinion_committees}
        for div in generic_procedure_sections:
            code = extract_committee_from_table(div, opinion_labels)
            if code and code.upper() not in existing:
                opinion_committees.append(code)
                existing.add(code.upper())

    opinion_rollcall_count = count_rollcall_sections(soup, "FINAL VOTE BY ROLL CALL IN COMMITTEE ASKED FOR OPINION")

    # Build rows
    rows = []

    if resp_committee:
        rows.append({
            'committee': resp_committee,
            'designation': 'lead',
            'procedure_available': True,
            'rollcall_available': resp_rollcall_exists
        })
    elif resp_sections:
        rows.append({
            'committee': 'UNKNOWN',
            'designation': 'lead',
            'procedure_available': True,
            'rollcall_available': resp_rollcall_exists
        })

    for i, comm in enumerate(opinion_committees):
        rows.append({
            'committee': comm,
            'designation': 'opinion',
            'procedure_available': True,
            'rollcall_available': i < opinion_rollcall_count
        })

    return pd.DataFrame(rows)