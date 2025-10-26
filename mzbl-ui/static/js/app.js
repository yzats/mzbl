/**
 * MZBL Management UI - JavaScript Application
 * Handles client-side functionality for the web interface
 */

// Application state
const AppState = {
    currentProcessId: null,
    currentTargetInput: null,
    currentBrowserType: 'directory',
    eventSource: null,
    settings: {}
};

// Initialize application when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
});

/**
 * Initialize the application
 */
function initializeApp() {
    loadSettings();
    setupFormHandlers();
    setupEventListeners();
    
    console.log('MZBL Management UI initialized');
}

/**
 * Setup event listeners
 */
function setupEventListeners() {
    // Auto-save settings on form changes with debouncing
    let saveTimeout;
    document.addEventListener('change', function(e) {
        if (e.target.closest('#image-uploader-form') || e.target.closest('#stock-remover-form')) {
            clearTimeout(saveTimeout);
            saveTimeout = setTimeout(saveSettings, 500);
        }
    });
    
    // Handle modal cleanup
    document.getElementById('file-browser-modal').addEventListener('hidden.bs.modal', function() {
        AppState.currentTargetInput = null;
        AppState.currentBrowserType = 'directory';
    });
    
    // Handle window beforeunload to cleanup event sources
    window.addEventListener('beforeunload', function() {
        if (AppState.eventSource) {
            AppState.eventSource.close();
        }
    });
}

/**
 * Settings Management
 */
function loadSettings() {
    fetch('/api/settings')
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(settings => {
            AppState.settings = settings;
            populateFormFromSettings('image-uploader-form', settings.image_uploader || {});
            populateFormFromSettings('stock-remover-form', settings.stock_remover || {});
        })
        .catch(error => {
            console.error('Error loading settings:', error);
            showNotification('Failed to load saved settings', 'warning');
        });
}

function saveSettings() {
    const settings = {
        image_uploader: getFormData('image-uploader-form'),
        stock_remover: getFormData('stock-remover-form')
    };
    
    fetch('/api/settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(settings)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(result => {
        if (result.success) {
            AppState.settings = settings;
        }
    })
    .catch(error => {
        console.error('Error saving settings:', error);
    });
}

function populateFormFromSettings(formId, settings) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    Object.keys(settings).forEach(key => {
        const element = form.querySelector(`[name="${key}"]`);
        if (element) {
            if (element.type === 'checkbox') {
                element.checked = Boolean(settings[key]);
            } else {
                element.value = settings[key] || '';
            }
        }
    });
}

function getFormData(formId) {
    const form = document.getElementById(formId);
    if (!form) return {};
    
    const formData = new FormData(form);
    const data = {};
    
    // Get all form elements to handle unchecked checkboxes
    const elements = form.querySelectorAll('input, select, textarea');
    elements.forEach(element => {
        if (element.name) {
            if (element.type === 'checkbox') {
                data[element.name] = element.checked;
            } else if (element.type !== 'submit' && element.type !== 'button') {
                data[element.name] = element.value;
            }
        }
    });
    
    return data;
}

/**
 * Form Handlers
 */
function setupFormHandlers() {
    // Image uploader form
    const imageForm = document.getElementById('image-uploader-form');
    if (imageForm) {
        imageForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const data = getFormData('image-uploader-form');
            
            // Validate required fields for image uploader
            if (!data.icloud_path) {
                showNotification('Please specify an iCloud path', 'error');
                return;
            }
            
            saveSettings();
            startProcess('/api/upload-images', data, 'Image Upload');
        });
    }
    
    // Stock remover form
    const stockForm = document.getElementById('stock-remover-form');
    if (stockForm) {
        stockForm.addEventListener('submit', function(e) {
            e.preventDefault();
            const data = getFormData('stock-remover-form');
            
            // Validate required fields
            if (!data.csv_file) {
                showNotification('Please select a CSV file', 'error');
                return;
            }
            
            saveSettings();
            startProcess('/api/clear-inventory', data, 'Stock Removal');
        });
    }
}

/**
 * UI Section Management
 */
