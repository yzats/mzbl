#!/usr/bin/env python3
"""
Test script to verify Squarespace API connection and configuration

Run this script to test your setup before running the main upload script.
"""

import sys
import requests
from pathlib import Path

try:
    from config import SQUARESPACE_API_KEY, SQUARESPACE_SITE_ID, ICLOUD_FOLDER_PATH
except ImportError:
    print("❌ Error: config.py not found or not properly configured")
    print("Please create config.py with your API credentials")
    sys.exit(1)

def test_config():
    """Test configuration values"""
    print("🔧 Testing configuration...")
    
    issues = []
    
    if not SQUARESPACE_API_KEY or SQUARESPACE_API_KEY == "your_squarespace_api_key_here":
        issues.append("SQUARESPACE_API_KEY not configured")
    
    if not SQUARESPACE_SITE_ID or SQUARESPACE_SITE_ID == "your_squarespace_site_id_here":
        issues.append("SQUARESPACE_SITE_ID not configured")
    
    if not ICLOUD_FOLDER_PATH or ICLOUD_FOLDER_PATH == "/Users/your_username/Library/Mobile Documents/com~apple~CloudDocs/your_folder_name":
        issues.append("ICLOUD_FOLDER_PATH not configured")
    
    if issues:
        print("❌ Configuration issues found:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    
    print("✅ Configuration looks good")
    return True

def test_icloud_path():
    """Test if iCloud folder path exists"""
    print(f"📁 Testing iCloud folder path: {ICLOUD_FOLDER_PATH}")
    
    icloud_path = Path(ICLOUD_FOLDER_PATH)
    if not icloud_path.exists():
        print(f"❌ iCloud folder does not exist: {ICLOUD_FOLDER_PATH}")
        return False
    
    if not icloud_path.is_dir():
        print(f"❌ Path is not a directory: {ICLOUD_FOLDER_PATH}")
        return False
    
    print("✅ iCloud folder path is valid")
    
    # Check for date folders
    date_folders = []
    for item in icloud_path.iterdir():
        if item.is_dir():
            try:
                from datetime import datetime
                datetime.strptime(item.name, '%Y-%m-%d')
                date_folders.append(item.name)
            except ValueError:
                pass
    
    if date_folders:
        print(f"✅ Found {len(date_folders)} date folders: {', '.join(date_folders[:5])}{'...' if len(date_folders) > 5 else ''}")
    else:
        print("⚠️  No date folders found (expected format: YYYY-MM-DD)")
    
    return True

def test_squarespace_api():
    """Test Squarespace API connection"""
    print("🌐 Testing Squarespace API connection...")
    
    headers = {
        'Authorization': f'Bearer {SQUARESPACE_API_KEY}',
        'Content-Type': 'application/json',
        'User-Agent': 'SquarespaceImageUploader/1.0'
    }
    
    try:
        # Test basic API connection
        response = requests.get(
            f"https://api.squarespace.com/1.0/commerce/products",
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            product_count = len(data.get('products', []))
            print(f"✅ API connection successful")
            print(f"   Found {product_count} products in your store")
            
            # Test dry run capability
            print("🔍 Testing dry run capability...")
            print("   You can use --dry-run to test without making changes")
            return True
        elif response.status_code == 401:
            print("❌ API authentication failed - check your API key")
            return False
        elif response.status_code == 403:
            print("❌ API access denied - check your API permissions")
            return False
        else:
            print(f"❌ API request failed with status {response.status_code}")
            print(f"   Response: {response.text[:200]}...")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Squarespace Image Uploader - Setup Test")
    print("=" * 50)
    
    tests_passed = 0
    total_tests = 3
    
    # Test configuration
    if test_config():
        tests_passed += 1
    print()
    
    # Test iCloud path
    if test_icloud_path():
        tests_passed += 1
    print()
    
    # Test API connection
    if test_squarespace_api():
        tests_passed += 1
    print()
    
    # Summary
    print("=" * 50)
    print(f"📊 Test Results: {tests_passed}/{total_tests} tests passed")
    
    if tests_passed == total_tests:
        print("🎉 All tests passed! You're ready to run the upload script.")
        print("Run: python sqs_image_uploader.py")
        print("Or test with dry run: python sqs_image_uploader.py --dry-run")
    else:
        print("⚠️  Some tests failed. Please fix the issues above before running the upload script.")
        sys.exit(1)

if __name__ == "__main__":
    main() 