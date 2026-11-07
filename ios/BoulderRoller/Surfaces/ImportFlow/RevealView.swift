import SwiftUI
import UIKit

/// The ratified board: reading → coin → conditional mark → ledger → stone.
struct RevealView: View {
    let data: RevealData
    let onDone: () -> Void
    let onViewRide: () -> Void
    let onVerification: () -> Void
    private let freezesMotion: Bool
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.revealPreviewReduceMotion) private var previewReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || previewReduceMotion }
    @State private var page: Int
    @State private var drain: RevealDrain

    init(data: RevealData, initialBeat: RevealData.Beat? = nil,
         freezesMotion: Bool = false, drainSteps: Int = 0,
         onDone: @escaping () -> Void, onViewRide: @escaping () -> Void = {},
         onVerification: @escaping () -> Void = {}) {
        self.data = data
        self.onDone = onDone
        self.onViewRide = onViewRide
        self.onVerification = onVerification
        self.freezesMotion = freezesMotion
        _page = State(initialValue: initialBeat.flatMap { data.beats.firstIndex(of: $0) } ?? 0)
        var state = RevealDrain(climbCount: data.climbs.count, tributeCount: data.itemizedTribute.count)
        for _ in 0..<max(0, drainSteps) { state.advance() }
        _drain = State(initialValue: state)
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .bottom) {
                Theme.screen.ignoresSafeArea()
                if reduceMotion {
                    beatView(data.beats[page], active: true)
                        .id(page)
                        .transition(.opacity)
                        .animation(.easeInOut(duration: 0.2), value: page)
                } else {
                    TabView(selection: $page) {
                        ForEach(Array(data.beats.enumerated()), id: \.offset) { index, beat in
                            beatView(beat, active: index == page).tag(index)
                        }
                    }
                    .tabViewStyle(.page(indexDisplayMode: .never))
                    .animation(.spring(duration: 0.45), value: page)
                    .accessibilitySortPriority(1)
                }
                VStack(spacing: 18) {
                    HStack(spacing: 6) {
                        ForEach(data.beats.indices, id: \.self) { i in
                            Circle().fill(i == page ? Theme.ink : Theme.gray3).frame(width: 6, height: 6)
                        }
                    }.accessibilityHidden(true)
                    Button {
                        if page == data.beats.count - 1 {
                            if drain.isStone { onDone() } else { onViewRide() }
                        } else {
                            withAnimation(reduceMotion ? .easeInOut(duration: 0.2) : .spring(duration: 0.45)) { page += 1 }
                        }
                    } label: {
                        Text(page == data.beats.count - 1 ? (drain.isStone ? "Done" : "View Ride") : "Continue")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Theme.ink)
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .background(Capsule().fill(Theme.card))
                    }.buttonStyle(.plain)
                }
                .padding(.horizontal, 70)
                .padding(.bottom, max(36, geometry.safeAreaInsets.bottom))
                .padding(.top, 12)
                .background(Theme.screen)
            }
        }
        .ignoresSafeArea()
    }

    @ViewBuilder private func beatView(_ beat: RevealData.Beat, active: Bool) -> some View {
        switch beat {
        case .coin: CoinBeat(data: data, active: active, freezesMotion: freezesMotion)
        case .mark:
            if let entry = data.leaderboardEntry {
                MarkBeat(entry: entry, active: active, freezesMotion: freezesMotion)
            }
        case .ledger:
            LedgerBeat(data: data, drain: $drain, active: active,
                       freezesMotion: freezesMotion, onVerification: onVerification)
        }
    }
}

