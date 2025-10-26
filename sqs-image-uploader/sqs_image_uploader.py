#!/usr/bin/env python3
"""
Squarespace Product Image Uploader

This script uploads product images from an iCloud folder structure to Squarespace.
The folder structure should be: iCloud_folder/YYYY-MM-DD/SKU/image_files

Requirements:
- Squarespace API credentials in config.py
- iCloud folder path configured
- Product images organized by date and SKU
"""

import os
import sys
import json
import requests
import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

# Add parent directory to path for shared library and config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sqs_shared import SquarespaceInventoryManager, rate_limited
from config import SQUARESPACE_PRODUCTS_RW_KEY, SQUARESPACE_SITE_ID, ICLOUD_FOLDER_PATH, MAX_IMAGES_PER_SKU_FOLDER, REQUESTS_PER_MINUTE, MAX_RETRIES, RETRY_DELAY

# Note: Logging will be configured in main() after parsing command line args
logger = logging.getLogger(__name__)

class SquarespaceImageUploader:
    def __init__(self, dry_run=False, icloud_path=None, cache_filename="squarespace_products_cache.json", force_refresh=False, non_interactive=False):
        self.api_key = SQUARESPACE_PRODUCTS_RW_KEY
        self.site_id = SQUARESPACE_SITE_ID
        self.base_url = f"https://api.squarespace.com/1.0/commerce/products"
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'SquarespaceImageUploader/1.0'
        }
        self.dry_run = dry_run
        self.icloud_path = icloud_path or ICLOUD_FOLDER_PATH
        self.force_refresh = force_refresh
        
        # Initialize inventory manager from shared library
        self.inventory_manager = SquarespaceInventoryManager(
            api_key=SQUARESPACE_PRODUCTS_RW_KEY,
            site_id=SQUARESPACE_SITE_ID,
            cache_filename=cache_filename,
            requests_per_minute=REQUESTS_PER_MINUTE,
            non_interactive=non_interactive
        )
        
        # Statistics tracking
        self.stats = {
            'products_successfully_updated': 0,
            'skus_not_found': [],
            'skus_no_photos': [],
            'skus_other_reasons': []  # List of tuples (sku, reason)
        }
        
        if dry_run:
            logger.info("🔍 DRY RUN MODE: No changes will be made to Squarespace")
        

        
        logger.info(f"📁 Using iCloud folder: {self.icloud_path}")
    
    def should_skip_product(self, product: Dict) -> Tuple[bool, str]:
        """
        Check if product should be skipped based on business rules.
        Returns (should_skip, reason)
        """
        # Get SKU from variants if not at product level
        sku = product.get('sku')
        if not sku:
            variants = product.get('variants', [])
            if variants:
                sku = variants[0].get('sku', 'Unknown')
        
        # Get product name from the correct field
        product_name = product.get('name', product.get('title', 'Unknown'))
        
        
        # Check if product has images at product level
        product_images = product.get('images', [])

        if product_images:
            logger.info(f"   ⚠️ Product has {len(product_images)} existing images")
            return True, f"Product {sku} already has images"
        

        
        # Check if product is visible
        is_visible = product.get('isVisible', False)
        store_page_id = product.get('storePageId')
        
        if store_page_id and is_visible:
            logger.info(f"   ⚠️ Product is visible on store")
            return True, f"Product {sku} is set to visible"
        
        return False, ""

    @rate_limited(REQUESTS_PER_MINUTE)
    def _upload_image_impl(self, product_id: str, image_path: Path) -> bool:
        """Upload implementation with rate limiting"""
        try:
            # Upload the image file
            with open(image_path, 'rb') as f:
                files = {'file': (image_path.name, f, 'image/jpeg')}
                upload_response = requests.post(
                    f"https://api.squarespace.com/1.0/commerce/products/{product_id}/images",
                    headers={'Authorization': f'Bearer {self.api_key}'},
                    files=files
                )
                upload_response.raise_for_status()
            
            logger.info(f"Successfully uploaded {image_path.name} to product {product_id}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to upload {image_path.name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error uploading {image_path.name}: {e}")
            return False
    
    def upload_image(self, product_id: str, image_path: Path) -> bool:
        """Upload a single image to a product"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would upload {image_path.name} to product {product_id}")
            return True
        
        return self._upload_image_impl(product_id, image_path)

    def process_date_folder(self, date_folder: Path) -> None:
        """Process all SKU folders within a date folder"""
        if not date_folder.exists():
            logger.warning(f"Date folder {date_folder} does not exist")
            return
            
        logger.info(f"Processing date folder: {date_folder.name}")
        
        # Get all SKU folders
        sku_folders = [f for f in date_folder.iterdir() if f.is_dir()]
        
        for sku_folder in sku_folders:
            sku = sku_folder.name
            logger.info(f"Processing SKU: {sku}")
            
            # Get all image files in the SKU folder first
            image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
            image_files = [
                f for f in sku_folder.iterdir() 
                if f.is_file() and f.suffix.lower() in image_extensions
            ]
            
            # Check if SKU folder has more than the maximum allowed images
            if MAX_IMAGES_PER_SKU_FOLDER > 0 and len(image_files) > MAX_IMAGES_PER_SKU_FOLDER:
                reason = f"SKU folder contains {len(image_files)} images (maximum allowed: {MAX_IMAGES_PER_SKU_FOLDER})"
                logger.info(f"Skipping {sku}: {reason}")
                self.stats['skus_other_reasons'].append((sku, reason))
                continue
            
            if not image_files:
                logger.warning(f"No image files found in {sku_folder}")
                self.stats['skus_no_photos'].append(sku)
                continue
            
            # Sort images by number extracted from end of filename
            def extract_number_from_filename(file_path):
                # Get filename without extension
                filename = file_path.stem
                # Find the last sequence of digits in the filename
                import re
                numbers = re.findall(r'\d+', filename)
                if numbers:
                    return int(numbers[-1])  # Return the last number found
                return 0  # Default if no number found
            
            image_files.sort(key=extract_number_from_filename)
            
            # Get product from Squarespace
            product = self.inventory_manager.get_product_by_sku(sku)
            if not product:
                logger.warning(f"Product with SKU {sku} not found on Squarespace")
                self.stats['skus_not_found'].append(sku)
                continue
            
            # Check if we should skip this product
            should_skip, reason = self.should_skip_product(product)
            if should_skip:
                logger.info(f"Skipping {sku}: {reason}")
                self.stats['skus_other_reasons'].append((sku, reason))
                continue
            
            # Upload images
            product_id = product['id']
            successful_uploads = 0
            
            for image_file in image_files:
                if self.upload_image(product_id, image_file):
                    successful_uploads += 1
            
            if successful_uploads > 0:
                self.stats['products_successfully_updated'] += 1
            
            if self.dry_run:
                logger.info(f"[DRY RUN] Would upload {successful_uploads}/{len(image_files)} images for SKU {sku}")
            else:
                logger.info(f"Successfully uploaded {successful_uploads}/{len(image_files)} images for SKU {sku}")

    def process_icloud_folder(self) -> None:
        """Process the main iCloud folder structure"""
        icloud_path = Path(self.icloud_path)
        
        if not icloud_path.exists():
            logger.error(f"iCloud folder path does not exist: {self.icloud_path}")
            return
        
        # Fetch all products upfront
        self.inventory_manager.get_products_with_cache(force_refresh=self.force_refresh)
        
        # Get all date folders (ISO8601 format: YYYY-MM-DD)
        date_folders = []
        for item in icloud_path.iterdir():
            if item.is_dir():
                try:
                    # Validate ISO8601 format
                    datetime.strptime(item.name, '%Y-%m-%d')
                    date_folders.append(item)
                except ValueError:
                    logger.warning(f"Skipping non-date folder: {item.name}")
        
        # Sort date folders chronologically
        date_folders.sort(key=lambda x: x.name)
        
        for date_folder in date_folders:
            self.process_date_folder(date_folder)
    
    def print_summary(self) -> None:
        """Print a comprehensive summary of the processing results"""
        logger.info("\n" + "="*60)
        logger.info("📊 PROCESSING SUMMARY")
        logger.info("="*60)
        
        # Summary statistics
        logger.info(f"✅ Products successfully updated: {self.stats['products_successfully_updated']}")
        
        # SKUs not found on SQS
        if self.stats['skus_not_found']:
            logger.info(f"❌ SKUs not found on Squarespace ({len(self.stats['skus_not_found'])}):")
            for sku in self.stats['skus_not_found']:
                logger.info(f"   • {sku}")
        else:
            logger.info("✅ All processed SKUs were found on Squarespace")
        
        # SKUs with no photos
        if self.stats['skus_no_photos']:
            logger.info(f"📷 SKUs with no photos ({len(self.stats['skus_no_photos'])}):")
            for sku in self.stats['skus_no_photos']:
                logger.info(f"   • {sku}")
        else:
            logger.info("✅ All processed SKUs had photos available")
        
        # SKUs skipped for other reasons
        if self.stats['skus_other_reasons']:
            logger.info(f"⚠️ SKUs not processed for other reasons ({len(self.stats['skus_other_reasons'])}):")
            for sku, reason in self.stats['skus_other_reasons']:
                logger.info(f"   • {sku}: {reason}")
        else:
            logger.info("✅ No SKUs were skipped for other reasons")
        
        # Total counts
        total_processed = len(self.stats['skus_not_found']) + len(self.stats['skus_no_photos']) + len(self.stats['skus_other_reasons']) + self.stats['products_successfully_updated']
        if total_processed > 0:
            success_rate = (self.stats['products_successfully_updated'] / total_processed) * 100
            logger.info(f"\n📈 Overall success rate: {success_rate:.1f}% ({self.stats['products_successfully_updated']}/{total_processed})")
        
        logger.info("="*60)

def main():
    """Main function to run the image upload process"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Upload product images to Squarespace from iCloud folders',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Normal upload mode (prompts for cache refresh)
  %(prog)s --dry-run -d                       # Show what would be uploaded without making changes
  %(prog)s --force-refresh  -f                # Force download fresh inventory without prompting
  %(prog)s --path -p /path/to/folder          # Specify custom folder path
  %(prog)s --log -l mylog.log                 # Log output to custom file
        """
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Show what would be uploaded without making any changes to Squarespace'
    )
    parser.add_argument(
        '--path', '-p',
        type=str,
        help='Path to the folder (overrides config.py setting)'
    )

    parser.add_argument(
        '--force-refresh', '-f',
        action='store_true',
        help='Force download fresh inventory without prompting (ignores cache)'
    )
    parser.add_argument(
        '--log', '-l',
        type=str,
        help='Log output to specified file (default: squarespace_upload.log)'
    )
    parser.add_argument(
        '--non-interactive',
        action='store_true',
        help='Run in non-interactive mode (no prompts for cache refresh)'
    )
    
    args = parser.parse_args()
    
    # Configure logging based on command line arguments
    log_file = args.log if args.log else 'squarespace_upload.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ],
        force=True  # Reconfigure if already configured
    )
    
    if args.dry_run:
        logger.info("🔍 Starting Squarespace Image Upload Process (DRY RUN MODE)")
    else:
        logger.info("🚀 Starting Squarespace Image Upload Process")
    
    # Validate configuration
    if not SQUARESPACE_PRODUCTS_RW_KEY:
        logger.error("SQUARESPACE_PRODUCTS_RW_KEY not configured")
        sys.exit(1)
    
    if not SQUARESPACE_SITE_ID:
        logger.error("SQUARESPACE_SITE_ID not configured")
        sys.exit(1)
    
    # Determine which iCloud path to use
    icloud_path = args.path if args.path else ICLOUD_FOLDER_PATH
    
    if not icloud_path:
        logger.error("ICLOUD_FOLDER_PATH not configured in config.py and no --path provided")
        sys.exit(1)
    
    # Create uploader instance
    uploader = SquarespaceImageUploader(dry_run=args.dry_run, icloud_path=icloud_path, force_refresh=args.force_refresh, non_interactive=args.non_interactive)
    
    # Process the upload
    uploader.process_icloud_folder()
    
    # Print summary
    uploader.print_summary()
    
    if args.dry_run:
        logger.info("🔍 Squarespace Image Upload Process completed (DRY RUN MODE)")
    else:
        logger.info("✅ Squarespace Image Upload Process completed")

if __name__ == "__main__":
    main() 