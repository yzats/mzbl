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
        // Default path: ~/Library/Mobile Documents/com~apple~CloudDocs/MZBL
        let defaultPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
            .appendingPathComponent("../Library/Mobile Documents/com~apple~CloudDocs/MZBL")
            .standardizedFileURL.path ?? "~/Library/Mobile Documents/com~apple~CloudDocs/MZBL"
        
        self.inventoryFolderPath = UserDefaults.standard.string(forKey: "inventoryFolderPath") ?? defaultPath
        self.deletePhotosAfterScan = UserDefaults.standard.bool(forKey: "deletePhotosAfterScan")
    }
    
    var expandedInventoryPath: String {
        return NSString(string: inventoryFolderPath).expandingTildeInPath
    }
}
