# ChatGPT prompt
# Create a python script to use squarespace api and delete a list of products from squarespace store. 
# - The script should accept a file name as command line argument. The file will contain a CSV-delimited list of product ids to delete. 
# - The script should accept an optional "dry" argument. If provided, the script should show the actions but not call any api
# Use pandas library to parse csv file.


import pandas as pd
import requests
import argparse
import sys

BASE_URL = "https://api.squarespace.com/1.0/commerce/products"
CLIENT_ID = "YOUR_CLIENT_ID"
CLIENT_SECRET = "YOUR_CLIENT_SECRET"

def delete_product(product_id, dry_run=False):
    if dry_run:
        print(f"Dry run: Would delete product with ID: {product_id}")
    else:
        url = f"{BASE_URL}/{product_id}"
        headers = {
            "Authorization": f"Bearer {CLIENT_ID} {CLIENT_SECRET}",
            "Content-Type": "application/json"
        }
        response = requests.delete(url, headers=headers)
        if response.status_code == 204:
            print(f"Deleted product with ID: {product_id}")
        else:
            print(f"Failed to delete product with ID: {product_id}. Status code: {response.status_code}")

def main(csv_file, dry_run=False):
    try:
        # Read CSV file into DataFrame
        df = pd.read_csv(csv_file)

        # Check if 'Product Ids' column exists
        if 'Product Ids' not in df.columns:
            raise ValueError("Error: 'Product Ids' column not found in the CSV file.")

        # Get list of product IDs
        product_ids = df['Product Ids'].tolist()

        # Delete products based on IDs
        for product_id in product_ids:
            delete_product(product_id, dry_run)
    except FileNotFoundError:
        print(f"Error: File '{csv_file}' not found.")
    except ValueError as ve:
        print(ve)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delete products from Squarespace store")
    parser.add_argument("csv_file", type=str, help="CSV file containing Product IDs to delete")
    parser.add_argument("--dry", action="store_true", help="Dry run mode to show actions but not execute API calls")
    args = parser.parse_args()

    main(args.csv_file, args.dry)
