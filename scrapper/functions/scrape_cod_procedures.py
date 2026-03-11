import requests
from bs4 import BeautifulSoup
import time
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def parse_search_results(html):
    """Extract reference, title, committees, rapporteur, stage, url."""
    soup = BeautifulSoup(html, 'html.parser')
    procedures = []
    for doc in soup.find_all('div', class_='es_document-wrapper'):
        proc = {}
        title_tag = doc.find('h3', class_='es_document-title')
        if title_tag:
            link = title_tag.find('a')
            if link and link.get('href'):
                proc['url'] = "https://oeil.europarl.europa.eu" + link['href']
                ref_match = re.search(r'reference=([^&]+)', link['href'])
                if ref_match:
                    proc['reference'] = ref_match.group(1)
            badges = title_tag.find_all('span', class_='es_badge-committee')
            if badges:
                proc['committees'] = ', '.join(b.get_text(strip=True) for b in badges)
            t_item = title_tag.find('span', class_='t-item')
            if t_item:
                text = t_item.get_text(separator=' ', strip=True)
                parts = text.split()
                if len(parts) >= 2 and re.match(r'^\*+[I]+$', parts[1]):
                    proc['stage'] = parts[1]
        body = doc.find('div', class_='es_document-body')
        if body:
            p = body.find('p')
            if p:
                proc['title'] = p.get_text(strip=True)
        rapporteur_div = doc.find('div', string=re.compile(r'Rapporteur\s*:'))
        if rapporteur_div:
            authors = rapporteur_div.find_all('span', class_='es_document-subtitle-author')
            if authors:
                proc['rapporteur'] = '; '.join(a.get_text(strip=True) for a in authors)
        if proc.get('reference') or proc.get('title'):
            procedures.append(proc)
    return procedures

def get_total_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    span = soup.find('span', class_='document-search-total-results-count')
    if span:
        return int(span.get_text(strip=True).replace(',', ''))
    return None

def fetch_page_with_retry(url, retries=3, delay=2):
    """Fetch a page, retrying on failure."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            procs = parse_search_results(resp.text)
            if procs:
                return procs, resp.text
            print(f"  (attempt {attempt+1} returned 0, retrying...)")
            time.sleep(delay * (attempt + 1))
        except Exception as e:
            print(f"  (attempt {attempt+1} failed: {e}, retrying...)")
            time.sleep(delay * (attempt + 1))
    return [], None

def fetch_all_procedures(procedure_type=8):
    """
    Fetch all procedures of a given type (default COD = 8).
    Returns list of procedure dicts, page statistics, and expected total.
    """
    all_procs = []
    page_stats = {}
    page = 1
    expected_total = None
    results_per_page = 30
    empty_streak = 0
    max_empty_pages = 3   # stop after this many consecutive empty pages
    max_pages = 200       # safety limit

    while page <= max_pages:
        url = f"https://oeil.europarl.europa.eu/oeil/en/search?fullText.mode=EXACT_WORD&pageIndex={page}&procedureType={procedure_type}"
        print(f"Fetching page {page}...", end=' ')

        # Get total from first page
        if page == 1:
            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                r.raise_for_status()
                expected_total = get_total_results(r.text)
                if expected_total:
                    print(f"Total results: {expected_total}")
                else:
                    print("Could not determine total.")
                first_procs = parse_search_results(r.text)
                all_procs.extend(first_procs)
                count = len(first_procs)
                page_stats[page] = count
                print(f"found {count} procedures")
                page += 1
                time.sleep(1)
                continue
            except Exception as e:
                print(f"Error on first page: {e}")
                break

        # Fetch subsequent pages with retry
        procs, html = fetch_page_with_retry(url, retries=3, delay=2)
        count = len(procs)
        page_stats[page] = count
        all_procs.extend(procs)
        print(f"found {count} procedures")

        # Stop condition: three consecutive empty pages
        if count == 0:
            empty_streak += 1
            if empty_streak >= max_empty_pages:
                print(f"{max_empty_pages} consecutive empty pages – stopping.")
                break
        else:
            empty_streak = 0

        page += 1
        time.sleep(1)

    return all_procs, page_stats, expected_total