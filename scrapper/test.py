import asyncio
import json
import os
import random
import re
import shutil
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

import nodriver as uc
from seleniumbase import SB


# =========================================================
# CONFIG
# =========================================================
BASE_URL = "https://www.consilium.europa.eu"

INPUT_FILE = "council_lop_df1.csv"
OUTPUT_FILE = "output.csv"

REQUEST_TIMEOUT = 20
HEADLESS = False   # Keep False for anti-bot / manual verification
DEBUG = True

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

STATE_DIR = Path("browser_state")
NODRIVER_PROFILE_DIR = STATE_DIR / "nodriver_profile"
SELENIUMBASE_PROFILE_DIR = STATE_DIR / "seleniumbase_uc_profile"
SESSION_MANIFEST_FILE = STATE_DIR / "session_manifest.json"

STATE_DIR.mkdir(parents=True, exist_ok=True)
NODRIVER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
SELENIUMBASE_PROFILE_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# SESSION MANIFEST
# Real persisted session = browser profile dirs
# JSON manifest just records metadata / one-time verification status
# =========================================================
def load_session_manifest():
    if SESSION_MANIFEST_FILE.exists():
        with open(SESSION_MANIFEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "nodriver_verified": False,
        "nodriver_verified_at": None,
        "nodriver_profile_dir": str(NODRIVER_PROFILE_DIR),
        "seleniumbase_verified": False,
        "seleniumbase_verified_at": None,
        "seleniumbase_profile_dir": str(SELENIUMBASE_PROFILE_DIR),
    }


