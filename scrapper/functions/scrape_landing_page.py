import requests
from bs4 import BeautifulSoup
import time
import re

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

def parse_search_results(html):
    """Extract all available information from search page HTML"""
    soup = BeautifulSoup(html, 'html.parser')
    procedures = []
    
    for doc in soup.find_all('div', class_='es_document-wrapper'):
        proc = {}
        
        # Find the main title/header area
        title_tag = doc.find('h3', class_='es_document-title')
        if title_tag:
            link_tag = title_tag.find('a')
            if link_tag:
                proc['url'] = "https://oeil.europarl.europa.eu" + link_tag['href']
                # Extract reference from URL
                match = re.search(r'reference=([^&]+)', link_tag['href'])
                if match:
                    proc['reference'] = match.group(1)
            
            # Extract committees from badges inside the title
            committees = []
            badge_spans = title_tag.find_all('span', class_='es_badge-committee')
            for badge in badge_spans:
                committees.append(badge.get_text(strip=True))
            if committees:
                proc['committees'] = ', '.join(committees)
        
        # Get the title text
        body = doc.find('div', class_='es_document-body')
        if body:
            title_p = body.find('p')
            if title_p:
                proc['title'] = title_p.get_text(strip=True)
        
        # Extract rapporteur(s) - improved
        rapporteur_div = doc.find('div', class_='es_document-subtitle', 
                                string=lambda text: text and 'Rapporteur' in text)
        if rapporteur_div:
            # Find all author spans
            author_spans = rapporteur_div.find_all('span', class_='es_document-subtitle-author')
            rapporteurs = [span.get_text(strip=True) for span in author_spans]
            if rapporteurs:
                proc['rapporteur'] = '; '.join(rapporteurs)
        
        # Only add if we found something
        if proc:
            procedures.append(proc)
    
    return procedures

def get_total_results_from_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    total_span = soup.find('span', class_='document-search-total-results-count')
    if total_span:
        # Remove commas and convert to int
        total_text = total_span.get_text(strip=True).replace(',', '')
        return int(total_text)
    return None

def fetch_all_pages():
    all_procedures = []
    page = 1
    results_per_page = 30
    
    # First, fetch page 1 to get total
    first_url = f"https://oeil.europarl.europa.eu/oeil/en/search?fullText.mode=EXACT_WORD&pageIndex=1"
    print("Fetching first page to get total...")
    response = requests.get(first_url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    
    total_results = get_total_results_from_page(response.text)
    if total_results is None:
        print("Could not find total results count. Using hardcoded 22062.")
        total_results = 22062
    
    total_pages = (total_results + results_per_page - 1) // results_per_page
    print(f"Total results: {total_results}, total pages: {total_pages}")
    
    # Parse first page
    first_page_results = parse_search_results(response.text)
    all_procedures.extend(first_page_results)
    print(f"  Page 1: found {len(first_page_results)} procedures")
    
    # Loop for remaining pages
    page = 2
    while page <= total_pages:
        print(f"Fetching page {page}/{total_pages}...")
        url = f"https://oeil.europarl.europa.eu/oeil/en/search?fullText.mode=EXACT_WORD&pageIndex={page}"
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            
            page_results = parse_search_results(response.text)
            all_procedures.extend(page_results)
            
            print(f"  Found {len(page_results)} procedures on this page")
            
            page += 1
            time.sleep(1)
            
        except Exception as e:
            print(f"Error on page {page}: {e}")
            break
    
    return all_procedures