// facescan — 디렉터리의 이미지들에서 얼굴 박스 감지(Vision), JSONL 출력
// 사용: facescan <dir>  → 각 줄: {"f":"파일명","faces":[[x,y,w,h,conf],...]} (픽셀, 좌상단 원점)
import Foundation
import Vision
import AppKit

let dir = CommandLine.arguments[1]
let fm = FileManager.default
let files = try fm.contentsOfDirectory(atPath: dir).filter { $0.hasSuffix(".png") }.sorted()

for f in files {
    let path = (dir as NSString).appendingPathComponent(f)
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        print("{\"f\":\"\(f)\",\"faces\":[]}"); continue
    }
    let W = CGFloat(cg.width), H = CGFloat(cg.height)
    let req = VNDetectFaceRectanglesRequest()
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    try? handler.perform([req])
    var out: [String] = []
    for o in req.results ?? [] {
        let b = o.boundingBox  // 정규화, 좌하단 원점
        let x = b.origin.x * W
        let y = (1 - b.origin.y - b.height) * H
        let w = b.width * W, h = b.height * H
        out.append(String(format: "[%.0f,%.0f,%.0f,%.0f,%.2f]", x, y, w, h, o.confidence))
    }
    print("{\"f\":\"\(f)\",\"faces\":[\(out.joined(separator: ","))]}")
}
