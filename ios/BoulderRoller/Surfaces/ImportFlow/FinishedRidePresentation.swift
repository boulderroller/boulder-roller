import SwiftUI

/// Durable acknowledgement is shared by both exits. Done returns to the feed;
/// View Ride opens the ride sheet. A ride with no counted climbs skips every beat.
struct FinishedRidePresentation: View {
    let pending: PendingRideReveal
    @Environment(AppSession.self) private var session
    @State private var showsVerification = false

    var body: some View {
        Group {
            if pending.data.beats.isEmpty {
                NavigationStack {
                    RideDetailView(rideId: pending.authoritativeRideID)
                        .toolbar {
                            ToolbarItem(placement: .topBarLeading) { Button("Done") { finish(openRide: false) } }
                        }
                }
            } else {
                RevealView(data: pending.data,
                           onDone: { finish(openRide: false) },
                           onViewRide: { finish(openRide: true) },
                           onVerification: { showsVerification = true })
            }
        }
        .sheet(isPresented: $showsVerification) {
            RevealVerificationView(verification: pending.data.verification)
        }
    }

    private func finish(openRide: Bool) {
        Task { await session.acknowledgePendingRideReveal(pending, openRide: openRide) }
        if pending.data.beats.contains(.mark) { PushRegistrar.maybeAsk(.firstLeaderboardEntry) }
    }
}

struct RevealVerificationView: View {
    let verification: RevealData.Verification?
    @Environment(\.dismiss) private var dismiss

    private var transactionURL: URL? {
        guard let transaction = verification?.transaction, !transaction.isEmpty else { return nil }
        var url = URLComponents(string: "https://explorer.solana.com")
        url?.path = "/tx/\(transaction)"
        if AppConfig.solanaNetwork != "mainnet-beta" {
            url?.queryItems = [URLQueryItem(name: "cluster", value: AppConfig.solanaNetwork)]
        }
        return url?.url
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    if let status = verification?.status { Text(status).font(.body) }
                    if let hash = verification?.rideHash {
                        Text(hash).font(.footnote.monospaced()).textSelection(.enabled)
                    }
                    if let transaction = verification?.transaction, let url = transactionURL {
                        Link(transaction, destination: url).font(.footnote.monospaced()).tint(Theme.blue)
                    }
                }.foregroundStyle(Theme.ink).padding(Theme.margin)
            }
            .background(Theme.sheet).navigationTitle("Verification")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }
}
