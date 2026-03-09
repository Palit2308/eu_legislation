import sys
import os
import pandas as pd

# Add the parent directory to sys.path so that the 'functions' module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.scrape_landing_page import fetch_all_pages

def main():
    print("Starting to fetch all procedures...")
    all_data = fetch_all_pages()
    print(f"\nTotal procedures collected: {len(all_data)}")

    # Create DataFrame
    df_all = pd.DataFrame(all_data)
    print(f"DataFrame shape: {df_all.shape}")
    print("\nFirst 5 rows:")
    print(df_all.head())

    # Determine project root (parent of the 'scripts' directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)  # Go up one level from scripts
    bld_dir = os.path.join(project_root, 'bld')
    os.makedirs(bld_dir, exist_ok=True)

    # Save CSV
    output_file = os.path.join(bld_dir, 'oeil_all_procedures_landing_page.csv')
    df_all.to_csv(output_file, index=False)
    print(f"\nData saved to {output_file}")

if __name__ == "__main__":
    main()