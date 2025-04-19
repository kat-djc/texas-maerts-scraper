import os
import pandas as pd
import glob

# Paths to the folders
county_dir = os.path.join("data", "regulated_entities_county")
zipcode_dir = os.path.join("data", "regulated_entities_zipcode")
output_path = os.path.join("data", "all_scraped_rns.csv")

# Get all CSV file paths
county_files = glob.glob(os.path.join(county_dir, "*.csv"))
zipcode_files = glob.glob(os.path.join(zipcode_dir, "*.csv"))
all_files = county_files + zipcode_files

rn_numbers = []

for file_path in all_files:
    try:
        df = pd.read_csv(file_path, dtype=str, encoding='utf-8', on_bad_lines='skip')
        df.columns = [col.strip() for col in df.columns]  # Clean column names
        rn_col = next((col for col in df.columns if 'RN' in col), None)
        if rn_col:
            rn_numbers.extend(df[rn_col].dropna().tolist())
    except Exception as e:
        print(f"Failed to process {file_path}: {e}")

# Create a DataFrame with unique RN numbers
rn_df = pd.DataFrame({'rn_number': pd.Series(rn_numbers).drop_duplicates().sort_values().reset_index(drop=True)})

# Save to CSV
os.makedirs(os.path.dirname(output_path), exist_ok=True)
rn_df.to_csv(output_path, index=False)
print(f"Saved {len(rn_df)} unique RN numbers to {output_path}")
