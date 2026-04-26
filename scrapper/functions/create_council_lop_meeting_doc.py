import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import unquote, urljoin
import re
import numpy as np
import time
from seleniumbase import SB
import pymupdf  # PyMuPDF


BASE_URL = "https://www.consilium.europa.eu/en/meetings/"
BASE_DOMAIN = "https://www.consilium.europa.eu"


def get_council_config_df():
    url = "https://en.wikipedia.org/wiki/Council_of_the_European_Union"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Find the bold label "Configurations"
    config_title = soup.find("b", string="Configurations")

    # Move to the next div with class="hlist"
    hlist_div = config_title.find_parent("div").find_next("div", class_="hlist")

    # Top-level list items only
    top_ul = hlist_div.find("ul")
    top_lis = top_ul.find_all("li", recursive=False)

    rows = []
    for li in top_lis:
        a = li.find("a", href=True)
        if a and a["href"].startswith("/wiki/"):
            rows.append({
                "config": unquote(a["href"].split("/wiki/")[-1]),
                "code": a.get_text(strip=True)
            })

    council_config_df = pd.DataFrame(rows)
    council_config_df["code"] = council_config_df["code"].replace("ENVI", "ENV")

    return council_config_df


def normalize_text(x):
    if pd.isna(x):
        return ""
    x = str(x).lower()
    x = x.replace("_", " ")
    x = re.sub(r"\(.*?\)", "", x)          # remove things like (COMPET)
    x = re.sub(r"\bcouncil\b", "", x)      # remove the word 'council'
    x = re.sub(r"[^a-z0-9\s&]", " ", x)    # remove punctuation except &
    x = re.sub(r"\s+", " ", x).strip()
    return x


def build_config_lookup(council_config_df):
    # --- if needed, rename config column to council_config ---
    # only run this if your council_config_df still has column name "config"
    if "config" in council_config_df.columns:
        council_config_df = council_config_df.rename(columns={"config": "council_config"})

    config_lookup = council_config_df.copy()
    config_lookup["config_norm"] = config_lookup["council_config"].apply(normalize_text)
    return config_lookup


def match_council_config(council_configuration, config_lookup):
    target = normalize_text(council_configuration)
    if target == "":
        return pd.Series([pd.NA, pd.NA])

    # exact normalized match first
    exact = config_lookup[config_lookup["config_norm"] == target]
    if not exact.empty:
        row = exact.iloc[0]
        return pd.Series([row["council_config"], row["code"]])

    # containment either way
    contains = config_lookup[
        config_lookup["config_norm"].apply(
            lambda x: (x in target) or (target in x)
        )
    ]

    if not contains.empty:
        # pick the closest match by string length difference
        contains = contains.copy()
        contains["len_diff"] = contains["config_norm"].apply(lambda x: abs(len(x) - len(target)))
        row = contains.sort_values("len_diff").iloc[0]
        return pd.Series([row["council_config"], row["code"]])

    return pd.Series([pd.NA, pd.NA])


def create_council_lop_df1(council_meta, council_config_df):
    config_lookup = build_config_lookup(council_config_df)

    council_lop_df1 = council_meta.copy()

    council_lop_df1["date"] = pd.to_datetime(
        council_lop_df1["date"],
        format="%d/%m/%Y",
        errors="coerce"
    ).dt.strftime("%Y/%m/%d")

    # match canonical council config + code
    council_lop_df1[["council_config", "code"]] = council_lop_df1["council_configuration"].apply(
        lambda x: match_council_config(x, config_lookup)
    )

    # keep only required columns
    council_lop_df1 = council_lop_df1[["procedure", "date", "council_config", "code"]]

    return council_lop_df1


def build_meeting_link(code, date_value):
    """Build meeting link from code + date."""
    if pd.isna(code) or pd.isna(date_value):
        return np.nan

    code_str = str(code).strip().lower()

    # Parse date safely
    dt = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(dt):
        return np.nan

    return f"{BASE_URL}{code_str}/{dt.strftime('%Y/%m/%d')}/"


def page_looks_like_meeting(sb, url):
    try:
        sb.uc_open_with_reconnect(url, 6)
        time.sleep(2)

        current_url = sb.get_current_url().rstrip("/") + "/"
        expected_url = url.rstrip("/") + "/"

        page_source = sb.get_page_source().lower()
        page_title = sb.get_title().lower()

        if "404" in page_title or "page not found" in page_source:
            return False

        if current_url != expected_url:
            return False

        positive_signals = [
            "main results",
            "agenda",
            "press releases",
            "photos and videos",
            "meeting page",
        ]

        return any(signal in page_source for signal in positive_signals)

    except Exception as e:
        print(f"Error while checking {url}: {e}")
        return False


