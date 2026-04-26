import os
import sys
import pandas as pd
from playwright.sync_api import sync_playwright, Error as PlaywrightError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# Resolve project root and bld directory once
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(script_dir, ".."))
BLD = os.path.join(project_root, "bld")

# Create bld folder if it does not exist
os.makedirs(BLD, exist_ok=True)

# Load
input_path = os.path.join(BLD, "timeline_table.csv")
output_path = os.path.join(BLD, "timeline_table_eulex_link_check.csv")

print("=" * 80)
print("Starting example_with_prints.py")
print(f"Script directory: {script_dir}")
print(f"Project root: {project_root}")
print(f"BLD directory: {BLD}")
print(f"Input file: {input_path}")
print(f"Output file: {output_path}")
print("=" * 80)

df = pd.read_csv(input_path)
print(f"[Load] Loaded dataframe with {len(df)} rows and {len(df.columns)} columns.")

# Keep only rows where event contains "Final act published"
df1 = (
    df.loc[
        df["event"].str.contains(r"Final act published", case=False, na=False),
        ["procedure", "date", "event", "hyperlink"],
    ]
    .copy()
)
print(f"[Filter] Rows matching 'Final act published': {len(df1)}")

# Extract CELEX number from the hyperlink
df1["celex_number_raw"] = df1["hyperlink"].str.extract(r"numdoc=([A-Z0-9]+)")
df1["celex_number"] = df1["celex_number_raw"].str.extract(r"^(\d{5}[A-Z]\d{4})")
print(f"[Extract] Non-missing celex_number values: {df1['celex_number'].notna().sum()}")

# One row per procedure
df1 = (
    df1.sort_values(["procedure", "date"]) 
    .drop_duplicates(subset="procedure", keep="first")
    .reset_index(drop=True)
)
print(f"[Deduplicate] Unique procedures kept: {len(df1)}")

# Build Eur-Lex URL
df1["eurlex_url"] = df1["celex_number"].apply(
    lambda x: f"https://eur-lex.europa.eu/legal-content/EN/HIS/?uri=CELEX:{x}"
    if pd.notna(x)
    else None
)
print(f"[Build URL] Non-missing Eur-Lex URLs: {df1['eurlex_url'].notna().sum()}")


def classify_page(page, url):
    if pd.isna(url):
        print("[Page check] Missing URL -> missing_url")
        return "missing_url"

    print(f"[Page check] Visiting: {url}")

    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        html = page.content()
        final_url = page.url
        status = response.status if response else None

        if "AwsWafIntegration" in html or "challenge.js" in html or "token.awswaf.com" in html:
            print(f"[Page check] Result for {url}: waf_challenge")
            return "waf_challenge"

        # stronger existence check
        if status == 200 and ("CELEX:" in html or "legal-content" in final_url):
            print(f"[Page check] Result for {url}: reachable")
            return "reachable"

        if status is not None:
            result = f"http_{status}"
            print(f"[Page check] Result for {url}: {result}")
            return result

        print(f"[Page check] Result for {url}: unknown")
        return "unknown"

    except PlaywrightError as e:
        result = f"playwright_error: {str(e)[:120]}"
        print(f"[Page check] Result for {url}: {result}")
        return result
    except Exception as e:
        result = f"python_error: {str(e)[:120]}"
        print(f"[Page check] Result for {url}: {result}")
        return result


def main():
    results = []

    print("\n[Main] Launching Playwright browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="en-GB")
        page = context.new_page()

        total = len(df1)
        print(f"[Main] Starting page classification for {total} URLs...")

        for i, url in enumerate(df1["eurlex_url"], start=1):
            print(f"\n[Main] Processing {i}/{total}")
            results.append(classify_page(page, url))

        browser.close()
        print("\n[Main] Browser closed.")

    df1["browser_status"] = results
    print("[Main] browser_status column created.")
    # print(df1[["procedure", "celex_number", "browser_status"]])

    df1.to_csv(output_path, index=False)
    print(f"[Save] File written to: {output_path}")


if __name__ == "__main__":
    main()


