import SwiftUI

/// The climb preview and full leaderboard share the same inscription.
/// At accessibility sizes time joins the leading stack, preserving room
/// for the rider's name, the estimate range, and opted-in W/kg.
struct LeaderboardEntryRow: View {
    let entry: RecordBoardEntry
    let isMe: Bool
    let dateLine: String
    let action: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @ScaledMetric(relativeTo: .caption) private var rankWidth = 30.0

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 10) {
                Text(entry.sportingRankLabel)
                    .font(.numeral(.caption))
                    .foregroundStyle(Theme.gray)
                    .frame(width: rankWidth, alignment: .trailing)
                if !dynamicTypeSize.isAccessibilitySize {
                    AvatarView(name: entry.shownName, url: entry.avatarURL, size: 34)
                }
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline, spacing: 5) {
                        Text(isMe ? "You" : entry.shownName)
                            .font(isMe ? .body.weight(.semibold) : .body)
                            .foregroundStyle(Theme.ink)
                            .fixedSize(horizontal: false, vertical: true)
                        if entry.sportingRank == 1 {
                            Image(systemName: "crown")
                                .font(.caption2)
                                .foregroundStyle(Theme.gray)
                                .accessibilityLabel("Crown")
                        }
                    }
                    if dynamicTypeSize.isAccessibilitySize { time }
                    if !dateLine.isEmpty {
                        Text(dateLine)
                            .font(.caption2)
                            .foregroundStyle(Theme.gray)
                    }
                    ClimbPowerLabel(power: Format.climbPower(entry))
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if !dynamicTypeSize.isAccessibilitySize { time }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: Theme.row)
            .background(isMe ? Theme.blue.opacity(0.06) : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
    }

    private var time: some View {
        Text(Format.climbTime(entry.bestTimeSeconds))
            .font(.numeral(.body))
            .monospacedDigit()
            .foregroundStyle(Theme.ink)
            .fixedSize()
    }
}
