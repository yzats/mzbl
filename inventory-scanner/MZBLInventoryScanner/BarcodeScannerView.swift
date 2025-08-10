import SwiftUI
import AVFoundation

struct BarcodeScannerView: View {
    let onScanComplete: (String) -> Void
    @State private var showingAlert = false
    @State private var alertMessage = ""
    @State private var showingTestOptions = false
    @Environment(\.presentationMode) var presentationMode
    
    var body: some View {
        NavigationView {
            ZStack {
                CameraView(onScanComplete: onScanComplete, showingAlert: $showingAlert, alertMessage: $alertMessage)
                    .edgesIgnoringSafeArea(.all)
                
                // Overlay with scanning guide
                VStack {
                    Spacer()
                    
                    // Scanning frame
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.white, lineWidth: 3)
                        .frame(width: 250, height: 150)
                        .overlay(
                            VStack {
                                Text("Position barcode here")
                                    .foregroundColor(.white)
                                    .font(.headline)
                                    .padding(.top, 8)
                                Spacer()
                            }
                        )
                    
                    Spacer()
                    
                    Text("Point camera at barcode to scan")
                        .foregroundColor(.white)
                        .font(.subheadline)
                        .padding(.bottom, 50)
                }
            }
            .navigationTitle("Scan Barcode")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        presentationMode.wrappedValue.dismiss()
                    }
                    .foregroundColor(.white)
                }
                
                // Debug button for simulator testing
                #if targetEnvironment(simulator)
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Test") {
                        showingTestOptions = true
                    }
                    .foregroundColor(.yellow)
                }
                #endif
            }
        }
        .alert("Scanner Error", isPresented: $showingAlert) {
            Button("OK") { }
        } message: {
            Text(alertMessage)
        }
        #if targetEnvironment(simulator)
        .alert("Test Barcode Scan", isPresented: $showingTestOptions) {
            Button("Sneaker SKU") {
                onScanComplete("SNK123456789")
            }
            Button("Electronics") {
                onScanComplete("ELC987654321")
            }
            Button("Clothing") {
                onScanComplete("CLT555666777")
            }
            Button("Test SKU") {
                onScanComplete("TEST123456789")
            }
            Button("Cancel", role: .cancel) { }
        } message: {
            Text("Choose a test SKU to simulate scanning:")
        }
        #endif
    }
}

struct CameraView: UIViewRepresentable {
    let onScanComplete: (String) -> Void
    @Binding var showingAlert: Bool
    @Binding var alertMessage: String
    
    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: UIScreen.main.bounds)
        let captureSession = AVCaptureSession()
        
        guard let videoCaptureDevice = AVCaptureDevice.default(for: .video) else {
            alertMessage = "Camera not available"
            showingAlert = true
            return view
        }
        
        let videoInput: AVCaptureDeviceInput
        
        do {
            videoInput = try AVCaptureDeviceInput(device: videoCaptureDevice)
        } catch {
            alertMessage = "Camera input error: \(error.localizedDescription)"
            showingAlert = true
            return view
        }
        
        if captureSession.canAddInput(videoInput) {
            captureSession.addInput(videoInput)
        } else {
            alertMessage = "Could not add video input"
            showingAlert = true
            return view
        }
        
        let metadataOutput = AVCaptureMetadataOutput()
        
        if captureSession.canAddOutput(metadataOutput) {
            captureSession.addOutput(metadataOutput)
            
            metadataOutput.setMetadataObjectsDelegate(context.coordinator, queue: DispatchQueue.main)
            metadataOutput.metadataObjectTypes = [
                .ean8, .ean13, .pdf417, .qr, .code128, .code39, .code93,
                .upce, .codabar, .aztec, .dataMatrix, .interleaved2of5,
                .itf14, .gs1DataBar, .gs1DataBarExpanded, .gs1DataBarLimited
            ]
        } else {
            alertMessage = "Could not add metadata output"
            showingAlert = true
            return view
        }
        
        let previewLayer = AVCaptureVideoPreviewLayer(session: captureSession)
        previewLayer.frame = view.layer.bounds
        previewLayer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(previewLayer)
        
        DispatchQueue.global(qos: .background).async {
            captureSession.startRunning()
        }
        
        return view
    }
    
    func updateUIView(_ uiView: UIView, context: Context) {}
    
    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }
    
    class Coordinator: NSObject, AVCaptureMetadataOutputObjectsDelegate {
        let parent: CameraView
        private var hasScanned = false
        private var lastScannedValue: String?
        private var lastScanTime: Date?
        
        init(_ parent: CameraView) {
            self.parent = parent
        }
        
        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
            // Prevent multiple scans
            guard !hasScanned else { return }
            
            if let metadataObject = metadataObjects.first {
                guard let readableObject = metadataObject as? AVMetadataMachineReadableCodeObject else { return }
                guard let stringValue = readableObject.stringValue else { return }
                
                // Additional protection: check if we just scanned the same value recently
                let now = Date()
                if let lastValue = lastScannedValue, 
                   let lastTime = lastScanTime,
                   lastValue == stringValue,
                   now.timeIntervalSince(lastTime) < 2.0 {
                    return
                }
                
                // Mark as scanned to prevent duplicates
                hasScanned = true
                lastScannedValue = stringValue
                lastScanTime = now
                
                AudioServicesPlaySystemSound(SystemSoundID(kSystemSoundID_Vibrate))
                
                // Dispatch to main queue and add slight delay to ensure UI state is consistent
                DispatchQueue.main.async {
                    self.parent.onScanComplete(stringValue)
                }
            }
        }
    }
}

#Preview {
    BarcodeScannerView { sku in
        print("Scanned: \(sku)")
    }
}
