import SwiftUI
import UIKit

/// Weight-only numeral entry. Threshold is derived and read-only.
struct PhysiologyEditSheet: View {
    let riderID: String
    let usesMetricWeight: Bool
    var onChanged: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var hadStoredValue = false
    @FocusState private var focused: Bool

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Weight", doneEnabled: inputIsValid, onDone: save)
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        amountCard
                        if hadStoredValue {
                            GroupCard {
                                CenteredActionRow(label: "Clear", color: Theme.gray) {
                                    clear()
                                }
                            }
                            .padding(.top, 20)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .onAppear(perform: prefill)
    }

    private var amountCard: some View {
        HStack(alignment: .firstTextBaseline, spacing: 7) {
            TextField("0", text: $text)
                .keyboardType(usesMetricWeight ? .decimalPad : .numberPad)
                .focused($focused)
                .font(.system(size: 40, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .kerning(-0.5)
                .foregroundStyle(Theme.ink)
                .onChange(of: text) { old, new in
                    let cleaned = sanitize(new)
                    if cleaned != new { text = cleaned }
                    if Int(wholePart(old)) ?? 0 != Int(wholePart(cleaned)) ?? 0,
                       (Int(wholePart(cleaned)) ?? 0) % 10 == 0 {
                        UISelectionFeedbackGenerator().selectionChanged()
                    }
                }
                .accessibilityLabel(
                    usesMetricWeight ? "Weight in kilograms" : "Weight in pounds"
                )
            Text(usesMetricWeight ? "kg" : "lb")
                .font(.body)
                .foregroundStyle(Theme.gray)
        }
        .padding(16)
        .background(Theme.card)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
        .task { focused = true }
    }

    private func sanitize(_ raw: String) -> String {
        guard usesMetricWeight else {
            return String(raw.filter(\.isNumber).prefix(3))
        }
        var out = ""
        var sawSeparator = false
        for character in raw {
            if character.isNumber {
                out.append(character)
            } else if character == "." || character == ",", !sawSeparator, !out.isEmpty {
                sawSeparator = true
                out.append(".")
            }
        }
        if let dot = out.firstIndex(of: ".") {
            let maxEnd = out.index(dot, offsetBy: 2, limitedBy: out.endIndex) ?? out.endIndex
            out = String(out[..<maxEnd])
        }
        return String(out.prefix(5))
    }

    private func wholePart(_ value: String) -> String {
        value.split(separator: ".").first.map(String.init) ?? value
    }

    private var enteredKilograms: Double? {
        guard let value = Double(text), value.isFinite else { return nil }
        return usesMetricWeight ? value : value / Format.poundsPerKilogram
    }

    private var inputIsValid: Bool {
        guard let kg = enteredKilograms else { return false }
        return RiderPhysiologyStore.plausibleWeightKg.contains((kg * 10).rounded() / 10)
    }

    private func save() {
        guard let kg = enteredKilograms, inputIsValid,
              RiderPhysiologyStore.setWeight(kg: kg, riderID: riderID)
        else { return }
        let rounded = (kg * 10).rounded() / 10
        Task { _ = try? await APIClient.shared.updateWeight(kg: rounded) }
        onChanged()
        dismiss()
    }

    private func clear() {
        RiderPhysiologyStore.clearWeight(riderID: riderID)
        Task { _ = try? await APIClient.shared.updateWeight(kg: nil) }
        onChanged()
        dismiss()
    }

    private func prefill() {
        let physiology = RiderPhysiologyStore.load(riderID: riderID)
        hadStoredValue = physiology.weightKg != nil
        guard let kg = physiology.weightKg else { return }
        if usesMetricWeight {
            let tenths = (kg * 10).rounded() / 10
            text = tenths == tenths.rounded()
                ? "\(Int(tenths))"
                : Format.number(tenths, places: Precision.weightKg)
        } else {
            text = "\(Int((kg * Format.poundsPerKilogram).rounded()))"
        }
    }
}
