#!/usr/bin/env python3
"""
Squarespace Stock Remover

This script sets stock levels to 0 for products listed in a CSV file.
It uses the Squarespace Inventory API to adjust stock quantities.

Requirements:
- Squarespace API credentials in config.py (in parent folder)
- CSV file with SKUs (single column, optional "SKU" header)
"""

import os
import sys
import csv
import requests
import argparse
import uuid
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime

# Add parent directory to path for shared library and config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from sqs_shared import SquarespaceInventoryManager, rate_limited
from config import SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY, SQUARESPACE_SITE_ID, REQUESTS_PER_MINUTE

# Note: Logging will be configured in main() after parsing command line args
logger = logging.getLogger(__name__)


class SquarespaceStockRemover:
    """Manages setting stock levels to 0 for specified products"""
    
    def __init__(self, dry_run=False, cache_filename="squarespace_products_cache.json", force_refresh=False, non_interactive=False):
        """
        Initialize the stock remover.
        
        Args:
            dry_run: If True, preview changes without making them
            cache_filename: Path to cache file for products
            force_refresh: If True, force download fresh inventory
            non_interactive: If True, don't prompt user for input
        """
        self.api_key = SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY
        self.site_id = SQUARESPACE_SITE_ID
        self.inventory_url = "https://api.squarespace.com/1.0/commerce/inventory/adjustments"
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'SquarespaceStockRemover/1.0'
        }
        self.dry_run = dry_run
        self.force_refresh = force_refresh
        
        # Initialize inventory manager from shared library
        self.inventory_manager = SquarespaceInventoryManager(
            api_key=SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY,
            site_id=SQUARESPACE_SITE_ID,
            cache_filename=cache_filename,
            requests_per_minute=REQUESTS_PER_MINUTE,
            non_interactive=non_interactive
        )
        
        # Statistics tracking
        self.stats = {
            'stock_changed': [],      # List of SKUs where stock was set to 0
            'already_zero': [],        # List of SKUs already at 0
            'sku_not_found': [],      # List of SKUs not found on Squarespace
            'errors': []               # List of tuples (sku, reason)
        }
        
        if dry_run:
            logger.info("🔍 DRY RUN MODE: No changes will be made to Squarespace")
    
    def parse_csv(self, csv_path: str) -> List[str]:
        """
        Parse CSV file and extract SKUs.
        
        Supports two formats:
        1. Single column of SKUs with no header
        2. Multi-column CSV with a column named "SKU" (case-insensitive)
        
        Args:
            csv_path: Path to CSV file
            
        Returns:
            List of SKUs
        """
        skus = []
        
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Try to detect if there's a header
                sample = f.read(1024)
                f.seek(0)
                
                reader = csv.reader(f)
                
                # Read first row to check for header
                first_row = next(reader)
                
                # Check if first row contains "SKU" (case-insensitive)
                sku_column_index = None
                for i, cell in enumerate(first_row):
                    if cell.strip().upper() == 'SKU':
                        sku_column_index = i
                        logger.info(f"📋 CSV header detected with SKU in column {i+1}: {first_row}")
                        break
                
                # If we found a SKU column header, use that column
                if sku_column_index is not None:
                    # Read remaining rows and extract SKU column
                    for row in reader:
                        if row and len(row) > sku_column_index:
                            sku = row[sku_column_index].strip()
                            if sku:  # Skip empty cells
                                skus.append(sku)
                else:
                    # No header found, treat first row as data and use first column
                    logger.info(f"📋 No SKU header found, using first column as SKUs")
                    
                    # Add first row if it's not empty
                    if first_row and first_row[0].strip():
                        skus.append(first_row[0].strip())
                    
                    # Read remaining rows
                    for row in reader:
                        if row and row[0].strip():  # Skip empty rows
                            skus.append(row[0].strip())
            
            logger.info(f"📥 Loaded {len(skus)} SKUs from {csv_path}")
            return skus
            
        except FileNotFoundError:
            logger.error(f"❌ CSV file not found: {csv_path}")
            return []
        except Exception as e:
            logger.error(f"❌ Error reading CSV file: {e}")
            return []
    
    def get_variant_stock_info(self, product: Dict) -> List[Tuple[str, int, bool]]:
        """
        Extract variant IDs and their current stock quantities from a product.
        
        Args:
            product: Product dictionary from Squarespace
            
        Returns:
            List of tuples (variant_id, quantity, is_unlimited)
        """
        variant_info = []
        
        variants = product.get('variants', [])
        for variant in variants:
            variant_id = variant.get('id')
            if not variant_id:
                continue
            
            # Get stock information (Squarespace stores this in 'stock', not 'inventory')
            stock = variant.get('stock', {})
            quantity = stock.get('quantity', 0)
            is_unlimited = stock.get('unlimited', False)
            
            variant_info.append((variant_id, quantity, is_unlimited))
        
        return variant_info
    
    @rate_limited(REQUESTS_PER_MINUTE)
    def _set_stock_to_zero_impl(self, variant_id: str, sku: str) -> bool:
        """
        Set stock to 0 for a specific variant (rate-limited implementation).
        
        Args:
            variant_id: Variant ID to update
            sku: SKU for logging purposes
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Generate unique idempotency key
            idempotency_key = str(uuid.uuid4())
            
            # Prepare request
            headers = self.headers.copy()
            headers['Idempotency-Key'] = idempotency_key
            
            payload = {
                'setFiniteOperations': [
                    {
                        'variantId': variant_id,
                        'quantity': 0
                    }
                ]
            }
            
            # Make API request
            response = requests.post(
                self.inventory_url,
                headers=headers,
                json=payload
            )
            
            # Check response
            if response.status_code == 204:
                logger.info(f"✅ Successfully set stock to 0 for variant {variant_id} (SKU: {sku})")
                return True
            else:
                logger.error(f"❌ Failed to update stock for variant {variant_id} (SKU: {sku}): {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Network error updating stock for variant {variant_id} (SKU: {sku}): {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error updating stock for variant {variant_id} (SKU: {sku}): {e}")
            return False
    
    def set_stock_to_zero(self, variant_id: str, sku: str) -> bool:
        """
        Set stock to 0 for a specific variant.
        
        Args:
            variant_id: Variant ID to update
            sku: SKU for logging purposes
            
        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would set stock to 0 for variant {variant_id} (SKU: {sku})")
            return True
        
        return self._set_stock_to_zero_impl(variant_id, sku)
    
    def process_sku(self, sku: str) -> None:
        """
        Process a single SKU - check stock and set to 0 if needed.
        
        Args:
            sku: SKU to process
        """
        logger.info(f"📦 Processing SKU: {sku}")
        
        # Look up product
        product = self.inventory_manager.get_product_by_sku(sku)
        if not product:
            logger.warning(f"❌ Product with SKU {sku} not found on Squarespace")
            self.stats['sku_not_found'].append(sku)
            return
        
        # Get variant stock information
        variant_info = self.get_variant_stock_info(product)
        
        if not variant_info:
            logger.warning(f"⚠️ No variants found for SKU {sku}")
            self.stats['errors'].append((sku, "No variants found"))
            return
        
        # Check if all variants already have 0 stock
        all_zero = all(
            quantity == 0 and not is_unlimited 
            for _, quantity, is_unlimited in variant_info
        )
        
        if all_zero:
            logger.info(f"✓ SKU {sku} already has 0 stock for all variants")
            self.stats['already_zero'].append(sku)
            return
        
        # Update stock for variants that need it
        success_count = 0
        needs_update = False
        
        for variant_id, quantity, is_unlimited in variant_info:
            if is_unlimited:
                logger.info(f"   Variant {variant_id}: Unlimited stock, setting to 0")
                needs_update = True
                if self.set_stock_to_zero(variant_id, sku):
                    success_count += 1
            elif quantity > 0:
                logger.info(f"   Variant {variant_id}: Stock = {quantity}, setting to 0")
                needs_update = True
                if self.set_stock_to_zero(variant_id, sku):
                    success_count += 1
            else:
                logger.info(f"   Variant {variant_id}: Already at 0")
        
        # Record result
        if needs_update:
            if success_count == sum(1 for _, q, u in variant_info if u or q > 0):
                self.stats['stock_changed'].append(sku)
            else:
                self.stats['errors'].append((sku, "Partial update failure"))
    
    def process_csv(self, csv_path: str) -> None:
        """
        Process all SKUs from a CSV file.
        
        Args:
            csv_path: Path to CSV file
        """
        # Load products from cache or API
        logger.info("📥 Loading product inventory...")
        self.inventory_manager.get_products_with_cache(force_refresh=self.force_refresh)
        
        # Parse CSV
        skus = self.parse_csv(csv_path)
        
        if not skus:
            logger.error("❌ No SKUs found in CSV file")
            return
        
        # Process each SKU
        logger.info(f"🔄 Processing {len(skus)} SKUs...")
        for i, sku in enumerate(skus, 1):
            logger.info(f"\n[{i}/{len(skus)}] Processing {sku}")
            self.process_sku(sku)
    
    def print_summary(self) -> None:
        """Print a comprehensive summary of the processing results"""
        logger.info("\n" + "="*60)
        logger.info("📊 PROCESSING SUMMARY")
        logger.info("="*60)
        
        # Stock changed
        if self.stats['stock_changed']:
            logger.info(f"✅ Stock set to 0 ({len(self.stats['stock_changed'])} SKUs):")
            for sku in self.stats['stock_changed']:
                logger.info(f"   • {sku}")
        else:
            logger.info("ℹ️ No stock levels were changed")
        
        # Already zero
        if self.stats['already_zero']:
            logger.info(f"\n✓ Already at 0 stock ({len(self.stats['already_zero'])} SKUs):")
            for sku in self.stats['already_zero']:
                logger.info(f"   • {sku}")
        
        # SKUs not found
        if self.stats['sku_not_found']:
            logger.info(f"\n❌ SKUs not found on Squarespace ({len(self.stats['sku_not_found'])} SKUs):")
            for sku in self.stats['sku_not_found']:
                logger.info(f"   • {sku}")
        
        # Errors
        if self.stats['errors']:
            logger.info(f"\n⚠️ Errors ({len(self.stats['errors'])} SKUs):")
            for sku, reason in self.stats['errors']:
                logger.info(f"   • {sku}: {reason}")
        
        # Total counts
        total_processed = len(self.stats['stock_changed']) + len(self.stats['already_zero']) + len(self.stats['sku_not_found']) + len(self.stats['errors'])
        if total_processed > 0:
            logger.info(f"\n📈 Total SKUs processed: {total_processed}")
            logger.info(f"   • Changed to 0: {len(self.stats['stock_changed'])}")
            logger.info(f"   • Already at 0: {len(self.stats['already_zero'])}")
            logger.info(f"   • Not found: {len(self.stats['sku_not_found'])}")
            logger.info(f"   • Errors: {len(self.stats['errors'])}")
        
        logger.info("="*60)


