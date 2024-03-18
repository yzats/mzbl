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
- add column "Description"
- remove any rows where value of "Lineitem fulfillment status" is equal to "cancelled"
- remove any columns other than  "Order ID", "SKU", "Title", "Description", "Quantity", "Price", "Shipping"
- write remaining data into output file
 """

import pandas as pd
import sys

def process_csv(input_file, output_file):
    # Read the CSV file
    df = pd.read_csv(input_file)

    # Rename columns
    df.rename(columns={'Lineitem sku': 'SKU',
                       'Lineitem quantity': 'Quantity',
                       'Lineitem name': 'Title',
                       'Lineitem price': 'Price'}, inplace=True)

    # Add Description column
    df['Description'] = ''

    # Remove rows where "Lineitem fulfillment status" is "cancelled"
    df = df[df['Lineitem fulfillment status'] != 'cancelled']

    # Remove unnecessary columns
    columns_to_keep = ['Order ID', 'SKU', 'Title', 'Description', 'Quantity', 'Price', 'Shipping']
    df = df[columns_to_keep]

    # Write to output file
    df.to_csv(output_file, index=False)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python script.py input_file output_file")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    process_csv(input_file, output_file)
