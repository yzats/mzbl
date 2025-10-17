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
from config import SQUARESPACE_API_KEY, SQUARESPACE_SITE_ID, ICLOUD_FOLDER_PATH, MAX_IMAGES_PER_SKU_FOLDER, REQUESTS_PER_MINUTE, MAX_RETRIES, RETRY_DELAY

# Note: Logging will be configured in main() after parsing command line args
logger = logging.getLogger(__name__)

class SquarespaceImageUploader:
    def __init__(self, dry_run=False, icloud_path=None, cache_filename="squarespace_products_cache.json", force_refresh=False):
        self.api_key = SQUARESPACE_API_KEY
        self.site_id = SQUARESPACE_SITE_ID
        self.base_url = f"https://api.squarespace.com/1.0/commerce/products"
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'SquarespaceImageUploader/1.0'
        }
        self.dry_run = dry_run
        self.icloud_path = icloud_path or ICLOUD_FOLDER_PATH
        self.cache_filename = cache_filename
        self.force_refresh = force_refresh
        
        # Rate limiting setup
        self.requests_per_minute = REQUESTS_PER_MINUTE
        self.request_times = []
        self.min_interval = 60.0 / self.requests_per_minute if self.requests_per_minute > 0 else 0
        
        # Cache for products
        self._products_cache = None
        self._sku_lookup = None
        
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
    
    def _rate_limit(self):
        """Implement rate limiting for API requests"""
        if self.requests_per_minute <= 0:
            return  # No rate limiting
        
        current_time = time.time()
        
        # Remove requests older than 1 minute
        self.request_times = [t for t in self.request_times if current_time - t < 60.0]
        
        # If we've made too many requests in the last minute, wait
        if len(self.request_times) >= self.requests_per_minute:
            oldest_request = min(self.request_times)
            wait_time = 60.0 - (current_time - oldest_request) + 0.1  # Add small buffer
            if wait_time > 0:
                logger.debug(f"Rate limit reached, waiting {wait_time:.1f} seconds")
                time.sleep(wait_time)
                current_time = time.time()
        
        # Record this request
        self.request_times.append(current_time)
        
    def get_products(self) -> List[Dict]:
        """Fetch all products from Squarespace with pagination"""
        all_products = []
        cursor = None
        page = 1
        
        logger.info("📥 Retrieving all products from Squarespace...")
        
        while True:
            self._rate_limit()
            try:
                params = {'limit': 50}  # Maximum page size
                if cursor:
                    params['cursor'] = cursor
                
                response = requests.get(
                    f"{self.base_url}",
                    headers=self.headers,
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                
                products = data.get('products', [])
                all_products.extend(products)
                
                # Show progress every 1000 products
                if len(all_products) % 1000 == 0:
                    logger.info(f"📥 Retrieved {len(all_products)} products so far...")
                
                # Check if there are more pages
                pagination = data.get('pagination', {})
                cursor = pagination.get('nextPageCursor')
                
                if not cursor:
                    break
                    
                page += 1
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch products on page {page}: {e}")
                break
        
        logger.info(f"✅ Retrieved {len(all_products)} total products from Squarespace")
        return all_products

    def _get_cached_products(self) -> List[Dict]:
        """Get products from cache (file or memory), fetching if not cached"""
        if self._products_cache is None:
            # Check if we should use file cache or download fresh
            self._products_cache = self._get_products_with_file_cache()
        return self._products_cache

    def _get_products_with_file_cache(self) -> List[Dict]:
        """Get products using file cache with user prompting for refresh"""
        cache_age = self._get_cache_file_age()
        
        if self.force_refresh:
            # Force refresh was requested, download unconditionally
            logger.info("🔄 Force refresh requested, downloading fresh inventory from Squarespace...")
            products = self.get_products()
            self._save_products_to_cache(products)
            return products
        elif cache_age is None:
            # No cache file exists, download unconditionally
            logger.info("📥 No cached inventory found, downloading from Squarespace...")
            products = self.get_products()
            self._save_products_to_cache(products)
            return products
        else:
            # Cache file exists, prompt user
            age_str = self._format_age(cache_age)
            print(f"\n📁 Found cached inventory file: {self.cache_filename}")
            print(f"🕐 Cache age: {age_str} old")
            
            while True:
                response = input("\n🔄 Download fresh inventory from Squarespace? (y/n): ").strip().lower()
                if response in ['y', 'yes']:
                    logger.info("📥 Downloading fresh inventory from Squarespace...")
                    products = self.get_products()
                    self._save_products_to_cache(products)
                    return products
                elif response in ['n', 'no']:
                    logger.info("📂 Using cached inventory...")
                    return self._load_products_from_cache()
                else:
                    print("Please enter 'y' or 'n'")

    def _get_cache_file_age(self) -> Optional[timedelta]:
        """Get the age of the cache file"""
        if not os.path.exists(self.cache_filename):
            return None
        
        file_mtime = os.path.getmtime(self.cache_filename)
        file_time = datetime.fromtimestamp(file_mtime)
        return datetime.now() - file_time

    def _format_age(self, age: timedelta) -> str:
        """Format age in human-readable format"""
        if age.days > 0:
            hours = age.seconds // 3600
            if hours > 0:
                return f"{age.days} day{'s' if age.days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
            else:
                return f"{age.days} day{'s' if age.days != 1 else ''}"
        elif age.seconds >= 3600:
            hours = age.seconds // 3600
            minutes = (age.seconds % 3600) // 60
            if minutes > 0:
                return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            minutes = age.seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"

    def _save_products_to_cache(self, products: List[Dict]):
        """Save products to cache file"""
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'products': products,
                'count': len(products)
            }
            
            with open(self.cache_filename, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"💾 Saved {len(products)} products to cache file: {self.cache_filename}")
            
        except Exception as e:
            logger.error(f"Failed to save cache file: {e}")
            # Continue without caching rather than failing completely

    def _load_products_from_cache(self) -> List[Dict]:
        """Load products from cache file"""
        try:
            with open(self.cache_filename, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            products = cache_data.get('products', [])
            count = cache_data.get('count', len(products))
            timestamp = cache_data.get('timestamp', 'unknown')
            
            logger.info(f"📂 Loaded {count} products from cache (saved: {timestamp})")
            return products
            
        except Exception as e:
            logger.error(f"Failed to load cache file: {e}")
            # Fall back to downloading fresh
            logger.info("📥 Falling back to downloading fresh inventory...")
            return self.get_products()

    def _build_sku_lookup(self) -> Dict[str, List[Dict]]:
        """Build a fast lookup dictionary for SKU searches (case-insensitive using uppercase keys)"""
        if self._sku_lookup is None:
            products = self._get_cached_products()
            self._sku_lookup = {}
            case_conflicts = {}  # Track different case variants of same SKU
            
            for product in products:
                # Add product-level SKU
                product_sku = product.get('sku', '')
                if product_sku:
                    # Use uppercase for case-insensitive matching
                    sku_key = product_sku.upper()
                    
                    # Track case variants for conflict detection
                    if sku_key not in case_conflicts:
                        case_conflicts[sku_key] = set()
                    case_conflicts[sku_key].add(product_sku)
                    
                    if sku_key not in self._sku_lookup:
                        self._sku_lookup[sku_key] = []
                    self._sku_lookup[sku_key].append(product)
                
                # Add variant-level SKUs
                variants = product.get('variants', [])
                for variant in variants:
                    variant_sku = variant.get('sku', '')
                    if variant_sku and variant_sku != product_sku:
                        # Use uppercase for case-insensitive matching
                        sku_key = variant_sku.upper()
                        
                        # Track case variants for conflict detection
                        if sku_key not in case_conflicts:
                            case_conflicts[sku_key] = set()
                        case_conflicts[sku_key].add(variant_sku)
                        
                        if sku_key not in self._sku_lookup:
                            self._sku_lookup[sku_key] = []
                        self._sku_lookup[sku_key].append(product)
            
            # Log any case conflicts found
            for sku_key, variants in case_conflicts.items():
                if len(variants) > 1:
                    logger.warning(f"⚠️ Multiple case variants found for SKU '{sku_key}': {sorted(variants)}")
                    logger.warning(f"   Will use first match found during lookup")
            
        
        return self._sku_lookup

    def debug_product_images(self, product: Dict) -> None:
        """Debug method to show all image information for a product"""
        sku = product.get('sku', 'Unknown')
        logger.info(f"🔍 DEBUG: Image analysis for SKU {sku}")
        
        variants = product.get('variants', [])
        logger.info(f"📊 Product has {len(variants)} variants")
        
        for i, variant in enumerate(variants):
            variant_id = variant.get('id', 'Unknown')
            images = variant.get('images', [])
            logger.info(f"   Variant {i+1} (ID: {variant_id}): {len(images)} images")
            
            for j, image in enumerate(images):
                image_id = image.get('id', 'Unknown')
                filename = image.get('filename', 'Unknown')
                url = image.get('url', 'Unknown')
                logger.info(f"     Image {j+1}: ID={image_id}, Filename={filename}")
                logger.info(f"       URL: {url}")
        
        # Also check product-level images
        product_images = product.get('images', [])
        if product_images:
            for j, image in enumerate(product_images):
                image_id = image.get('id', 'Unknown')
                filename = image.get('filename', 'Unknown')
                logger.info(f"   Product Image {j+1}: ID={image_id}, Filename={filename}")

    def get_product_by_sku(self, sku: str) -> Optional[Dict]:
        """Get a specific product by SKU (case-insensitive)"""
        try:
            # Get fast SKU lookup
            sku_lookup = self._build_sku_lookup()
            
            # Convert to uppercase for case-insensitive matching
            sku_key = sku.upper()
            
            # Log case normalization if it occurred
            if sku != sku_key:
                logger.info(f"🔤 Normalizing SKU case: '{sku}' → '{sku_key}'")
            
            # Fast lookup using uppercase key
            matching_products = sku_lookup.get(sku_key, [])
            logger.info(f"📊 Found {len(matching_products)} products with SKU '{sku}'")
            
            if len(matching_products) > 1:
                logger.warning(f"⚠️ Multiple products found with SKU {sku}:")
                for i, product in enumerate(matching_products):
                    logger.warning(f"   {i+1}. Product ID: {product.get('id')}, Title: {product.get('title', 'Unknown')}")
            
            if matching_products:
                product = matching_products[0]
                product_name = product.get('name', product.get('title', 'Unknown'))
                return product
            else:
                logger.warning(f"❌ No products found with SKU: {sku} (searched as: {sku_key})")
                return None
                
        except Exception as e:
            logger.error(f"Error searching for SKU {sku}: {e}")
            return None

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

    def upload_image(self, product_id: str, image_path: Path) -> bool:
        """Upload a single image to a product"""
        if self.dry_run:
            logger.info(f"[DRY RUN] Would upload {image_path.name} to product {product_id}")
            return True
            
        self._rate_limit()
        try:
            # First, upload the image file
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
            product = self.get_product_by_sku(sku)
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
        self._get_cached_products()
        
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
        '--debug-sku',
        type=str,
        help='Debug a specific SKU to see its current images and structure'
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
    if not SQUARESPACE_API_KEY:
        logger.error("SQUARESPACE_API_KEY not configured")
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
    uploader = SquarespaceImageUploader(dry_run=args.dry_run, icloud_path=icloud_path, force_refresh=args.force_refresh)
    
    # Handle debug options
    if args.debug_sku:
        product = uploader.get_product_by_sku(args.debug_sku)
        if product:
            uploader.debug_product_images(product)
        else:
            logger.error(f"Product with SKU {args.debug_sku} not found")
        return
    
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