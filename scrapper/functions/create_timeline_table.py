import pandas as pd
import requests
import os
import re
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup, NavigableString, Tag

def institution_from_event(event_text):
    """Determine the institution responsible for an event."""
    text = event_text.lower()
    if any(kw in text for kw in ['council', 'act adopted by council', 'council position', 'parliament\'s amendments rejected by council']):
        return 'Council of the EU'
    if any(kw in text for kw in ['commission', 'legislative proposal published', 'modified legislative proposal']):
        return 'European Commission'
    if 'conciliation committee' in text:
        return 'Conciliation Committee'
    return 'European Parliament'

def extract_final_act_link(soup, base_url):
    """
    Find the 'Final act' section and extract the first non‑PDF link.
    Returns absolute URL or None if not found.
    """
    # Use CSS selector to find any div with both classes
    sections = soup.select('div.erpl-product-content.oeil-spy-section')
    for section in sections:
        h2 = section.find('h2')
        if h2 and 'Final act' in h2.get_text():
            # Get all links in this section
            for a in section.find_all('a', href=True):
                href = a['href']
                # Skip the procedure PDF download link
                if '/oeil/en/procedure-file/pdf' not in href:
                    return urljoin(base_url, href)
    return None

def extract_key_events_detailed(soup, policy_ref, base_url):
    """
    Extract key events from the procedure page.
    Returns a list of dicts with keys:
        event_id, date, event, institution,
        reference (displayed text of the first link, or plain text if no link),
        hyperlink (URL of the first link, if any),
        summary_available (bool),
        summary_link (URL of summary, if any).
    """

    # Pre‑fetch final act link once (saves repeated parsing)
    final_act_link = extract_final_act_link(soup, base_url)

    events = []
    section = soup.find('div', id='section3')
    if not section:
        return events

    table = section.find('table', class_='table-bordered')
    if not table:
        return events

    tbody = table.find('tbody')
    if not tbody:
        return events

    event_rows = tbody.find_all('tr')
    for idx, tr in enumerate(event_rows, start=1):
        cells = tr.find_all('td')
        if len(cells) < 3:
            continue

        date_cell = cells[0]
        event_cell = cells[1]
        ref_cell = cells[2]
        summary_cell = cells[3] if len(cells) > 3 else None

        date = date_cell.get_text(strip=True)
        event_text = event_cell.get_text(strip=True)
        institution = institution_from_event(event_text)  # use the earlier function

        # ---- Reference cell ----
        # Find the first hyperlink (if any)
        first_a = ref_cell.find('a', href=True)
        if first_a:
            # Reference text: get the text of the link (or nested span)
            link_text = first_a.get_text(strip=True)
            if not link_text:
                span = first_a.find('span')
                link_text = span.get_text(strip=True) if span else ''
            hyperlink = urljoin(base_url, first_a['href'])
        else:
            # No link: use the entire text content of the cell as reference
            link_text = ref_cell.get_text(strip=True)
            hyperlink = ''

        # If link_text is empty, fall back to cell text
        if not link_text:
            link_text = ref_cell.get_text(strip=True)

        # ---- Summary ----
        summary_available = False
        summary_link = ''
        if summary_cell:
            summary_a = summary_cell.find('a', href=True)
            if summary_a:
                summary_available = True
                summary_link = urljoin(base_url, summary_a['href'])

        # ---- Override hyperlink for final act event ----
        if 'Final act published in Official Journal' in event_text and final_act_link:
            hyperlink = final_act_link
                
        events.append({
            'event_id': idx,
            'date': date,
            'event': event_text,
            'institution': institution,
            'reference': link_text,
            'hyperlink': hyperlink,
            'summary_available': summary_available,
            'summary_link': summary_link
        })

    return events

