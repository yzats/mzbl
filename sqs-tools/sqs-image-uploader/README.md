# Squarespace Product Image Uploader

A Python script to automatically upload product images to Squarespace from an organized iCloud folder structure.

## Features

- Uploads product images from iCloud folders to Squarespace products
- Respects business rules: skips products that already have images or are set to visible
- Processes folders organized by date (ISO8601 format) and SKU
- Comprehensive logging and error handling
- Secure API key management

## Folder Structure

The script expects the following folder structure in your iCloud folder:

```
iCloud_folder/
├── 2025-01-15/
│   ├── A12345/
│   │   ├── product_image_1.jpg
│   │   ├── product_image_2.jpg
│   │   └── product_image_3.png
│   └── B67890/
│       ├── product_image_1.jpg
│       └── product_image_2.jpeg
└── 2025-01-16/
    └── C11111/
        └── product_image_1.jpg
```

- **Date folders**: Must be in ISO8601 format (YYYY-MM-DD)
- **SKU folders**: Named with the product SKU (e.g., A12345)
- **Image files**: Supported formats: JPG, JPEG, PNG, GIF, WEBP

## Setup Instructions

### 1. Install Python Dependencies

```bash
# Create a uv-managed environment
uv venv

# Install dependencies into .venv
uv pip install -r requirements.txt
```

### 2. Configure API Keys

1. Copy `config.py` and update it with your credentials:

```python
# Get these from your Squarespace Developer account
SQUARESPACE_PRODUCTS_RW_KEY = "your_actual_api_key_here"
SQUARESPACE_SITE_ID = "your_actual_site_id_here"

# Update this to your iCloud folder path
ICLOUD_FOLDER_PATH = "/Users/your_username/Library/Mobile Documents/com~apple~CloudDocs/your_folder_name"
```

2. **Important**: Never commit your actual API keys to version control!

### 3. Get Squarespace API Credentials

