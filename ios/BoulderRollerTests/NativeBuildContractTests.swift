import XCTest

/// Static contracts for production-path boundaries that cannot be exercised
/// with local Privy wallet objects or hosted GitHub runners.
final class NativeBuildContractTests: XCTestCase {
    private var repositoryRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BoulderRollerTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
    }

    func testPrivySignerRequiresAnExactWalletMatch() throws {
        let source = try String(
            contentsOf: repositoryRoot
                .appendingPathComponent("ios/BoulderRoller/Money/TransactionSigner.swift"),
            encoding: .utf8
        )

        XCTAssertTrue(source.contains("user.embeddedSolanaWallets.first(where: { $0.address == wallet })"))
        XCTAssertFalse(source.contains("?? user.embeddedSolanaWallets.first"))
    }

    func testIOSWorkflowUsesTheCheckedInNativeBuildContract() throws {
        let workflow = try String(
            contentsOf: repositoryRoot.appendingPathComponent(".github/workflows/ios-ci.yml"),
            encoding: .utf8
        )
        let requiredSnippets = [
            // Tim's self-hosted Mac by default; a manual run may choose the paid hosted runner.
            "\"boulder-ios\"",
            "'macos-26'",
            "sudo xcode-select -s /Applications/Xcode_26.6.app",
            "bash ios/scripts/build_parser.sh",
            "brew install xcodegen",
            "xcodegen generate --spec project.yml",
            "xcodebuild -project ios/BoulderRoller.xcodeproj -scheme BoulderRoller",
            "echo \"SIM_NAME=iPhone 17\" >> \"$GITHUB_ENV\"",
            "\"iPhone 17\" com.apple.CoreSimulator.SimRuntime.iOS-26-5",
            "platform=iOS Simulator,name=$SIM_NAME,OS=26.5",
            "if: github.event_name != 'pull_request' || !github.event.pull_request.draft",
        ]

        // Pull requests, pushes to main that touch the app (direct pushes skip pull
        // requests; the self-hosted Mac is free), and manual release runs.
        XCTAssertTrue(workflow.contains("\n  workflow_dispatch:\n"))
        XCTAssertTrue(workflow.contains("""
          push:
            branches: [main]
            paths:
              - 'ios/**'
        """))
        XCTAssertTrue(workflow.contains("""
          pull_request:
            types: [opened, synchronize, reopened, ready_for_review]
            paths:
              - 'ios/**'
              - 'workout-parse/**'
              - '.github/workflows/ios-ci.yml'
        """))

        for snippet in requiredSnippets {
            XCTAssertTrue(workflow.contains(snippet), "workflow is missing: \(snippet)")
        }
        XCTAssertFalse(workflow.contains("runs-on: macos-14"))
        XCTAssertFalse(workflow.contains("Xcode_16.1.app"))
        XCTAssertFalse(workflow.contains("BoulderRollers"))
        XCTAssertFalse(workflow.contains("iPhone 16,OS=18.1"))
    }
}
