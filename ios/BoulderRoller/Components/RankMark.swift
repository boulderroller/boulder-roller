import SwiftUI

enum RankMarkAsset: Equatable {
    case numbered(String)
    case podium(String)
    case unavailable

    static func resolve(rank: Int) -> RankMarkAsset {
        switch rank {
        case 1...3:
            return .podium(["rank01_crown", "rank02_laurel", "rank03_cobble"][rank - 1])
        case 4...50:
            let rankNumber = rank < 10 ? "0\(rank)" : "\(rank)"
            return .numbered("rank\(rankNumber)")
        default:
            return .unavailable
        }
    }
}

/// Asset-only rank display primitive. The baked sprite owns the complete look;
/// under the ratified tab codex the mark's state derives from rank alone.
struct RankMark: View {
    static let defaultPointSize: CGFloat = 36

    let rank: Int
    let pointSize: CGFloat
    let tint: Color?

    init(rank: Int, size: CGFloat = RankMark.defaultPointSize, tint: Color? = nil) {
        self.rank = rank
        pointSize = size
        self.tint = tint
    }

    var body: some View {
        content
            .frame(width: safePointSize, height: safePointSize)
    }

    @ViewBuilder
    private var content: some View {
        switch RankMarkAsset.resolve(rank: rank) {
        case let .numbered(imageName), let .podium(imageName):
            Image(imageName)
                .resizable()
                .renderingMode(.original)
                .saturation(tint == nil ? 1 : 0)
                .colorMultiply(tint ?? .white)
                .scaledToFit()
                .accessibilityLabel("Rank \(rank)")
        case .unavailable:
            Color.clear
                .accessibilityHidden(true)
        }
    }

    private var safePointSize: CGFloat {
        pointSize.isFinite && pointSize > 0 ? pointSize : 0
    }
}