def main():
    """Main function to run the stock removal process"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Set stock levels to 0 for products listed in a CSV file',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --csv skus.csv                      # Normal mode
  %(prog)s --csv skus.csv --dry-run            # Preview changes without making them
  %(prog)s --csv skus.csv --force-refresh      # Force download fresh inventory
  %(prog)s --csv skus.csv --log mylog.log      # Log output to custom file
        """
    )
    parser.add_argument(
        '--csv', '-c',
        type=str,
        required=True,
        help='Path to CSV file containing SKUs'
    )
    parser.add_argument(
        '--dry-run', '-d',
        action='store_true',
        help='Show what would be changed without making any changes to Squarespace'
    )
    parser.add_argument(
        '--force-refresh', '-f',
        action='store_true',
        help='Force download fresh inventory without prompting (ignores cache)'
    )
    parser.add_argument(
        '--log', '-l',
        type=str,
        help='Log output to specified file (default: stock_remover.log)'
    )
    parser.add_argument(
        '--non-interactive',
        action='store_true',
        help='Run in non-interactive mode (no prompts for cache refresh)'
    )
    
    args = parser.parse_args()
    
    # Configure logging based on command line arguments
    log_file = args.log if args.log else 'stock_remover.log'
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ],
        force=True  # Reconfigure if already configured
    )
    
    if args.dry_run:
        logger.info("🔍 Starting Squarespace Stock Remover (DRY RUN MODE)")
    else:
        logger.info("🚀 Starting Squarespace Stock Remover")
    
    # Validate configuration
    if not SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY:
        logger.error("❌ SQUARESPACE_PRODUCTS_INVENTORY_RW_KEY not configured")
        sys.exit(1)
    
    if not SQUARESPACE_SITE_ID:
        logger.error("❌ SQUARESPACE_SITE_ID not configured")
        sys.exit(1)
    
    # Validate CSV file
    if not os.path.exists(args.csv):
        logger.error(f"❌ CSV file not found: {args.csv}")
        sys.exit(1)
    
    # Create remover instance
    remover = SquarespaceStockRemover(
        dry_run=args.dry_run,
        force_refresh=args.force_refresh,
        non_interactive=args.non_interactive
    )
    
    # Process the CSV
    remover.process_csv(args.csv)
    
    # Print summary
    remover.print_summary()
    
    if args.dry_run:
        logger.info("\n🔍 Squarespace Stock Remover completed (DRY RUN MODE)")
    else:
        logger.info("\n✅ Squarespace Stock Remover completed")


if __name__ == "__main__":
    main()

