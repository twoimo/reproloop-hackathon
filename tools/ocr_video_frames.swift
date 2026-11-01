import Foundation
import Vision
import AppKit
import CryptoKit

struct Stop: Error { let reason: String }
func need(_ ok: Bool, _ reason: String) throws { if !ok { throw Stop(reason: reason) } }
func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
func canonical(_ path: String) throws -> URL {
    let u = URL(fileURLWithPath: path).standardizedFileURL
    try need(path.hasPrefix("/") && u.path == path && !path.split(separator: "/").contains(".."), "canonical absolute path required")
    var current = URL(fileURLWithPath: "/")
    for part in u.pathComponents.dropFirst() {
        current.appendPathComponent(part)
        let attrs = try FileManager.default.attributesOfItem(atPath: current.path)
        try need(attrs[.type] as? FileAttributeType != .typeSymbolicLink, "symlinks forbidden")
    }
    return u
}
func read(_ path: String, _ maximum: Int) throws -> Data {
    let u = try canonical(path), attrs = try FileManager.default.attributesOfItem(atPath: u.path)
    try need(attrs[.type] as? FileAttributeType == .typeRegular, "regular file required")
    let count = (attrs[.size] as? NSNumber)?.intValue ?? 0
    try need(count > 0 && count <= maximum, "file byte bound")
    let raw = try Data(contentsOf: u)
    try need(raw.count == count, "file size changed")
    return raw
}
func number(_ x: Any?) throws -> Double {
    guard let n = x as? NSNumber, String(cString: n.objCType) != "c" else { throw Stop(reason: "nonboolean number required") }
    let value = n.doubleValue
    try need(value.isFinite && value >= 0, "finite nonnegative number required")
    return value
}
func run() throws {
    try need(CommandLine.arguments.count == 3, "usage: ocr_video_frames DECODER_DIR FRESH_OUTPUT_JSON")
    let root = try canonical(CommandLine.arguments[1]), output = URL(fileURLWithPath: CommandLine.arguments[2])
    _ = try canonical(output.deletingLastPathComponent().path)
    try need(output.path == output.standardizedFileURL.path && !FileManager.default.fileExists(atPath: output.path), "fresh canonical output required")
    let decoderRaw = try read(root.appendingPathComponent("decode.json").path, 65536)
    guard let decoder = try JSONSerialization.jsonObject(with: decoderRaw) as? [String: Any],
          let media = decoder["media_sha256"] as? String,
          let frames = decoder["frames"] as? [[String: Any]] else { throw Stop(reason: "decoder schema") }
    try need(media.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil, "media SHA")
    try need(decoder["decoder"] as? String == "macOS AVFoundation" && frames.count > 0 && frames.count <= 16, "decoder/frame bound")
    try need(try number(decoder["video_tracks"]) == 1 && number(decoder["audio_tracks"]) == 0, "track contract")
    let duration = try number(decoder["duration_seconds"])
    try need(duration > 0 && duration <= 45, "duration bound")
    var rows = [[String: Any]](), prior = -1
    for frame in frames {
        guard let name = frame["file"] as? String, let expected = frame["sha256"] as? String else { throw Stop(reason: "frame schema") }
        try need(name.range(of: "^frame-[0-9]{2}\\.png$", options: .regularExpression) != nil, "flat PNG filename required")
        let seconds = try number(frame["decoded_seconds"]), timestamp = Int(floor(seconds * 1000))
        try need(seconds <= duration && timestamp > prior, "actual decoded timestamp order")
        let raw = try read(root.appendingPathComponent(name).path, 8 * 1024 * 1024)
        try need(hash(raw) == expected, "PNG SHA mismatch")
        try need(raw.starts(with: [137,80,78,71,13,10,26,10]), "PNG required")
        guard let image = NSBitmapImageRep(data: raw), let cg = image.cgImage else { throw Stop(reason: "PNG decode failed") }
        try need(image.pixelsWide == 720 && image.pixelsHigh == 1280 && number(frame["width"]) == 720 && number(frame["height"]) == 1280, "fixed frame dimensions")
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["en-US"]
        request.usesLanguageCorrection = false
        try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
        let observations = request.results ?? []
        try need(observations.count <= 64, "OCR region bound; never truncate")
        var regions = [[String: Any]]()
        for observation in observations {
            guard let text = observation.topCandidates(1).first else { throw Stop(reason: "missing OCR candidate") }
            let confidence = Double(text.confidence), b = observation.boundingBox
            try need(!text.string.isEmpty && text.string.count <= 256 && confidence.isFinite && confidence >= 0 && confidence <= 1, "OCR text/confidence bound")
            let bounds = [max(0,Int(floor(b.minX * 720))), max(0,Int(floor((1-b.maxY) * 1280))),
                          min(720,Int(ceil(b.maxX * 720))), min(1280,Int(ceil((1-b.minY) * 1280)))]
            try need(bounds[0] < bounds[2] && bounds[1] < bounds[3], "OCR box bound")
            regions.append(["text": text.string, "confidence": confidence, "bounds": bounds])
        }
        rows.append(["png_sha256": expected, "timestamp_ms": timestamp, "regions": regions])
        prior = timestamp
    }
    let sourceHash = hash(try read(URL(fileURLWithPath: #filePath).standardizedFileURL.path, 65536))
    let result: [String: Any] = ["schema_version": 1, "decoder": "macOS Vision", "media_sha256": media,
                               "tool_source_sha256": sourceHash, "attestation": false, "frames": rows]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys, .prettyPrinted])
    try need(data.count <= 1024 * 1024, "OCR output bound")
    try data.write(to: output, options: .withoutOverwriting)
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: output.path)
    print("OCR_COMPLETE frames=\(rows.count) output_sha256=\(hash(data))")
}
do { try run() } catch { fputs("OCR_STOP: \(error)\n", stderr); exit(1) }
