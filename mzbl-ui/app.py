#!/usr/bin/env python3
"""
MZBL Web UI - Flask Application
Local web interface for managing MZBL Squarespace scripts
"""

import os
import sys
import json
import subprocess
import threading
import time
from pathlib import Path
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from datetime import datetime
import logging

# Add parent directory to path for config access
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

app = Flask(__name__)
app.secret_key = 'mzbl-ui-secret-key-change-in-production'

# Configuration
BASE_DIR = Path(__file__).parent
PARENT_DIR = BASE_DIR.parent
SETTINGS_FILE = BASE_DIR / 'settings.json'
LOG_DIR = BASE_DIR / 'logs'

# Ensure log directory exists
LOG_DIR.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_DIR / 'mzbl-ui.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Global variables for process management
running_processes = {}
process_logs = {}

class ProcessManager:
    """Manages running subprocess and their logs"""
    
    def __init__(self):
        self.processes = {}
        self.logs = {}
    
    def start_process(self, process_id, command, cwd=None):
        """Start a new process and capture its output"""
        if process_id in self.processes:
            if self.processes[process_id].poll() is None:
                return False, "Process already running"
        
        try:
            # Start process
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                cwd=cwd
            )
            
            self.processes[process_id] = process
            self.logs[process_id] = []
            
            # Start log capture thread
            thread = threading.Thread(
                target=self._capture_output,
                args=(process_id, process)
            )
            thread.daemon = True
            thread.start()
            
            return True, "Process started successfully"
            
        except Exception as e:
            logger.error(f"Failed to start process {process_id}: {e}")
            return False, str(e)
    
    def _capture_output(self, process_id, process):
        """Capture process output in a separate thread"""
        try:
            for line in iter(process.stdout.readline, ''):
                if line:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    log_entry = f"[{timestamp}] {line.rstrip()}"
                    self.logs[process_id].append(log_entry)
                    
                    # Keep only last 1000 lines to prevent memory issues
                    if len(self.logs[process_id]) > 1000:
                        self.logs[process_id] = self.logs[process_id][-1000:]
            
            process.wait()
            
            # Add completion message
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            exit_code = process.returncode
            status = "completed successfully" if exit_code == 0 else f"failed with exit code {exit_code}"
            self.logs[process_id].append(f"[{timestamp}] Process {status}")
            
        except Exception as e:
            logger.error(f"Error capturing output for {process_id}: {e}")
    
    def get_process_status(self, process_id):
        """Get the status of a process"""
        if process_id not in self.processes:
            return "not_found"
        
        process = self.processes[process_id]
        if process.poll() is None:
            return "running"
        elif process.returncode == 0:
            return "completed"
        else:
            return "failed"
    
    def get_logs(self, process_id):
        """Get logs for a process"""
        return self.logs.get(process_id, [])
    
    def stop_process(self, process_id):
        """Stop a running process"""
        if process_id in self.processes:
            process = self.processes[process_id]
            if process.poll() is None:
                process.terminate()
                return True
        return False

# Global process manager
process_manager = ProcessManager()

def load_settings():
    """Load settings from JSON file"""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading settings: {e}")
    
    # Return default settings
    return {
        'image_uploader': {
            'icloud_path': '',
            'dry_run': True,
            'force_refresh': False
        },
        'stock_remover': {
            'csv_file': '',
            'dry_run': True,
            'force_refresh': False
        }
    }

