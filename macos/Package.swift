// swift-tools-version: 6.1

import PackageDescription

let package = Package(
  name: "FindMeGamer",
  platforms: [
    .macOS(.v14)
  ],
  products: [
    .library(name: "FindMeGamerCore", targets: ["FindMeGamerCore"]),
    .executable(name: "FindMeGamer", targets: ["FindMeGamer"]),
  ],
  targets: [
    .target(name: "FindMeGamerCore"),
    .executableTarget(
      name: "FindMeGamer",
      dependencies: ["FindMeGamerCore"]
    ),
    .testTarget(
      name: "FindMeGamerCoreTests",
      dependencies: ["FindMeGamerCore"]
    ),
  ]
)
