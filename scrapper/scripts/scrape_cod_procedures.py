import sys
import os
import pandas as pd

# Add the parent directory to sys.path so that the 'functions' module can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from functions.scrape_cod_procedures import fetch_all_procedures

def main():
    print("Starting to fetch all COD procedures...")
    all_data, stats, expected = fetch_all_procedures(procedure_type=8)
    print(f"\nTotal COD procedures collected: {len(all_data)}")
    if expected:
        print(f"Expected total from website: {expected}")
        if len(all_data) != expected:
            print("⚠️  Discrepancy – see page stats above.")

    # Create DataFrame
    df_all = pd.DataFrame(all_data)
    # Reorder columns for clarity
    desired_order = ['reference', 'title', 'stage', 'committees', 'rapporteur', 'url']
    df_all = df_all[[col for col in desired_order if col in df_all.columns]]
    
    print(f"DataFrame shape: {df_all.shape}")
    print("\nFirst 5 rows:")
    print(df_all.head())

    # Determine project root (parent of the 'scripts' directory)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)  # Go up one level from scripts
    bld_dir = os.path.join(project_root, 'bld')
    os.makedirs(bld_dir, exist_ok=True)

    # Save CSV
    output_file = os.path.join(bld_dir, 'oeil_cod_procedures.csv')
    df_all.to_csv(output_file, index=False)
    print(f"\nData saved to {output_file}")

if __name__ == "__main__":
    main()


# the code fetches that the total number of cod procedures is 2903, because it scrapes that from the website. However in the website, there are only 95
# pages with 30 results and 96th page with 23 results. That is 2873 entries. 

# The json code for the scraped page shows that the 2903 is a number written as a string, not a sum. 

# https://oeil.europarl.europa.eu/oeil/en/search/facets?fullText.term=&fullText.mode=EXACT_WORD&reference.type=&term=&year=&procedureType=8&procedureStage=&rapporteurResponsible=&rapporteurOpinion=&committeeResponsible=&committeeOpinion=&politicalGroupResponsible=&politicalGroupForOpinion=&keyEventId=&forecastId=&plenaryActivityId=&epDocumentRoleId=&councilDgId=&commissionDgId=&commissionDocumentTypeId=&institutionId=&subject=&geographicalArea=&legalBaseId=&legislativeActTypeId=&session=

# {
#       "type": "tree",
#       "label": "Procedure type",
#       "name": "procedureType",
#       "hidden": false,
#       "valueMode": "grouped",
#       "availableValues": [
#         {
#           "type": "option",
#           "label": "All procedure types",
#           "value": "",
#           "selected": false
#         },
#         {
#           "type": "option",
#           "label": "COD - Ordinary legislative procedure (ex-codecision procedure) (2903)",
#           "value": "8",
#           "selected": true
#         }
#       ],
#       "multiple": false,
#       "disabled": false,
#       "showRefiner": false
#     },

# Rapporteur code is not working for some reason. But we collect that in the meta page anyway. But here somehow it is not working. 