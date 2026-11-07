import CoreLocation
import SwiftUI

/// The share card — the ride as one image in the app's own material: map,
/// name, stat trio, wordmark. A restrained v1; the design remains Tim's to
/// reshape. Presented as a task sheet with a live preview and the system
/// share affordance.
struct ShareCardView: View {
    let title: String
    let dateLine: String
    let distance: String
    let speed: String?
    let climbing: String
    let time: String
    let fragments: [[CLLocationCoordinate2D]]
    /// Passed explicitly (not environment) so ImageRenderer output matches.
    let units: UnitSystem

    @Environment(\.dismiss) private var dismiss
    @State private var rendered: Image?

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            VStack(spacing: 0) {
                SheetHeader(title: "Share Card") { dismiss() }
                    .padding(.top, 6)

                Spacer()
                card
                    .frame(width: 320, height: 400)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
                Spacer()

                if let rendered {
                    ShareLink(
                        item: rendered,
                        preview: SharePreview(title, image: rendered)
                    ) {
                        Text("Share")
                            .font(.body.weight(.semibold))
                            .foregroundStyle(Theme.ink)
                            .frame(maxWidth: .infinity, minHeight: 50)
                            .background(Capsule().fill(Theme.blue))
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.bottom, 24)
                } else {
                    ProgressView()
                        .tint(Theme.gray)
                        .frame(minHeight: 50)
                        .padding(.bottom, 24)
                }
            }
        }
        .task {
            // Rendered at 3x for a crisp export of the same composition the
            // preview shows.
            try? await Task.sleep(for: .milliseconds(700))
            let renderer = ImageRenderer(content: card.frame(width: 320, height: 400))
            renderer.scale = 3
            if let image = renderer.uiImage {
                rendered = Image(uiImage: image)
            }
        }
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 0) {
            RouteMapSnapshot(fragments: fragments)
                .frame(height: 230)

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.headline)
                        .foregroundStyle(Theme.ink)
                        .lineLimit(1)
                    Text(dateLine)
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
                HStack {
                    cardStat("Distance", distance, units.distanceUnit)
                    Spacer()
                    if let speed {
                        cardStat("Avg speed", speed, units.speedUnit)
                        Spacer()
                    }
                    cardStat("Climbing", climbing, units.elevationUnit)
                    Spacer()
                    cardStat("Time", time, nil)
                }
                Spacer(minLength: 0)
                Text("Boulder Roller")
                    .font(.caption.weight(.semibold))
                    .kerning(-0.2)
                    .foregroundStyle(Theme.gray)
            }
            .padding(16)
            .frame(maxHeight: .infinity, alignment: .top)
        }
        .background(Theme.screen)
    }

    private func cardStat(_ label: String, _ value: String, _ unit: String?) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(Theme.gray)
            StatValueText(value: value, unit: unit, valueFont: .numeral(.subheadline))
        }
    }
}
