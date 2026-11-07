import SwiftUI

/// The design constitution's measurable law.
/// `docs/design/MOBILE_DESIGN_CONSTITUTION.md` §1–§3. Deviations are bugs.
enum Theme {
    // MARK: The four constants

    /// Sheet top corner radius.
    static let crown: CGFloat = 40
    /// Horizontal page inset.
    static let margin: CGFloat = 20
    /// Standard list row height.
    static let row: CGFloat = 52
    /// The one text size doing almost all work.
    static let body: CGFloat = 17

    /// Concentric corner rule: inner radius = outer radius − inset.
    /// Sheet crown 40 − margin 20 = card radius 20.
    static let cardRadius: CGFloat = crown - margin

    // MARK: Color ledger (exhaustive)
    //
    // Ratified by Tim 2026-08-21 (constitution §2): a warm charcoal ramp
    // (same luminance ladder the app always had, hue moved warm), warm ink
    // for text, and one cobalt action blue chosen over system blue for the
    // route line's authority and for eyes that bloom on electric blue.

    /// *Something to do or see* — the only action color. Cobalt #5592E2.
    /// Crispness on thin text comes from weight, never from chroma.
    static let blue = Color(red: 0x55 / 255.0, green: 0x92 / 255.0, blue: 0xE2 / 255.0)
    /// *Earning events only* — on screen seconds, never a state. #E8C15A.
    static let gold = Color(red: 0xE8 / 255.0, green: 0xC1 / 255.0, blue: 0x5A / 255.0)

    // Warm dark ramp (chrome/grays). Value is luminance, never hue.
    static let screen = Color(red: 0x0F / 255.0, green: 0x0E / 255.0, blue: 0x0C / 255.0)
    static let sheet = Color(red: 0x1B / 255.0, green: 0x1A / 255.0, blue: 0x17 / 255.0)
    static let card = Color(red: 0x2A / 255.0, green: 0x28 / 255.0, blue: 0x25 / 255.0)
    /// Cards sitting on the screen layer (feed); one step above `screen`,
    /// dimmer than sheet-layer cards.
    static let feedCard = Color(red: 0x1A / 255.0, green: 0x19 / 255.0, blue: 0x16 / 255.0)
    /// The gray transaction commit — blue in, gray out (constitution §4).
    static let commitGray = Color(red: 0x30 / 255.0, green: 0x2E / 255.0, blue: 0x2A / 255.0)
    static let mapBase = Color(red: 0x0E / 255.0, green: 0x10 / 255.0, blue: 0x13 / 255.0)

    /// Secondary text.
    static let gray = Color(red: 0x9A / 255.0, green: 0x94 / 255.0, blue: 0x88 / 255.0)
    /// Tertiary text.
    static let gray2 = Color(red: 0x6A / 255.0, green: 0x66 / 255.0, blue: 0x60 / 255.0)
    /// Faintest text / chevrons.
    static let gray3 = Color(red: 0x4E / 255.0, green: 0x4B / 255.0, blue: 0x46 / 255.0)

    static let separator = Color(red: 90 / 255.0, green: 87 / 255.0, blue: 82 / 255.0).opacity(0.45)

    /// Primary text and glyphs — warm off-white, so text and chrome share
    /// one temperature and the blue stands alone as the cool note.
    /// (Recording numerals and the map start dot stay pure white by design:
    /// the outdoor screen and the window keep their own temperature.)
    static let ink = Color(red: 0xF1 / 255.0, green: 0xEE / 255.0, blue: 0xE8 / 255.0)

    /// Route casing under the blue line on maps.
    static let routeCasing = Color(red: 0x0A / 255.0, green: 0x32 / 255.0, blue: 0x68 / 255.0)
    /// Counted (blue-tinted) relief fill.
    static let countedFill = Color(red: 0x0A / 255.0, green: 0x2C / 255.0, blue: 0x53 / 255.0)
    /// Uncounted relief fill.
    static let reliefFill = Color(red: 0x2A / 255.0, green: 0x28 / 255.0, blue: 0x25 / 255.0)
}

// MARK: Typography — SF Pro for words, SF Rounded for every numeral.

extension Font {
    /// A numeral that matters. SF Rounded + monospaced digits.
    static func numeral(_ style: Font.TextStyle, weight: Font.Weight = .medium) -> Font {
        .system(style, design: .rounded).weight(weight)
    }
}

extension View {
    /// Apple's small tracked uppercase section header voice.
    func sectionHeaderStyle() -> some View {
        font(.caption2)
            .fontWeight(.regular)
            .kerning(0.6)
            .textCase(.uppercase)
            .foregroundStyle(Theme.gray)
    }
}