private struct CoinBeat: View {
    let data: RevealData
    let active: Bool
    let freezesMotion: Bool
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.revealPreviewReduceMotion) private var previewReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || previewReduceMotion }
    @State private var completed = 0
    @State private var running: Int?
    @State private var runProgress: Double = 0
    @State private var performed = false

    private var spine: RideSpineData { data.spine ?? .empty }
    private var final: Bool { reduceMotion || freezesMotion }
    private var figure: Double { final ? data.calEarned ?? 0 : data.coinFigure(completedSpans: completed) }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                Text("BOULDER ROLLED")
                    .font(.caption2.weight(.semibold)).kerning(1.6).foregroundStyle(Theme.gray)
                    .padding(.top, 132)
                if let title = data.title, !title.isEmpty {
                    Text(title).font(.caption).foregroundStyle(Theme.gray).padding(.top, 10)
                }
                RideSpine(data: spine, spanColors: spine.spans.map { _ in Theme.gold },
                          spanProgress: spine.spans.indices.map { i in
                              final || i < completed ? 1 : (i == running ? runProgress : 0)
                          })
                    .frame(height: 84).padding(.top, 49).padding(.horizontal, 32)
                VStack(spacing: 6) {
                    Text(Format.amount(figure))
                        .font(.system(size: 64, weight: .semibold, design: .rounded))
                        .kerning(-2).monospacedDigit()
                    Text("CAL").font(.subheadline.weight(.medium))
                    Text("pending").font(.footnote).foregroundStyle(Theme.gray).padding(.top, 4)
                }
                .foregroundStyle(Theme.gold).padding(.top, 36)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("\(Format.amount(data.calEarned)) CAL pending")
                Spacer(minLength: 135)
            }
        }
        .scrollIndicators(.hidden).ignoresSafeArea().accessibilitySortPriority(1)
        .overlay(GoldMotes().ignoresSafeArea().accessibilityHidden(true))
        .task(id: active) {
            guard active, !performed else { return }
            if final { completed = spine.spans.count; performed = true; return }
            for index in completed..<spine.spans.count {
                guard !Task.isCancelled else { return }
                running = index
                runProgress = 0
                withAnimation(.linear(duration: 0.45)) { runProgress = 1 }
                do { try await Task.sleep(for: .milliseconds(450)) } catch { return }
                completed = index + 1
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
            }
            performed = true
        }
    }
}

private struct MarkBeat: View {
    let entry: RevealData.LeaderboardEntry
    let active: Bool
    let freezesMotion: Bool
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.revealPreviewReduceMotion) private var previewReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || previewReduceMotion }
    @State private var hasSet = false
    @State private var performed = false
    private var landed: Bool { hasSet || reduceMotion || freezesMotion }
    private var seats: [RevealData.LeaderboardEntry.Seat] {
        (entry.neighboringSeats ?? []).filter { $0.rank != entry.rank && (1...11).contains($0.rank) }
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                Text("LEADERBOARD").font(.caption2.weight(.semibold)).kerning(1.6)
                    .foregroundStyle(Theme.gray).padding(.top, 132)
                Text(entry.climbName).font(.body.weight(.semibold)).foregroundStyle(Theme.ink)
                    .padding(.top, 64)
                if let time = entry.timeS {
                    Text(entry.previousBestTimeS.map { "\(Format.climbTime(time)) · was \(Format.climbTime($0))" } ?? Format.climbTime(time))
                        .font(.numeral(.footnote, weight: .regular)).foregroundStyle(Theme.gray).padding(.top, 2)
                }
                VStack(spacing: 6) {
                    ForEach(Array(Set(seats.map(\.rank) + [entry.rank])).sorted(), id: \.self) { rank in
                        if rank == entry.rank {
                            seat(rank: rank, name: "You", time: entry.timeS, isRider: true)
                                .offset(y: landed ? 0 : -18).opacity(landed ? 1 : 0)
                        } else if let neighbor = seats.first(where: { $0.rank == rank }) {
                            seat(rank: rank, name: neighbor.name, time: neighbor.timeS, isRider: false)
                                .offset(y: !landed && neighbor.previousRank == rank - 1 ? -66 : 0)
                                .opacity(neighbor.previousRank == rank - 1 ? 0.6 : 1)
                        }
                    }
                }.padding(.top, 30)
                Spacer(minLength: 140)
            }.padding(.horizontal, 32)
        }.scrollIndicators(.hidden).ignoresSafeArea().accessibilitySortPriority(1)
        .overlay(GoldMotes().ignoresSafeArea().accessibilityHidden(true))
        .task(id: active) {
            guard active, !performed else { return }
            if !reduceMotion && !freezesMotion {
                withAnimation(.easeOut(duration: 0.35)) { hasSet = true }
                do { try await Task.sleep(for: .milliseconds(350)) } catch { return }
            }
            if !freezesMotion { UIImpactFeedbackGenerator(style: .heavy).impactOccurred() }
            performed = true
        }
    }

    private func ordinal(_ rank: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .ordinal
        return formatter.string(from: NSNumber(value: rank)) ?? "\(rank)"
    }

    private func seat(rank: Int, name: String, time: Double?, isRider: Bool) -> some View {
        HStack(spacing: 14) {
            Group {
                if rank <= 3 {
                    RankMark(rank: rank, size: isRider ? 44 : 34, tint: isRider ? Theme.gold : nil)
                } else {
                    Text(ordinal(rank)).font(.numeral(.body)).foregroundStyle(isRider ? Theme.gold : Theme.gray)
                }
            }.frame(width: 34)
            Text(name).font(.body.weight(isRider ? .semibold : .regular))
                .foregroundStyle(isRider ? Theme.ink : Theme.gray)
            Spacer(minLength: 8)
            if let time {
                Text(Format.climbTime(time)).font(.numeral(.footnote, weight: .regular))
                    .foregroundStyle(isRider ? Theme.gold : Theme.gray)
            }
        }.frame(minHeight: 60).accessibilityElement(children: .combine)
    }
}

