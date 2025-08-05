import pandas as pd

# Replace 'your_file.csv' with the path to your CSV file
file_path = 'ebay-in.csv'

# Read the CSV file, skipping the first row
df = pd.read_csv(file_path, skiprows=[0])

# Output the column names, one per line
for column in df.columns:
    print(column)
 