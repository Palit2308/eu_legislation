import pandas as pd
import re
import os

# ------------------------------
# Configuration
# ------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
BLD = os.path.join(project_root, 'bld')

input_file = os.path.join(BLD, 'meta_table.csv')
output_file = os.path.join(BLD, 'wide_meta.csv')

# ------------------------------
# Read long format
# ------------------------------
df = pd.read_csv(input_file)

# ------------------------------
# Create base meta column by stripping trailing numeric index
# ------------------------------
def strip_index(meta):
    # Remove trailing _digits (e.g., _1, _12) from the end
    return re.sub(r'_\d+$', '', meta)

df['base_meta'] = df['meta_column'].apply(strip_index)

# ------------------------------
# Group by procedure and base_meta, concatenate values
# ------------------------------
grouped = df.groupby(['year', 'procedure', 'base_meta'], as_index=False)['value'].agg(
    lambda x: ', '.join(x.dropna().astype(str))
)

# ------------------------------
# Pivot to wide format – temporarily rename index to avoid conflict
# ------------------------------
pivoted = grouped.pivot(index=['procedure'], columns='base_meta', values='value')

# Rename index levels so they won't clash with any column created by pivot
pivoted.index.names = ['procedure_idx']

# Reset index to turn them into columns
wide = pivoted.reset_index()

# Restore original column names
wide = wide.rename(columns={'procedure_idx': 'procedure'})

# Remove the columns attribute name (if any)
wide.columns.name = None

# ------------------------------
# Save
# ------------------------------
wide.to_csv(output_file, index=False)
print(f"Wide table saved to: {output_file}")
print(f"Shape: {wide.shape}")