private struct LedgerBeat: View {
    let data: RevealData
    @Binding var drain: RevealDrain
    let active: Bool
    let freezesMotion: Bool
    let onVerification: () -> Void
    @Environment(\.units) private var units
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    @Environment(\.revealPreviewReduceMotion) private var previewReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || previewReduceMotion }
    @Environment(\.dynamicTypeSize) private var typeSize

    private var spine: RideSpineData { data.spine ?? .empty }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                VStack(spacing: 3) {
                    if let title = data.title, !title.isEmpty {
                        Text(title).font(.body.weight(.semibold)).foregroundStyle(Theme.ink)
                    }
                    if !data.subtitle.isEmpty { Text(data.subtitle).font(.caption2).foregroundStyle(Theme.gray) }
                }.padding(.top, 64)
                RideSpine(data: spine, spanColors: spine.spans.map { span in
                    let index = data.climbs.firstIndex { $0.id == span.climbID }
                    // Unidentified API spans cannot claim a per-climb
                    // settlement moment. They arrive in their final ink.
                    return index == nil || index.map { drain.settledClimb($0) } == true || drain.isStone ? Theme.blue : Theme.gold
                })
                    .frame(height: 72).padding(.top, 18)
                let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12)) : AnyLayout(HStackLayout(alignment: .top, spacing: 12))
                layout {
                    stat("Distance", data.distanceM.map { "\(Format.distance(fromMeters: $0, units: units)) \(units.distanceUnit)" })
                    if !typeSize.isAccessibilitySize { Spacer(minLength: 0) }
                    stat("Elevation", data.elevationM.map { "\(Format.elevation(fromMeters: $0, units: units)) \(units.elevationUnit)" })
                    if !typeSize.isAccessibilitySize { Spacer(minLength: 0) }
                    stat("Time", data.durationS.map { Format.clockDuration($0) })
                }.frame(maxWidth: .infinity, alignment: .leading).padding(.top, 14)
                VStack(spacing: 0) {
                    ForEach(Array(data.climbs.enumerated()), id: \.element.id) { index, climb in
                        climbRow(climb, index: index)
                    }
                    if !data.itemizedTribute.isEmpty {
                        HStack(spacing: 5) {
                            Text("CAL TRIBUTE").kerning(1.2)
                            Text("· pending")
                        }.font(.caption2).foregroundStyle(Theme.gray)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 18).padding(.bottom, 4)
                        ForEach(Array(data.itemizedTribute.enumerated()), id: \.element.id) { index, line in
                            row(name: line.climbName,
                                value: "\(Format.baseUnits(line.baseUnits, tokenDecimals: line.decimals)) CAL",
                                color: drain.settledTribute(index) ? Theme.gray : Theme.gold)
                                .padding(.leading, 24)
                        }
                    }
                    if data.thresholdEconomyState == "held" {
                        Text("Held — clears when your Threshold is established.")
                            .font(.caption).foregroundStyle(Theme.gray)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 18)
                    }
                    if drain.showsVerification {
                        Button(action: onVerification) {
                            HStack {
                                Text("Verification").foregroundStyle(Theme.ink)
                                Spacer()
                                Image(systemName: "chevron.right").font(.caption2).foregroundStyle(Theme.gray2)
                            }.font(.body).frame(minHeight: 44)
                        }.buttonStyle(.plain).padding(.top, 12)
                    }
                }.padding(.top, 22)
                Spacer(minLength: 140)
            }.padding(.horizontal, 32)
        }.scrollIndicators(.hidden).ignoresSafeArea().accessibilitySortPriority(1)
        .task(id: active) {
            guard active, !freezesMotion, !drain.isStone else { return }
            if reduceMotion { drain.finish(); return }
            while drain.next != nil {
                do { try await Task.sleep(for: .milliseconds(240)) } catch { return }
                withAnimation(.easeOut(duration: 0.18)) { drain.advance() }
            }
        }
    }

    private func climbRow(_ climb: RevealData.ClimbLine, index: Int) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: "checkmark").font(.footnote.weight(.semibold))
                .foregroundStyle(drain.settledClimb(index) ? Theme.gray : Theme.gold)
                .opacity(drain.ticked(index) ? 1 : 0).frame(width: 14).accessibilityHidden(true)
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 5) { climbName(climb); best(climb) }
                VStack(alignment: .leading, spacing: 3) { climbName(climb); best(climb) }
            }
            Spacer(minLength: 6)
            if let time = climb.timeS {
                Text(Format.climbTime(time)).font(.numeral(.footnote, weight: .regular)).foregroundStyle(Theme.gray)
            }
        }.frame(minHeight: 34).padding(.vertical, typeSize.isAccessibilitySize ? 8 : 0)
            .accessibilityElement(children: .combine)
    }
    private func climbName(_ climb: RevealData.ClimbLine) -> some View {
        Text(climb.name).font(.body).foregroundStyle(Theme.ink).fixedSize(horizontal: false, vertical: true)
    }
    @ViewBuilder private func best(_ climb: RevealData.ClimbLine) -> some View {
        if climb.isNewBest == true {
            Text("New best").font(.caption2.weight(.medium)).foregroundStyle(Theme.blue).fixedSize()
        }
    }
    private func row(name: String, value: String, color: Color) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(name).font(.body).foregroundStyle(Theme.gray)
            Spacer(minLength: 8)
            Text(value).font(.numeral(.footnote, weight: .regular)).foregroundStyle(color)
        }.frame(minHeight: 34).padding(.vertical, typeSize.isAccessibilitySize ? 8 : 0)
            .accessibilityElement(children: .combine)
    }
    private func stat(_ label: String, _ value: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.caption2).foregroundStyle(Theme.gray)
            if let value { Text(value).font(.numeral(.body)).foregroundStyle(Theme.ink) }
        }.accessibilityElement(children: .combine)
    }
}

private struct GoldMotes: View {
    var body: some View {
        GeometryReader { proxy in
            Circle().fill(Theme.gold.opacity(0.6)).frame(width: 3, height: 3)
                .position(x: 70, y: 188)
            Circle().fill(Theme.gold.opacity(0.4)).frame(width: 3, height: 3)
                .position(x: proxy.size.width * 0.67, y: 440)
        }.allowsHitTesting(false)
    }
}

// DEBUG fixture injection exercises the same reduced-motion branches without
// changing the simulator user's accessibility settings.
extension EnvironmentValues {
    @Entry var revealPreviewReduceMotion = false
}
