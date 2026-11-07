import SwiftUI

/// Surface 7 — Rider profile. Times are public, money is private (Law 6):
/// rides, seats, crowns — never a balance, theirs or yours.
struct RiderProfileView: View {
    let identifier: String
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @Environment(\.units) private var units

    @State private var profile: PublicProfile?
    @State private var recentRides: [PublicRiderRideSummary] = []
    @State private var positions: [VaultPositionSummary] = []
    @State private var stats: UserLeaderboardStats?
    /// Own page only: the twelve-week fold (Depth Ledger 3).
    @State private var trainingWeeks: [TrainingWeek] = []
    /// Own page only: every canon climb with confirmed completions.
    @State private var riddenClimbs: [RiddenClimb] = []
    @State private var pushedClimbId: String?

    private var isOwnPage: Bool {
        guard let me = session.currentUser else { return false }
        return me.wallet == identifier || me.id == identifier
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 0) {
                    identity

                    VStack(alignment: .leading, spacing: 0) {
                        if trainingWeeks.contains(where: { $0.partial || ($0.distanceM ?? 0) > 0 }) {
                            TrainingLogSection(weeks: trainingWeeks)
                                .padding(.bottom, 22)
                        }

                        trophyCase

                        yourClimbs

                        if !positions.isEmpty {
                            SectionHeader(title: "Leaderboards")
                            GroupCard {
                                ForEach(Array(positions.prefix(6).enumerated()), id: \.element.id) { index, position in
                                    if index > 0 { RowSeparator(inset: 44) }
                                    positionRow(position)
                                }
                            }
                        }

                        if !recentRides.isEmpty {
                            SectionHeader(title: "Rides")
                                .padding(.top, positions.isEmpty ? 0 : 22)
                            GroupCard {
                                ForEach(Array(recentRides.prefix(6).enumerated()), id: \.element.id) { index, ride in
                                    if index > 0 { RowSeparator() }
                                    rideRow(ride)
                                }
                            }
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 24)
                    .padding(.bottom, 32)
                }
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $pushedClimbId) { climbId in
            ClimbDetailView(climbId: climbId)
        }
        .task { await load() }
    }

    private var identity: some View {
        VStack(spacing: 2) {
            AvatarView(
                name: profile?.shownName,
                url: profile?.avatarUrl.flatMap(URL.init),
                size: 58
            )
            Text(profile?.shownName ?? "")
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .padding(.top, 8)

            // The rider's own words, verbatim from the server — shown only
            // when they wrote one (empty renders nothing, Law 11 footing).
            if let bio = profile?.bio?.trimmingCharacters(in: .whitespacesAndNewlines),
               !bio.isEmpty
            {
                Text(bio)
                    .font(.footnote)
                    .foregroundStyle(Theme.gray)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 4)
                    .padding(.horizontal, 28)
            }

            HStack(spacing: 34) {
                trioStat("\(profile?.totalRides ?? 0)", "RIDES")
                trioStat("\(stats?.totalPositions ?? positions.count)", "SEATS")
                trioStat("\(stats?.komCount ?? 0)", "CROWNS")
            }
            .padding(.top, 16)
        }
        .padding(.top, 2)
    }

    private func trioStat(_ value: String, _ label: String) -> some View {
        VStack(spacing: 1) {
            Text(value)
                .font(.numeral(.body))
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
            Text(label)
                .font(.caption2)
                .kerning(0.5)
                .foregroundStyle(Theme.gray)
        }
        .accessibilityElement(children: .combine)
    }

    private func positionRow(_ position: VaultPositionSummary) -> some View {
        HStack(spacing: 12) {
            Text("\(position.rank ?? 0)")
                .font(.numeral(.caption, weight: .regular))
                .foregroundStyle(Theme.gray)
                .frame(width: 18, alignment: .trailing)
            HStack(spacing: 5) {
                Text(position.vaultName ?? "")
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .lineLimit(1)
                if position.isKom == true {
                    Image(systemName: "crown")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                        .accessibilityLabel("Crown")
                }
            }
            Spacer()
            Text(Format.climbTime(position.bestTimeSeconds))
                .font(.numeral(.body))
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 44)
        .accessibilityElement(children: .combine)
    }

    /// Crowns get their own case (Depth Ledger, trophy case): every #1 with
    /// its time. Absent when there are none — no empty objects.
    @ViewBuilder
    private var trophyCase: some View {
        let crowns = positions.filter { $0.isKom == true }
        if !crowns.isEmpty {
            SectionHeader(title: "Crowns")
            GroupCard {
                ForEach(Array(crowns.enumerated()), id: \.element.id) { index, crown in
                    if index > 0 { RowSeparator(inset: 44) }
                    HStack(spacing: 12) {
                        Image(systemName: "crown")
                            .font(.footnote)
                            .foregroundStyle(Theme.ink)
                            .frame(width: 22)
                        Text(crown.vaultName ?? "Climb")
                            .font(.body)
                            .foregroundStyle(Theme.ink)
                            .lineLimit(1)
                        Spacer()
                        Text(Format.climbTime(crown.bestTimeSeconds))
                            .font(.numeral(.body))
                            .monospacedDigit()
                            .foregroundStyle(Theme.ink)
                    }
                    .padding(.horizontal, 14)
                    .frame(minHeight: 44)
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.bottom, 22)
        }
    }

    /// Your Climbs (Depth Ledger 5): the canon you've ridden, straight into
    /// each climb. Confirmed completions only; absent when there are none.
    @ViewBuilder
    private var yourClimbs: some View {
        if !riddenClimbs.isEmpty {
            SectionHeader(title: "Your Climbs")
            GroupCard {
                ForEach(Array(riddenClimbs.prefix(10).enumerated()), id: \.element.id) { index, climb in
                    if index > 0 { RowSeparator() }
                    Button {
                        if let canonId = climb.canonClimbId {
                            pushedClimbId = canonId
                        }
                    } label: {
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(climb.name ?? "Climb")
                                    .font(.body)
                                    .foregroundStyle(Theme.ink)
                                    .lineLimit(1)
                                Text(climbSubtitle(climb))
                                    .font(.caption2)
                                    .foregroundStyle(Theme.gray)
                            }
                            Spacer(minLength: 8)
                            Text(Format.climbTime(climb.bestTimeSeconds))
                                .font(.numeral(.body))
                                .monospacedDigit()
                                .foregroundStyle(Theme.ink)
                            if climb.canonClimbId != nil {
                                Image(systemName: "chevron.right")
                                    .font(.footnote.weight(.semibold))
                                    .foregroundStyle(Theme.gray3)
                            }
                        }
                        .padding(.horizontal, 14)
                        .frame(minHeight: Theme.row)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(climb.canonClimbId == nil)
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.bottom, 22)
        }
    }

    private func climbSubtitle(_ climb: RiddenClimb) -> String {
        var parts: [String] = []
        if let attempts = climb.attempts, attempts > 0 {
            parts.append("\(attempts) attempt\(attempts == 1 ? "" : "s")")
        }
        parts.append(Format.climbSubtitle(
            distanceM: climb.lengthM,
            gradientPct: climb.avgGradientPct,
            units: units
        ))
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private func rideRow(_ ride: PublicRiderRideSummary) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 1) {
                Text(ride.title ?? "")
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .lineLimit(1)
                Text(rideSubtitle(ride))
                    .font(.caption2)
                    .foregroundStyle(Theme.gray)
            }
            Spacer()
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 44)
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }

    private func rideSubtitle(_ ride: PublicRiderRideSummary) -> String {
        var parts: [String] = []
        let timestamp = Format.rideTimestamp(ride.startedAt)
        if !timestamp.isEmpty { parts.append(timestamp) }
        if let d = ride.distanceM { parts.append("\(Format.distance(fromMeters: d, units: units)) \(units.distanceUnit)") }
        if let e = ride.elevationM { parts.append("\(Format.elevation(fromMeters: e, units: units)) \(units.elevationUnit)") }
        return parts.joined(separator: " · ")
    }

    /// Cached-first, then one parallel refresh — the profile never arrives
    /// in four separate beats (grout pass, 2026-08-21).
    private func load() async {
        if profile == nil { await assemble(policy: .cacheOnly) }
        await assemble(policy: .network)
    }

    private func assemble(policy: CachePolicy) async {
        let response = try? await APIClient.shared.riderProfile(identifier: identifier, policy: policy)
        var nextProfile: PublicProfile? = response?.profile
        var nextRides = response?.recentRides?.rides ?? []
        if nextProfile == nil, policy == .network,
           let me = session.currentUser, me.wallet == identifier || me.id == identifier
        {
            // Own page: same surface fed by the account's own record when the
            // public-profile projection is unavailable (private profiles).
            nextProfile = PublicProfile(
                id: me.id, wallet: me.wallet, username: me.username,
                displayName: me.displayName, bio: me.bio, avatarUrl: me.avatarUrl,
                totalRides: me.totalRides, totalDistanceKm: me.totalDistanceKm,
                totalElevationM: me.totalElevationM
            )
        }
        guard nextProfile != nil || policy == .network else { return }
        let wallet = nextProfile?.wallet ?? identifier
        let own = isOwnPage
        async let summary: UserLeaderboardSummaryResponse? = try? await APIClient.shared.leaderboardPositions(wallet: wallet, policy: policy)
        async let weeksRequest: [TrainingWeek]? = own ? (try? await APIClient.shared.trainingWeeks(policy: policy)) : nil
        async let climbsRequest: RiddenClimbsResponse? = own ? (try? await APIClient.shared.myClimbs(policy: policy)) : nil
        let (loadedSummary, loadedWeeks, loadedClimbs) = await (summary, weeksRequest, climbsRequest)
        if policy == .cacheOnly, nextProfile == nil { return }
        // One reveal.
        if let nextProfile { profile = nextProfile }
        if !nextRides.isEmpty || policy == .network { recentRides = nextRides }
        if let loadedSummary {
            positions = loadedSummary.positions ?? []
            stats = loadedSummary.stats
        }
        if let loadedWeeks { trainingWeeks = loadedWeeks }
        if let loadedClimbs { riddenClimbs = loadedClimbs.climbs ?? [] }
        if policy == .network {
            // Warm what this page links to: recent rides (detail+climbs) and
            // the top ridden climbs' sheets — small reads only.
            let rideIds = nextRides.prefix(3).map(\.id)
            let climbIds = (loadedClimbs?.climbs ?? []).prefix(3).compactMap(\.canonClimbId)
            Task.detached(priority: .utility) {
                for id in rideIds {
                    _ = try? await APIClient.shared.rideDetail(id: id)
                    _ = try? await APIClient.shared.ridePatterns(id: id)
                }
                for id in climbIds {
                    guard let climb = try? await APIClient.shared.climb(id: id) else { continue }
                    if let vaultId = climb.vaultEconomy?.vaultId ?? climb.vaultId {
                        _ = try? await APIClient.shared.climbVaultDetail(vaultId: vaultId)
                        _ = try? await APIClient.shared.myClimbResults(vaultId: vaultId)
                    }
                }
            }
        }
    }
}