def create_df1(council_lop_df1):
    df = council_lop_df1.copy()

    df["meeting_link"] = df.apply(
        lambda row: build_meeting_link(row["code"], row["date"]),
        axis=1
    )

    # Initialize result column
    df["meeting_exists?"] = False

    with SB(uc=True, headless=False) as sb:
        for idx, row in df.iterrows():
            url = row["meeting_link"]

            if pd.isna(url):
                df.at[idx, "meeting_exists?"] = False
                continue

            exists = page_looks_like_meeting(sb, url)
            df.at[idx, "meeting_exists?"] = exists

            print(f"{idx} | {url} | exists={exists}")

            # Small pause between requests
            time.sleep(2)

    df1 = df[
        ["procedure", "date", "council_config", "code", "meeting_link", "meeting_exists?"]
    ].copy()

    return df1


def extract_lop_link(sb, meeting_url):
    """
    Open a meeting page with SeleniumBase and try to extract the
    'List of participants' PDF link from the 'Outcome documents' section.

    Returns
    -------
    (lop_exists, lop_link)
        lop_exists : bool
        lop_link   : str or np.nan
    """
    try:
        sb.uc_open_with_reconnect(meeting_url, 6)
        time.sleep(2)

        current_url = sb.get_current_url().rstrip("/") + "/"
        expected_url = meeting_url.rstrip("/") + "/"

        # If redirected away, treat as not found
        if current_url != expected_url:
            return False, np.nan

        html = sb.get_page_source()
        soup = BeautifulSoup(html, "html.parser")

        # First try: exact "Outcome documents" box
        info_boxes = soup.select("div.gsc-info-box")

        for box in info_boxes:
            title_el = box.select_one("h2, h3")
            if title_el:
                title_text = title_el.get_text(" ", strip=True).lower()
                if "outcome documents" in title_text:
                    for a in box.select("a[href]"):
                        link_text = a.get_text(" ", strip=True).lower()
                        if "list of participants" in link_text:
                            href = a.get("href")
                            full_link = urljoin(BASE_DOMAIN, href)
                            return True, full_link

        # Fallback: search the whole page
        for a in soup.select("a[href]"):
            link_text = a.get_text(" ", strip=True).lower()
            href = a.get("href", "")

            if "list of participants" in link_text:
                full_link = urljoin(BASE_DOMAIN, href)
                return True, full_link

        return False, np.nan

    except Exception as e:
        print(f"Error while extracting LOP from {meeting_url}: {e}")
        return False, np.nan


def add_lop_links(df1):
    df1 = df1.copy()

    # Initialize new columns
    df1["lop_exists"] = False
    df1["lop_link"] = None

    with SB(uc=True, headless=False) as sb:
        for idx, row in df1.iterrows():
            meeting_exists = row["meeting_exists?"]
            meeting_link = row["meeting_link"]

            # Skip rows where the meeting page doesn't exist
            if (not meeting_exists) or pd.isna(meeting_link):
                df1.at[idx, "lop_exists"] = False
                df1.at[idx, "lop_link"] = np.nan
                continue

            lop_exists, lop_link = extract_lop_link(sb, meeting_link)

            df1.at[idx, "lop_exists"] = lop_exists
            df1.at[idx, "lop_link"] = lop_link

            print(f"{idx} | lop_exists={lop_exists} | lop_link={lop_link}")

            time.sleep(2)

    return df1