def save_settings(settings):
    """Save settings to JSON file"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False

def handle_icloud_drive_access(requested_path=None):
    """Special handler for iCloud Drive access to bypass macOS restrictions"""
    try:
        # Use subprocess to list iCloud Drive contents to bypass Python restrictions
        import subprocess
        
        # Convert symlink path to real path for subprocess
        if requested_path and '/Users/yzats/iCloudDrive' in requested_path:
            # Replace symlink path with real path
            real_path = requested_path.replace('/Users/yzats/iCloudDrive', 
                                             '/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs')
        else:
            real_path = requested_path or "/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs"
        
        # Run ls command to get directory contents
        result = subprocess.run(['ls', '-la', real_path], 
                              capture_output=True, text=True)
        
        # Check if command failed
        if result.returncode != 0:
            logger.error(f"ls command failed with return code {result.returncode}")
            logger.error(f"stderr: {result.stderr}")
            logger.error(f"stdout: {result.stdout}")
            
            # Try alternative approach - use find command which might have different permissions
            result = subprocess.run(['find', real_path, '-maxdepth', '1', '-ls'], 
                                  capture_output=True, text=True)
            
            if result.returncode != 0:
                # If both ls and find fail, return error with helpful message
                logger.warning(f"Both ls and find failed, iCloud Drive access denied")
                return jsonify({
                    'error': 'iCloud Drive access denied. Please grant Full Disk Access to Terminal in System Preferences → Security & Privacy → Privacy → Full Disk Access',
                    'current_path': '/Users/yzats/iCloudDrive',
                    'items': [{
                        'name': '..',
                        'path': str(Path.home()),
                        'type': 'directory',
                        'is_parent': True
                    }]
                }), 403
        
        items = []
        
        # Add parent directory
        parent_path = str(Path(real_path).parent)
        # Convert back to symlink path for display
        if '/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs' in parent_path:
            display_parent = parent_path.replace('/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs',
                                               '/Users/yzats/iCloudDrive')
        else:
            display_parent = str(Path.home())
            
        items.append({
            'name': '..',
            'path': display_parent,
            'type': 'directory',
            'is_parent': True
        })
        
        # Parse ls output
        lines = result.stdout.strip().split('\n')[3:]  # Skip ., .., and total line
        for line in lines:
            if not line.strip():
                continue
                
            parts = line.split()
            if len(parts) < 9:
                continue
                
            permissions = parts[0]
            name = ' '.join(parts[8:])  # Handle names with spaces
            
            if name.startswith('.'):
                continue  # Skip hidden files
                
            item_type = 'directory' if permissions.startswith('d') else 'file'
            # Use real path for actual access but convert to symlink path for display
            full_real_path = f"{real_path}/{name}"
            display_path = full_real_path.replace('/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs',
                                                '/Users/yzats/iCloudDrive')
            
            items.append({
                'name': name,
                'path': display_path,
                'type': item_type,
                'is_parent': False
            })
        
        # Convert current path to symlink path for display
        display_current = real_path.replace('/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs',
                                          '/Users/yzats/iCloudDrive')
        
        return jsonify({
            'current_path': display_current,
            'items': items
        })
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Error accessing iCloud Drive via subprocess: {e}")
        return jsonify({'error': 'Cannot access iCloud Drive'}), 500
    except Exception as e:
        logger.error(f"Error in iCloud Drive handler: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get current settings"""
    return jsonify(load_settings())

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update settings"""
    try:
        settings = request.json
        if save_settings(settings):
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Failed to save settings'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/browse')
def browse_files():
    """Browse files and directories"""
    path = request.args.get('path', str(Path.home()))
    file_type = request.args.get('type', 'directory')  # 'directory' or 'file'
    
    
    try:
        # Special handling for iCloud Drive paths
        if ('/Users/yzats/iCloudDrive' in path or 
            '/Users/yzats/Library/Mobile Documents/com~apple~CloudDocs' in path):
            return handle_icloud_drive_access(path)
        
        current_path = Path(path)
        
        # Only resolve if it's not a symlink to avoid permission issues
        if not current_path.is_symlink():
            current_path = current_path.resolve()
        
        # If path doesn't exist or is not a directory, fall back to home
        if not current_path.exists() or not current_path.is_dir():
            current_path = Path.home().resolve()
        
        items = []
        
        # Add parent directory option (allow navigation up to filesystem root)
        parent_path = current_path.parent
        # Only exclude if we're at the actual filesystem root
        if str(current_path) != str(parent_path):  # Not at filesystem root
            items.append({
                'name': '..',
                'path': str(parent_path),
                'type': 'directory',
                'is_parent': True
            })
            logger.info(f"Added parent directory: {parent_path}")
        else:
            logger.info(f"At filesystem root, no parent added: {current_path}")
        
        # Add special shortcuts when in home directory
        if current_path == Path.home():
            # Add iCloud Drive shortcut if symlink exists and is accessible
            icloud_symlink = Path.home() / 'iCloudDrive'
            if icloud_symlink.exists():
                try:
                    # Test if we can actually access it
                    list(icloud_symlink.iterdir())
                    items.append({
                        'name': '📱 iCloud Drive',
                        'path': str(icloud_symlink),
                        'type': 'directory',
                        'is_parent': False,
                        'is_shortcut': True
                    })
                except (PermissionError, OSError):
                    # Don't show the shortcut if we can't access it
                    logger.debug("iCloud Drive shortcut hidden due to permission issues")
        
        # List directory contents
        try:
            for item in sorted(current_path.iterdir()):
                if item.name.startswith('.'):
                    continue  # Skip hidden files
                
                item_type = 'directory' if item.is_dir() else 'file'
                
                # For symlinks, use the symlink path to avoid permission issues
                if item.is_symlink():
                    item_path = str(item)
                else:
                    item_path = str(item.resolve())
                
                items.append({
                    'name': item.name,
                    'path': item_path,
                    'type': item_type,
                    'is_parent': False
                })
        except PermissionError as e:
            logger.warning(f"Permission denied reading directory {current_path}: {e}")
        except Exception as e:
            logger.error(f"Error reading directory contents: {e}")
        
        return jsonify({
            'current_path': str(current_path),
            'items': items
        })
        
    except Exception as e:
        logger.error(f"Error browsing files: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-images', methods=['POST'])
def upload_images():
    """Execute image uploader script"""
    try:
        data = request.json
        
        # Build command
        command = [sys.executable, str(PARENT_DIR / 'sqs-image-uploader' / 'sqs_image_uploader.py')]
        
        if data.get('dry_run'):
            command.extend(['--dry-run'])
        
        if data.get('force_refresh'):
            command.extend(['--force-refresh'])
        
        if data.get('icloud_path'):
            command.extend(['--path', data['icloud_path']])
        
        # Always run in non-interactive mode when invoked from UI
        command.extend(['--non-interactive'])
        
        # Start process
        process_id = 'image_uploader'
        success, message = process_manager.start_process(
            process_id, 
            command, 
            cwd=str(PARENT_DIR / 'sqs-image-uploader')
        )
        
        if success:
            return jsonify({'success': True, 'process_id': process_id})
        else:
            return jsonify({'success': False, 'error': message}), 500
            
    except Exception as e:
        logger.error(f"Error starting image uploader: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/clear-inventory', methods=['POST'])
def clear_inventory():
    """Execute stock remover script"""
    try:
        data = request.json
        
        # Validate required fields
        if not data.get('csv_file'):
            return jsonify({'success': False, 'error': 'CSV file is required'}), 400
        
        # Build command
        command = [sys.executable, str(PARENT_DIR / 'sqs-stock-remover' / 'sqs_stock_remover.py')]
        command.extend(['--csv', data['csv_file']])
        
        if data.get('dry_run'):
            command.extend(['--dry-run'])
        
        if data.get('force_refresh'):
            command.extend(['--force-refresh'])
        
        # Always run in non-interactive mode when invoked from UI
        command.extend(['--non-interactive'])
        
        # Start process
        process_id = 'stock_remover'
        success, message = process_manager.start_process(
            process_id, 
            command, 
            cwd=str(PARENT_DIR / 'sqs-stock-remover')
        )
        
        if success:
            return jsonify({'success': True, 'process_id': process_id})
        else:
            return jsonify({'success': False, 'error': message}), 500
            
    except Exception as e:
        logger.error(f"Error starting stock remover: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/process-status/<process_id>')
def get_process_status(process_id):
    """Get status of a running process"""
    status = process_manager.get_process_status(process_id)
    return jsonify({'status': status})

@app.route('/api/process-logs/<process_id>')
def get_process_logs(process_id):
    """Get logs for a process"""
    logs = process_manager.get_logs(process_id)
    return jsonify({'logs': logs})

@app.route('/api/process-logs-stream/<process_id>')
def stream_process_logs(process_id):
    """Stream logs for a process using Server-Sent Events"""
    def generate():
        last_line = 0
        while True:
            logs = process_manager.get_logs(process_id)
            
            # Send new log lines
            if len(logs) > last_line:
                for line in logs[last_line:]:
                    yield f"data: {json.dumps({'log': line})}\n\n"
                last_line = len(logs)
            
            # Check if process is still running
            status = process_manager.get_process_status(process_id)
            if status in ['completed', 'failed', 'not_found']:
                yield f"data: {json.dumps({'status': status})}\n\n"
                break
            
            time.sleep(1)
    
    return Response(generate(), mimetype='text/event-stream')

@app.route('/api/stop-process/<process_id>', methods=['POST'])
def stop_process(process_id):
    """Stop a running process"""
    success = process_manager.stop_process(process_id)
    return jsonify({'success': success})

if __name__ == '__main__':
    logger.info("Starting MZBL Web UI...")
    app.run(debug=True, host='127.0.0.1', port=5000)
