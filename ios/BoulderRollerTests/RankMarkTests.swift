import Foundation
import UIKit
import XCTest
@testable import BoulderRoller

final class RankMarkTests: XCTestCase {
    private struct Manifest: Decodable {
        struct Rank: Decodable {}

        let codex: Codex
        let ranks: [String: Rank]

        struct Codex: Decodable {
            let ratified: String
        }
    }

    private struct ImageSetContents: Decodable {
        struct Image: Decodable {
            let filename: String?
            let idiom: String?
            let scale: String?
        }

        let images: [Image]
    }

    private var repositoryRoot: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // BoulderRollerTests
            .deletingLastPathComponent() // ios
            .deletingLastPathComponent() // repository root
    }

    func testEveryManifestRankResolvesToAnInstalledImageSet() throws {
        let decoder = JSONDecoder()
        let manifest = try decoder.decode(
            Manifest.self,
            from: Data(contentsOf: manifestURL)
        )

        XCTAssertEqual(manifest.ranks.count, 47)
        XCTAssertFalse(manifest.codex.ratified.isEmpty)

        for rankKey in manifest.ranks.keys.sorted() {
            let rank = try XCTUnwrap(Int(rankKey))
            guard case let .numbered(imageName) = RankMarkAsset.resolve(rank: rank) else {
                return XCTFail("rank \(rank) did not resolve")
            }

            let imageSet = rankMarksCatalog
                .appendingPathComponent("\(imageName).imageset", isDirectory: true)
            let contents = try decoder.decode(
                ImageSetContents.self,
                from: Data(contentsOf: imageSet.appendingPathComponent("Contents.json"))
            )
            let installedScales = Set(contents.images.compactMap(\.scale))

            XCTAssertEqual(installedScales, ["1x", "2x", "3x"], imageName)
            XCTAssertTrue(
                contents.images.allSatisfy { $0.idiom == "universal" },
                imageName
            )
            for image in contents.images {
                let filename = try XCTUnwrap(image.filename)
                XCTAssertTrue(
                    FileManager.default.fileExists(
                        atPath: imageSet.appendingPathComponent(filename).path
                    ),
                    "missing \(imageName)/\(filename)"
                )
            }
            XCTAssertNotNil(UIImage(named: imageName), "\(imageName) is not in the app bundle")
        }
    }

    func testNumberedAssetNamesFollowTheCatalogContract() {
        XCTAssertEqual(RankMarkAsset.resolve(rank: 4), .numbered("rank04"))
        XCTAssertEqual(RankMarkAsset.resolve(rank: 50), .numbered("rank50"))
    }

    func testPodiumRanksUseTheSharedLedgerPNGs() {
        for rank in 1...3 {
            let name = ["rank01_crown", "rank02_laurel", "rank03_cobble"][rank - 1]
            XCTAssertEqual(RankMarkAsset.resolve(rank: rank), .podium(name))
            XCTAssertNotNil(UIImage(named: name))
        }
    }

    func testOutOfRangeRanksFailSafe() {
        for rank in [-1, 0, 51, Int.max] {
            XCTAssertEqual(RankMarkAsset.resolve(rank: rank), .unavailable)
        }
    }

    func testRowDefaultUsesAnExplicitPointSize() {
        XCTAssertEqual(RankMark.defaultPointSize, 36)
    }

    private var manifestURL: URL {
        repositoryRoot.appendingPathComponent("tools/rankmarks/build/manifest.json")
    }

    private var rankMarksCatalog: URL {
        repositoryRoot.appendingPathComponent(
            "ios/BoulderRoller/Resources/Assets.xcassets/RankMarks",
            isDirectory: true
        )
    }
}
