import SwiftUI

struct ScannedItem: Identifiable {
    let id = UUID()
    let sku: String
}

struct ContentView: View {
    @EnvironmentObject var appSettings: AppSettings
    @State private var showingBarcodeScanner = false
    @State private var showingSettings = false
    @State private var currentItem: ScannedItem? = nil
    
    var body: some View {
        NavigationView {
            VStack(spacing: 50) {
                Spacer()
                
                // App Logo/Title
                VStack(spacing: 20) {
                    Image(systemName: "qrcode.viewfinder")
                        .font(.system(size: 80))
                        .foregroundColor(.blue)
                    
                    Text("MZBL Inventory Scanner")
                        .font(.title)
                        .fontWeight(.bold)
                        .multilineTextAlignment(.center)
                    
                    Text("Scan barcodes and organize photos")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                }
                
                Spacer()
                
                // New Item Button
                Button(action: {
                    showingBarcodeScanner = true
                }) {
                    HStack {
                        Image(systemName: "plus.circle.fill")
                            .font(.title2)
                        Text("New Item")
                            .font(.title2)
                            .fontWeight(.semibold)
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 60)
                    .background(Color.blue)
                    .cornerRadius(12)
                }
                .padding(.horizontal, 40)
                
                Spacer()
            }
            .navigationTitle("")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: {
                        showingSettings = true
                    }) {
                        Image(systemName: "gear")
                            .font(.title2)
                            .foregroundColor(.blue)
                    }
                }
            }
        }
        .navigationViewStyle(StackNavigationViewStyle())
        .fullScreenCover(isPresented: $showingBarcodeScanner) {
            BarcodeScannerView { sku in
                print("🔍 SCAN COMPLETE: SKU = \(sku)")
                showingBarcodeScanner = false
                DispatchQueue.main.async {
                    currentItem = ScannedItem(sku: sku)
                }
            }
        }
        .sheet(isPresented: $showingSettings) {
            SettingsView()
        }
        .fullScreenCover(item: $currentItem) { item in
            PhotoSelectorView(scannedSKU: item.sku) {
                print("🔍 PhotoSelector onComplete called")
                currentItem = nil
            }
            .onAppear {
                print("🔍 PRESENTING PhotoSelectorView with SKU: \(item.sku)")
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppSettings())
}
