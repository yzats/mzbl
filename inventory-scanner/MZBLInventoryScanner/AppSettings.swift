import Foundation

class AppSettings: ObservableObject {
    @Published var inventoryFolderPath: String {
        didSet {
            UserDefaults.standard.set(inventoryFolderPath, forKey: "inventoryFolderPath")
        }
    }
    
    @Published var deletePhotosAfterScan: Bool {
        didSet {
            UserDefaults.standard.set(deletePhotosAfterScan, forKey: "deletePhotosAfterScan")
        }
    }
    
    init() {
        // Default path: iCloud Drive MZBL/SQS Upload folder
        let defaultPath: String
        if let iCloudURL = FileManager.default.url(forUbiquityContainerIdentifier: nil)?.appendingPathComponent("MZBL/SQS Upload") {
            defaultPath = iCloudURL.path
        } else {
            // Fallback to local Documents if iCloud is not available
            defaultPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
                .appendingPathComponent("MZBL/SQS Upload")
                .path ?? NSHomeDirectory() + "/Documents/MZBL/SQS Upload"
        }
        
        self.inventoryFolderPath = UserDefaults.standard.string(forKey: "inventoryFolderPath") ?? defaultPath
        self.deletePhotosAfterScan = UserDefaults.standard.bool(forKey: "deletePhotosAfterScan")
        
        // Restore access to security-scoped resource if we have a bookmark
        restoreFolderAccess()
    }
    
    private func restoreFolderAccess() {
        guard let bookmarkData = UserDefaults.standard.data(forKey: "folderBookmark") else {
            print("📁 No folder bookmark found")
            return
        }
        
        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmarkData, options: .withoutUI, relativeTo: nil, bookmarkDataIsStale: &isStale)
            
            if isStale {
                print("⚠️ Bookmark is stale, user needs to reselect folder")
                return
            }
            
            guard url.startAccessingSecurityScopedResource() else {
                print("❌ Failed to restore access to security-scoped resource")
                return
            }
            
            print("✅ Restored access to folder: \(url.path)")
            
        } catch {
            print("❌ Failed to resolve bookmark: \(error)")
        }
    }
    
    var expandedInventoryPath: String {
        // On iOS, always use the path as-is since it should be within the app's sandbox
        // Don't expand tildes (~) as they don't work reliably on iOS devices
        return inventoryFolderPath
    }
}
