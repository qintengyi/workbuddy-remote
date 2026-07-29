// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "WorkBuddyRemote",
    platforms: [
        .iOS(.v17)
    ],
    products: [
        .executable(name: "WorkBuddyRemote", targets: ["WorkBuddyRemote"])
    ],
    targets: [
        .executableTarget(
            name: "WorkBuddyRemote",
            path: "Sources/WorkBuddyRemote",
            exclude: [
                "Info.plist",
                "Assets.xcassets",
                "LaunchScreen.storyboard"
            ]
        )
    ]
)
