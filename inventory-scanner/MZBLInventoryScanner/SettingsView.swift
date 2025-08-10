import SwiftUI
import UniformTypeIdentifiers

struct SettingsView: View {
    @EnvironmentObject var appSettings: AppSettings
    @Environment(\.presentationMode) var presentationMode
    @State private var showingFolderPicker = false
    
    private var folderDisplayName: String {
        let path = appSettings.inventoryFolderPath
        let components = path.components(separatedBy: "/")
        
        // Try to show as much of the tail as possible while keeping it readable
        if components.count <= 2 {
            return path
        }
        
        // Show the last 2-3 components depending on length
        let lastTwo = components.suffix(2).joined(separator: "/")
        let lastThree = components.suffix(3).joined(separator: "/")
        
        // If the last 3 components are reasonably short, use them
        if lastThree.count <= 40 {
            return ".../" + lastThree
        } else if lastTwo.count <= 30 {
            return ".../" + lastTwo
        } else {
            // Just show the last component (folder name)
            return ".../" + (components.last ?? path)
        }
    }
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Storage")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Inventory Folder")
                            .font(.headline)
                        
                        Text(folderDisplayName)
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                            .truncationMode(.head)
                        
                        Button("Browse & Select Folder") {
                            showingFolderPicker = true
                        }
                        .foregroundColor(.blue)
                    }
                    .padding(.vertical, 4)
                }
                
                Section(header: Text("Photo Management")) {
                    Toggle("Delete photos after scan", isOn: $appSettings.deletePhotosAfterScan)
                }
                
                Section(header: Text("About")) {
                    HStack {
                        Text("App Version")
                        Spacer()
                        Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "Unknown")
                            .foregroundColor(.secondary)
                    }
                    
                    HStack {
                        Text("Build")
                        Spacer()
                        Text(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "Unknown")
                            .foregroundColor(.secondary)
                    }
                }

            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        presentationMode.wrappedValue.dismiss()
                    }
                }
            }
        }
        .sheet(isPresented: $showingFolderPicker) {
            DocumentPicker { selectedURL in
                if let url = selectedURL {
                    appSettings.inventoryFolderPath = url.path
                }
            }
        }
    }
}

struct DocumentPicker: UIViewControllerRepresentable {
    let onFolderSelected: (URL?) -> Void
    
    init(onFolderSelected: @escaping (URL?) -> Void) {
        self.onFolderSelected = onFolderSelected
    }
    
    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let documentPicker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder])
        documentPicker.delegate = context.coordinator
        documentPicker.allowsMultipleSelection = false
        documentPicker.shouldShowFileExtensions = true
        return documentPicker
    }
    
    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {
        // No updates needed
    }
    
    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }
    
    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let parent: DocumentPicker
        
        init(_ parent: DocumentPicker) {
            self.parent = parent
        }
        
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let selectedURL = urls.first else {
                parent.onFolderSelected(nil)
                return
            }
            
            // Start accessing security-scoped resource
            guard selectedURL.startAccessingSecurityScopedResource() else {
                print("❌ Failed to access security-scoped resource: \(selectedURL)")
                parent.onFolderSelected(nil)
                return
            }
            
            print("✅ Successfully accessed security-scoped resource: \(selectedURL.path)")
            
            // Store the bookmark data for persistent access
            do {
                let bookmarkData = try selectedURL.bookmarkData(options: .minimalBookmark, includingResourceValuesForKeys: nil, relativeTo: nil)
                UserDefaults.standard.set(bookmarkData, forKey: "folderBookmark")
                print("✅ Stored bookmark data for persistent access")
            } catch {
                print("⚠️ Failed to create bookmark: \(error)")
            }
            
            // Don't stop accessing the resource immediately - keep it for the session
            parent.onFolderSelected(selectedURL)
        }
        
        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
            parent.onFolderSelected(nil)
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppSettings())
}
