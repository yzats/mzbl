"""
Squarespace Inventory Manager

This module provides a class for managing Squarespace product inventory,
including downloading, caching, and looking up products by SKU.
"""

import os
import json
import requests
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from .rate_limiter import rate_limited

logger = logging.getLogger(__name__)


class SquarespaceInventoryManager:
    """
    Manages Squarespace product inventory with caching and SKU lookup.
    
    This class handles:
    - Downloading product inventory from Squarespace API
    - Caching inventory to disk
    - Building case-insensitive SKU lookup dictionaries
    - Looking up products by SKU
    """
    
    def __init__(
        self,
        api_key: str,
        site_id: Optional[str] = None,
        cache_filename: str = "squarespace_products_cache.json",
        requests_per_minute: int = 300
    ):
        """
        Initialize the inventory manager.
        
        Args:
            api_key: Squarespace API key
            site_id: Squarespace site ID (optional, for future use)
            cache_filename: Path to cache file
            requests_per_minute: API rate limit (requests per minute)
        """
        self.api_key = api_key
        self.site_id = site_id
        self.base_url = "https://api.squarespace.com/1.0/commerce/products"
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'User-Agent': 'SquarespaceInventoryManager/1.0'
        }
        self.cache_filename = cache_filename
        self.requests_per_minute = requests_per_minute
        
        # Internal caches
        self._products_cache = None
        self._sku_lookup = None
    
    def get_products(self) -> List[Dict]:
        """
        Fetch all products from Squarespace with pagination.
        
        Returns:
            List of product dictionaries
        """
        all_products = []
        cursor = None
        page = 1
        
        logger.info("📥 Retrieving all products from Squarespace...")
        
        while True:
            try:
                params = {'limit': 50}  # Maximum page size
                if cursor:
                    params['cursor'] = cursor
                
                # Apply rate limiting
                response = self._make_request('GET', self.base_url, params=params)
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
    
    @rate_limited(300)  # Default rate limit, will be overridden by instance value
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Make a rate-limited HTTP request.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments to pass to requests
        
        Returns:
            Response object
        """
        return requests.request(method, url, headers=self.headers, **kwargs)
    
    def get_products_with_cache(self, force_refresh: bool = False) -> List[Dict]:
        """
        Get products using file cache with user prompting for refresh.
        
        Args:
            force_refresh: If True, download fresh inventory without prompting
        
        Returns:
            List of product dictionaries
        """
        cache_age = self.get_cache_age()
        
        if force_refresh:
            # Force refresh was requested, download unconditionally
            logger.info("🔄 Force refresh requested, downloading fresh inventory from Squarespace...")
            products = self.get_products()
            self.save_to_cache(products)
            self._products_cache = products
            return products
        elif cache_age is None:
            # No cache file exists, download unconditionally
            logger.info("📥 No cached inventory found, downloading from Squarespace...")
            products = self.get_products()
            self.save_to_cache(products)
            self._products_cache = products
            return products
        else:
            # Cache file exists, prompt user
            age_str = self.format_cache_age(cache_age)
            print(f"\n📁 Found cached inventory file: {self.cache_filename}")
            print(f"🕐 Cache age: {age_str} old")
            
            while True:
                response = input("\n🔄 Download fresh inventory from Squarespace? (y/n): ").strip().lower()
                if response in ['y', 'yes']:
                    logger.info("📥 Downloading fresh inventory from Squarespace...")
                    products = self.get_products()
                    self.save_to_cache(products)
                    self._products_cache = products
                    return products
                elif response in ['n', 'no']:
                    logger.info("📂 Using cached inventory...")
                    products = self.load_from_cache()
                    self._products_cache = products
                    return products
                else:
                    print("Please enter 'y' or 'n'")
    
    def get_cache_age(self) -> Optional[timedelta]:
        """
        Get the age of the cache file.
        
        Returns:
            timedelta representing cache age, or None if cache doesn't exist
        """
        if not os.path.exists(self.cache_filename):
            return None
        
        file_mtime = os.path.getmtime(self.cache_filename)
        file_time = datetime.fromtimestamp(file_mtime)
        return datetime.now() - file_time
    
    def format_cache_age(self, age: timedelta) -> str:
        """
        Format age in human-readable format.
        
        Args:
            age: timedelta to format
        
        Returns:
            Human-readable string (e.g., "2 days, 3 hours")
        """
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
    
    def save_to_cache(self, products: List[Dict]) -> None:
        """
        Save products to cache file.
        
        Args:
            products: List of product dictionaries to cache
        """
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
    
    def load_from_cache(self) -> List[Dict]:
        """
        Load products from cache file.
        
        Returns:
            List of product dictionaries
        """
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
    
    def build_sku_lookup(self, products: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Build a fast lookup dictionary for SKU searches (case-insensitive using uppercase keys).
        
        Args:
            products: List of product dictionaries
        
        Returns:
            Dictionary mapping uppercase SKU to list of matching products
        """
        sku_lookup = {}
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
                
                if sku_key not in sku_lookup:
                    sku_lookup[sku_key] = []
                sku_lookup[sku_key].append(product)
            
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
                    
                    if sku_key not in sku_lookup:
                        sku_lookup[sku_key] = []
                    sku_lookup[sku_key].append(product)
        
        # Log any case conflicts found
        for sku_key, variants in case_conflicts.items():
            if len(variants) > 1:
                logger.warning(f"⚠️ Multiple case variants found for SKU '{sku_key}': {sorted(variants)}")
                logger.warning(f"   Will use first match found during lookup")
        
        return sku_lookup
    
    def get_product_by_sku(self, sku: str, products: Optional[List[Dict]] = None) -> Optional[Dict]:
        """
        Get a specific product by SKU (case-insensitive).
        
        Args:
            sku: SKU to search for
            products: Optional list of products to search. If None, uses cached products.
        
        Returns:
            Product dictionary if found, None otherwise
        """
        try:
            # Use provided products or get from cache
            if products is None:
                if self._products_cache is None:
                    # Need to load products first
                    logger.warning("No products loaded. Call get_products_with_cache() first.")
                    return None
                products = self._products_cache
            
            # Build or use cached SKU lookup
            if self._sku_lookup is None or products != self._products_cache:
                self._sku_lookup = self.build_sku_lookup(products)
            
            # Convert to uppercase for case-insensitive matching
            sku_key = sku.upper()
            
            # Log case normalization if it occurred
            if sku != sku_key:
                logger.info(f"🔤 Normalizing SKU case: '{sku}' → '{sku_key}'")
            
            # Fast lookup using uppercase key
            matching_products = self._sku_lookup.get(sku_key, [])
            logger.info(f"📊 Found {len(matching_products)} products with SKU '{sku}' ")
            
            if len(matching_products) > 1:
                logger.warning(f"⚠️ Multiple products found with SKU {sku}:")
                for i, product in enumerate(matching_products):
                    logger.warning(f"   {i+1}. Product ID: {product.get('id')}, Title: {product.get('title', 'Unknown')}")
            
            if matching_products:
                product = matching_products[0]
                return product
            else:
                logger.warning(f"❌ No products found with SKU: {sku}")
                return None
                
        except Exception as e:
            logger.error(f"Error searching for SKU {sku}: {e}")
            return None


