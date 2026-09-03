// swift-tools-version: 6.1

import PackageDescription

let package = Package(
  name: "FindMeGamer",
  platforms: [
    .macOS(.v14)
  ],
  products: [
    .library(name: "FindMeGamerAPI", targets: ["FindMeGamerAPI"]),
    .library(name: "FindMeGamerCore", targets: ["FindMeGamerCore"]),
    .executable(name: "FindMeGamer", targets: ["FindMeGamer"]),
  ],
  dependencies: [
    .package(
      url: "https://github.com/apple/swift-openapi-generator",
      from: "1.13.0"
    ),
    .package(
      url: "https://github.com/apple/swift-openapi-runtime",
      from: "1.12.0"
    ),
    .package(
      url: "https://github.com/apple/swift-openapi-urlsession",
      from: "1.3.0"
    ),
  ],
  targets: [
    .target(
      name: "FindMeGamerAPI",
      dependencies: [
        .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
        .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
      ],
      swiftSettings: [
        // Generator 1.13.1 emits unused public imports in empty split files.
        .unsafeFlags(["-Xfrontend", "-no-warnings-as-errors"])
      ],
      plugins: [
        .plugin(name: "OpenAPIGenerator", package: "swift-openapi-generator")
      ]
    ),
    .target(
      name: "FindMeGamerCore",
      dependencies: [
        "FindMeGamerAPI",
        .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
        .product(name: "OpenAPIURLSession", package: "swift-openapi-urlsession"),
      ]
    ),
    .executableTarget(
      name: "FindMeGamer",
      dependencies: ["FindMeGamerCore"]
    ),
    .testTarget(
      name: "FindMeGamerCoreTests",
      dependencies: [
        "FindMeGamerAPI",
        "FindMeGamerCore",
        .product(name: "OpenAPIRuntime", package: "swift-openapi-runtime"),
      ]
    ),
    .testTarget(
      name: "FindMeGamerUITests",
      dependencies: ["FindMeGamer", "FindMeGamerCore"]
    ),
  ]
)
