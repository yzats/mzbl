
""" write me a python script to process a csv file using pandas.
Command line parameters to the script should be:
1) the name of input file
2) the name of output file.
The script should do the following:

- rename column "product quantity" to "Quantity"
- rename column "product name" to "Title"
- rename column "product description" to "Description"
- rename column "sold price" to "Price"
- rename column "order id" to "Order ID"
- rename column "placed at" to "Order Time"
- add column "Shipping"
- add column "SKU" 
- for each row, do the following:
    1.   if the cell "cancelled or failed" has any text in it, delete the row
    2. use regular expression `[A-Za-z]\d+$` to extract value from "Description" and assign it 
         to "SKU" . If there's no match, assign "SKU" a value of "***"
- remove any columns other than   "SKU", "Title", "Description", "Order Time", "Quantity", "Price", "Shipping", "Order ID"

- write remaining data into output file
"""

import pandas as pd
import sys
import re

def process_csv(input_file, output_file):
    # Read CSV
    df = pd.read_csv(input_file)

    # Rename columns
    df = df.rename(columns={
        "product quantity": "Quantity",
        "product name": "Title",
        "product description": "Description",
        "sold price": "Price",
        "order id": "Order ID",
        "placed at": "Order Time"
    })

    # Add columns
    df['Shipping'] = ''
    df['SKU'] = ''

    # Filter rows
    df = df[df['cancelled or failed'].isnull()]

    # Extract SKU
    df['SKU'] = df['Description'].str.extract(r'([A-Za-z]\d+$)').fillna('***')

    # Remove extra columns
    df = df[['SKU', 'Title', 'Description', 'Order Time', 'Quantity', 'Price', 'Shipping', 'Order ID']]

    # Write to output file
    df.to_csv(output_file, index=False)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python script.py input_file output_file")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    process_csv(input_file, output_file)
