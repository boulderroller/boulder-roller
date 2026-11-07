import SwiftUI
import UIKit

/// Surface 8 — Sensor pairing: stock Bluetooth-settings choreography.
/// My Devices with type subtitles and "Connected" in gray; Available with
/// blue Pair; "Searching…" while scanning. Per-device attestation status
/// lands here when hardware signing does.
struct SensorPairingView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var sensors = SensorManager.shared
    @State private var detailSensor: Sensor?

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Sensors") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        if bluetoothOff {
                            GroupCard {
                                // Chevron = tappable; the row hands off to
                                // Settings — never a dead affordance.
                                GrammarRow(label: "Bluetooth is off", value: "Settings", chevron: true) {
                                    if let url = URL(string: UIApplication.openSettingsURLString) {
                                        UIApplication.shared.open(url)
                                    }
                                }
                            }
                            GroupFooter(text: "Turn on Bluetooth in Settings to pair sensors.")
                        } else {
                            if !sensors.myDevices.isEmpty {
                                SectionHeader(title: "My Devices")
                                GroupCard {
                                    ForEach(Array(sensors.myDevices.enumerated()), id: \.element.id) { index, sensor in
                                        if index > 0 { RowSeparator() }
                                        GrammarRow(
                                            label: sensor.name,
                                            value: sensor.isConnected ? "Connected" : "Not Connected",
                                            subtitle: sensor.kindLabel,
                                            chevron: true
                                        ) {
                                            detailSensor = sensor
                                        }
                                    }
                                }
                                .padding(.bottom, 24)
                            }

                            // Two connected devices providing the same
                            // channel: the rider picks the source of truth —
                            // never a silent average, never last-callback.
                            ForEach(sensors.conflictedKinds, id: \.self) { kind in
                                SectionHeader(title: kind.sourceLabel)
                                GroupCard {
                                    let providers = sensors.connectedProviders(of: kind)
                                    ForEach(Array(providers.enumerated()), id: \.element.id) { index, device in
                                        if index > 0 { RowSeparator() }
                                        GrammarRow(
                                            label: device.name,
                                            trailingSystemImage: sensors.resolvedSourceID(for: kind) == device.id
                                                ? "checkmark" : nil
                                        ) {
                                            sensors.selectSource(device.id, for: kind)
                                        }
                                    }
                                }
                                .padding(.bottom, 24)
                            }

                            SectionHeader(
                                title: "Available",
                                trailing: sensors.isScanning ? "Searching…" : nil
                            )
                            GroupCard {
                                ForEach(Array(sensors.available.enumerated()), id: \.element.id) { index, sensor in
                                    if index > 0 { RowSeparator() }
                                    GrammarRow(
                                        label: sensor.name,
                                        value: "Pair",
                                        valueColor: Theme.blue,
                                        subtitle: sensor.kindLabel
                                    ) {
                                        sensors.pair(sensor)
                                    }
                                }
                                if sensors.available.isEmpty {
                                    HStack(spacing: 10) {
                                        ProgressView()
                                            .controlSize(.small)
                                            .tint(Theme.gray)
                                        Text("Searching…")
                                            .font(.body)
                                            .foregroundStyle(Theme.gray)
                                    }
                                    .padding(.horizontal, 14)
                                    .frame(minHeight: Theme.row)
                                    .accessibilityElement(children: .combine)
                                }
                            }
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .sheet(item: $detailSensor) { sensor in
            SensorDetailView(sensorID: sensor.id)
                .presentationCornerRadius(Theme.crown)
        }
        .onAppear { sensors.startScanning() }
        .onDisappear { sensors.stopScanning() }
    }

    private var bluetoothOff: Bool {
        switch sensors.bluetoothState {
        case .poweredOff, .unauthorized, .unsupported:
            return true
        default:
            return false
        }
    }
}
