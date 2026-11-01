import Foundation
import AVFoundation
import AppKit
import CryptoKit

let source = URL(fileURLWithPath: CommandLine.arguments[1])
let destination = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: destination, withIntermediateDirectories: false)
let bytes = try Data(contentsOf: source)
let mediaSHA = SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined()
let asset = AVURLAsset(url: source)
let duration = try await asset.load(.duration)
let seconds = CMTimeGetSeconds(duration)
guard seconds.isFinite && seconds > 0 && seconds <= 46 else { fatalError("bounded finite duration required") }
let video = try await asset.loadTracks(withMediaType: .video)
let audio = try await asset.loadTracks(withMediaType: .audio)
guard video.count == 1 && audio.isEmpty else { fatalError("one silent video track required") }
let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero
var frames: [[String: Any]] = []
let times = stride(from: 0.25, to: seconds, by: 3.0).map { min($0, seconds - 0.001) } + [seconds - 0.001]
for (index, requested) in times.enumerated() {
    let result = try await generator.image(at: CMTime(seconds: requested, preferredTimescale: 600))
    let bitmap = NSBitmapImageRep(cgImage: result.image)
    guard let png = bitmap.representation(using: .png, properties: [:]) else { fatalError("PNG encode failed") }
    let name = String(format: "frame-%02d.png", index)
    try png.write(to: destination.appendingPathComponent(name), options: .withoutOverwriting)
    frames.append(["file": name, "requested_seconds": requested, "decoded_seconds": CMTimeGetSeconds(result.actualTime), "width": result.image.width, "height": result.image.height, "sha256": SHA256.hash(data: png).map { String(format: "%02x", $0) }.joined()])
}
let proof: [String: Any] = ["schema_version": 1, "decoder": "macOS AVFoundation", "media_sha256": mediaSHA, "duration_seconds": seconds, "video_tracks": video.count, "audio_tracks": audio.count, "frames": frames, "coverage_judgment": "REQUIRES_HUMAN_INSPECTION", "attestation": false]
let output = try JSONSerialization.data(withJSONObject: proof, options: [.prettyPrinted, .sortedKeys])
try output.write(to: destination.appendingPathComponent("decode.json"), options: .withoutOverwriting)
print(String(data: output, encoding: .utf8)!)
