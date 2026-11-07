import SwiftUI

/// fullScreenCover(item:) needs an Identifiable; the tapped band index is
/// the whole identity.
struct PhotoLightboxSelection: Identifiable {
    let index: Int
    var id: Int { index }
}

/// Full-screen ride photo viewer (bead boulderroller-v2-2etd7): black
/// ground, paged photos fit to the screen, the app's glass ✕ — Photos-app
/// bones, no chrome beyond the close control.
struct PhotoLightboxView: View {
    let photos: [RideMedia]
    let initialIndex: Int

    @Environment(\.dismiss) private var dismiss
    @State private var currentIndex: Int

    init(photos: [RideMedia], initialIndex: Int) {
        self.photos = photos
        self.initialIndex = initialIndex
        _currentIndex = State(initialValue: initialIndex)
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.black.ignoresSafeArea()

            TabView(selection: $currentIndex) {
                ForEach(Array(photos.enumerated()), id: \.element.id) { index, photo in
                    RideMediaImage(url: photo.url.flatMap(URL.init), fit: true)
                        .tag(index)
                        .accessibilityLabel(
                            photo.role == "cover" ? "Cover photo" : "Ride photo"
                        )
                }
            }
            .tabViewStyle(.page(indexDisplayMode: photos.count > 1 ? .automatic : .never))
            .ignoresSafeArea()

            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.subheadline)
                    .foregroundStyle(Theme.ink)
                    .frame(width: 34, height: 34)
                    .glassEffect(.regular.interactive(), in: .circle)
            }
            .buttonStyle(.plain)
            .padding(.leading, 16)
            .padding(.top, 12)
            .accessibilityLabel("Close photo")
        }
        .statusBarHidden()
    }
}
