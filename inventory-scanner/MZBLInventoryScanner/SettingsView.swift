import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appSettings: AppSettings
    @Environment(\.presentationMode) var presentationMode
    @State private var tempFolderPath: String = ""
    @State private var showingFolderPicker = false
    
    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Storage")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Inventory Folder")
                            .font(.headline)
                        
                        Text(appSettings.inventoryFolderPath)
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .lineLimit(3)
                        
                        Button("Change Folder") {
                            tempFolderPath = appSettings.inventoryFolderPath
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
                
                Section(header: Text("Folder Structure")) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Photos are organized as:")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                        
                        VStack(alignment: .leading, spacing: 4) {
                            Text("📁 Inventory Folder/")
                                .font(.caption)
                                .fontFamily(.monospaced)
                            Text("  └── 📁 MM-DD-YYYY/")
                                .font(.caption)
                                .fontFamily(.monospaced)
                            Text("      └── 📁 SKU/")
                                .font(.caption)
                                .fontFamily(.monospaced)
                            Text("          ├── 📄 IMG_1234.jpg")
                                .font(.caption)
                                .fontFamily(.monospaced)
                            Text("          └── 📄 DSC_5678.jpg")
                                .font(.caption)
                                .fontFamily(.monospaced)
                        }
                        .padding(.leading, 8)
                        .padding(.vertical, 4)
                        .background(Color(.systemGray6))
                        .cornerRadius(8)
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
        .alert("Change Folder Path", isPresented: $showingFolderPicker) {
            TextField("Folder Path", text: $tempFolderPath)
            Button("Cancel", role: .cancel) { }
            Button("Save") {
                if !tempFolderPath.trimmingCharacters(in: .whitespaces).isEmpty {
                    appSettings.inventoryFolderPath = tempFolderPath
                }
            }
        } message: {
            Text("Enter the full path where inventory photos should be saved.")
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppSettings())
}
