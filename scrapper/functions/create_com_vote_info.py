import requests
from bs4 import BeautifulSoup, NavigableString, Tag
import pandas as pd
import re
from typing import List, Optional, Union, Dict, Set, Tuple


# ---------------------------------------------------------------------
# basic helpers
# ---------------------------------------------------------------------
def fetch_html(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def norm_key(text: str) -> str:
    return normalize_text(text).lower()


def is_probable_committee_code(text: str) -> bool:
    """
    Committee codes are usually short uppercase tokens like ECON, IMCO, LIBE, JURI.
    """
    text = normalize_text(text)
    if not text:
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9&/\-]{1,10}", text))


def get_cell_primary_text(cell: BeautifulSoup) -> str:
    """
    First meaningful paragraph text, otherwise full cell text.
    """
    paragraphs = [normalize_text(p.get_text(" ", strip=True)) for p in cell.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if paragraphs:
        return paragraphs[0]
    return normalize_text(cell.get_text(" ", strip=True))


def get_cell_all_texts(cell: BeautifulSoup) -> List[str]:
    """
    All paragraph texts in the cell, preserving order.
    """
    paragraphs = [normalize_text(p.get_text(" ", strip=True)) for p in cell.find_all("p")]
    paragraphs = [p for p in paragraphs if p]
    if paragraphs:
        return paragraphs
    text = normalize_text(cell.get_text(" ", strip=True))
    return [text] if text else []


def extract_codes_from_cells(cells: List[BeautifulSoup]) -> List[str]:
    """
    Extract committee codes from a row's data cells.
    Usually the first paragraph in each committee cell is the code, the second is a date.
    """
    out = []
    seen = set()

    for cell in cells:
        # Prefer paragraph-by-paragraph extraction
        texts = get_cell_all_texts(cell)
        candidate = None

        for txt in texts:
            if is_probable_committee_code(txt):
                candidate = txt
                break

        # fallback to first text if it itself looks like a code
        if candidate is None:
            primary = get_cell_primary_text(cell)
            if is_probable_committee_code(primary):
                candidate = primary

        if candidate:
            key = candidate.upper()
            if key not in seen:
                out.append(candidate.upper())
                seen.add(key)

    return out


def table_rows(table: BeautifulSoup) -> List[List[BeautifulSoup]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if cells:
            rows.append(cells)
    return rows


# ---------------------------------------------------------------------
# locating sections / tables
# ---------------------------------------------------------------------
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
HEADER_CONTAINER_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section"]


def find_header_nodes(soup: BeautifulSoup, header_text: str) -> List[Tag]:
    """
    Find elements whose visible text exactly matches the requested header text.
    This avoids matching random text inside tables.
    """
    target = norm_key(header_text)
    nodes = []

    for tag in soup.find_all(HEADER_CONTAINER_TAGS):
        text = norm_key(tag.get_text(" ", strip=True))
        if text == target:
            nodes.append(tag)

    return nodes


def collect_section_table_divs(header_node: Tag, class_name: str = "table-responsive") -> List[Tag]:
    """
    Starting from a header node, collect only the table-responsive divs that
    belong to that section. Stop when the next heading starts.
    """
    divs = []

    for sib in header_node.next_siblings:
        if isinstance(sib, NavigableString):
            if normalize_text(str(sib)):
                if divs:
                    break
            continue

        if not isinstance(sib, Tag):
            continue

        # stop at next section header
        if sib.name in HEADING_TAGS:
            break

        classes = set(sib.get("class", []))
        sib_text = normalize_text(sib.get_text(" ", strip=True))

        # direct table div
        if sib.name == "div" and class_name in classes:
            divs.append(sib)
            continue

        # ignore separators / blank blocks
        if not sib_text:
            continue

        if sib.name == "div" and "separator" in classes:
            continue

        # allow wrapped content containing table-responsive divs
        nested = sib.find_all("div", class_=class_name)
        if nested:
            divs.extend(nested)
            continue

        # if tables already started and meaningful new content appears, stop
        if divs:
            break

    return divs


def find_sections_by_header(soup: BeautifulSoup, header_text: str) -> List[BeautifulSoup]:
    """
    Finds the first table-responsive div belonging to each matching header section.
    """
    sections = []

    for header_node in find_header_nodes(soup, header_text):
        table_divs = collect_section_table_divs(header_node, class_name="table-responsive")
        if table_divs:
            sections.append(table_divs[0])

    return sections


def find_all_divs_after_header(
    soup: BeautifulSoup,
    header_text: str,
    class_name: str = "table-responsive"
) -> List[BeautifulSoup]:
    """
    Collect all table-responsive divs belonging only to the matched header section.
    """
    divs = []

    for header_node in find_header_nodes(soup, header_text):
        section_divs = collect_section_table_divs(header_node, class_name=class_name)
        for div in section_divs:
            if div not in divs:
                divs.append(div)

    return divs

# # ---------------------------------------------------------------------
# # locating sections / tables
# # ---------------------------------------------------------------------
# def find_sections_by_header(soup: BeautifulSoup, header_text: str) -> List[BeautifulSoup]:
#     """
#     Finds the first following div.table-responsive after matching header text.
#     """
#     sections = []
#     pattern = re.compile(re.escape(header_text), re.IGNORECASE)

#     for elem in soup.find_all(string=pattern):
#         parent = elem.parent
#         while parent and parent.name not in ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section"]:
#             parent = parent.parent
#         if not parent:
#             parent = elem.parent

#         next_div = parent.find_next("div", class_="table-responsive")
#         if next_div and next_div not in sections:
#             sections.append(next_div)

#     return sections


# def find_all_divs_after_header(
#     soup: BeautifulSoup,
#     header_text: str,
#     class_name: str = "table-responsive"
# ) -> List[BeautifulSoup]:
#     """
#     Collect all following divs with a given class after a matching header.
#     """
#     divs = []
#     pattern = re.compile(re.escape(header_text), re.IGNORECASE)

#     for elem in soup.find_all(string=pattern):
#         parent = elem.parent
#         while parent and parent.name not in ["h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section"]:
#             parent = parent.parent
#         if not parent:
#             parent = elem.parent

#         for sibling in parent.find_all_next("div", class_=class_name):
#             if sibling not in divs:
#                 divs.append(sibling)

#     return divs
def find_div_groups_after_header(
    soup: BeautifulSoup,
    header_text: str,
    class_name: str = "table-responsive"
) -> List[List[BeautifulSoup]]:
    """
    Return one list of table-responsive divs per matched header section.
    """
    groups = []

    for header_node in find_header_nodes(soup, header_text):
        section_divs = collect_section_table_divs(header_node, class_name=class_name)
        if section_divs:
            groups.append(section_divs)

    return groups

# ---------------------------------------------------------------------
# table parsing
# ---------------------------------------------------------------------
def parse_procedure_table(procedure_div: BeautifulSoup) -> Dict[str, Set[str]]:
    """
    Parse one procedure table and classify committees mentioned in it.

    Returns:
        {
            'lead': {...},
            'opinion_requested': {...},
            'opinion_explicit': {...},
            'no_op': {...}
        }

    Notes
    -----
    - 'lead' covers rows like:
        * Committee responsible
        * Committees responsible
    - 'opinion_requested' covers rows like:
        * Committee(s) asked for opinion(s)
        * Committees asked for opinions
    - 'opinion_explicit' covers rows like:
        * Opinion by
    - 'no_op' covers rows like:
        * Not delivering opinions
    """
    result = {
        "lead": set(),
        "opinion_requested": set(),
        "opinion_explicit": set(),
        "no_op": set(),
    }

    table = procedure_div.find("table")
    if not table:
        return result

    for cells in table_rows(table):
        if len(cells) < 2:
            continue

        label = norm_key(cells[0].get_text(" ", strip=True))
        codes = extract_codes_from_cells(cells[1:])

        if not codes:
            continue

        # lead committees
        if (
            "committee responsible" in label
            or "committees responsible" in label
        ):
            result["lead"].update(codes)

        # explicit opinion procedure table row
        elif (
            "opinion by" in label
        ):
            result["opinion_explicit"].update(codes)

        # opinion requested in another table (usually lead table)
        elif (
            "committee asked for opinion" in label
            or "committees asked for opinion" in label
            or "committees asked for opinions" in label
            or "committee(s) asked for opinion(s)" in label
        ):
            result["opinion_requested"].update(codes)

        # explicitly no opinion delivered
        elif "not delivering opinions" in label:
            result["no_op"].update(codes)

    return result


def extract_first_lead_committee(procedure_div: BeautifulSoup) -> Optional[str]:
    """
    Backward-compatible helper if you need a single lead code.
    """
    parsed = parse_procedure_table(procedure_div)
    leads = sorted(parsed["lead"])
    return leads[0] if leads else None


# ---------------------------------------------------------------------
# main extraction logic
# ---------------------------------------------------------------------
def get_committee_votes_with_html(url: str, procedure_number: str) -> pd.DataFrame:
    """
    Returns one row per committee with designation:
        - lead
        - opinion
        - no_op
        - other format

    Output columns:
        procedure, committee, designation, procedure_available,
        rollcall_available, procedure_string, rollcall_string
    """
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")

    # ---------------------------------------------------------------
    # 1. placeholder: document not available in HTML
    # ---------------------------------------------------------------
    placeholder = soup.select_one("div.card.mb-3 div.card-body p.bg-white.alert.alert-info.mb-3")
    if placeholder and "This document does not exist in HTML but is available in the following formats:" in placeholder.get_text():
        return pd.DataFrame([{
            "procedure": procedure_number,
            "committee": "other format",
            "designation": "other format",
            "procedure_available": False,
            "rollcall_available": False,
            "procedure_string": "",
            "rollcall_string": "",
        }])

    # ---------------------------------------------------------------
    # 2. find responsible procedure sections
    # ---------------------------------------------------------------
    resp_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE RESPONSIBLE")

    if not resp_sections:
        # fallback
        resp_sections = find_sections_by_header(soup, "PROCEDURE")

    # choose the first section that contains lead committee info
    resp_procedure_div = None
    resp_parsed = None

    for div in resp_sections:
        parsed = parse_procedure_table(div)
        if parsed["lead"]:
            resp_procedure_div = div
            resp_parsed = parsed
            break

    # if no lead found but sections exist, keep first section as fallback
    if resp_procedure_div is None and resp_sections:
        resp_procedure_div = resp_sections[0]
        resp_parsed = parse_procedure_table(resp_procedure_div)

    if resp_parsed is None:
        resp_parsed = {"lead": set(), "opinion_requested": set(), "opinion_explicit": set(), "no_op": set()}

    lead_committees = sorted(resp_parsed["lead"])
    requested_opinions_from_lead = set(resp_parsed["opinion_requested"])
    no_op_from_lead = set(resp_parsed["no_op"])

    # ---------------------------------------------------------------
    # 3. responsible roll-call tables
    # ---------------------------------------------------------------

    resp_rollcall_sections = find_div_groups_after_header(
        soup,
        "FINAL VOTE BY ROLL CALL IN COMMITTEE RESPONSIBLE"
    )

    resp_rollcall_exists = len(resp_rollcall_sections) > 0
    resp_rollcall_html = "".join(str(div) for div in resp_rollcall_sections[0]) if resp_rollcall_exists else ""
    
    # resp_rollcall_divs = find_all_divs_after_header(
    #     soup,
    #     "FINAL VOTE BY ROLL CALL IN COMMITTEE RESPONSIBLE"
    # )
    # resp_rollcall_exists = len(resp_rollcall_divs) > 0
    # resp_rollcall_html = "".join(str(div) for div in resp_rollcall_divs) if resp_rollcall_exists else ""

     # ---------------------------------------------------------------
    # 4. opinion procedure sections
    # ---------------------------------------------------------------
    # Important:
    # - "Opinion by" = verified opinion procedure table exists
    # - "Committee(s) asked for opinion(s)" = only requested, not verified
    # - "Not delivering opinions" = explicit no_op
    #
    # So we ONLY create opinion rows from tables that explicitly contain
    # an "Opinion by" row.
    #
    # We also REMOVE the fallback find_sections_by_header(..., "OPINION")
    # because that can match row text inside a table and jump to the wrong
    # next table (this is what breaks 2012/0364(COD)).

    opinion_committee_to_div: Dict[str, BeautifulSoup] = {}
    opinion_committee_order: List[str] = []

    def add_explicit_opinion_entries(div: BeautifulSoup) -> None:
        parsed = parse_procedure_table(div)
        codes = sorted(parsed["opinion_explicit"])
        for code in codes:
            up = code.upper()
            if up not in opinion_committee_to_div:
                opinion_committee_to_div[up] = div
                opinion_committee_order.append(up)

    # 1. best case: dedicated opinion sections
    opinion_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE ASKED FOR OPINION")
    for div in opinion_sections:
        add_explicit_opinion_entries(div)

    # 2. fallback: generic PROCEDURE tables
    # only keep those that explicitly contain an "Opinion by" row
    if not opinion_committee_to_div:
        generic_sections = find_sections_by_header(soup, "PROCEDURE")
        for div in generic_sections:
            add_explicit_opinion_entries(div)
    
    # # ---------------------------------------------------------------
    # # 4. opinion procedure sections
    # # ---------------------------------------------------------------
    # opinion_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE ASKED FOR OPINION")

    # if not opinion_sections:
    #     opinion_sections = find_sections_by_header(soup, "OPINION")

    # # as last fallback, inspect generic PROCEDURE blocks but only take
    # # those that explicitly contain 'Opinion by'
    # if not opinion_sections:
    #     generic_sections = find_sections_by_header(soup, "PROCEDURE")
    #     filtered = []
    #     for div in generic_sections:
    #         parsed = parse_procedure_table(div)
    #         if parsed["opinion_explicit"]:
    #             filtered.append(div)
    #     opinion_sections = filtered

    # # Build explicit opinion committee -> table mapping
    # opinion_committee_to_div: Dict[str, BeautifulSoup] = {}
    # opinion_committee_order: List[str] = []

    # for div in opinion_sections:
    #     parsed = parse_procedure_table(div)

    #     # Prefer explicit "Opinion by"
    #     codes = sorted(parsed["opinion_explicit"])

    #     # fallback inside opinion section itself: if no explicit "Opinion by",
    #     # but the section is clearly an opinion section and has requested committees
    #     if not codes:
    #         codes = sorted(parsed["opinion_requested"])

    #     for code in codes:
    #         up = code.upper()
    #         if up not in opinion_committee_to_div:
    #             opinion_committee_to_div[up] = div
    #             opinion_committee_order.append(up)

    # ---------------------------------------------------------------
    # 5. opinion roll-call tables
    # ---------------------------------------------------------------

    opinion_rollcall_sections = find_div_groups_after_header(
        soup,
        "FINAL VOTE BY ROLL CALL IN COMMITTEE ASKED FOR OPINION"
    )

    opinion_rollcall_map: Dict[str, str] = {}

    # correct case: one opinion rollcall section per opinion committee
    if len(opinion_rollcall_sections) == len(opinion_committee_order):
        for code, section_divs in zip(opinion_committee_order, opinion_rollcall_sections):
            opinion_rollcall_map[code] = "".join(str(div) for div in section_divs)

    # safe special case: only one opinion committee
    elif len(opinion_committee_order) == 1 and len(opinion_rollcall_sections) == 1:
        opinion_rollcall_map[opinion_committee_order[0]] = "".join(
            str(div) for div in opinion_rollcall_sections[0]
        )

    # otherwise ambiguous: better to leave blank than assign wrong HTML
    else:
        opinion_rollcall_map = {}

    # opinion_rollcall_divs = find_all_divs_after_header(
    #     soup,
    #     "FINAL VOTE BY ROLL CALL IN COMMITTEE ASKED FOR OPINION"
    # )
    # opinion_rollcall_count = len(opinion_rollcall_divs)

    # # Simple assignment strategy:
    # # - if counts match the number of explicit opinion committees, map by order
    # # - otherwise attach all opinion roll-call HTML to all opinion rows
    
    # # opinion_rollcall_map: Dict[str, str] = {}

    # # # clean 1-to-1 case
    # # if opinion_rollcall_count == len(opinion_committee_order):
    # #     for code, div in zip(opinion_committee_order, opinion_rollcall_divs):
    # #         opinion_rollcall_map[code] = str(div)

    # # # only one opinion committee -> safe to assign all opinion rollcall tables to it
    # # elif opinion_rollcall_count > 0 and len(opinion_committee_order) == 1:
    # #     combined = "".join(str(div) for div in opinion_rollcall_divs)
    # #     opinion_rollcall_map[opinion_committee_order[0]] = combined

    # # # otherwise ambiguous: do not assign
    # # else:
    # #     opinion_rollcall_map = {}
    
    # opinion_rollcall_map: Dict[str, str] = {}

    # if opinion_rollcall_count == len(opinion_committee_order):
    #     for code, div in zip(opinion_committee_order, opinion_rollcall_divs):
    #         opinion_rollcall_map[code] = str(div)
    # elif opinion_rollcall_count > 0:
    #     combined = "".join(str(div) for div in opinion_rollcall_divs)
    #     for code in opinion_committee_order:
    #         opinion_rollcall_map[code] = combined

    # ---------------------------------------------------------------
    # 6. build final committee universe
    # ---------------------------------------------------------------
    explicit_opinion_committees = set(opinion_committee_to_div.keys())

    # Real opinions:
    # only committees for which an opinion procedure table exists
    real_opinion_committees = explicit_opinion_committees.copy()

    # no_op committees:
    # committees explicitly marked as not delivering opinions
    no_op_committees = no_op_from_lead.copy()

    # clean overlaps
    real_opinion_committees -= no_op_committees
    no_op_committees -= set(lead_committees)

    # requested opinions that have neither an explicit opinion table nor no_op
    # are NOT emitted as opinion rows, because procedure table not verified.
    unresolved_requested = requested_opinions_from_lead - real_opinion_committees - no_op_committees

    rows = []

    # ---------------------------------------------------------------
    # 7. lead rows (supports dual lead committees)
    # ---------------------------------------------------------------
    if lead_committees:
        proc_html = str(resp_procedure_div) if resp_procedure_div else ""
        for committee in lead_committees:
            rows.append({
                "procedure": procedure_number,
                "committee": committee,
                "designation": "lead",
                "procedure_available": resp_procedure_div is not None,
                "rollcall_available": resp_rollcall_exists,
                "procedure_string": proc_html,
                "rollcall_string": resp_rollcall_html,
            })
    elif resp_procedure_div is not None:
        # fallback if a responsible procedure block exists but no committee code was parsed
        rows.append({
            "procedure": procedure_number,
            "committee": "UNKNOWN",
            "designation": "lead",
            "procedure_available": True,
            "rollcall_available": resp_rollcall_exists,
            "procedure_string": str(resp_procedure_div),
            "rollcall_string": resp_rollcall_html,
        })

    # ---------------------------------------------------------------
    # 8. opinion rows (only verified ones)
    # ---------------------------------------------------------------
    for committee in sorted(real_opinion_committees):
        proc_div = opinion_committee_to_div.get(committee)
        proc_html = str(proc_div) if proc_div else ""
        roll_html = opinion_rollcall_map.get(committee, "")
        rows.append({
            "procedure": procedure_number,
            "committee": committee,
            "designation": "opinion",
            "procedure_available": proc_div is not None,
            "rollcall_available": bool(roll_html),
            "procedure_string": proc_html,
            "rollcall_string": roll_html,
        })

    # ---------------------------------------------------------------
    # 9. no-op rows
    # ---------------------------------------------------------------
    # also include unresolved requested committees as no_op? No:
    # we only mark no_op if explicitly stated.
    for committee in sorted(no_op_committees):
        rows.append({
            "procedure": procedure_number,
            "committee": committee,
            "designation": "no_op",
            "procedure_available": False,
            "rollcall_available": False,
            "procedure_string": "",
            "rollcall_string": "",
        })

    # Optional: if you want visibility into ambiguous cases, uncomment this.
    # That would preserve committees that were requested for opinion but for
    # which neither a procedure table nor a "not delivering opinions" row was found.
    #
    # for committee in sorted(unresolved_requested):
    #     rows.append({
    #         "procedure": procedure_number,
    #         "committee": committee,
    #         "designation": "opinion_unverified",
    #         "procedure_available": False,
    #         "rollcall_available": False,
    #         "procedure_string": "",
    #         "rollcall_string": "",
    #     })

    return pd.DataFrame(rows)







# import requests
# from bs4 import BeautifulSoup
# import pandas as pd
# import re
# from typing import List, Optional, Union, Tuple

# # ---------- existing functions (unchanged, kept for reference) ----------
# def fetch_html(url: str) -> str:
#     response = requests.get(url)
#     response.raise_for_status()
#     return response.text

# def find_sections_by_header(soup: BeautifulSoup, header_text: str) -> List[BeautifulSoup]:
#     sections = []
#     pattern = re.compile(re.escape(header_text), re.IGNORECASE)
#     for elem in soup.find_all(string=pattern):
#         parent = elem.parent
#         while parent and parent.name not in ['h1','h2','h3','h4','h5','h6','p','div','section']:
#             parent = parent.parent
#         if not parent:
#             parent = elem.parent
#         next_div = parent.find_next('div', class_='table-responsive')
#         if next_div and next_div not in sections:
#             sections.append(next_div)
#     return sections

# def extract_committee_from_table(procedure_div: BeautifulSoup, label_texts: Union[str, List[str]]) -> Optional[str]:
#     if isinstance(label_texts, str):
#         label_texts = [label_texts]
#     table = procedure_div.find('table')
#     if not table:
#         return None
#     rows = table.find_all('tr')
#     for row in rows:
#         cells = row.find_all('td')
#         if len(cells) < 2:
#             continue
#         label = cells[0].get_text(strip=True)
#         if any(lt.lower() in label.lower() for lt in label_texts):
#             p = cells[1].find('p')
#             if p:
#                 return p.get_text(strip=True)
#             return cells[1].get_text(strip=True)
#     return None

# def count_rollcall_sections(soup: BeautifulSoup, header_text: str) -> int:
#     pattern = re.compile(re.escape(header_text), re.IGNORECASE)
#     return len(list(soup.find_all(string=pattern)))

# # ---------- new helper functions ----------
# def find_all_divs_after_header(soup: BeautifulSoup, header_text: str, class_name: str = 'table-responsive') -> List[BeautifulSoup]:
#     """
#     Find all divs with class `class_name` that appear after an element containing header_text.
#     Returns a list of those divs.
#     """
#     divs = []
#     pattern = re.compile(re.escape(header_text), re.IGNORECASE)
#     for elem in soup.find_all(string=pattern):
#         parent = elem.parent
#         while parent and parent.name not in ['h1','h2','h3','h4','h5','h6','p','div','section']:
#             parent = parent.parent
#         if not parent:
#             parent = elem.parent
#         # find all following divs with the given class
#         for sibling in parent.find_all_next('div', class_=class_name):
#             # stop if we hit another header? For simplicity we collect all until end of section.
#             # But the page structure is consistent: all such divs under the same heading belong to it.
#             if sibling not in divs:
#                 divs.append(sibling)
#     return divs

# def extract_committees_from_table(procedure_div: BeautifulSoup, label_texts: Union[str, List[str]]) -> List[str]:
#     """
#     Extract all committee codes from a procedure table.
#     Finds the row whose first cell contains any of the label_texts (case‑insensitive),
#     then collects the text from all subsequent cells (or their first paragraphs).
#     Returns a list of committee codes.
#     """
#     if isinstance(label_texts, str):
#         label_texts = [label_texts]
#     table = procedure_div.find('table')
#     if not table:
#         return []
#     rows = table.find_all('tr')
#     for row in rows:
#         cells = row.find_all('td')
#         if len(cells) < 2:
#             continue
#         label = cells[0].get_text(strip=True)
#         if any(lt.lower() in label.lower() for lt in label_texts):
#             committees = []
#             # start from cell 1 (index 1) because cell 0 is the label
#             for cell in cells[1:]:
#                 # committee code is usually in the first paragraph, otherwise whole cell text
#                 p = cell.find('p')
#                 text = p.get_text(strip=True) if p else cell.get_text(strip=True)
#                 if text:  # ignore empty cells
#                     committees.append(text)
#             return committees
#     return []

# # ---------- new main function ----------
# def get_committee_votes_with_html(url: str, procedure_number: str) -> pd.DataFrame:
#     """
#     Fetch the HTML from the given Europarl document URL and extract
#     information about responsible and opinion committees, including the
#     full HTML of the procedure and roll‑call tables.

#     Parameters
#     ----------
#     url : str
#         The URL of the document (e.g. https://www.europarl.europa.eu/doceo/document/...)
#     procedure_number : str
#         The procedure identifier, e.g. '2021/0366(COD)'

#     Returns
#     -------
#     pd.DataFrame
#         Columns: procedure, committee, designation, procedure_available,
#                  rollcall_available, procedure_string, rollcall_string
#     """
#     html = fetch_html(url)
#     soup = BeautifulSoup(html, 'html.parser')

#     # ----- Check for "document not in HTML" placeholder -----
#     placeholder = soup.select_one('div.card.mb-3 div.card-body p.bg-white.alert.alert-info.mb-3')
#     if placeholder and "This document does not exist in HTML but is available in the following formats:" in placeholder.get_text():
#         return pd.DataFrame([{
#             'procedure': procedure_number,
#             'committee': 'other format',
#             'designation': 'other format',
#             'procedure_available': False,
#             'rollcall_available': False,
#             'procedure_string': '',
#             'rollcall_string': ''
#         }])

#     # ---- Collect responsible committee and its procedure table ----
#     resp_procedure_div = None
#     resp_committee = None

#     # Try specific header first
#     resp_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE RESPONSIBLE")
#     for div in resp_sections:
#         code = extract_committee_from_table(div, "Committee responsible")
#         if code:
#             resp_committee = code
#             resp_procedure_div = div
#             break

#     # If not found, try generic "PROCEDURE"
#     if not resp_committee:
#         generic_sections = find_sections_by_header(soup, "PROCEDURE")
#         for div in generic_sections:
#             code = extract_committee_from_table(div, "Committee responsible")
#             if code:
#                 resp_committee = code
#                 resp_procedure_div = div
#                 break

#     # ---- Collect responsible roll‑call tables ----
#     resp_rollcall_divs = find_all_divs_after_header(soup, "FINAL VOTE BY ROLL CALL IN COMMITTEE RESPONSIBLE")
#     resp_rollcall_exists = len(resp_rollcall_divs) > 0

#     # ---- Collect opinion committees with their source tables ----
#     # We'll store tuples (committee_code, procedure_div)
#     opinion_entries = []

#     # 1. Sections with header "PROCEDURE – COMMITTEE ASKED FOR OPINION"
#     opinion_sections = find_sections_by_header(soup, "PROCEDURE – COMMITTEE ASKED FOR OPINION")
#     for div in opinion_sections:
#         codes = extract_committees_from_table(div, ["Opinion by", "Committee(s) asked for opinion(s)"])
#         for code in codes:
#             opinion_entries.append((code, div))

#     # 2. Sections with header "OPINION"
#     if not opinion_entries:
#         opinion_headers_sections = find_sections_by_header(soup, "OPINION")
#         for div in opinion_headers_sections:
#             codes = extract_committees_from_table(div, ["Opinion by", "Committee(s) asked for opinion(s)"])
#             for code in codes:
#                 opinion_entries.append((code, div))

#     # 3. Generic "PROCEDURE" sections (only if we haven't found any yet, and avoid duplicates)
#     if not opinion_entries:
#         generic_sections = find_sections_by_header(soup, "PROCEDURE")
#         existing = set()
#         for div in generic_sections:
#             codes = extract_committees_from_table(div, ["Opinion by", "Committee(s) asked for opinion(s)"])
#             for code in codes:
#                 if code.upper() not in existing:
#                     opinion_entries.append((code, div))
#                     existing.add(code.upper())

#     # ---- Collect opinion roll‑call tables ----
#     opinion_rollcall_divs = find_all_divs_after_header(soup, "FINAL VOTE BY ROLL CALL IN COMMITTEE ASKED FOR OPINION")
#     opinion_rollcall_count = len(opinion_rollcall_divs)

#     # ---- Build rows ----
#     rows = []

#     # Responsible committee row
#     if resp_committee:
#         proc_html = str(resp_procedure_div) if resp_procedure_div else ''
#         roll_html = ''.join(str(div) for div in resp_rollcall_divs) if resp_rollcall_exists else ''
#         rows.append({
#             'procedure': procedure_number,
#             'committee': resp_committee,
#             'designation': 'lead',
#             'procedure_available': resp_procedure_div is not None,
#             'rollcall_available': resp_rollcall_exists,
#             'procedure_string': proc_html,
#             'rollcall_string': roll_html
#         })
#     elif resp_sections:  # section exists but no committee code found
#         proc_html = str(resp_sections[0]) if resp_sections else ''
#         roll_html = ''.join(str(div) for div in resp_rollcall_divs) if resp_rollcall_exists else ''
#         rows.append({
#             'procedure': procedure_number,
#             'committee': 'UNKNOWN',
#             'designation': 'lead',
#             'procedure_available': True,
#             'rollcall_available': resp_rollcall_exists,
#             'procedure_string': proc_html,
#             'rollcall_string': roll_html
#         })

#     # Opinion committee rows
#     for i, (comm, proc_div) in enumerate(opinion_entries):
#         proc_html = str(proc_div) if proc_div else ''
#         # rollcall available only for the first `opinion_rollcall_count` committees
#         roll_avail = i < opinion_rollcall_count
#         roll_html = ''.join(str(div) for div in opinion_rollcall_divs) if roll_avail else ''
#         rows.append({
#             'procedure': procedure_number,
#             'committee': comm,
#             'designation': 'opinion',
#             'procedure_available': True,  # we have a procedure div
#             'rollcall_available': roll_avail,
#             'procedure_string': proc_html,
#             'rollcall_string': roll_html
#         })

#     return pd.DataFrame(rows)