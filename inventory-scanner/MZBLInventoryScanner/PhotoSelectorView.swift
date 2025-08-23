import SwiftUI
import Photos

struct PhotoThumbnailView: View {
    let asset: PHAsset
    let isSelected: Bool
    @Binding var thumbnails: [String: UIImage]
    let onTap: () -> Void
    
    var body: some View {
        ZStack {
            if let thumbnail = thumbnails[asset.localIdentifier] {
                Image(uiImage: thumbnail)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(width: 100, height: 100)
                    .clipped()
            } else {
                Rectangle()
                    .fill(Color.gray.opacity(0.3))
                    .frame(width: 100, height: 100)
                    .overlay(
                        ProgressView()
                            .scaleEffect(0.8)
                    )
                    .onAppear {
                        loadThumbnail(for: asset)
                    }
            }
            
            // Selection overlay
            if isSelected {
                Rectangle()
                    .fill(Color.blue.opacity(0.3))
                    .frame(width: 100, height: 100)
                
                VStack {
                    HStack {
                        Spacer()
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.blue)
                            .background(Color.white)
                            .clipShape(Circle())
                            .padding(4)
                    }
                    Spacer()
                }
                .frame(width: 100, height: 100)
            }
        }
        .cornerRadius(8)
        .contentShape(Rectangle()) // Ensures entire area is tappable
        .onTapGesture {
            onTap()
        }
    }
    
    private func loadThumbnail(for asset: PHAsset) {
        let manager = PHImageManager.default()
        let options = PHImageRequestOptions()
        options.deliveryMode = .opportunistic
        options.resizeMode = .fast
        options.isSynchronous = false
        options.isNetworkAccessAllowed = true
        
        manager.requestImage(
            for: asset,
            targetSize: CGSize(width: 200, height: 200), // Increased size for better quality
            contentMode: .aspectFill,
            options: options
        ) { image, _ in
            if let image = image {
                DispatchQueue.main.async {
                    thumbnails[asset.localIdentifier] = image
                }
            }
        }
    }
}

struct PhotoSelectorView: View {
    let scannedSKU: String
    let onComplete: () -> Void
    
    @EnvironmentObject var appSettings: AppSettings
    @State private var selectedImages: [PHAsset] = []
    @State private var allPhotos: [PHAsset] = []
    @State private var thumbnails: [String: UIImage] = [:]
    @State private var showingAlert = false
    @State private var alertTitle = ""
    @State private var alertMessage = ""
    @State private var alertAction: (() -> Void)? = nil
    @State private var isProcessing = false
    @State private var existingPhotosCount = 0
    @State private var existingPhotosDate = ""
    @State private var showingToast = false
    @State private var toastMessage = ""
    @State private var isCheckingExistingPhotos = false
    
    private let imageManager = PHImageManager.default()
    private let imageRequestOptions: PHImageRequestOptions = {
        let options = PHImageRequestOptions()
        options.deliveryMode = .highQualityFormat
        options.resizeMode = .exact
        options.isSynchronous = false
        options.isNetworkAccessAllowed = true
        return options
    }()
    