def extract_reference_items(cell, base_url):
    """
    Parse a reference cell and return a list of (reference_text, hyperlink) tuples.
    Merges a text element (plain text, <span>, or text anchor) with an immediately
    following icon link (anchor with no visible text). Line breaks separate distinct references.
    """
    items = []
    current_text = ''
    current_link = ''

    for child in cell.children:
        # ---- Line break: finalise current reference (if any) and reset ----
        if isinstance(child, Tag) and child.name == 'br':
            if current_text:
                items.append((current_text, current_link))
                current_text = ''
                current_link = ''
            continue

        # ---- Plain text node ----
        if isinstance(child, NavigableString):
            text = child.strip()
            if text:
                # If we already have text, this might be a new reference (rare) – better to finalise previous
                if current_text:
                    items.append((current_text, current_link))
                current_text = text
                current_link = ''
            continue

        # ---- Tag ----
        if isinstance(child, Tag):
            if child.name == 'span':
                text = child.get_text(strip=True)
                if text:
                    if current_text:
                        items.append((current_text, current_link))
                    current_text = text
                    current_link = ''
            elif child.name == 'a':
                link_text = child.get_text(strip=True)
                href = child.get('href')
                # Determine if this is an icon link (no visible text)
                if link_text:
                    # Text anchor – start a new reference
                    if current_text:
                        items.append((current_text, current_link))
                    current_text = link_text
                    current_link = urljoin(base_url, href) if href else ''
                else:
                    # Icon link – should attach to the previous text (if any)
                    if current_text and not current_link:
                        current_link = urljoin(base_url, href) if href else ''
                    else:
                        # No preceding text? treat as separate empty reference (fallback)
                        items.append(('', urljoin(base_url, href) if href else ''))
            else:
                # Any other tag – treat its text as a plain reference (fallback)
                text = child.get_text(strip=True)
                if text:
                    if current_text:
                        items.append((current_text, current_link))
                    current_text = text
                    current_link = ''

    # Finalise any remaining reference
    if current_text:
        items.append((current_text, current_link))
    elif current_link:
        # Should not happen, but just in case
        items.append(('', current_link))

    return items

def extract_documentation_gateway(soup, base_url):
    """
    Extract all documents from the "Documentation gateway" section.
    Returns a list of dicts with keys:
        institution,
        event (combined document_type and committee/parliament name),
        reference,
        hyperlink (if any),
        date,
        summary_available (bool),
        summary_link (if any)
    """
    docs = []
    section = soup.find('div', id='section6')
    if not section:
        return docs

    accordion = section.find('ul', class_='a-i')
    if not accordion:
        return docs

    for item in accordion.find_all('li', class_='es_accordion-item'):
        # ---- Institution name (from accordion button) ----
        button = item.find('button')
        if not button:
            continue
        inst_span = button.find('span', class_='t-x')
        institution = inst_span.get_text(strip=True) if inst_span else 'Unknown'

        content_div = item.find('div', class_='es_accordion-item-content')
        if not content_div:
            continue

        table = content_div.find('table', class_='table-bordered')
        if not table:
            continue

        thead = table.find('thead')
        tbody = table.find('tbody')
        if not thead or not tbody:
            continue

        headers = [th.get_text(strip=True) for th in thead.find_all('th')]

        for tr in tbody.find_all('tr'):
            cells = tr.find_all(['th', 'td'])
            if len(cells) < len(headers):
                continue

            row_meta = {}
            summary_available = False
            summary_link = ''

            # Identify the column indices for special fields
            ref_idx = None
            summary_idx = None
            doc_type_idx = None
            committee_idx = None
            parliament_idx = None
            inst_body_idx = None

            for i, header in enumerate(headers):
                if header == 'Reference':
                    ref_idx = i
                elif header == 'Summary':
                    summary_idx = i
                elif header == 'Document type':
                    doc_type_idx = i
                elif header == 'Committee':
                    committee_idx = i
                elif header == 'Parliament/Chamber':
                    parliament_idx = i
                elif header == 'Institution/body':
                    inst_body_idx = i

            # Process each cell according to its role
            for i, cell in enumerate(cells):
                if i == ref_idx:
                    ref_cell = cell
                elif i == summary_idx:
                    summary_a = cell.find('a', href=True)
                    if summary_a:
                        summary_available = True
                        summary_link = urljoin(base_url, summary_a['href'])
                elif i == doc_type_idx:
                    # Document type – store as 'document_type'
                    row_meta['document_type'] = cell.get_text(strip=True)
                elif i == committee_idx:
                    # Committee – store descriptive name from badge title if available
                    badge = cell.find('span', class_='es_badge-committee')
                    if badge and badge.has_attr('title'):
                        row_meta['committee'] = badge['title']
                    else:
                        row_meta['committee'] = cell.get_text(strip=True)
                elif i == parliament_idx:
                    # Parliament/Chamber – store descriptive name from badge title
                    badge = cell.find('span', class_='es_badge-committee')
                    if badge and badge.has_attr('title'):
                        row_meta['parliament'] = badge['title']
                    else:
                        row_meta['parliament'] = cell.get_text(strip=True)
                elif i == inst_body_idx:
                    # Institution/body – store as 'institution_body'
                    row_meta['institution_body'] = cell.get_text(strip=True)
                else:
                    # Any other column – store with normalised key (lowercase, underscores)
                    field = re.sub(r'\s+', '_', header.lower())
                    # Special handling for date columns: ensure they are stored as 'date'
                    if 'date' in header.lower():
                        field = 'date'
                    row_meta[field] = cell.get_text(strip=True)

                # Fallback: if no 'date' key yet, try to find any column with 'date' in its header
            if 'date' not in row_meta:
                for i, header in enumerate(headers):
                    if 'date' in header.lower():
                        row_meta['date'] = cells[i].get_text(strip=True)
                        break

            # ---- Build event description ----
            doc_type = row_meta.get('document_type', '')

            # Priority: 1) parliament name + document_type, 2) committee + document_type, 3) institution_body + document_type, 4) just document_type
            if 'parliament' in row_meta:
                event_description = f"{row_meta['parliament']} {doc_type}".strip()
            elif 'committee' in row_meta:
                event_description = f"{row_meta['committee']} {doc_type}".strip()
            elif 'institution_body' in row_meta:
                event_description = f"{row_meta['institution_body']} {doc_type}".strip()
            else:
                event_description = doc_type

            # ---- Process reference cell ----
            ref_items = extract_reference_items(ref_cell, base_url)

            for ref_text, hyperlink in ref_items:
                doc = {
                    'institution': institution,
                    'event': event_description,
                    'reference': ref_text,
                    'hyperlink': hyperlink,
                    'date': row_meta.get('date', ''),
                    'summary_available': summary_available,
                    'summary_link': summary_link
                }
                docs.append(doc)

    return docs

