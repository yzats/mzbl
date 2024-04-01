""" ChatGPT recipe:
write me a python script to process a csv file. 
Command line parameters to the script should be:
1) the name of input file
2) the name of output file.
The script should do the following:

- rename column "Lineitem sku"  to "SKU"
- rename column "Lineitem quantity" to "Quantity"
- rename column "Lineitem name" to "Title"
- rename column "Lineitem price" to "Price"
- rename column "Created at" to "Order Time"
- add column "Description"
- remove any rows where value of "Lineitem fulfillment status" is equal to "cancelled"
- remove any columns other than  "SKU", "Title", "Description", "Order Time", "Quantity", "Price", "Shipping", "Order ID"
- write remaining data into output file
 """

import argparse
import pandas as pd

def process_csv(input_file, output_file):
    # Read the CSV file into a DataFrame
    df = pd.read_csv(input_file)

    # Rename columns
    df = df.rename(columns={
        "Lineitem sku": "SKU",
        "Lineitem quantity": "Quantity",
        "Lineitem name": "Title",
        "Lineitem price": "Price",
        "Created at": "Order Time"
    })

    # Add Description column
    df["Description"] = ""

    # Remove rows where Lineitem fulfillment status is "cancelled"
    df = df[df["Lineitem fulfillment status"] != "cancelled"]

    # Keep only specified columns
    columns_to_keep = ["SKU", "Title", "Description", "Order Time", "Quantity", "Price", "Shipping", "Order ID"]
    df = df[columns_to_keep]

    # Write remaining data to output file
    df.to_csv(output_file, index=False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process a CSV file")
    parser.add_argument("input_file", help="Input CSV file")
    parser.add_argument("output_file", help="Output CSV file")
    args = parser.parse_args()

    process_csv(args.input_file, args.output_file)

