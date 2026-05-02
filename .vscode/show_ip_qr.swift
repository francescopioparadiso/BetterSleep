import AppKit
import CoreImage
import Foundation

func runCommand(_ launchPath: String, _ arguments: [String]) -> String? {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: launchPath)
    process.arguments = arguments

    let pipe = Pipe()
    process.standardOutput = pipe
    process.standardError = Pipe()

    do {
        try process.run()
        process.waitUntilExit()
    } catch {
        return nil
    }

    guard process.terminationStatus == 0 else {
        return nil
    }

    let data = pipe.fileHandleForReading.readDataToEndOfFile()
    let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
    return (output?.isEmpty == false) ? output : nil
}

func discoverLocalIP() -> String? {
    runCommand("/usr/sbin/ipconfig", ["getifaddr", "en0"])
        ?? runCommand("/usr/sbin/ipconfig", ["getifaddr", "en1"])
}

guard let ip = discoverLocalIP() else {
    fputs("Unable to determine Mac LAN IP address.\n", stderr)
    exit(1)
}

let context = CIContext()
guard let filter = CIFilter(name: "CIQRCodeGenerator") else {
    fputs("Failed to create QR code filter.\n", stderr)
    exit(1)
}
filter.setValue(Data(ip.utf8), forKey: "inputMessage")
filter.setValue("M", forKey: "inputCorrectionLevel")

guard let outputImage = filter.outputImage else {
    fputs("Failed to generate QR code.\n", stderr)
    exit(1)
}

let scaleX = 12.0
let scaleY = 12.0
let transformed = outputImage.transformed(by: CGAffineTransform(scaleX: scaleX, y: scaleY))

guard let cgImage = context.createCGImage(transformed, from: transformed.extent) else {
    fputs("Failed to render QR code image.\n", stderr)
    exit(1)
}

let bitmapRep = NSBitmapImageRep(cgImage: cgImage)
guard let pngData = bitmapRep.representation(using: NSBitmapImageRep.FileType.png, properties: [:]) else {
    fputs("Failed to encode QR code PNG.\n", stderr)
    exit(1)
}

let outputDirectory = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    .appendingPathComponent(".vscode", isDirectory: true)

do {
    try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
} catch {
    fputs("Failed to create QR code output directory: \(error.localizedDescription)\n", stderr)
    exit(1)
}

let outputURL = outputDirectory.appendingPathComponent("IPaddress_QRcode.png")

do {
    try pngData.write(to: outputURL, options: Data.WritingOptions.atomic)
    _ = runCommand("/usr/bin/open", [outputURL.path])
    print(ip)
    print(outputURL.path)
} catch {
    fputs("Failed to save QR code image: \(error.localizedDescription)\n", stderr)
    exit(1)
}
