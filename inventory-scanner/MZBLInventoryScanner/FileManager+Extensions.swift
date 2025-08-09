import Foundation

extension FileManager {
    /// Creates a directory at the specified path if it doesn't exist
    func createDirectoryIfNeeded(at url: URL) throws {
        var isDirectory: ObjCBool = false
        
        if fileExists(atPath: url.path, isDirectory: &isDirectory) {
            if !isDirectory.boolValue {
                throw NSError(domain: "FileManagerError", code: 1, userInfo: [
                    NSLocalizedDescriptionKey: "File exists at path but is not a directory"
                ])
            }
        } else {
            try createDirectory(at: url, withIntermediateDirectories: true, attributes: nil)
        }
    }
    
    /// Returns the size of a directory in bytes
    func sizeOfDirectory(at url: URL) -> Int64 {
        guard let enumerator = enumerator(at: url, includingPropertiesForKeys: [.fileSizeKey], options: [.skipsHiddenFiles]) else {
            return 0
        }
        
        var totalSize: Int64 = 0
        
        for case let fileURL as URL in enumerator {
            do {
                let resourceValues = try fileURL.resourceValues(forKeys: [.fileSizeKey])
                totalSize += Int64(resourceValues.fileSize ?? 0)
            } catch {
                continue
            }
        }
        
        return totalSize
    }
    
    /// Returns a formatted string representation of file size
    static func formattedSize(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }
    
    /// Checks if a directory exists and is not empty
    func directoryExistsAndNotEmpty(at path: String) -> Bool {
        var isDirectory: ObjCBool = false
        
        guard fileExists(atPath: path, isDirectory: &isDirectory), isDirectory.boolValue else {
            return false
        }
        
        do {
            let contents = try contentsOfDirectory(atPath: path)
            return !contents.isEmpty
        } catch {
            return false
        }
    }
}
