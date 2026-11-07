import SwiftUI

/// One paired device's room — stock Bluetooth-settings choreography
/// (Settings → Bluetooth → ⓘ). Facts on top; zero-offset calibration where
/// the meter's GATT actually supports it (Cycling Power Control Point +
/// feature bit), with truthful result states; Forget This Device below.
struct SensorDetailView: View {
    let sensorID: UUID

    @Environment(\.dismiss) private var dismiss
    @State private var sensors = SensorManager.shared
    @State private var confirmingForget = false

    private var sensor: Sensor? {
        sensors.myDevices.first { $0.id == sensorID }
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: sensor?.name ?? "Sensor") { dismiss() }
                        .padding(.top, 6)

                    if let sensor {
                        VStack(alignment: .leading, spacing: 0) {
                            GroupCard {
                                GrammarRow(label: "Type", value: sensor.kindLabel)
                                RowSeparator()
                                GrammarRow(
                                    label: "Status",
                                    value: sensor.isConnected ? "Connected" : "Not Connected"
                                )
                            }

                            if sensors.supportsCalibration(sensor.id) {
                                calibrationCard(sensor)
                            }

                            GroupCard {
                                CenteredActionRow(label: "Forget This Device", color: Theme.blue) {
                                    confirmingForget = true
                                }
                            }
                            .padding(.top, 24)
                        }
                        .padding(.horizontal, Theme.margin)
                        .padding(.top, 22)
                        .padding(.bottom, 32)
                    }
                }
            }
        }
        .confirmationDialog(
            "Forget \(sensor?.name ?? "this device")?",
            isPresented: $confirmingForget,
            titleVisibility: .visible
        ) {
            Button("Forget Device", role: .destructive) {
                if let sensor { sensors.forget(sensor) }
                dismiss()
            }
        }
    }

    // MARK: Calibration (zero offset)

    @ViewBuilder
    private func calibrationCard(_ sensor: Sensor) -> some View {
        let state = sensors.calibrationState(sensor.id)
        VStack(alignment: .leading, spacing: 0) {
            GroupCard {
                switch state {
                case .preparing, .awaitingResponse:
                    HStack(spacing: 10) {
                        ProgressView()
                            .controlSize(.small)
                            .tint(Theme.gray)
                        Text("Calibrating…")
                            .font(.body.weight(.medium))
                            .foregroundStyle(Theme.gray)
                    }
                    .frame(maxWidth: .infinity, minHeight: Theme.row)
                    .accessibilityElement(children: .combine)
                case .idle, .succeeded, .failed:
                    CenteredActionRow(label: "Calibrate", color: Theme.gray) {
                        sensors.startCalibration(sensor.id)
                    }
                }
            }
            GroupFooter(text: calibrationFooter(state))
        }
        .padding(.top, 24)
    }

    /// Truthful result states only — the footer reports exactly what the
    /// meter said, or the instruction while nothing is pending.
    private func calibrationFooter(_ state: PowerCalibrationFlow.State) -> String {
        switch state {
        case .idle, .preparing, .awaitingResponse:
            return "Keep weight off the pedals, then calibrate."
        case let .succeeded(rawOffset):
            if let rawOffset {
                return "Calibrated. Offset \(rawOffset)."
            }
            return "Calibrated."
        case let .failed(failure):
            switch failure {
            case .notSupported:
                return "This sensor does not support calibration."
            case .rejected:
                return "The sensor rejected calibration."
            case .writeFailed:
                return "Calibration failed."
            case .timedOut:
                return "The sensor did not respond."
            case .disconnected:
                return "The sensor disconnected."
            }
        }
    }
}