    var body: some View {
        VStack(spacing: 0) {
            // Fixed header with SKU
            VStack(spacing: 8) {
                Text("SKU: \(scannedSKU)")
                    .font(.title2)
                    .fontWeight(.bold)
                    .padding(.horizontal)
                
                Text("\(selectedImages.count) of \(allPhotos.count) photos selected")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }
            .padding(.vertical, 16)
            .frame(maxWidth: .infinity)
            .background(Color(.systemBackground))
            .overlay(
                Rectangle()
                    .frame(height: 0.5)
                    .foregroundColor(Color(.separator)),
                alignment: .bottom
            )
            
            // Scrollable photo gallery
            if allPhotos.isEmpty {
                // Empty state
                VStack(spacing: 20) {
                    Spacer()
                    
                    Image(systemName: "photo.on.rectangle")
                        .font(.system(size: 50))
                        .foregroundColor(.secondary)
                    
                    Text("No photos available")
                        .font(.title2)
                        .fontWeight(.medium)
                    
                    Text("Add photos to your photo library to get started")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                    
                    Button("Reload") {
                        requestPhotoLibraryAccess()
                    }
                    .buttonStyle(.borderedProminent)
                    
                    Spacer()
                }
                .padding()
            } else {
                ScrollView {
                    LazyVGrid(columns: [
                        GridItem(.adaptive(minimum: 100), spacing: 2)
                    ], spacing: 2) {
                        ForEach(allPhotos, id: \.localIdentifier) { asset in
                            PhotoThumbnailView(
                                asset: asset,
                                isSelected: selectedImages.contains(asset),
                                thumbnails: $thumbnails
                            ) {
                                toggleSelection(asset)
                            }
                        }
                    }
                    .padding(.horizontal, 4)
                    .padding(.bottom, 80) // Space for fixed bottom buttons
                }
            }
            
            // Fixed bottom buttons
            VStack(spacing: 0) {
                Rectangle()
                    .frame(height: 0.5)
                    .foregroundColor(Color(.separator))
                
                HStack(spacing: 20) {
                    Button(action: {
                        onComplete()
                    }) {
                        Text("Cancel")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .frame(minHeight: 44) // Ensure minimum touch target
                            .background(Color(.systemGray5))
                            .foregroundColor(.primary)
                            .cornerRadius(8)
                    }
                    .buttonStyle(PlainButtonStyle()) // Remove default button styling
                    
                    Button(action: {
                        copyPhotosToDestination()
                    }) {
                        Text("OK")
                            .font(.headline)
                            .frame(maxWidth: .infinity)
                            .frame(minHeight: 44) // Ensure minimum touch target
                            .background(selectedImages.isEmpty ? Color(.systemGray4) : Color.accentColor)
                            .foregroundColor(selectedImages.isEmpty ? Color(.systemGray2) : .white)
                            .cornerRadius(8)
                    }
                    .buttonStyle(PlainButtonStyle()) // Remove default button styling
                    .disabled(selectedImages.isEmpty || isProcessing)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Color(.systemBackground))
            }
        }
        .overlay(
            // Toast notification
            VStack {
                if showingToast {
                    Text(toastMessage)
                        .font(.subheadline)
                        .foregroundColor(.white)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(Color.black.opacity(0.8))
                        .cornerRadius(8)
                        .transition(.move(edge: .top).combined(with: .opacity))
                        .zIndex(1)
                }
                Spacer()
            }
            .padding(.top, 50)
            .animation(.easeInOut(duration: 0.3), value: showingToast)
        )
        .onAppear {
            checkForExistingPhotos()
        }
        .alert(alertTitle, isPresented: $showingAlert) {
            Button("OK") {
                alertAction?()
            }
        } message: {
            Text(alertMessage)
        }
    }
    
    private func checkForExistingPhotos() {
        // Prevent multiple simultaneous checks
        guard !isCheckingExistingPhotos else {
            print("📁 Already checking existing photos, skipping...")
            return
        }
        
        isCheckingExistingPhotos = true
        print("📁 Starting existing photos check for SKU: \(scannedSKU)")
        
        // Run this check in background to avoid blocking UI
        DispatchQueue.global(qos: .userInitiated).async {
            // Restore access to security-scoped resource before checking
            let hasAccess = self.restoreSecurityScopedAccess()
            if !hasAccess {
                // If we can't access the folder, just proceed with photo selection
                // The error will be shown when user tries to save
                DispatchQueue.main.async {
                    self.isCheckingExistingPhotos = false
                    self.requestPhotoLibraryAccess()
                }
                return
            }
        
            let inventoryFolderURL = URL(fileURLWithPath: self.appSettings.expandedInventoryPath)
            
            // Check if inventory folder exists
            guard FileManager.default.fileExists(atPath: inventoryFolderURL.path) else {
                // No inventory folder exists, proceed normally
                DispatchQueue.main.async {
                    self.isCheckingExistingPhotos = false
                    self.requestPhotoLibraryAccess()
                }
                return
            }
        
        do {
            // Get all contents of inventory folder (all date folders)
            let inventoryContents = try FileManager.default.contentsOfDirectory(at: inventoryFolderURL, includingPropertiesForKeys: [.isDirectoryKey])
            print("📁 Checking \(inventoryContents.count) items in inventory folder")
            
            // Filter for directories that match date format (YYYY-MM-DD)
            let dateFormatter = DateFormatter()
            dateFormatter.dateFormat = "yyyy-MM-dd"
            
            for dateFolder in inventoryContents {
                do {
                    // Check if it's a directory
                    var isDirectory: ObjCBool = false
                    guard FileManager.default.fileExists(atPath: dateFolder.path, isDirectory: &isDirectory),
                          isDirectory.boolValue else { continue }
                    
                    let dateFolderName = dateFolder.lastPathComponent
                    
                    // Validate date format (optional - helps filter out non-date folders)
                    guard dateFolderName.count == 10 && dateFolderName.contains("-") else { continue }
                    
                    // Check for SKU folder inside this date folder
                    let skuFolderURL = dateFolder.appendingPathComponent(scannedSKU)
                    
                    guard FileManager.default.fileExists(atPath: skuFolderURL.path) else { continue }
                    
                    // Count image files in the SKU folder
                    let skuContents = try FileManager.default.contentsOfDirectory(at: skuFolderURL, includingPropertiesForKeys: nil)
                    
                    // Filter for image files (common extensions)
                    // Note: We now convert all images to JPEG, but check for all formats for backward compatibility
                    let imageExtensions = ["jpg", "jpeg", "png", "heic", "heif"]
                    let imageFiles = skuContents.filter { url in
                        imageExtensions.contains(url.pathExtension.lowercased())
                    }
                    
                    if imageFiles.count > 0 {
                        print("⚠️ Found \(imageFiles.count) existing photos for SKU \(self.scannedSKU) in \(dateFolderName)")
                        // Found existing photos, show warning on main thread
                        DispatchQueue.main.async {
                            self.isCheckingExistingPhotos = false
                            self.showExistingPhotosAlert(count: imageFiles.count, date: dateFolderName)
                        }
                        return
                    }
                } catch {
                    print("⚠️ Error checking date folder \(dateFolder.lastPathComponent): \(error)")
                    // Continue checking other folders even if one fails
                    continue
                }
            }
            print("✅ No existing photos found for SKU \(self.scannedSKU)")
        } catch {
            print("❌ Error checking existing photos: \(error)")
            // On error, proceed with photo selection anyway
        }
        
        // No existing photos found across all dates, proceed normally
        DispatchQueue.main.async {
            self.isCheckingExistingPhotos = false
            self.requestPhotoLibraryAccess()
        }
        }
    }
    
