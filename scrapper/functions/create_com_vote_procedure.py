"""
Functions to parse Europarl procedure table HTML into a long‑format DataFrame.
"""
from bs4 import BeautifulSoup
import pandas as pd
import re

def parse_procedure_table(html_str: str, committee_type: str = 'lead') -> list:
    """
    Parse the procedure table HTML and extract relevant rows as head-value pairs.
    Handles multi-line heads and multiple value cells.

    Parameters
    ----------
    html_str : str
        The HTML content of the div.table-responsive containing the procedure table.
    committee_type : str
        Either 'lead' or 'opinion'. Used for context, but not heavily used now.

    Returns
    -------
    list of dict
        Each dict has keys 'head' and 'value'.
    """
    soup = BeautifulSoup(html_str, 'html.parser')
    table = soup.find('table')
    if not table:
        return []

    rows = table.find_all('tr')
    extracted = []

    for tr in rows:
        cells = tr.find_all(['td', 'th'])
        if len(cells) < 2:
            continue

        # Head cell (first cell)
        head_cell = cells[0]
        head_text = head_cell.get_text('\n', strip=True)  # preserve line breaks
        # Split head by lines, ignore empty
        head_parts = [h.strip() for h in head_text.split('\n') if h.strip()]

        # Value cells (all after first)
        value_cells = cells[1:]

        # --- Special handling for result of final vote ---
        if any('result of final vote' in part.lower() for part in head_parts):
            symbols = []
            numbers = []
            # Collect lines from all value cells
            for cell in value_cells:
                cell_text = cell.get_text('\n', strip=True)
                lines = [ln.strip() for ln in cell_text.split('\n') if ln.strip()]
                for line in lines:
                    # Check if line is a symbol (maybe with colon)
                    if re.match(r'^[+\-–0]:?$', line):
                        sym = line.rstrip(':')
                        symbols.append(sym)
                    elif line.isdigit():
                        numbers.append(line)
                    # ignore any other content (should not happen)
            # Pair symbols and numbers in order
            for sym, num in zip(symbols, numbers):
                extracted.append({
                    'head': f'Result of final vote {sym}',
                    'value': num
                })
            continue

        # --- Special handling for members/substitutes (keep as one row) ---
        if any(key in head_text.lower() for key in ['members present', 'substitutes present']):
            all_text = ' '.join(cell.get_text(separator=' ', strip=True) for cell in value_cells)
            # Clean up multiple spaces, but keep names as a block
            all_text = re.sub(r'\s+', ' ', all_text).strip()
            extracted.append({'head': head_text, 'value': all_text})
            continue

        # --- General case: align head parts with value parts ---
        # Collect all text from value cells, each cell may contain multiple lines
        value_parts = []
        for cell in value_cells:
            cell_text = cell.get_text('\n', strip=True)
            parts = [p.strip() for p in cell_text.split('\n') if p.strip()]
            value_parts.extend(parts)

        # If number of head parts equals number of value parts, zip them
        if len(head_parts) == len(value_parts):
            for h, v in zip(head_parts, value_parts):
                extracted.append({'head': h, 'value': v})
        else:
            # Possible cases:
            # 1. One head part, multiple value parts (e.g., list of committees in separate cells)
            #    We'll treat each value part as a separate row with same head.
            if len(head_parts) == 1 and len(value_parts) > 1:
                for v in value_parts:
                    extracted.append({'head': head_parts[0], 'value': v})
            # 2. Multiple head parts, but value parts are grouped per cell (e.g., committees with dates)
            #    We need to pair head parts with groups of value parts from each cell.
            #    For example, head = ["Committee asked", "Date announced"] and each value cell contains two lines.
            #    We'll assume each value cell has as many lines as head_parts.
            elif len(head_parts) > 1:
                # Process each value cell separately
                for cell in value_cells:
                    cell_lines = cell.get_text('\n', strip=True).split('\n')
                    cell_lines = [ln.strip() for ln in cell_lines if ln.strip()]
                    if len(cell_lines) == len(head_parts):
                        for h, v in zip(head_parts, cell_lines):
                            extracted.append({'head': h, 'value': v})
                    else:
                        # fallback: treat whole cell as one value for each head? Not good.
                        # Instead, just join and give one row per head? We'll skip for now.
                        pass
            else:
                # Fallback: just join all value parts and assign to first head
                extracted.append({'head': head_parts[0] if head_parts else head_text,
                                  'value': ' '.join(value_parts)})

    return extracted


def expand_committee_procedure(df: pd.DataFrame) -> pd.DataFrame:
    """
    Takes the DataFrame from get_committee_votes_with_html and expands the procedure_string
    into a long-format table with columns: procedure, committee, designation, head, value.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: procedure, committee, designation, procedure_available, procedure_string.

    Returns
    -------
    pd.DataFrame
        Long-format table with extracted head-value pairs.
    """
    rows = []
    for _, row in df.iterrows():
        if not row['procedure_available']:
            continue
        html = row['procedure_string']
        if not html or pd.isna(html):
            continue
        # Determine committee type based on designation
        ctype = 'lead' if row['designation'] == 'lead' else 'opinion'
        extracted = parse_procedure_table(html, committee_type=ctype)
        for item in extracted:
            rows.append({
                'procedure': row['procedure'],
                'committee': row['committee'],
                'designation': row['designation'],
                'head': item['head'],
                'value': item['value']
            })
    return pd.DataFrame(rows)