def save_session_manifest(meta):
    with open(SESSION_MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


# =========================================================
# CHROME PATH / PROFILE UTILITIES
# =========================================================
def detect_chrome_executable():
    """
    Try to find Chrome/Chromium/Edge on Windows first.
    You can also override with environment variable CHROME_PATH.
    """
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    candidates = []

    # shutil.which
    for name in ["chrome", "chrome.exe", "msedge", "msedge.exe", "chromium", "chromium.exe"]:
        p = shutil.which(name)
        if p:
            candidates.append(p)

    # Common Windows locations
    env_keys = ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"]
    bases = [os.environ.get(k) for k in env_keys if os.environ.get(k)]

    suffixes = [
        r"Google\Chrome\Application\chrome.exe",
        r"Google\Chrome Beta\Application\chrome.exe",
        r"Google\Chrome Canary\Application\chrome.exe",
        r"Microsoft\Edge\Application\msedge.exe",
    ]

    for base in bases:
        for suffix in suffixes:
            candidate = os.path.join(base, suffix)
            if os.path.exists(candidate):
                candidates.append(candidate)

    # Deduplicate while preserving order
    seen = set()
    unique_candidates = []
    for c in candidates:
        norm = os.path.normpath(c)
        if norm not in seen:
            seen.add(norm)
            unique_candidates.append(norm)

    return unique_candidates[0] if unique_candidates else None


def remove_stale_profile_locks(profile_dir: Path):
    """
    Harmless cleanup for Chrome profile lock artifacts.
    """
    filenames = [
        "SingletonCookie",
        "SingletonLock",
        "SingletonSocket",
        "LOCK",
        "lockfile",
    ]
    for name in filenames:
        path = profile_dir / name
        if path.exists():
            try:
                if path.is_file() or path.is_symlink():
                    path.unlink()
            except Exception:
                pass


def backup_bad_profile(profile_dir: Path):
    """
    If Nodriver cannot attach, the profile may be in a bad state.
    Move it aside and recreate it.
    """
    if not profile_dir.exists():
        return

    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = profile_dir.parent / f"{profile_dir.name}_bad_{timestamp}"

    try:
        shutil.move(str(profile_dir), str(backup_dir))
    except Exception:
        # Fallback: try removing only if move fails
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass

    profile_dir.mkdir(parents=True, exist_ok=True)


# =========================================================
# LINK BUILDING
# =========================================================
def build_meeting_link(row):
    if pd.isna(row["code"]) or pd.isna(row["date"]):
        return pd.NA
    return f"{BASE_URL}/en/meetings/{str(row['code']).lower()}/{row['date']}/"


# =========================================================
# PARSING HELPERS
# =========================================================
def get_expected_date_from_meeting_url(url):
    if pd.isna(url):
        return pd.NaT

    m = re.search(r"/meetings/[^/]+/(\d{4})/(\d{2})/(\d{2})/?$", str(url))
    if not m:
        return pd.NaT

    y, mth, d = m.groups()
    return pd.to_datetime(f"{y}-{mth}-{d}", errors="coerce").normalize()


def parse_date_from_lop_candidate(text, href):
    text = "" if pd.isna(text) else str(text)
    href = "" if pd.isna(href) else str(href)
    combined = f"{text} {href}"

    for val in re.findall(r"(?<!\d)(\d{8})(?!\d)", combined):
        dt = pd.to_datetime(val, format="%Y%m%d", errors="coerce")
        if pd.notna(dt):
            return dt.normalize()

    for val in re.findall(r"(?<!\d)(\d{1,2}\.\d{1,2}\.\d{4})(?!\d)", combined):
        dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
        if pd.notna(dt):
            return dt.normalize()

    text_clean = text.replace(",", " ")
    for val in re.findall(r"(?<!\d)(\d{1,2}\s+[A-Za-z]+\s+\d{4})(?!\d)", text_clean):
        dt = pd.to_datetime(val, errors="coerce")
        if pd.notna(dt):
            return dt.normalize()

    return pd.NaT


def get_outcome_documents_box(soup):
    for box in soup.select("div.gsc-info-box"):
        title_el = box.find(["h1", "h2", "h3", "h4"])
        if title_el:
            title_text = title_el.get_text(" ", strip=True).lower()
            if "outcome documents" in title_text:
                return box

    for tag in soup.find_all(["div", "section"]):
        txt = tag.get_text(" ", strip=True).lower()
        if "outcome documents" in txt:
            return tag

    return None


def collect_lop_candidates(container, debug=False, label="container"):
    candidates = []

    if container is None:
        if debug:
            print(f"-> No {label} to scan")
        return candidates

    for a in container.find_all("a", href=True):
        link_text = a.get_text(" ", strip=True)
        href = a["href"]

        link_text_lower = link_text.lower()
        href_lower = href.lower()

        is_lop = (
            "list of participants" in link_text_lower
            or ("participants" in href_lower and href_lower.endswith(".pdf"))
            or ("presslist" in href_lower and href_lower.endswith(".pdf"))
        )

        if is_lop:
            full_url = urljoin(BASE_URL, href)
            parsed_date = parse_date_from_lop_candidate(link_text, href)

            candidates.append({
                "text": link_text,
                "href": href,
                "full_url": full_url,
                "parsed_date": parsed_date
            })

    if debug:
        print(f"-> {label} candidates found:", len(candidates))
        for c in candidates:
            print("   ", c["text"], "|", c["full_url"], "| parsed_date:", c["parsed_date"])

    return candidates


def choose_best_candidate(candidates, expected_date, debug=False):
    if len(candidates) == 0:
        return pd.NA

    if len(candidates) == 1:
        return candidates[0]["full_url"]

    if pd.notna(expected_date):
        exact_matches = [
            c for c in candidates
            if pd.notna(c["parsed_date"]) and c["parsed_date"].date() == expected_date.date()
        ]
        if debug:
            print("-> exact date matches:", len(exact_matches))
        if len(exact_matches) >= 1:
            return exact_matches[0]["full_url"]

    undated = [c for c in candidates if pd.isna(c["parsed_date"])]
    if len(undated) == 1:
        return undated[0]["full_url"]

    dated = [c for c in candidates if pd.notna(c["parsed_date"])]
    if len(dated) >= 1:
        if debug:
            print("-> fallback to first dated candidate")
        return dated[0]["full_url"]

    if debug:
        print("-> fallback to first candidate")
    return candidates[0]["full_url"]


def find_best_lop_link(soup, meeting_url, debug=False):
    expected_date = get_expected_date_from_meeting_url(meeting_url)
    if debug:
        print("-> Expected meeting date:", expected_date)

    outcome_box = get_outcome_documents_box(soup)

    if debug:
        if outcome_box is None:
            print("-> No dedicated Outcome documents box found")
        else:
            title_preview = outcome_box.get_text(" ", strip=True)[:200]
            print("-> Outcome box found. Preview:")
            print(title_preview)

    candidates = collect_lop_candidates(outcome_box, debug=debug, label="outcome_box")
    best = choose_best_candidate(candidates, expected_date, debug=debug)
    if pd.notna(best):
        return best

    if debug:
        print("-> Falling back to whole page search")
    all_candidates = collect_lop_candidates(soup, debug=debug, label="whole_page")
    best = choose_best_candidate(all_candidates, expected_date, debug=debug)
    if pd.notna(best):
        return best

    return pd.NA


# =========================================================
# PAGE TYPE HELPERS
# =========================================================
def extract_title_from_html(html):
    if not html:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def is_challenge_page(title, html):
    title_lower = title.lower() if title else ""
    html_lower = html.lower() if html else ""

    return (
        "just a moment" in title_lower
        or "browser check" in title_lower
        or "attention required" in title_lower
        or "cf-chl" in html_lower
        or "challenge-platform" in html_lower
        or "cf-turnstile" in html_lower
        or ("cloudflare" in html_lower and "verify you are human" in html_lower)
    )


def is_page_not_found(title, html, final_url=""):
    title_lower = title.lower() if title else ""
    html_lower = html.lower() if html else ""
    final_url_lower = final_url.lower() if final_url else ""

    return (
        "page not found" in title_lower
        or "404" in title_lower
        or "page not found" in html_lower
        or "/error/404" in final_url_lower
    )


def looks_like_real_meeting_page(final_url, html):
    if not final_url or not html:
        return False

    final_url_lower = final_url.lower()
    html_lower = html.lower()

    return (
        "/en/meetings/" in final_url_lower
        and (
            "outcome documents" in html_lower
            or "meeting files" in html_lower
            or "main results" in html_lower
        )
    )


# =========================================================
# REQUESTS FAST PATH
# =========================================================
def inspect_via_requests(url, session, debug=False):
    result = {
        "ok": False,
        "blocked_challenge": False,
        "not_found": False,
        "final_url": None,
        "title": "",
        "html": ""
    }

    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        html = r.text
        final_url = r.url
        title = extract_title_from_html(html)

        if debug:
            print("-> requests status:", r.status_code)
            print("-> requests final_url:", final_url)
            print("-> requests title:", title)

        result["final_url"] = final_url
        result["title"] = title
        result["html"] = html

        if is_challenge_page(title, html):
            result["blocked_challenge"] = True
            return result

        if r.status_code == 404 or is_page_not_found(title, html, final_url):
            result["not_found"] = True
            return result

        if r.status_code == 200 and looks_like_real_meeting_page(final_url, html):
            result["ok"] = True

        return result

    except Exception as e:
        if debug:
            print("-> requests error:", repr(e))
        return result


# =========================================================
# NODRIVER STARTUP / HELPERS
# =========================================================
async def maybe_await(obj):
    if asyncio.iscoroutine(obj):
        return await obj
    return obj


async def close_tab_safely(tab):
    if tab is None:
        return
    try:
        await maybe_await(tab.close())
    except Exception:
        pass


async def stop_browser_safely(browser):
    if browser is None:
        return
    try:
        await maybe_await(browser.stop())
    except Exception:
        pass


async def start_nodriver_once(profile_dir: Path, chrome_exe=None):
    remove_stale_profile_locks(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)

    kwargs = {
        "headless": HEADLESS,
        "user_data_dir": str(profile_dir),
        "sandbox": False,
        "lang": "en-US",
        "browser_args": [
            f"--user-agent={REQUEST_HEADERS['User-Agent']}",
            "--window-size=1400,900",
        ],
    }

    if chrome_exe:
        kwargs["browser_executable_path"] = chrome_exe

    browser = await uc.start(**kwargs)
    return browser


async def build_nodriver():
    """
    Robust startup:
    1) try saved persistent profile
    2) if that fails, back it up and create a fresh profile
    """
    chrome_exe = detect_chrome_executable()

    if DEBUG:
        print("-> detected chrome executable:", chrome_exe)

    first_error = None

    try:
        browser = await start_nodriver_once(NODRIVER_PROFILE_DIR, chrome_exe=chrome_exe)
        return browser
    except Exception as e:
        first_error = e
        if DEBUG:
            print("-> nodriver startup failed with persistent profile:", repr(e))

    # Backup possibly bad profile and retry fresh
    backup_bad_profile(NODRIVER_PROFILE_DIR)

    try:
        browser = await start_nodriver_once(NODRIVER_PROFILE_DIR, chrome_exe=chrome_exe)
        return browser
    except Exception as e2:
        if DEBUG:
            print("-> nodriver startup failed again after fresh profile:", repr(e2))

        raise RuntimeError(
            "Nodriver could not attach to Chrome. "
            "This usually means the chosen browser/profile could not expose a usable "
            "remote debugging session. "
            f"First error: {repr(first_error)} | Second error: {repr(e2)}"
        ) from e2


async def nodriver_click_by_text(tab, text, debug=False):
    try:
        el = await tab.find(text)
        if el:
            await maybe_await(el.click())
            if debug:
                print(f"-> nodriver clicked: {text}")
            await asyncio.sleep(1.0)
            return True
    except Exception:
        pass
    return False


async def nodriver_try_common_buttons(tab, debug=False):
    texts = [
        "Accept all cookies",
        "Accept all",
        "Accept",
        "I agree",
        "Agree",
        "Allow all",
        "Continue",
        "Proceed",
        "OK",
    ]
    clicked = False
    for txt in texts:
        ok = await nodriver_click_by_text(tab, txt, debug=debug)
        clicked = clicked or ok
    return clicked


async def nodriver_try_verification(tab, debug=False):
    """
    First try nodriver's cf_verify() if available.
    Then try text-based clicks.
    """
    tried_anything = False

    try:
        if hasattr(tab, "cf_verify"):
            await maybe_await(tab.cf_verify())
            tried_anything = True
            if debug:
                print("-> nodriver cf_verify() attempted")
            await asyncio.sleep(2.0)
    except Exception as e:
        if debug:
            print("-> nodriver cf_verify failed:", repr(e))

    texts = [
        "Verify",
        "Verify you are human",
        "I am human",
        "Continue",
        "Check",
    ]
    for txt in texts:
        ok = await nodriver_click_by_text(tab, txt, debug=debug)
        tried_anything = tried_anything or ok

    return tried_anything


async def inspect_via_nodriver(url, browser, session_meta, debug=False):
    result = {
        "ok": False,
        "blocked_challenge": False,
        "not_found": False,
        "final_url": url,
        "title": "",
        "html": ""
    }

    if browser is None:
        return result

    tab = None
    try:
        tab = await browser.get(url)
        await asyncio.sleep(2.5)

        try:
            await nodriver_try_common_buttons(tab, debug=debug)
        except Exception:
            pass

        await asyncio.sleep(1.0)

        html = await tab.get_content()
        title = extract_title_from_html(html)
        final_url = getattr(tab, "url", url) or url

        if debug:
            print("-> nodriver title:", title)
            print("-> nodriver final_url:", final_url)

        if is_challenge_page(title, html):
            if debug:
                print("-> nodriver detected challenge page")
            try:
                await nodriver_try_verification(tab, debug=debug)
                await asyncio.sleep(2.0)
                html = await tab.get_content()
                title = extract_title_from_html(html)
                final_url = getattr(tab, "url", url) or url
            except Exception:
                pass

        if is_challenge_page(title, html) and not session_meta.get("nodriver_verified", False):
            print("\nNodriver reached a verification page.")
            print("Complete the verification manually in the opened browser window.")
            input("After verification succeeds, press ENTER here to continue... ")

            session_meta["nodriver_verified"] = True
            session_meta["nodriver_verified_at"] = pd.Timestamp.utcnow().isoformat()
            save_session_manifest(session_meta)

            await asyncio.sleep(1.5)
            html = await tab.get_content()
            title = extract_title_from_html(html)
            final_url = getattr(tab, "url", url) or url

        result["title"] = title
        result["html"] = html
        result["final_url"] = final_url

        if is_challenge_page(title, html):
            result["blocked_challenge"] = True
            return result

        if is_page_not_found(title, html, final_url):
            result["not_found"] = True
            return result

        if looks_like_real_meeting_page(final_url, html):
            result["ok"] = True

        return result

    except Exception as e:
        if debug:
            print("-> nodriver inspect error:", repr(e))
        return result

    finally:
        await close_tab_safely(tab)


# =========================================================
# SELENIUMBASE FALLBACK
# =========================================================
def seleniumbase_try_common_buttons(sb, debug=False):
    selectors = [
        'button:contains("Accept all cookies")',
        'button:contains("Accept all")',
        'button:contains("Accept")',
        'button:contains("I agree")',
        'button:contains("Agree")',
        'button:contains("Allow all")',
        'button:contains("Continue")',
        'button:contains("Proceed")',
        'a:contains("Accept")',
        'a:contains("Continue")',
    ]

    clicked_any = False
    for sel in selectors:
        try:
            if sb.is_element_visible(sel):
                sb.click(sel)
                clicked_any = True
                if debug:
                    print(f"-> seleniumbase clicked: {sel}")
                sb.sleep(1)
        except Exception:
            pass

    return clicked_any


def inspect_via_seleniumbase(url, session_meta, debug=False):
    result = {
        "ok": False,
        "blocked_challenge": False,
        "not_found": False,
        "final_url": url,
        "title": "",
        "html": ""
    }

    try:
        with SB(
            uc=True,
            incognito=False,
            user_data_dir=str(SELENIUMBASE_PROFILE_DIR),
            test=False,
            headless=HEADLESS,
        ) as sb:
            sb.uc_open_with_reconnect(url, reconnect_time=4)
            sb.sleep(1.5)

            try:
                seleniumbase_try_common_buttons(sb, debug=debug)
            except Exception:
                pass

            try:
                sb.uc_gui_click_captcha()
                if debug:
                    print("-> seleniumbase uc_gui_click_captcha() attempted")
                sb.sleep(2)
            except Exception as e:
                if debug:
                    print("-> seleniumbase uc_gui_click_captcha failed:", repr(e))

            html = sb.driver.page_source
            title = sb.get_page_title()
            final_url = sb.driver.current_url

            if debug:
                print("-> seleniumbase title:", title)
                print("-> seleniumbase final_url:", final_url)

            if is_challenge_page(title, html) and not session_meta.get("seleniumbase_verified", False):
                print("\nSeleniumBase fallback reached a verification page.")
                print("You can solve it manually now.")
                print("When ready, SeleniumBase will continue after the breakpoint.")

                sb.uc_open_with_reconnect(url, reconnect_time="breakpoint")

                session_meta["seleniumbase_verified"] = True
                session_meta["seleniumbase_verified_at"] = pd.Timestamp.utcnow().isoformat()
                save_session_manifest(session_meta)

                sb.sleep(1.5)
                html = sb.driver.page_source
                title = sb.get_page_title()
                final_url = sb.driver.current_url

            result["title"] = title or ""
            result["html"] = html or ""
            result["final_url"] = final_url or url

            if is_challenge_page(title, html):
                result["blocked_challenge"] = True
                return result

            if is_page_not_found(title, html, final_url):
                result["not_found"] = True
                return result

            if looks_like_real_meeting_page(final_url, html):
                result["ok"] = True

            return result

    except Exception as e:
        if debug:
            print("-> seleniumbase error:", repr(e))
        return result


# =========================================================
# COMMON PIPELINE
# =========================================================
def build_result_from_html(html, final_url, status_detail, debug=False):
    soup = BeautifulSoup(html, "html.parser")
    lop_link = find_best_lop_link(soup, final_url, debug=debug)

    return {
        "meeting_exists?": "yes",
        "lop_exists?": "yes" if pd.notna(lop_link) else "no",
        "lop_pdf_link": lop_link,
        "status_detail": status_detail
    }


async def inspect_meeting_page(url, session, browser, session_meta, debug=False):
    result = {
        "meeting_exists?": "no",
        "lop_exists?": "no",
        "lop_pdf_link": pd.NA,
        "status_detail": "unverified"
    }

    if pd.isna(url):
        result["status_detail"] = "missing_url"
        return result

    if debug:
        print("\n" + "=" * 100)
        print("Checking:", url)

    # 1) Requests fast path
    req_res = inspect_via_requests(url, session, debug=debug)

    if req_res["ok"]:
        return build_result_from_html(
            req_res["html"],
            req_res["final_url"],
            "ok_requests",
            debug=debug
        )

    if req_res["not_found"]:
        result["status_detail"] = "not_found"
        return result

    # 2) Nodriver browser
    nd_res = await inspect_via_nodriver(url, browser, session_meta, debug=debug)

    if nd_res["ok"]:
        return build_result_from_html(
            nd_res["html"],
            nd_res["final_url"],
            "ok_nodriver",
            debug=debug
        )

    if nd_res["not_found"]:
        result["status_detail"] = "not_found"
        return result

    # 3) SeleniumBase fallback
    sb_res = inspect_via_seleniumbase(url, session_meta, debug=debug)

    if sb_res["ok"]:
        return build_result_from_html(
            sb_res["html"],
            sb_res["final_url"],
            "ok_seleniumbase",
            debug=debug
        )

    if sb_res["not_found"]:
        result["status_detail"] = "not_found"
        return result

    if req_res["blocked_challenge"] or nd_res["blocked_challenge"] or sb_res["blocked_challenge"]:
        result["status_detail"] = "blocked_challenge"
        return result

    result["status_detail"] = "unverified"
    return result


# =========================================================
# MAIN
# =========================================================
async def async_main():
    df = pd.read_csv(INPUT_FILE)
    df["meeting_link"] = df.apply(build_meeting_link, axis=1)

    unique_links = df["meeting_link"].dropna().unique()
    link_status = {}

    session_meta = load_session_manifest()

    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)

    browser = None

    # Try to build Nodriver, but don't crash the whole script if it fails.
    try:
        browser = await build_nodriver()
        if DEBUG:
            print("-> nodriver startup succeeded")
    except Exception as e:
        print("\nWARNING: Nodriver startup failed.")
        print("The script will continue with Requests + SeleniumBase fallback.")
        print("Nodriver error:", repr(e))

    # Optional warm-up
    if browser is not None:
        warm_tab = None
        try:
            warm_tab = await browser.get(f"{BASE_URL}/en/")
            await asyncio.sleep(2.0)
            await nodriver_try_common_buttons(warm_tab, debug=DEBUG)
            await asyncio.sleep(1.0)
        except Exception:
            pass
        finally:
            await close_tab_safely(warm_tab)

    try:
        for i, url in enumerate(unique_links, start=1):
            print(f"[{i}/{len(unique_links)}] {url}")

            link_status[url] = await inspect_meeting_page(
                url=url,
                session=session,
                browser=browser,
                session_meta=session_meta,
                debug=DEBUG
            )

            await asyncio.sleep(0.7 + random.random() * 0.8)

    finally:
        await stop_browser_safely(browser)

    df["meeting_exists?"] = df["meeting_link"].map(
        lambda x: link_status.get(x, {}).get("meeting_exists?", "no")
    )
    df["lop_exists?"] = df["meeting_link"].map(
        lambda x: link_status.get(x, {}).get("lop_exists?", "no")
    )
    df["lop_pdf_link"] = df["meeting_link"].map(
        lambda x: link_status.get(x, {}).get("lop_pdf_link", pd.NA)
    )
    df["status_detail"] = df["meeting_link"].map(
        lambda x: link_status.get(x, {}).get("status_detail", "unverified")
    )

    df.to_csv(OUTPUT_FILE, index=False)

    print("\nDone.")
    print(f"Saved: {OUTPUT_FILE}")
    print(df[[
        "procedure",
        "date",
        "code",
        "meeting_link",
        "meeting_exists?",
        "lop_exists?",
        "lop_pdf_link",
        "status_detail"
    ]].head(10))


if __name__ == "__main__":
    uc.loop().run_until_complete(async_main())