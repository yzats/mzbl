# ChatGPT instructions:
# write me a python script to process a csv file using pandas.
# Command line parameters to the script should be:
# 1) the name of input file
# 2) the name of output file.
# The script should do the following:

# - rename column "product_quantity" to "Quantity"
# - rename column "product_name" to "Title"
# - rename column "product_description" to "Description"
# - rename column "original_item_price" to "Price"
# - rename column "order_id" to "Order ID"
# - rename column "placed_at" to "Order Time"
# - add column "Shipping"
# - for each row, do the following:
#     1.   if the cell "cancelled_or_failed" has any text in it, delete the row
  
# - remove any columns other than   "sku", "Title", "Description", "Order Time", "Quantity", "Price", "Shipping", "Order ID"
# - write remaining data into output file
#
# ----------------------
# To execute:
# uv run --with pandas wnot-orders.py <in.csv> <out.csv>


import argparse
import sys

def process_csv(input_file, output_file):
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        if exc.name != "pandas":
            raise
        print(
            "Missing dependency: pandas\n"
            "Run this script with uv so it uses the project environment:\n"
            "  uv run --with pandas wnot-tools/wnot-orders.py <input_file> <output_file>",
            file=sys.stderr,
        )
        sys.exit(1)

    # Load the CSV file
    df = pd.read_csv(input_file)
    
    # Rename columns
    rename_dict = {
        "product_quantity": "Quantity",
        "product_name": "Title",
        "product_description": "Description",
        "original_item_price": "Price",
        "order_id": "Order ID",
        "placed_at": "Order Time",
    }
    df.rename(columns=rename_dict, inplace=True)
    
    # Add 'Shipping' column
    df["Shipping"] = ""
    
    # Remove rows where cancelled_or_failed has any text
    df = df[df["cancelled_or_failed"].isna()]
    
    # Keep only required columns
    required_columns = ["sku", "Title", "Description", "Order Time", "Quantity", "Price", "Shipping", "Order ID"]
    df = df[required_columns]
    
    # Save to output file
    df.to_csv(output_file, index=False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert a Whatnot orders CSV into the MZBL import format."
    )
    parser.add_argument("input_file", help="Path to the input CSV file")
    parser.add_argument("output_file", help="Path for the converted output CSV file")
    args = parser.parse_args()

    process_csv(args.input_file, args.output_file)