    private func toggleSelection(_ asset: PHAsset) {
        if let index = selectedImages.firstIndex(of: asset) {
            selectedImages.remove(at: index)
        } else {
            selectedImages.append(asset)
        }
    }
    
    private func requestPhotoLibraryAccess() {
        let currentStatus = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        print("🔍 Current permission status: \(currentStatus.rawValue)")
        
        if currentStatus == .authorized || currentStatus == .limited {
            print("🔍 Already authorized, loading photos directly")
            loadPhotos()
            return
        }
        
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            print("🔍 Permission request result: \(status.rawValue)")
            DispatchQueue.main.async {
                switch status {
                case .authorized, .limited:
                    print("🔍 Permission granted, loading photos")
                    self.loadPhotos()
                case .denied, .restricted:
                    print("🔍 Permission denied")
                    break
                case .notDetermined:
                    print("🔍 Permission still not determined")
                    break
                @unknown default:
                    break
                }
            }
        }
    }
    
    private func loadPhotos() {
        let fetchOptions = PHFetchOptions()
        fetchOptions.sortDescriptors = [NSSortDescriptor(key: "creationDate", ascending: false)]
        
        let fetchResult = PHAsset.fetchAssets(with: .image, options: fetchOptions)
        
        var photos: [PHAsset] = []
        fetchResult.enumerateObjects { asset, _, _ in
            photos.append(asset)
        }
        
        self.allPhotos = photos
    }
    
    private func copyPhotosToDestination() {
        guard !selectedImages.isEmpty else { return }
        
        isProcessing = true
        
        // Restore access to security-scoped resource before creating folders
        let hasAccess = restoreSecurityScopedAccess()
        if !hasAccess {
            showAlert(title: "Permission Error", message: "Cannot access the selected folder. Please reselect the folder in Settings.")
            isProcessing = false
            return
        }
        
        // Create folder structure: InventoryFolder/MM-DD-YYYY/SKU
        let inventoryFolderURL = URL(fileURLWithPath: appSettings.expandedInventoryPath)
        print("📁 Inventory folder path: \(inventoryFolderURL.path)")
        
        // Create date folder in YYYY-MM-DD format
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"
        let dateString = dateFormatter.string(from: Date())
        let dateFolderURL = inventoryFolderURL.appendingPathComponent(dateString)
        
        // Create SKU folder inside date folder
        let skuFolderURL = dateFolderURL.appendingPathComponent(scannedSKU)
        print("📁 Creating folder: \(skuFolderURL.path)")
        
        do {
            try FileManager.default.createDirectory(at: skuFolderURL, withIntermediateDirectories: true, attributes: nil)
            print("✅ Successfully created folder: \(skuFolderURL.path)")
        } catch {
            print("❌ Failed to create folder: \(error)")
            print("❌ Error details: \(error.localizedDescription)")
            print("❌ Attempted path: \(skuFolderURL.path)")
            
            showAlert(title: "Error", message: "Failed to create folder: \(error.localizedDescription)")
            isProcessing = false
            return
        }
        
        let dispatchGroup = DispatchGroup()
        var successCount = 0
        var errors: [String] = []
        
        for asset in selectedImages {
            dispatchGroup.enter()
            
            let resources = PHAssetResource.assetResources(for: asset)
            let originalFileName = resources.first?.originalFilename ?? "IMG_\(asset.localIdentifier)"
            
            // Always use .jpg extension for JPEG conversion
            let baseFileName = (originalFileName as NSString).deletingPathExtension
            let fileName = "\(baseFileName).jpg"
            let destinationURL = skuFolderURL.appendingPathComponent(fileName)
            
            // Request full-size image for conversion to JPEG
            let fullSizeOptions = PHImageRequestOptions()
            fullSizeOptions.deliveryMode = .highQualityFormat
            fullSizeOptions.resizeMode = .none
            fullSizeOptions.isSynchronous = false
            fullSizeOptions.isNetworkAccessAllowed = true
            
            imageManager.requestImage(for: asset, targetSize: PHImageManagerMaximumSize, contentMode: .default, options: fullSizeOptions) { image, _ in
                defer { dispatchGroup.leave() }
                
                guard let image = image else {
                    errors.append("Failed to get image for \(fileName)")
                    return
                }
                
                // Convert to JPEG with high quality (0.9 compression)
                guard let jpegData = image.jpegData(compressionQuality: 0.9) else {
                    errors.append("Failed to convert \(fileName) to JPEG")
                    return
                }
                
                do {
                    try jpegData.write(to: destinationURL)
                    successCount += 1
                    print("✅ Converted and saved \(fileName) as JPEG")
                } catch {
                    errors.append("Failed to save \(fileName): \(error.localizedDescription)")
                }
            }
        }
        
        dispatchGroup.notify(queue: .main) {
            self.isProcessing = false
            
            if successCount == self.selectedImages.count {
                let dateFormatter = DateFormatter()
                dateFormatter.dateFormat = "yyyy-MM-dd"
                let dateString = dateFormatter.string(from: Date())
                self.showToast("Copied \(successCount) photos to \(dateString)/\(self.scannedSKU)")
                
                // Delay before proceeding to allow toast to be seen
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                    if self.appSettings.deletePhotosAfterScan {
                        self.deleteSelectedPhotos()
                    } else {
                        self.onComplete()
                    }
                }
            } else {
                let errorMessage = "Copied \(successCount) of \(self.selectedImages.count) photos.\n\nErrors:\n" + errors.joined(separator: "\n")
                self.showAlert(title: "Partial Success", message: errorMessage) {
                    self.onComplete()
                }
            }
        }
    }
    
    private func deleteSelectedPhotos() {
        PHPhotoLibrary.shared().performChanges {
            PHAssetChangeRequest.deleteAssets(self.selectedImages as NSArray)
        } completionHandler: { success, error in
            DispatchQueue.main.async {
                if success {
                    let dateFormatter = DateFormatter()
                    dateFormatter.dateFormat = "yyyy-MM-dd"
                    let dateString = dateFormatter.string(from: Date())
                    self.showToast("Copied \(self.selectedImages.count) photos to \(dateString)/\(self.scannedSKU)")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        self.onComplete()
                    }
                } else {
                    self.showAlert(title: "Warning", message: "Photos copied but could not be deleted: \(error?.localizedDescription ?? "Unknown error")") {
                        self.onComplete()
                    }
                }
            }
        }
    }
    
    private func restoreSecurityScopedAccess() -> Bool {
        guard let bookmarkData = UserDefaults.standard.data(forKey: "folderBookmark") else {
            print("📁 No folder bookmark found - using default path")
            return true // Assume it's the default path which should work
        }
        
        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmarkData, options: .withoutUI, relativeTo: nil, bookmarkDataIsStale: &isStale)
            
            if isStale {
                print("⚠️ Bookmark is stale, user needs to reselect folder")
                return false
            }
            
            guard url.startAccessingSecurityScopedResource() else {
                print("❌ Failed to restore access to security-scoped resource")
                return false
            }
            
            print("✅ Restored access to folder: \(url.path)")
            return true
            
        } catch {
            print("❌ Failed to resolve bookmark: \(error)")
            return false
        }
    }
    
    private func showToast(_ message: String) {
        toastMessage = message
        withAnimation(.easeInOut(duration: 0.3)) {
            showingToast = true
        }
        
        // Auto-hide after 1.5 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
            withAnimation(.easeInOut(duration: 0.3)) {
                self.showingToast = false
            }
        }
    }
    
    private func showAlert(title: String, message: String, action: (() -> Void)? = nil) {
        alertTitle = title
        alertMessage = message
        alertAction = action
        showingAlert = true
    }
    
    private func showExistingPhotosAlert(count: Int, date: String) {
        showAlert(
            title: "Photos Already Exist",
            message: "Found \(count) photos for \(scannedSKU) from \(date), delete them manually first",
            action: {
                self.onComplete() // Go back to main screen
            }
        )
    }
}

#Preview {
    PhotoSelectorView(scannedSKU: "123456789") {
        print("Photo selection completed")
    }
    .environmentObject(AppSettings())
}