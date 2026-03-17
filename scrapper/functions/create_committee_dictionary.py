import re
from typing import List, Dict

import pandas as pd
import requests
from bs4 import BeautifulSoup


COMMITTEE_URL = "https://www.europarl.europa.eu/committees/en/about/list-of-committees"


def fetch_html(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def clean_text(text: str) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def normalize_committee_type(section_heading: str) -> str:
    heading = clean_text(section_heading).lower()
    if heading == "standing committees":
        return "Standing committee"
    if heading == "special committees":
        return "Special committee"
    return clean_text(section_heading)


def parse_committee_section(section) -> List[Dict[str, str]]:
    """
    Parse one section such as:
    - Standing committees
    - Special committees
    """
    out = []

    h2 = section.find("h2")
    if not h2:
        return out

    committee_type = normalize_committee_type(h2.get_text(" ", strip=True))

    for item in section.find_all("div", class_="es_committees-list-item"):
        code_links = item.find_all("a", class_="es_badge-committee")
        name_links = item.find_all("a", class_="es_committee-title")

        n = min(len(code_links), len(name_links))
        for code_link, name_link in zip(code_links[:n], name_links[:n]):
            committee_code = clean_text(code_link.get_text(" ", strip=True)).upper()
            committee_name = clean_text(name_link.get_text(" ", strip=True))

            if committee_code and committee_name:
                out.append({
                    "committee_code": committee_code,
                    "committee": committee_name,
                    "committee_type": committee_type,
                })

    return out


def build_committee_dictionary(url: str = COMMITTEE_URL) -> pd.DataFrame:
    """
    Scrape the European Parliament committee list page and return a dictionary
    with columns:
        committee_code, committee, committee_type
    """
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    rows: List[Dict[str, str]] = []

    for section in soup.find_all("section"):
        rows.extend(parse_committee_section(section))

    df = pd.DataFrame(rows, columns=["committee_code", "committee", "committee_type"])

    if df.empty:
        return df

    df = (
        df.drop_duplicates()
          .sort_values(["committee_type", "committee_code"], kind="stable")
          .reset_index(drop=True)
    )

    return df