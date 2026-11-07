import SwiftUI

/// One image treatment for ride detail and edit surfaces. A storage URL is
/// the only production source; DEBUG fixture URLs exist solely for renders.
struct RideMediaImage: View {
    let url: URL?
    /// Band strips fill and clip; the lightbox fits the whole photo.
    var fit = false

    var body: some View {
        #if DEBUG
        if url?.scheme == "br-fixture" {
            fixtureImage
        } else {
            remoteImage
        }
        #else
        remoteImage
        #endif
    }

    private var remoteImage: some View {
        CachedRemoteImage(url: url) { image in
            if fit {
                image.resizable().scaledToFit()
            } else {
                image.resizable().scaledToFill()
            }
        } placeholder: {
            Color.white.opacity(0.03)
        }
    }

    private var placeholder: some View {
        ZStack {
            Theme.card
            Image(systemName: "photo")
                .foregroundStyle(Theme.gray)
        }
    }

    #if DEBUG
    private var fixtureImage: some View {
        ZStack {
            LinearGradient(
                colors: url?.host == "warm"
                    ? [.orange.opacity(0.9), .indigo.opacity(0.85)]
                    : [.teal.opacity(0.85), .blue.opacity(0.9)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            Path { path in
                path.move(to: CGPoint(x: 0, y: 155))
                path.addCurve(
                    to: CGPoint(x: 420, y: 115),
                    control1: CGPoint(x: 100, y: 65),
                    control2: CGPoint(x: 270, y: 185)
                )
            }
            .stroke(.white.opacity(0.82), lineWidth: 5)
        }
    }
    #endif
}
