// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AmosclaudXcode",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "amosclaud-xcode", targets: ["AmosclaudXcode"])
    ],
    targets: [
        .executableTarget(
            name: "AmosclaudXcode",
            path: "Sources/AmosclaudXcode"
        )
    ]
)