def create_timeline_simple(df_events, df_docs):
    """
    Concatenate events and documents, sort by date, and remove duplicate rows
    that share the same non‑empty reference (keeping the first occurrence).
    Returns a DataFrame with a new sequential event_id.
    """
    # Ensure both DataFrames have the same columns
    # (df_docs already has 'event' instead of separate document_type/committee)
    common_cols = ['date', 'institution', 'event', 'reference', 'hyperlink',
                   'summary_available', 'summary_link']
    df_events = df_events[common_cols].copy()
    df_docs = df_docs[common_cols].copy()

    # Add source marker (optional, for debugging)
    df_events['_src'] = 'event'
    df_docs['_src'] = 'document'

    # Concatenate
    df_timeline = pd.concat([df_events, df_docs], ignore_index=True)

    # Convert date to datetime for proper sorting
    df_timeline['date_parsed'] = pd.to_datetime(df_timeline['date'], format='%d/%m/%Y', errors='coerce')
    df_timeline = df_timeline.sort_values('date_parsed').reset_index(drop=True)
    df_timeline.drop(columns=['date_parsed'], inplace=True)

    # # Remove duplicates based on (link, reference) where reference is non-empty
    # df_timeline['event_norm'] = df_timeline['event'].str.strip()
    # mask_nonempty = df_timeline['reference'].str.strip().astype(bool)
    # df_dedup = df_timeline[mask_nonempty].drop_duplicates(subset=['event_norm', 'reference'], keep='first')
    # df_timeline = pd.concat([df_dedup, df_timeline[~mask_nonempty]], ignore_index=True).drop(columns=['event_norm'], errors='ignore')

    # Re‑sort after deduplication (just in case)
    df_timeline['date_parsed'] = pd.to_datetime(df_timeline['date'], format='%d/%m/%Y', errors='coerce')
    df_timeline = df_timeline.sort_values('date_parsed').reset_index(drop=True)
    df_timeline.drop(columns=['date_parsed'], inplace=True)

    # Add sequential event_id
    df_timeline.insert(0, 'event_id', range(1, len(df_timeline) + 1))

    # Optionally drop the _src column
    if '_src' in df_timeline.columns:
        df_timeline.drop(columns=['_src'], inplace=True)

    return df_timeline