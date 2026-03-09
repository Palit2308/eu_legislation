import time
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import requests

def parse_transparency_table(table, section_type, base_domain):
    """
    Parse a single transparency table.
    section_type: 'special' (with Role, Committee) or 'regular' (without).
    Returns list of dicts.
    """
    rows = []
    tbody = table.find('tbody')
    if not tbody:
        return rows

    for tr in tbody.find_all('tr'):
        cells = tr.find_all(['th', 'td'])

        if section_type == 'special':
            if len(cells) < 5:
                continue
            name_cell, role_cell, committee_cell, date_cell, interest_cell = cells[:5]
        else:  # regular
            if len(cells) < 3:
                continue
            name_cell, date_cell, interest_cell = cells[:3]
            role_cell = committee_cell = None

        # ---- Name and MEP link ----
        name_link = name_cell.find('a')
        if name_link:
            mep_name = name_link.get_text(strip=True)
            mep_link = urljoin(base_domain, name_link['href'])
        else:
            mep_name = name_cell.get_text(strip=True)
            mep_link = ''

        # ---- Role (special only) ----
        role = role_cell.get_text(strip=True) if role_cell else ''

        # ---- Committee (special only) ----
        committee_code = ''
        committee_name = ''
        committee_link = ''
        if committee_cell:
            badge = committee_cell.find('a', class_='es_badge-committee')
            if badge:
                committee_code = badge.get_text(strip=True)
                committee_name = badge.get('title', '')
                committee_link = urljoin(base_domain, badge['href']) if badge.get('href') else ''
            else:
                committee_code = committee_cell.get_text(strip=True)

        # ---- Date ----
        date = date_cell.get_text(strip=True)

        # ---- Interest representatives (split by <br/>) ----
        interest_raw = interest_cell.get_text(separator='\n').strip()
        interest_list = [line.strip() for line in interest_raw.split('\n') if line.strip()]

        # Create one row per interest representative
        for interest in interest_list:
            row = {
                'name': mep_name,
                'member_link': mep_link,
                'role': role,
                'committee_code': committee_code,
                'committee_name': committee_name,
                'committee_link': committee_link,
                'date': date,
                'interest_representative': interest
            }
            rows.append(row)

    return rows

def fetch_all_pages(session, start_url, section_type, base_domain, referer_url, delay=0.5):
    """
    Fetch all pages starting from start_url until no more "Load more" button.
    Returns list of dicts.
    """
    all_rows = []
    next_url = start_url
    page_num = 1

    while next_url:
        print(f"  Fetching {section_type} page {page_num}: {next_url}")
        try:
            resp = session.get(next_url, headers={'Referer': referer_url})
            resp.raise_for_status()
        except Exception as e:
            print(f"    Error: {e}")
            break

        soup_page = BeautifulSoup(resp.text, 'html.parser')
        container = soup_page.find('div', class_='oeil-meetings-list-container')
        if not container:
            print("    No container found, stopping.")
            break

        table = container.find('table', class_='table-bordered')
        if table:
            rows = parse_transparency_table(table, section_type, base_domain)
            all_rows.extend(rows)
        else:
            print("    No table found, stopping.")
            break

        # Look for next "Load more" button
        load_more = container.find('button', class_='oei-loadmore-button')
        if load_more and load_more.has_attr('data-next-page-url'):
            next_url = urljoin(base_domain, load_more['data-next-page-url'])
            page_num += 1
            time.sleep(delay)
        else:
            next_url = None

    return all_rows