def extract_pdf_text_with_seleniumbase(pdf_url, reconnect_time=6, wait_time=3):
    with SB(uc=True, headless=False) as sb:
        # 1) Normal browser navigation to the PDF URL
        sb.uc_open_with_reconnect(pdf_url, reconnect_time)
        time.sleep(wait_time)

        # If a challenge is still visible in your environment, uncomment this:
        # sb.uc_gui_click_captcha()
        # time.sleep(3)

        final_url = sb.get_current_url()

        # 2) Reuse the browser session cookies
        driver_cookies = sb.driver.get_cookies()
        user_agent = sb.execute_script("return navigator.userAgent;")

        session = requests.Session()
        session.headers.update({
            "User-Agent": user_agent,
            "Referer": final_url,
        })

        for cookie in driver_cookies:
            session.cookies.set(
                name=cookie["name"],
                value=cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

        # 3) Download the same PDF using the cleared browser session
        response = session.get(final_url, timeout=60)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").lower()
        if "pdf" not in content_type and not final_url.lower().endswith(".pdf"):
            raise ValueError(
                f"Did not receive a PDF. Final URL: {final_url} | Content-Type: {content_type}"
            )

        # 4) Extract text with PyMuPDF
        doc = pymupdf.open(stream=response.content, filetype="pdf")
        all_text = []

        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text", sort=True)
            all_text.append(f"\n--- PAGE {page_num} ---\n{text}")

        doc.close()
        return "\n".join(all_text)


def parse_lop_text_to_df(extracted_text, procedure):
    """
    Parse extracted plain text from a Council 'List of participants' PDF
    into a dataframe with columns:
    procedure, group, participant, role

    Rules:
    - Start at 'Belgium:'
    - Include everything up to 'Other participants:' if present
      (so Commission members are included, Other participants excluded)
    - Group = country name / Commission
    - Participant = left-side person line
    - Role = right-side text, including wrapped continuation lines
    """

    lines = extracted_text.splitlines()

    # Clean obvious junk but keep indentation structure
    cleaned_lines = []
    for line in lines:
        raw = line.rstrip("\n")
        stripped = raw.strip()

        if not stripped:
            cleaned_lines.append("")
            continue

        # remove page markers like --- PAGE 1 ---
        if re.match(r"^-+\s*PAGE\s+\d+\s*-+$", stripped, flags=re.I):
            continue

        # remove separator lines like ________
        if re.fullmatch(r"_+", stripped):
            continue

        cleaned_lines.append(raw.rstrip())

    # Find start at Belgium
    start_idx = None
    for i, line in enumerate(cleaned_lines):
        if line.strip() == "Belgium:":
            start_idx = i
            break

    if start_idx is None:
        raise ValueError("Could not find 'Belgium:' in the extracted text.")

    # Take everything from Belgium: until the end
    relevant_lines = cleaned_lines[start_idx:]

    records = []
    current_group = None
    current_participant = None
    current_role_parts = []

    def flush_current():
        nonlocal current_participant, current_role_parts
        if current_group is not None and current_participant is not None:
            role = " ".join(current_role_parts)
            role = re.sub(r"\s+", " ", role).strip()

            records.append({
                "procedure": procedure,
                "group": current_group,
                "participant": re.sub(r"\s+", " ", current_participant).strip(),
                "role": role
            })

        current_participant = None
        current_role_parts = []

    # titles that usually start a participant line
    participant_start_pattern = re.compile(
        r"^(Mr|Ms|Mrs|Miss|Mme|M\.|Dr|Prof)\b"
    )

    for raw_line in relevant_lines:
        stripped = raw_line.strip()

        if not stripped:
            continue

        # Group header like Belgium:, France:, Commission:
        if stripped.endswith(":") and not participant_start_pattern.match(stripped):
            flush_current()
            current_group = stripped[:-1]
            continue

        # New participant line
        if participant_start_pattern.match(stripped):
            flush_current()

            # Split participant vs role using long spaces from extracted text
            parts = re.split(r"\s{2,}", stripped, maxsplit=1)

            current_participant = parts[0].strip()

            if len(parts) > 1:
                current_role_parts = [parts[1].strip()]
            else:
                current_role_parts = []

            continue

        # Otherwise, continuation of the current role
        if current_participant is not None:
            current_role_parts.append(stripped)

    # flush last entry
    flush_current()

    df_lop = pd.DataFrame(records, columns=["procedure", "group", "participant", "role"])
    return df_lop


def create_df_lop(df1):
    all_dfs = []

    for idx, row in df1.iterrows():
        procedure = row["procedure"]
        lop_exists = row["lop_exists"]
        pdf_url = row["lop_link"]

        if not lop_exists or pd.isna(pdf_url):
            print(f"Skipping row {idx} | procedure={procedure} | no lop_link")
            continue

        try:
            print(f"Processing row {idx} | procedure={procedure}")
            print(f"PDF: {pdf_url}")

            pdf_text = extract_pdf_text_with_seleniumbase(pdf_url)
            temp_df = parse_lop_text_to_df(pdf_text, procedure)

            all_dfs.append(temp_df)

            print(f"Done row {idx} | extracted {len(temp_df)} participants")

        except Exception as e:
            print(f"Error on row {idx} | procedure={procedure} | {e}")

    if all_dfs:
        df_lop = pd.concat(all_dfs, ignore_index=True)
    else:
        df_lop = pd.DataFrame(columns=["procedure", "group", "participant", "role"])

    return df_lop