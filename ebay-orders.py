""" ChatGPT instructions:
write me a python script to process a csv file using pandas.
Command line parameters to the script should be:
1) the name of input file
2) the name of output file.
The file column names are in second row; First row must be ignored
The script should do the following:

- rename column "Item Title" to "Title"
- rename column "Order Number" to "Order ID"
- rename column "Sold For" to "Price"
- rename column "Custom Label" to "SKU"
- rename column "Sale Date" to "Order Time"
- rename column "Shipping And Handling" to "Shipping"
- remove any row where "Item Number" is blank
- remove any columns other than "SKU", "Title", "Description", "Order Time", "Quantity", "Price", "Shipping", "Order ID"
- remove all any row where "Item Number" is blank
- write remaining data into output file
"""

import pandas as pd
import sys

def process_csv(input_file, output_file):
    # Read the CSV file, skipping the first row
    df = pd.read_csv(input_file, skiprows=[0])
    
    # Rename columns
    df = df.rename(columns={
        "Item Title": "Title",
        "Order Number": "Order ID",
        "Sold For": "Price",
        "Custom Label": "SKU",
        "Sale Date": "Order Time",
        "Shipping And Handling": "Shipping"
    })
    
    # Remove any row where "Item Number" is blank
    df = df.dropna(subset=["Item Number"])
    
    # Remove any columns other than specified
    columns_to_keep = ["SKU", "Title", "Order Time", "Quantity", "Price", "Shipping", "Order ID"]
    df = df[columns_to_keep]
    
    # Write the processed data to the output file
    df.to_csv(output_file, index=False)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python script.py <input_file> <output_file>")
    else:
        input_file = sys.argv[1]
        output_file = sys.argv[2]
        process_csv(input_file, output_file)
