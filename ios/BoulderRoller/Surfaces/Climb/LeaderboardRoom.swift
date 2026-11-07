import SwiftUI

/// Surface 6 — the leaderboard room. Monuments don't accordion (Law 4):
/// the stone gets its own surface, all ten inscriptions with dates set.
struct LeaderboardRoom: View {
    let climbName: String
    let entries: [RecordBoardEntry]
    let myWallet: String?
    var totalEfforts: Int?
    /// Canon identity enables the sporting windows; without it the room is
    /// the all-time stone alone.
    var climbId: String?

    static let overallNote = "Each rider's fastest ascent. Power with ⚡ was measured by a power meter. Power with ≈ is an estimate from the time and the climb, at a standard rider weight."

    private enum Window: String, CaseIterable, Identifiable {
        case allTime = "All-time"
        case year = "This year"
        case today = "Today"
        var id: String { rawValue }
        var query: String? {
            switch self {
            case .allTime: return nil
            case .year: return "year"
            case .today: return "today"
            }
        }
    }

    @State private var window: Window = .allTime
    @State private var windowEntries: [RecordBoardEntry] = []
    @State private var windowUnavailable = false
    @State private var isLoadingWindow = false
    @Environment(\.dismiss) private var dismiss

    @State private var riderProfileWallet: String?

    var body: some View {
        ZStack {
                Theme.sheet.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(
                            totalEfforts.map { "\(climbName) · \($0) efforts" } ?? climbName
                        )
                        .font(.subheadline)
                        .foregroundStyle(Theme.gray)
                        .fixedSize(horizontal: false, vertical: true)

                        // The record stays all-time; the windows make
                        // Tuesday matter (Depth Ledger 6).
                        if climbId != nil {
                            Picker("Window", selection: $window) {
                                ForEach(Window.allCases) { option in
                                    Text(option.rawValue).tag(option)
                                }
                            }
                            .pickerStyle(.segmented)
                        }

                        if window == .allTime {
                            GroupCard {
                                ForEach(Array(entries.enumerated()), id: \.element.id) { index, entry in
                                    if index > 0 { RowSeparator(inset: 58) }
                                    row(entry)
                                }
                            }
                        } else if isLoadingWindow {
                            HStack {
                                Spacer()
                                ProgressView().tint(Theme.gray)
                                Spacer()
                            }
                            .frame(minHeight: 80)
                        } else if windowUnavailable {
                            GroupCard {
                                GrammarRow(label: "This window is unavailable")
                                RowSeparator(inset: 0)
                                CenteredActionRow(label: "Retry") {
                                    Task { await loadWindow() }
                                }
                            }
                        } else if windowEntries.isEmpty {
                            Text(window == .today ? "No times today yet." : "No times this year yet.")
                                .font(.footnote)
                                .foregroundStyle(Theme.gray)
                                .frame(maxWidth: .infinity, minHeight: 80)
                        } else {
                            GroupCard {
                                ForEach(Array(windowEntries.enumerated()), id: \.element.id) { index, entry in
                                    if index > 0 { RowSeparator(inset: 58) }
                                    row(entry)
                                }
                            }
                        }
                        GroupFooter(text: Self.overallNote)
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 14)
                    .padding(.bottom, 32)
                }
                .scrollEdgeEffectStyle(.hard, for: .top)
            }
        .navigationTitle("Leaderboard")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $riderProfileWallet) { wallet in
            RiderProfileView(identifier: wallet)
        }
        .onChange(of: window) {
            guard window != .allTime else { return }
            Task { await loadWindow() }
        }
    }

    private func row(_ entry: RecordBoardEntry) -> some View {
        LeaderboardEntryRow(
            entry: entry,
            isMe: myWallet.map { entry.wallet.caseInsensitiveCompare($0) == .orderedSame } ?? false,
            dateLine: dateLine(entry)
        ) {
            riderProfileWallet = entry.wallet
        }
    }

    private func loadWindow() async {
        guard let climbId, let query = window.query else { return }
        windowUnavailable = false
        // Cached-first: switching back to a window seen this session paints
        // instantly with no spinner; the fresh read replaces it quietly.
        let hadCache: Bool
        if let cached = try? await APIClient.shared.climbWindowBoard(
            climbId: climbId, window: query, policy: .cacheOnly
        ) {
            windowEntries = cached.entries ?? []
            hadCache = true
        } else {
            hadCache = false
        }
        isLoadingWindow = !hadCache
        defer { isLoadingWindow = false }
        do {
            let board = try await APIClient.shared.climbWindowBoard(
                climbId: climbId, window: query
            )
            windowEntries = board.entries ?? []
        } catch {
            windowUnavailable = windowEntries.isEmpty
        }
    }

    private func dateLine(_ entry: RecordBoardEntry) -> String {
        let isMe = entry.wallet == myWallet
        if isMe, let date = Format.date(from: entry.achievedAt),
           Calendar.current.isDateInToday(date) {
            return "PR today"
        }
        return Format.monthYear(entry.achievedAt)
    }
}
