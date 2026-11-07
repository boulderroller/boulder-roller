import SwiftUI
import WorkoutParse

/// Share-sheet GPX/FIT import joining the same pipeline as every ride:
/// preliminary on-device parse (the real workout-parse crate over UniFFI),
/// then the production upload path (init → storage PUT → complete), then the
/// processing beat while the backend pipeline runs, then the reveal.
struct ImportFlowView: View {
    let fileURL: URL
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss

    @State private var model = ImportModel()

    var body: some View {
        ZStack {
            Theme.screen.ignoresSafeArea()
            switch model.stage {
            case .working:
                ProcessingBeat(spine: model.spine)
            case .saved:
                ProcessingBeat(spine: model.spine)
            case let .failed(message):
                failureView(message)
            }
        }
        .task {
            await model.run(fileURL: fileURL, user: session.currentUser)
            if model.wasPersisted {
                await session.refreshRideUploads()
                dismiss()
            }
        }
        .interactiveDismissDisabled(model.stageIsWorking)
    }

    private func failureView(_ message: String) -> some View {
        VStack(spacing: 18) {
            Spacer()
            Text(message)
                .font(.subheadline)
                .foregroundStyle(Theme.gray)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            Spacer()
            Button {
                dismiss()
            } label: {
                Text("Done")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .frame(maxWidth: .infinity, minHeight: 44)
                    .background(Capsule().fill(Theme.card))
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 70)
            .padding(.bottom, 24)
        }
    }
}

/// The processing beat — a state, not a room.
struct ProcessingBeat: View {
    static let drawDuration: TimeInterval = 1.2
    var spine: RideSpineData = .empty
    var title: String? = nil
    var freezesMotion = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var progress: Double = 0

    var body: some View {
        VStack(spacing: 0) {
            Text("RIDE").font(.caption2.weight(.semibold)).kerning(1.6)
                .foregroundStyle(Theme.gray2).padding(.top, 132)
            if let title, !title.isEmpty {
                Text(title).font(.caption).foregroundStyle(Theme.gray).padding(.top, 10)
            }
            RideSpine(data: spine, drawProgress: reduceMotion ? 1 : freezesMotion ? 0.62 : progress,
                      spanColors: spine.spans.map { _ in Theme.ink },
                      spanProgress: spine.spans.map { _ in 0 })
                .frame(height: 84).padding(.horizontal, 32).padding(.top, 49)
            Text("Reading your ride…").font(.subheadline).foregroundStyle(Theme.gray).padding(.top, 36)
            Spacer()
        }.frame(maxWidth: .infinity).background(Theme.screen).ignoresSafeArea()
            .task(id: spine.runs.count) {
                guard !freezesMotion, !spine.runs.isEmpty else { return }
                if reduceMotion { progress = 1 }
                else { withAnimation(.linear(duration: Self.drawDuration)) { progress = 1 } }
            }
    }
}

@MainActor
@Observable
final class ImportModel {
    enum Stage {
        case working
        case saved
        case failed(String)
    }

    var stage: Stage = .working
    var wasPersisted = false
    var spine = RideSpineData.empty
    var stageIsWorking: Bool {
        if case .working = stage { return true }
        return false
    }

    func run(fileURL: URL, user: User?, uploadRuntime: RideUploadRuntime = .shared) async {
        do {
            guard let user else { throw APIError.notAuthenticated }
            let data = try readFile(at: fileURL)
            let ext = fileURL.pathExtension.lowercased()
            guard let kind = RideFileKind(fileExtension: ext) else {
                throw APIError.decoding("Unsupported file type")
            }

            // Preliminary on-device parse — the same Rust code the backend
            // runs. Surfaces bad files immediately, before any upload. The
            // rider's derived Threshold (or truthful absence) drives effort fields.
            let preliminary = try await WorkoutParser.preliminarySummary(
                data: data,
                kind: kind,
                // Only denominator-independent fields enter local custody.
                // The backend owns the current derived Threshold projection.
                thresholdWatts: nil
            )

            let profile = preliminary.elevationProfile.map {
                RideSpineData.Point(distanceM: $0.distanceM, elevationM: $0.elevationM)
            }
            spine = profile.count > 1 ? RideSpineData(runs: [profile], spans: []) : .empty
            let readingDeadline = ContinuousClock.now.advanced(by: .seconds(ProcessingBeat.drawDuration))

            // Persist the immutable bytes and owner-bound logical job before
            // any API or storage handoff. Transfer/reconciliation continues
            // independently of this view and always reuses the same UUID.
            _ = try await uploadRuntime.enqueue(
                user: user,
                fileName: fileURL.lastPathComponent,
                fileType: kind.rawValue,
                sourceBytes: data,
                summary: LocalRideSummary(
                    startedAt: Date(
                        timeIntervalSince1970: Double(preliminary.startedAtMs) / 1_000
                    ),
                    distanceM: Double(preliminary.distanceM),
                    elevationM: Double(preliminary.elevationGainM),
                    durationS: Double(preliminary.durationS)
                )
            )
            wasPersisted = true
            // Saving remains immediate. Keep the reading beat visible long
            // enough for its existing draw to finish before the sheet dismisses.
            if !spine.runs.isEmpty {
                try? await ContinuousClock().sleep(until: readingDeadline)
            }
            stage = .saved
        } catch {
            stage = .failed(error.localizedDescription)
        }
    }

    private func readFile(at url: URL) throws -> Data {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        return try Data(contentsOf: url)
    }

}
