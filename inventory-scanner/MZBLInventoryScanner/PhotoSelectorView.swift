import SwiftUI
import PhotosUI
import Photos

struct PhotoSelectorView: View {
    let scannedSKU: String
    let onComplete: () -> Void
    
    @EnvironmentObject var appSettings: AppSettings
    @State private var selectedImages: [PHAsset] = []
    @State private var allPhotos: [PHAsset] = []
    @State private var showingAlert = false
    @State private var alertTitle = ""
    @State private var alertMessage = ""
    @State private var isProcessing = false
    @State private var showingExistingPhotosAlert = false
    
    private let imageManager = PHImageManager.default()
    private let imageRequestOptions: PHImageRequestOptions = {
        let options = PHImageRequestOptions()
        options.deliveryMode = .highQualityFormat
        options.isNetworkAccessAllowed = true
        return options
    }()
    
    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                // Fixed SKU header
                VStack {
                    Text("SKU: \(scannedSKU)")
                        .font(.title2)
                        .fontWeight(.bold)
                        .padding()
                        .frame(maxWidth: .infinity)
                        .background(Color(.systemGray6))
                }
                
                // Photo gallery
                if allPhotos.isEmpty {
                    VStack {
                        Spacer()
                        Image(systemName: "photo.on.rectangle")
                            .font(.system(size: 50))
                            .foregroundColor(.gray)
                        Text("No photos available")
                            .font(.headline)
                            .foregroundColor(.gray)
                        Text("Grant photo library access to select photos")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                        Spacer()
                    }
                } else {
                    ScrollView {
                        LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 2), count: 3), spacing: 2) {
                            ForEach(allPhotos.indices, id: \.self) { index in
                                PhotoThumbnailView(
                                    asset: allPhotos[index],
                                    isSelected: selectedImages.contains(allPhotos[index]),
                                    imageManager: imageManager,
                                    imageRequestOptions: imageRequestOptions
                                ) {
                                    toggleSelection(allPhotos[index])
                                }
                            }
                        }
                        .padding(.horizontal, 1)
                    }
                }
                
                // Fixed bottom buttons
                VStack {
                    if !selectedImages.isEmpty {
                        Text("\(selectedImages.count) photo\(selectedImages.count == 1 ? "" : "s") selected")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .padding(.top, 8)
                    }
                    
                    HStack(spacing: 20) {
                        Button("Cancel") {
                            onComplete()
                        }
                        .frame(maxWidth: .infinity)
                        .frame(height: 50)
                        .background(Color(.systemGray5))
                        .foregroundColor(.primary)
                        .cornerRadius(8)
                        
                        Button("OK") {
                            processSelectedPhotos()
                        }
                        .disabled(selectedImages.isEmpty || isProcessing)
                        .frame(maxWidth: .infinity)
                        .frame(height: 50)
                        .background(selectedImages.isEmpty ? Color(.systemGray4) : Color.blue)
                        .foregroundColor(.white)
                        .cornerRadius(8)
                        .overlay(
                            Group {
                                if isProcessing {
                                    ProgressView()
                                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                        .scaleEffect(0.8)
                                }
                            }
                        )
                    }
                    .padding()
                }
                .background(Color(.systemBackground))
            }
            .navigationTitle("Select Photos")
            .navigationBarTitleDisplayMode(.inline)
            .navigationBarHidden(false)
        }
        .onAppear {
            requestPhotoLibraryAccess()
        }
        .alert(alertTitle, isPresented: $showingAlert) {
            Button("OK") { }
        } message: {
            Text(alertMessage)
        }
        .alert("Photos Already Exist", isPresented: $showingExistingPhotosAlert) {
            Button("Cancel") { }
            Button("Proceed") {
                copyPhotosToDestination()
            }
        } message: {
            Text("Photos for this SKU already exist in the destination folder. Do you want to proceed?")
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
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            DispatchQueue.main.async {
                switch status {
                case .authorized, .limited:
                    loadPhotos()
                case .denied, .restricted:
                    alertTitle = "Photo Access Denied"
                    alertMessage = "Please grant photo library access in Settings to select photos."
                    showingAlert = true
                case .notDetermined:
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
    
    private func processSelectedPhotos() {
        isProcessing = true
        
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "MM-dd-yyyy"
        let dateFolder = dateFormatter.string(from: Date())
        
        let destinationPath = "\(appSettings.expandedInventoryPath)/\(dateFolder)/\(scannedSKU)"
        let destinationURL = URL(fileURLWithPath: destinationPath)
        
        // Check if folder exists and has content
        if FileManager.default.fileExists(atPath: destinationPath) {
            do {
                let contents = try FileManager.default.contentsOfDirectory(atPath: destinationPath)
                if !contents.isEmpty {
                    isProcessing = false
                    showingExistingPhotosAlert = true
                    return
                }
            } catch {
                // If we can't read the directory, proceed anyway
            }
        }
        
        copyPhotosToDestination()
    }
    
    private func copyPhotosToDestination() {
        guard !selectedImages.isEmpty else { return }
        
        isProcessing = true
        
        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "MM-dd-yyyy"
        let dateFolder = dateFormatter.string(from: Date())
        
        let destinationPath = "\(appSettings.expandedInventoryPath)/\(dateFolder)/\(scannedSKU)"
        let destinationURL = URL(fileURLWithPath: destinationPath)
        
        // Create destination directory
        do {
            try FileManager.default.createDirectory(at: destinationURL, withIntermediateDirectories: true, attributes: nil)
        } catch {
            DispatchQueue.main.async {
                self.isProcessing = false
                self.alertTitle = "Error"
                self.alertMessage = "Failed to create destination folder: \(error.localizedDescription)"
                self.showingAlert = true
            }
            return
        }
        
        let group = DispatchGroup()
        var errors: [Error] = []
        var processedCount = 0
        
        for (index, asset) in selectedImages.enumerated() {
            group.enter()
            
            // Get original filename from PHAsset, with fallback to generic name
            let originalFileName = PHAssetResource.assetResources(for: asset).first?.originalFilename ?? "photo_\(index + 1).jpg"
            
            // Ensure the file has a .jpg extension for consistency
            let fileName: String
            if originalFileName.lowercased().hasSuffix(".jpg") || originalFileName.lowercased().hasSuffix(".jpeg") {
                fileName = originalFileName
            } else {
                // Replace extension with .jpg
                let nameWithoutExtension = URL(fileURLWithPath: originalFileName).deletingPathExtension().lastPathComponent
                fileName = "\(nameWithoutExtension).jpg"
            }
            
            let fileURL = destinationURL.appendingPathComponent(fileName)
            
            imageManager.requestImageDataAndOrientation(for: asset, options: imageRequestOptions) { data, dataUTI, orientation, info in
                defer { group.leave() }
                
                guard let data = data else {
                    errors.append(NSError(domain: "PhotoError", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to get image data"]))
                    return
                }
                
                do {
                    // Convert to JPEG if needed
                    let imageData: Data
                    if dataUTI == "public.jpeg" {
                        imageData = data
                    } else {
                        guard let image = UIImage(data: data),
                              let jpegData = image.jpegData(compressionQuality: 0.8) else {
                            errors.append(NSError(domain: "PhotoError", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to convert image to JPEG"]))
                            return
                        }
                        imageData = jpegData
                    }
                    
                    try imageData.write(to: fileURL)
                    processedCount += 1
                    
                    // Delete original photo if setting is enabled
                    if self.appSettings.deletePhotosAfterScan {
                        PHPhotoLibrary.shared().performChanges {
                            PHAssetChangeRequest.deleteAssets([asset] as NSArray)
                        }
                    }
                } catch {
                    errors.append(error)
                }
            }
        }
        
        group.notify(queue: .main) {
            self.isProcessing = false
            
            if errors.isEmpty {
                self.alertTitle = "Success"
                self.alertMessage = "\(processedCount) photo\(processedCount == 1 ? "" : "s") copied successfully to \(destinationPath)"
                self.showingAlert = true
                
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                    self.onComplete()
                }
            } else {
                self.alertTitle = "Partial Success"
                self.alertMessage = "\(processedCount) of \(self.selectedImages.count) photos copied. \(errors.count) error\(errors.count == 1 ? "" : "s") occurred."
                self.showingAlert = true
            }
        }
    }
}

struct PhotoThumbnailView: View {
    let asset: PHAsset
    let isSelected: Bool
    let imageManager: PHImageManager
    let imageRequestOptions: PHImageRequestOptions
    let onTap: () -> Void
    
    @State private var thumbnail: UIImage?
    
    var body: some View {
        ZStack {
            if let thumbnail = thumbnail {
                Image(uiImage: thumbnail)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(width: 120, height: 120)
                    .clipped()
            } else {
                Rectangle()
                    .fill(Color(.systemGray5))
                    .frame(width: 120, height: 120)
                    .overlay(
                        ProgressView()
                            .scaleEffect(0.8)
                    )
            }
            
            // Selection overlay
            if isSelected {
                Rectangle()
                    .fill(Color.blue.opacity(0.3))
                    .frame(width: 120, height: 120)
                
                VStack {
                    HStack {
                        Spacer()
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.blue)
                            .background(Color.white)
                            .clipShape(Circle())
                            .font(.title2)
                            .padding(8)
                    }
                    Spacer()
                }
            }
        }
        .onTapGesture {
            onTap()
        }
        .onAppear {
            loadThumbnail()
        }
    }
    
    private func loadThumbnail() {
        let targetSize = CGSize(width: 120, height: 120)
        
        imageManager.requestImage(
            for: asset,
            targetSize: targetSize,
            contentMode: .aspectRatio,
            options: imageRequestOptions
        ) { image, _ in
            DispatchQueue.main.async {
                self.thumbnail = image
            }
        }
    }
}

#Preview {
    PhotoSelectorView(scannedSKU: "123456789") {
        print("Photo selection completed")
    }
    .environmentObject(AppSettings())
}