1. Go to [Squarespace Developer Portal](https://developers.squarespace.com/)
2. Create a new application
3. Generate an API key with the following permissions:
   - `commerce.products.read`
   - `commerce.products.write`
   - `commerce.products.images.write`

### 4. Find Your Site ID

Your Squarespace Site ID can be found in your site's URL or in the Developer Portal.

## Usage

### Basic Usage

```bash
# Run the script (normal mode)
uv run sqs_image_uploader.py

# Run in dry-run mode (see what would be uploaded without making changes)
uv run sqs_image_uploader.py --dry-run

# Short form for dry run
uv run sqs_image_uploader.py -d

# Specify custom iCloud folder path
uv run sqs_image_uploader.py --path /path/to/your/folder

# Combine options
uv run sqs_image_uploader.py --dry-run --path /path/to/your/folder

# Mark products visible after fully successful uploads
uv run sqs_image_uploader.py --set-visible

# Show per-image upload and SKU lookup details
uv run sqs_image_uploader.py --verbose
```

### What the Script Does

1. **Scans iCloud folder**: Looks for date folders in ISO8601 format
2. **Processes each date**: Goes through SKU folders within each date
3. **Checks image count**: Skips SKU folders with more than 5 images (configurable)
4. **Checks products**: Verifies if products exist on Squarespace
5. **Applies business rules**: Skips products that:
   - Already have at least one image
   - Are set to be visible on the store
6. **Uploads images**: Uploads all images for eligible products (or simulates in dry-run mode)
7. **Logs everything**: Provides detailed console and file logging

### Dry Run Mode

The script includes a dry-run mode that shows you exactly what would be uploaded without making any changes to Squarespace:

- **No API uploads**: Images are not actually uploaded to Squarespace
- **Full simulation**: All business rules and checks are still applied
- **Detailed logging**: Shows exactly what would be uploaded and what would be skipped
- **Safe testing**: Perfect for testing your folder structure and configuration

Use `--dry-run` or `-d` flag to enable this mode.

### Custom iCloud Path

You can specify a custom iCloud folder path using the `--path` or `-p` parameter:

- **Overrides config**: Command line path takes precedence over config.py setting
- **Flexible usage**: Use different folders for different runs
- **No config changes**: Test with different paths without modifying config.py
- **Combines with dry-run**: Perfect for testing different folder structures

Example: `python sqs_image_uploader.py --path /Users/username/Documents/test-folder`

### Set Visible After Successful Upload

Use the `--set-visible` flag to mark a product as visible (`isVisible=true`) on the
Squarespace store **only when every image in that SKU's folder uploads successfully**.

- **Strict success guard**: If any image upload fails for a SKU, that product is NOT marked visible.
- **Per-SKU**: Each SKU is evaluated independently.
- **Dry-run aware**: With `--dry-run`, the script logs which products would be marked visible without writing.
- **Reported in summary**: The end-of-run summary lists products marked visible, visibility update failures, and SKUs skipped due to partial uploads.

Example: `python sqs_image_uploader.py --set-visible`

### Verbose Logging

By default, each SKU prints one concise status line, such as:

```text
A91448: uploaded 4/4 image(s), marked visible
```

Use `--verbose` or `-v` when you need lower-level details like each image filename,
product IDs, and SKU lookup counts.

### Command Line Options

```bash
python sqs_image_uploader.py [OPTIONS]

Options:
  --dry-run, -d          Show what would be uploaded without making changes
  --path, -p             Path to the iCloud folder (overrides config.py setting)
  --force-refresh, -f    Force refresh of cached inventory without prompting
  --log, -l FILE         Log output to specified file
  --non-interactive      Run without interactive prompts
  --set-visible          Mark products visible only when all images upload successfully
  --verbose, -v          Show per-image upload and SKU lookup details
  --help, -h             Show this help message and exit
```

### Output

The script provides:
- Console output showing progress and results
- Log file (`squarespace_upload.log`) with detailed information
- Clear indication of which products were skipped and why
- In dry-run mode: Clear indication of what would be uploaded vs. skipped

## Business Rules

The script follows these business rules:

1. **Skip if product has images**: If any variant of a product already has images, skip it
2. **Skip if product is visible**: If a product is set to be visible on the store, skip it
3. **Skip if too many images**: If a SKU folder contains more than 5 images (configurable), skip it
4. **Process in chronological order**: Date folders are processed in order (oldest first)
5. **Support multiple image formats**: JPG, JPEG, PNG, GIF, WEBP

## Error Handling

The script includes comprehensive error handling:

- **API errors**: Retries failed requests with exponential backoff
- **File errors**: Skips missing or corrupted image files
- **Network errors**: Logs and continues with next file
- **Invalid folders**: Skips non-date folders and logs warnings

## Logging

The script creates logs in two places:

1. **Console output**: Real-time progress and important messages
2. **Log file**: The same run output saved to `squarespace_upload.log`

Log levels:
- `INFO`: Concise progress and normal operation messages
- `DEBUG`: Detailed per-image and SKU lookup messages, enabled with `--verbose`
- `WARNING`: Non-critical issues (missing files, invalid folders)
- `ERROR`: Critical issues (API failures, missing products)

## Troubleshooting

### Common Issues

1. **"SQUARESPACE_PRODUCTS_RW_KEY not configured"**
   - Check that `SQUARESPACE_PRODUCTS_RW_KEY` is set in `config.py`

2. **"Site ID not configured"**
   - Verify `SQUARESPACE_SITE_ID` in `config.py`

3. **"iCloud folder path does not exist"**
   - Update `ICLOUD_FOLDER_PATH` to the correct path
   - Ensure the path is accessible

4. **"Product with SKU not found"**
   - Verify the SKU exists on your Squarespace store
   - Check for typos in folder names

5. **"Failed to upload image"**
   - Check file permissions
   - Verify image file is not corrupted
   - Check API rate limits

### Debug Mode

To get more detailed logging, modify the logging level in the script:

```python
logging.basicConfig(level=logging.DEBUG, ...)
```

## Security Notes

- Never commit `config.py` with real API keys to version control
- Add `config.py` to your `.gitignore` file
- Keep your API keys secure and rotate them regularly
- The script only reads from your iCloud folder and uploads to Squarespace

## API Rate Limits

Squarespace has rate limits on their API. The script includes automatic rate limiting to respect these limits:

- **Default**: 60 requests per minute
- **Configurable**: Adjust `REQUESTS_PER_MINUTE` in `config.py`
- **Automatic**: The script automatically waits when rate limits are reached
- **Disabled**: Set `REQUESTS_PER_MINUTE = 0` to disable rate limiting

### Rate Limiting Features

- **Sliding window**: Tracks requests over the last 60 seconds
- **Automatic waiting**: Pauses execution when limits are reached
- **Debug logging**: Shows when rate limiting is active (in debug mode)
- **Configurable**: Easy to adjust based on your API plan

### Configuration Examples

```python
# Conservative rate limiting (30 requests per minute)
REQUESTS_PER_MINUTE = 30

# Standard rate limiting (60 requests per minute)
REQUESTS_PER_MINUTE = 60

# Disable rate limiting (not recommended)
REQUESTS_PER_MINUTE = 0
```

## Support

For issues or questions:
1. Check the log file for detailed error messages
2. Verify your API credentials and permissions
3. Ensure your folder structure matches the expected format
4. Check Squarespace API documentation for any changes

## License

This script is provided as-is for educational and business use. Please ensure compliance with Squarespace's Terms of Service and API usage guidelines. 
