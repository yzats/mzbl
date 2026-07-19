#!/usr/bin/env python3
"""
Setup script for Squarespace Image Uploader

This script helps set up the environment and dependencies.
"""

import os
import sys
import subprocess
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors"""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"   Error: {e.stderr}")
        return False

def check_python_version():
    """Check if Python version is compatible"""
    print("🐍 Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 7):
        print(f"❌ Python 3.7+ required, found {version.major}.{version.minor}")
        return False
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} is compatible")
    return True

def create_virtual_environment():
    """Create a virtual environment"""
    if Path("venv").exists():
        print("✅ Virtual environment already exists")
        return True
    
    return run_command("python3 -m venv venv", "Creating virtual environment")

def install_dependencies():
    """Install Python dependencies"""
    # Determine the correct pip command based on OS
    if os.name == 'nt':  # Windows
        pip_cmd = "venv\\Scripts\\pip"
    else:  # macOS/Linux
        pip_cmd = "venv/bin/pip"
    
    return run_command(f"{pip_cmd} install -r requirements.txt", "Installing dependencies")

def create_config_template():
    """Create a config template if it doesn't exist"""
    config_path = Path("config.py")
    if config_path.exists():
        print("✅ config.py already exists")
        return True
    
    print("📝 Creating config.py template...")
    config_content = '''"""
Configuration file for Squarespace Image Uploader

This file contains all the configuration settings and API keys.
Make sure to keep this file secure and never commit it to version control.
"""

# Squarespace API Configuration
# Get these from your Squarespace Developer account
SQUARESPACE_API_KEY = "your_squarespace_api_key_here"
SQUARESPACE_SITE_ID = "your_squarespace_site_id_here"

# iCloud Folder Path
# Update this to point to your iCloud folder location
ICLOUD_FOLDER_PATH = "/Users/your_username/Library/Mobile Documents/com~apple~CloudDocs/MZBL/SQS Upload"

# Optional: Additional configuration
# Maximum number of images allowed per SKU folder (0 = no limit)
MAX_IMAGES_PER_SKU_FOLDER = 5

# Supported image formats
SUPPORTED_IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

# API rate limiting (requests per minute)
REQUESTS_PER_MINUTE = 300

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
'''
    
    try:
        with open(config_path, 'w') as f:
            f.write(config_content)
        print("✅ config.py template created")
        return True
    except Exception as e:
        print(f"❌ Failed to create config.py: {e}")
        return False

def main():
    """Main setup function"""
    print("🚀 Squarespace Image Uploader - Setup")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    print()
    
    # Create virtual environment
    if not create_virtual_environment():
        sys.exit(1)
    
    print()
    
    # Install dependencies
    if not install_dependencies():
        sys.exit(1)
    
    print()
    
    # Create config template
    if not create_config_template():
        sys.exit(1)
    
    print()
    print("=" * 50)
    print("🎉 Setup completed successfully!")
    print()
    print("Next steps:")
    print("1. Edit config.py with your Squarespace API credentials")
    print("2. Update the ICLOUD_FOLDER_PATH in config.py")
    print("3. Run the test script: python test_setup.py")
    print("4. If tests pass, run the upload script: python sqs_image_uploader.py")
    print()
    print("For detailed instructions, see README.md")

if __name__ == "__main__":
    main() 