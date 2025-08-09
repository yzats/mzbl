import SwiftUI
import AVFoundation

struct BarcodeScannerView: View {
    let onScanComplete: (String) -> Void
    @State private var showingAlert = false
    @State private var alertMessage = ""
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
            }
        }
        .alert("Scanner Error", isPresented: $showingAlert) {
            Button("OK") { }
        } message: {
            Text(alertMessage)
        }
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
        
        init(_ parent: CameraView) {
            self.parent = parent
        }
        
        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
            if let metadataObject = metadataObjects.first {
                guard let readableObject = metadataObject as? AVMetadataMachineReadableCodeObject else { return }
                guard let stringValue = readableObject.stringValue else { return }
                
                AudioServicesPlaySystemSound(SystemSoundID(kSystemSoundID_Vibrate))
                parent.onScanComplete(stringValue)
            }
        }
    }
}

#Preview {
    BarcodeScannerView { sku in
        print("Scanned: \(sku)")
    }
}