function showImageUploader() {
    hideAllSections();
    const section = document.getElementById('image-uploader-section');
    if (section) {
        section.style.display = 'block';
        section.classList.add('fade-in');
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function showStockRemover() {
    hideAllSections();
    const section = document.getElementById('stock-remover-section');
    if (section) {
        section.style.display = 'block';
        section.classList.add('fade-in');
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function hideAllSections() {
    const sections = ['image-uploader-section', 'stock-remover-section'];
    sections.forEach(sectionId => {
        const section = document.getElementById(sectionId);
        if (section) {
            section.style.display = 'none';
            section.classList.remove('fade-in');
        }
    });
    hideProcessStatus();
}

function showProcessStatus() {
    const section = document.getElementById('process-status-section');
    if (section) {
        section.style.display = 'block';
        section.classList.add('fade-in');
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function hideProcessStatus() {
    const section = document.getElementById('process-status-section');
    if (section) {
        section.style.display = 'none';
        section.classList.remove('fade-in');
    }
    
    if (AppState.eventSource) {
        AppState.eventSource.close();
        AppState.eventSource = null;
    }
}

/**
 * Process Management
 */
function startProcess(endpoint, data, processName) {
    // Disable form submission buttons
    setFormButtonsEnabled(false);
    
    fetch(endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(result => {
        if (result.success) {
            AppState.currentProcessId = result.process_id;
            showProcessStatus();
            updateProcessStatus('running');
            clearLogs();
            startLogStreaming();
            showNotification(`${processName} started successfully`, 'success');
        } else {
            setFormButtonsEnabled(true);
            showNotification(`Failed to start ${processName}: ${result.error}`, 'error');
        }
    })
    .catch(error => {
        setFormButtonsEnabled(true);
        console.error('Error starting process:', error);
        showNotification(`Error starting ${processName}: ${error.message}`, 'error');
    });
}

function stopProcess() {
    if (!AppState.currentProcessId) return;
    
    fetch(`/api/stop-process/${AppState.currentProcessId}`, {
        method: 'POST'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    })
    .then(result => {
        if (result.success) {
            showNotification('Process stopped', 'warning');
            updateProcessStatus('stopped');
        } else {
            showNotification('Failed to stop process', 'error');
        }
    })
    .catch(error => {
        console.error('Error stopping process:', error);
        showNotification('Error stopping process', 'error');
    });
}

function updateProcessStatus(status) {
    const badge = document.getElementById('process-status-badge');
    const stopBtn = document.getElementById('stop-process-btn');
    
    if (badge) {
        badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        badge.className = 'badge ms-2 ' + getStatusBadgeClass(status);
    }
    
    if (stopBtn) {
        stopBtn.style.display = (status === 'running') ? 'inline-block' : 'none';
    }
    
    // Re-enable form buttons when process completes
    if (status !== 'running') {
        setFormButtonsEnabled(true);
    }
}

function getStatusBadgeClass(status) {
    const classes = {
        'running': 'bg-primary',
        'completed': 'bg-success',
        'failed': 'bg-danger',
        'stopped': 'bg-warning'
    };
    return classes[status] || 'bg-secondary';
}

function setFormButtonsEnabled(enabled) {
    const buttons = document.querySelectorAll('#upload-submit-btn, #stock-submit-btn');
    buttons.forEach(button => {
        button.disabled = !enabled;
        if (enabled) {
            button.innerHTML = button.innerHTML.replace('Processing...', button.id.includes('upload') ? 'Start Upload' : 'Start Process');
        } else {
            const icon = button.innerHTML.includes('upload') ? '<i class="bi bi-hourglass-split me-2"></i>' : '<i class="bi bi-hourglass-split me-2"></i>';
            button.innerHTML = icon + 'Processing...';
        }
    });
}

/**
 * Log Management
 */
function startLogStreaming() {
    if (AppState.eventSource) {
        AppState.eventSource.close();
    }
    
    if (!AppState.currentProcessId) return;
    
    AppState.eventSource = new EventSource(`/api/process-logs-stream/${AppState.currentProcessId}`);
    
    AppState.eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            if (data.log) {
                appendLog(data.log);
            }
            
            if (data.status) {
                updateProcessStatus(data.status);
                if (data.status !== 'running') {
                    AppState.eventSource.close();
                    AppState.eventSource = null;
                    
                    // Show completion notification
                    const message = data.status === 'completed' ? 'Process completed successfully' : 'Process failed';
                    const type = data.status === 'completed' ? 'success' : 'error';
                    showNotification(message, type);
                }
            }
        } catch (error) {
            console.error('Error parsing log data:', error);
        }
    };
    
    AppState.eventSource.onerror = function(error) {
        console.error('EventSource error:', error);
        if (AppState.eventSource) {
            AppState.eventSource.close();
            AppState.eventSource = null;
        }
        showNotification('Lost connection to process logs', 'warning');
    };
}

function appendLog(logLine) {
    const logsContainer = document.getElementById('process-logs');
    if (!logsContainer) return;
    
    const logElement = document.createElement('div');
    logElement.textContent = logLine;
    
    // Add color coding for different log levels
    if (logLine.includes('ERROR') || logLine.includes('❌')) {
        logElement.style.color = '#ff6b6b';
    } else if (logLine.includes('WARNING') || logLine.includes('⚠️')) {
        logElement.style.color = '#ffd93d';
    } else if (logLine.includes('SUCCESS') || logLine.includes('✅')) {
        logElement.style.color = '#6bcf7f';
    } else if (logLine.includes('INFO') || logLine.includes('ℹ️')) {
        logElement.style.color = '#74c0fc';
    }
    
    logsContainer.appendChild(logElement);
    logsContainer.scrollTop = logsContainer.scrollHeight;
}

function clearLogs() {
    const logsContainer = document.getElementById('process-logs');
    if (logsContainer) {
        logsContainer.innerHTML = '<div class="text-muted">Waiting for process to start...</div>';
    }
}

/**
 * File Browser
 */
function browseFolder(targetInputId) {
    AppState.currentTargetInput = targetInputId;
    AppState.currentBrowserType = 'directory';
    
    const browserType = document.getElementById('browser-type');
    if (browserType) {
        browserType.textContent = 'Folder';
    }
    
    openFileBrowser();
}

function browseFile(targetInputId) {
    AppState.currentTargetInput = targetInputId;
    AppState.currentBrowserType = 'file';
    
    const browserType = document.getElementById('browser-type');
    if (browserType) {
        browserType.textContent = 'File';
    }
    
    openFileBrowser();
}

function openFileBrowser(path = null) {
    const modal = document.getElementById('file-browser-modal');
    if (!modal) return;
    
    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
    
    const startPath = path || (AppState.currentTargetInput ? document.getElementById(AppState.currentTargetInput).value : '') || '';
    loadDirectoryContents(startPath);
}

function loadDirectoryContents(path) {
    const fileList = document.getElementById('file-list');
    if (!fileList) return;
    
    fileList.innerHTML = '<div class="text-center p-3"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>';
    
    const url = `/api/browse?path=${encodeURIComponent(path)}&type=${AppState.currentBrowserType}`;
    
    fetch(url)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            const currentPath = document.getElementById('current-path');
            if (currentPath) {
                currentPath.value = data.current_path;
            }
            
            fileList.innerHTML = '';
            
            if (!data.items || data.items.length === 0) {
                fileList.innerHTML = '<div class="text-center p-3 text-muted">No items found</div>';
                return;
            }
            
            data.items.forEach(item => {
                const listItem = document.createElement('a');
                listItem.className = 'list-group-item list-group-item-action d-flex align-items-center';
                listItem.href = '#';
                
                const icon = item.type === 'directory' ? 'bi-folder-fill' : 'bi-file-earmark';
                const iconColor = item.is_parent ? 'text-secondary' : (item.type === 'directory' ? 'text-primary' : 'text-muted');
                
                listItem.innerHTML = `
                    <i class="bi ${icon} ${iconColor} me-3"></i>
                    <span class="flex-grow-1">${escapeHtml(item.name)}</span>
                `;
                
                listItem.addEventListener('click', function(e) {
                    e.preventDefault();
                    if (item.type === 'directory') {
                        loadDirectoryContents(item.path);
                    } else if (AppState.currentBrowserType === 'file') {
                        const currentPath = document.getElementById('current-path');
                        if (currentPath) {
                            currentPath.value = item.path;
                        }
                    }
                });
                
                fileList.appendChild(listItem);
            });
        })
        .catch(error => {
            console.error('Error loading directory:', error);
            fileList.innerHTML = '<div class="alert alert-danger">Error loading directory contents</div>';
        });
}

function selectCurrentPath() {
    const currentPath = document.getElementById('current-path');
    if (!currentPath || !AppState.currentTargetInput) return;
    
    const targetInput = document.getElementById(AppState.currentTargetInput);
    if (targetInput) {
        targetInput.value = currentPath.value;
        
        // Trigger change event to save settings
        targetInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
    
    const modal = bootstrap.Modal.getInstance(document.getElementById('file-browser-modal'));
    if (modal) {
        modal.hide();
    }
}

/**
 * Notifications
 */
function showNotification(message, type = 'info') {
    const toast = document.getElementById('notification-toast');
    if (!toast) return;
    
    const toastBody = toast.querySelector('.toast-body');
    const toastHeader = toast.querySelector('.toast-header');
    
    if (toastBody) {
        toastBody.textContent = message;
    }
    
    // Update icon and color based on type
    if (toastHeader) {
        const icon = toastHeader.querySelector('i');
        if (icon) {
            icon.className = `bi me-2 ${getNotificationIcon(type)} ${getNotificationColor(type)}`;
        }
    }
    
    const bsToast = new bootstrap.Toast(toast, {
        delay: type === 'error' ? 8000 : 4000 // Show errors longer
    });
    bsToast.show();
}

function getNotificationIcon(type) {
    const icons = {
        'success': 'bi-check-circle-fill',
        'error': 'bi-exclamation-triangle-fill',
        'warning': 'bi-exclamation-circle-fill',
        'info': 'bi-info-circle-fill'
    };
    return icons[type] || icons.info;
}

function getNotificationColor(type) {
    const colors = {
        'success': 'text-success',
        'error': 'text-danger',
        'warning': 'text-warning',
        'info': 'text-primary'
    };
    return colors[type] || colors.info;
}

/**
 * Utility Functions
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * File Browser Functions
 */
function browseFolder(targetInputId) {
    AppState.currentTargetInput = targetInputId;
    AppState.currentBrowserType = 'directory';
    
    const browserType = document.getElementById('browser-type');
    if (browserType) {
        browserType.textContent = 'Folder';
    }
    
    openFileBrowser();
}

function browseFile(targetInputId) {
    AppState.currentTargetInput = targetInputId;
    AppState.currentBrowserType = 'file';
    
    const browserType = document.getElementById('browser-type');
    if (browserType) {
        browserType.textContent = 'File';
    }
    
    openFileBrowser();
}

function openFileBrowser(path = null) {
    const modalElement = document.getElementById('file-browser-modal');
    if (!modalElement) {
        showNotification('File browser not available', 'error');
        return;
    }
    
    const modal = new bootstrap.Modal(modalElement);
    modal.show();
    
    const startPath = path || (AppState.currentTargetInput ? document.getElementById(AppState.currentTargetInput).value : '') || '';
    loadDirectoryContents(startPath);
}

function loadDirectoryContents(path) {
    const fileList = document.getElementById('file-list');
    if (!fileList) return;
    
    fileList.innerHTML = '<div class="text-center p-3"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div></div>';
    
    const url = `/api/browse?path=${encodeURIComponent(path)}&type=${AppState.currentBrowserType}`;
    
    fetch(url)
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            const currentPath = document.getElementById('current-path');
            if (currentPath) {
                currentPath.value = data.current_path;
            }
            
            fileList.innerHTML = '';
            
            if (!data.items || data.items.length === 0) {
                fileList.innerHTML = '<div class="text-center p-3 text-muted">No items found</div>';
                return;
            }
            
            data.items.forEach(item => {
                const listItem = document.createElement('a');
                listItem.className = 'list-group-item list-group-item-action d-flex align-items-center';
                listItem.href = '#';
                
                let icon = 'bi-file-earmark';
                let iconColor = 'text-muted';
                
                if (item.type === 'directory') {
                    icon = item.is_parent ? 'bi-arrow-up' : 'bi-folder-fill';
                    iconColor = item.is_parent ? 'text-secondary' : 'text-primary';
                }
                
                // Special styling for shortcuts
                if (item.is_shortcut) {
                    iconColor = 'text-info';
                }
                
                listItem.innerHTML = `
                    <i class="bi ${icon} ${iconColor} me-3"></i>
                    <span class="flex-grow-1">${escapeHtml(item.name)}</span>
                `;
                
                listItem.addEventListener('click', function(e) {
                    e.preventDefault();
                    if (item.type === 'directory') {
                        loadDirectoryContents(item.path);
                    } else if (AppState.currentBrowserType === 'file') {
                        const currentPath = document.getElementById('current-path');
                        if (currentPath) {
                            currentPath.value = item.path;
                        }
                    }
                });
                
                fileList.appendChild(listItem);
            });
        })
        .catch(error => {
            console.error('Error loading directory:', error);
            fileList.innerHTML = '<div class="alert alert-danger">Error loading directory contents</div>';
        });
}

function selectCurrentPath() {
    const selectedPath = document.getElementById('current-path').value;
    if (!selectedPath || !AppState.currentTargetInput) return;
    
    document.getElementById(AppState.currentTargetInput).value = selectedPath;
    
    const modal = bootstrap.Modal.getInstance(document.getElementById('file-browser-modal'));
    modal.hide();
    
    // Trigger change event to save settings
    document.getElementById(AppState.currentTargetInput).dispatchEvent(new Event('change'));
}

// Export functions to global scope for inline event handlers
window.showImageUploader = showImageUploader;
window.showStockRemover = showStockRemover;
window.hideAllSections = hideAllSections;
window.hideProcessStatus = hideProcessStatus;
window.stopProcess = stopProcess;
window.clearLogs = clearLogs;
window.browseFolder = browseFolder;
window.browseFile = browseFile;
window.selectCurrentPath = selectCurrentPath;
