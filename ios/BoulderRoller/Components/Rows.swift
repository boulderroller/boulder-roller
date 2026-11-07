import SwiftUI

/// Row grammar (constitution §4): `[icon] [label] .... [one trailing value] [›]`
/// At most one trailing element plus an optional chevron.
/// Chevron = tappable; value without chevron = read-only fact.
/// One ratified exception (Tim, 2026-08-17): ride-sheet effort rows stack
/// time over tribute CAL in the trailing slot — effort rows only, nowhere
/// else.
struct GrammarRow: View {
    var icon: String?
    var label: String
    var labelWeight: Font.Weight = .regular
    var value: String?
    var valueIsNumeral: Bool = false
    /// First-load window with nothing cached: the value slot is a quiet
    /// redaction, so "—" keeps meaning unavailable and never "still loading".
    var valueIsLoading: Bool = false
    var valueColor: Color = Theme.gray
    var subtitle: String?
    var chevron: Bool = false
    /// Trailing SF symbol in the one-trailing-element slot (source pickers'
    /// checkmark). Mutually exclusive with `value` by grammar.
    var trailingSystemImage: String? = nil
    var action: (() -> Void)?

    var body: some View {
        let content = HStack(spacing: 12) {
            if let icon {
                Image(systemName: icon)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                    .frame(width: 22)
                    .accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(label)
                    .font(.body)
                    .fontWeight(labelWeight)
                    .foregroundStyle(Theme.ink)
                if let subtitle {
                    Text(subtitle)
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
            }
            Spacer(minLength: 8)
            if let value {
                Text(value)
                    .font(valueIsNumeral ? .numeral(.body) : .body)
                    .monospacedDigit()
                    .foregroundStyle(valueColor)
                    .lineLimit(1)
                    .redacted(reason: valueIsLoading ? .placeholder : [])
            }
            if let trailingSystemImage {
                Image(systemName: trailingSystemImage)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.blue)
            }
            if chevron {
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.gray3)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 14)
        .frame(minHeight: Theme.row)
        .contentShape(Rectangle())

        if let action {
            Button(action: action) { content }
                .buttonStyle(.plain)
                .accessibilityElement(children: .combine)
        } else {
            content
                .accessibilityElement(children: .combine)
        }
    }
}

/// Centered blue text row = grouped action (Settings "Sign Out" species).
struct CenteredActionRow: View {
    var label: String
    var color: Color = Theme.blue
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            // Semibold: thin action text gets its crispness from weight, not
            // chroma (cobalt ledger, 2026-08-21).
            Text(label)
                .font(.body.weight(.semibold))
                .foregroundStyle(color)
                .frame(maxWidth: .infinity, minHeight: Theme.row)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// Grouped card: the app's one container species.
/// Card radius = crown − margin (concentric corner rule).
struct GroupCard<Content: View>: View {
    var leadingSeparatorInset: CGFloat = 14
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: 0) {
            content
        }
        .background(Theme.card)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

struct RowSeparator: View {
    var inset: CGFloat = 14

    var body: some View {
        Rectangle()
            .fill(Theme.separator)
            .frame(height: 0.5)
            .padding(.leading, inset)
    }
}

struct SectionHeader: View {
    var title: String
    var trailing: String?
    var trailingAction: (() -> Void)?

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .sectionHeaderStyle()
            Spacer()
            if let trailing {
                // "See All" lives in the section header, small and gray
                // (gray = navigation; blue = action). Apple Music grammar.
                if let trailingAction {
                    Button(action: trailingAction) {
                        Text(trailing)
                            .font(.caption)
                            .foregroundStyle(Theme.gray)
                    }
                    .buttonStyle(.plain)
                } else {
                    Text(trailing)
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                }
            }
        }
        .padding(.horizontal, 2)
        .padding(.bottom, 8)
    }
}

/// Grouped-list footer — the sanctioned home for education (Law 1).
struct GroupFooter: View {
    var text: String

    var body: some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(Theme.gray)
            .lineSpacing(2)
            .padding(.horizontal, 2)
            .padding(.top, 12)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Sheet header: title + gray subtitle left, semibold blue Done right.
struct SheetHeader: View {
    var title: String
    var subtitle: String?
    var doneLabel: String = "Done"
    var doneEnabled: Bool = true
    var onDone: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                if let subtitle {
                    Text(subtitle)
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
            }
            Spacer()
            Button(action: onDone) {
                Text(doneLabel)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(doneEnabled ? Theme.blue : Theme.gray3)
            }
            .buttonStyle(.plain)
            .disabled(!doneEnabled)
        }
        .padding(.horizontal, Theme.margin - 2)
        .padding(.top, 10)
    }
}

/// Numeral-with-unit text: white rounded numeral, small gray unit.
struct StatValueText: View {
    var value: String
    var unit: String?
    var valueFont: Font = .numeral(.body)

    var body: some View {
        let numeral = Text(value)
            .font(valueFont)
            .monospacedDigit()
            .foregroundStyle(Theme.ink)
        if let unit {
            Text("\(numeral) \(Text(unit).font(.caption2).foregroundStyle(Theme.gray))")
        } else {
            numeral
        }
    }
}

/// Circled avatar initials (real avatars load when the account has one).
struct AvatarView: View {
    var name: String?
    var url: URL?
    var size: CGFloat

    private var initials: String {
        let parts = (name ?? "").split(separator: " ").prefix(2)
        let letters = parts.compactMap { $0.first }.map(String.init).joined()
        return letters.isEmpty ? "•" : letters.uppercased()
    }

    var body: some View {
        ZStack {
            Circle().fill(Theme.card)
            if let url {
                CachedRemoteImage(url: url) { image in
                    image.resizable().scaledToFill()
                } placeholder: {
                    initialsText
                }
            } else {
                initialsText
            }
        }
        .frame(width: size, height: size)
        .clipShape(Circle())
        .accessibilityHidden(true)
    }

    private var initialsText: some View {
        Text(initials)
            .font(.system(size: size * 0.36, weight: .medium))
            .foregroundStyle(Theme.ink)
    }
}

/// The quiet unavailable card — the feed's species, shared so load
/// failures read the same everywhere: one gray sentence, one quiet Retry.
/// Never a stock full-screen apology (bead boulderroller-v2-2etd7).
struct UnavailableCard: View {
    let text: String
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text(text)
                .font(.footnote)
                .foregroundStyle(Theme.gray)
            Spacer(minLength: 8)
            Button("Retry", action: onRetry)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.gray)
                .buttonStyle(.plain)
                .frame(minHeight: 44)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: Theme.row)
        .background(Theme.card)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}
