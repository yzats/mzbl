# Squarespace Stock Remover

A Python script to set stock levels to 0 for products listed in a CSV file on Squarespace.

## Features

- **CSV Input**: Process SKUs from a CSV file (single column, optional "SKU" header)
- **Smart Detection**: Skips products already at 0 stock
- **Dry Run Mode**: Preview changes without modifying Squarespace
- **Rate Limiting**: Respects API rate limits using shared library
- **Caching**: Uses cached inventory to reduce API calls
- **Detailed Reporting**: Comprehensive summary of all operations
- **Logging**: Outputs to both console and log file

## Prerequisites

1. Python 3.7 or higher
2. Squarespace API credentials
3. `sqs_shared` library (in parent directory)
4. Configuration file (in parent directory)

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Make sure config.py exists in parent directory with your API credentials
```

## Configuration

The script uses `config.py` from the parent directory (`/Users/yzats/devl/mzbl/config.py`) which should contain:

```python
# Inventory API key - needs read/write access to Inventory API and read access to Products API
SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY = "your-inventory-api-key-here"

SQUARESPACE_SITE_ID = "your-site-id"
REQUESTS_PER_MINUTE = 300
```

**Note:** The script uses `SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY` which needs:
- Read access to Products API (to fetch product data)
- Read/Write access to Inventory API (to update stock levels)

## CSV File Format

The script supports two CSV formats:

### Format 1: Single Column (No Header)

A simple list of SKUs with no header:

```csv
ABC123
XYZ456
DEF789
```

### Format 2: Multi-Column with SKU Header

A CSV file with multiple columns where one column is named "SKU" (case-insensitive):

```csv
SKU,Product Name,Price,Quantity
ABC123,Widget A,29.99,10
XYZ456,Widget B,39.99,5
DEF789,Widget C,49.99,0
```

Or with SKU in a different column position:

```csv
ID,Name,SKU,Category
1,Widget A,ABC123,Electronics
2,Widget B,XYZ456,Home
3,Widget C,DEF789,Garden
```

**Note:** The script automatically detects which format is being used and will search for a column named "SKU" (case-insensitive). If found, it uses that column. If not found, it uses the first column.

## Usage

### Basic Usage

Set stock to 0 for all SKUs in a CSV file:

```bash
python sqs_stock_remover.py --csv skus.csv
```

### Dry Run Mode

Preview what would be changed without making any modifications:

```bash
python sqs_stock_remover.py --csv skus.csv --dry-run
```

### Force Refresh Inventory

Force download fresh inventory from Squarespace (bypass cache):

```bash
python sqs_stock_remover.py --csv skus.csv --force-refresh
```

### Custom Log File

Specify a custom log file location:

```bash
python sqs_stock_remover.py --csv skus.csv --log my_log.log
```

### Combined Options

```bash
python sqs_stock_remover.py --csv skus.csv --dry-run --force-refresh --log test.log
```

## Command Line Arguments

- `--csv`, `-c` (required): Path to CSV file containing SKUs
- `--dry-run`, `-d`: Preview mode - show what would be changed without making changes
- `--force-refresh`, `-f`: Force download fresh inventory without prompting
- `--log`, `-l`: Custom log file path (default: `stock_remover.log`)

## How It Works

1. **Load Inventory**: Downloads or loads cached product inventory from Squarespace
2. **Parse CSV**: Reads SKUs from the CSV file
3. **Process Each SKU**:
   - Looks up the product by SKU
   - Checks current stock levels for all variants
   - If stock is already 0, skips the product
   - If stock > 0 or unlimited, sets it to 0 using the Inventory API
4. **Generate Report**: Outputs a summary showing:
   - SKUs where stock was changed to 0
   - SKUs already at 0 (no action needed)
   - SKUs not found on Squarespace
   - Any errors encountered

## API Integration

The script uses the Squarespace Commerce Inventory API:

- **Endpoint**: `POST /1.0/commerce/inventory/adjustments`
- **Operation**: `setFiniteOperations` to set exact quantities
- **Rate Limiting**: Respects the configured rate limit (default: 300 requests/minute)
- **Idempotency**: Each request includes a unique idempotency key to prevent duplicate operations

## Output Categories

### Stock Changed ✅
SKUs where stock was successfully set to 0

### Already at Zero ✓
SKUs that already had 0 stock (no changes made)

### Not Found ❌
SKUs not found in the Squarespace inventory

### Errors ⚠️
SKUs where an error occurred (with reason)

## Example Output

```
🚀 Starting Squarespace Stock Remover
📥 Loading product inventory...
📥 Loaded 50 SKUs from skus.csv
🔄 Processing 50 SKUs...

[1/50] Processing ABC123
📦 Processing SKU: ABC123
   Variant 123-456: Stock = 5, setting to 0
✅ Successfully set stock to 0 for variant 123-456 (SKU: ABC123)

[2/50] Processing XYZ789
📦 Processing SKU: XYZ789
✓ SKU XYZ789 already has 0 stock for all variants

...

📊 PROCESSING SUMMARY
============================================================
✅ Stock set to 0 (25 SKUs):
   • ABC123
   • DEF456
   ...

✓ Already at 0 stock (20 SKUs):
   • XYZ789
   ...

❌ SKUs not found on Squarespace (3 SKUs):
   • INVALID123
   ...

📈 Total SKUs processed: 50
   • Changed to 0: 25
   • Already at 0: 20
   • Not found: 3
   • Errors: 2
============================================================

✅ Squarespace Stock Remover completed
```

## Error Handling

The script handles various error scenarios:

- CSV file not found
- Invalid CSV format
- SKU not found on Squarespace
- Network errors
- API rate limiting
- Partial update failures

All errors are logged with details for troubleshooting.

## Dependencies

- `requests`: HTTP library for API calls
- `sqs_shared`: Shared Squarespace utilities (inventory management, rate limiting)
- Python standard library: `csv`, `logging`, `argparse`, `uuid`

## Related Projects

- **sqs-image-uploader**: Upload product images to Squarespace
- **sqs_shared**: Shared library for Squarespace API interactions

## Security Notes

- Never commit `config.py` to version control
- Keep your API key secure
- Use environment variables for production deployments

## License

Internal use only.

