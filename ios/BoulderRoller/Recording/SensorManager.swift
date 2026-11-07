import CoreBluetooth
import Foundation
import Observation

/// One BLE sensor the rider has paired or can pair. Kind derives from the
/// advertised/discovered GATT service, never guessed from the name.
struct Sensor: Identifiable {
    enum Kind: String, Codable {
        case heartRate
        case power
        case cadence

        var label: String {
            switch self {
            case .heartRate: return "Heart Rate"
            case .power: return "Power"
            case .cadence: return "Cadence"
            }
        }

        /// Picker section title when two connected devices provide the
        /// same channel (stock Settings vocabulary).
        var sourceLabel: String {
            switch self {
            case .heartRate: return "Heart Rate Source"
            case .power: return "Power Source"
            case .cadence: return "Cadence Source"
            }
        }
    }

    let id: UUID
    var name: String
    var kinds: [Kind]
    var isConnected: Bool

    var kindLabel: String { kinds.map(\.label).joined(separator: " · ") }
}

/// Surface 8's engine and the recording screen's provenance source: full
/// CoreBluetooth against the standard cycling GATT services — Heart Rate
/// (0x180D/0x2A37), Cycling Power (0x1818/0x2A63 + 0x2A65 feature + 0x2A66
/// control point), Speed & Cadence (0x1816/0x2A5B).
///
/// Truth rules (bead boulderroller-v2-odmi6.11):
/// - Live values exist only while a characteristic is notifying; staleness
///   windows come from `SensorStreamPolicy`, nothing is ever synthesized.
/// - Every testimony is stored per device; the published live value is the
///   `SensorSourceResolver` choice — explicit rider selection first, then
///   earliest-paired connected provider. Never an average, never whichever
///   callback happened last.
/// - Zero-offset calibration is the pure `PowerCalibrationFlow` machine;
///   this class only performs its effects and forwards CoreBluetooth events.
@MainActor
@Observable
final class SensorManager: NSObject {
    static let shared = SensorManager()

    // GATT identifiers.
    private static let heartRateService = CBUUID(string: "180D")
    private static let powerService = CBUUID(string: "1818")
    private static let cadenceService = CBUUID(string: "1816")
    private static let heartRateMeasurement = CBUUID(string: "2A37")
    private static let powerMeasurement = CBUUID(string: "2A63")
    private static let powerFeature = CBUUID(string: "2A65")
    private static let powerControlPoint = CBUUID(string: "2A66")
    private static let cscMeasurement = CBUUID(string: "2A5B")
    private static let scannedServices = [heartRateService, powerService, cadenceService]

    private(set) var bluetoothState: CBManagerState = .unknown
    private(set) var isScanning = false
    /// Devices the rider has paired (persisted; auto-reconnected).
    private(set) var myDevices: [Sensor] = []
    /// Unpaired devices visible right now.
    private(set) var available: [Sensor] = []

    // Live resolved values — nil unless the resolved source testified within
    // its policy window. Published as stored properties so staleness drops
    // re-render observers.
    private(set) var liveHeartRateReading: TimedSensorReading?
    private(set) var liveCadenceReading: TimedSensorReading?
    private(set) var livePowerObservation: PowerObservation?
    var liveHeartRate: Int? { liveHeartRateReading?.value }
    var liveCadence: Int? { liveCadenceReading?.value }
    var livePower: Int? { livePowerObservation?.watts }

    var connectedCount: Int { myDevices.filter(\.isConnected).count }

    // Per-device latest testimony (the resolver's evidence base).
    private var heartRateByDevice: [UUID: TimedSensorReading] = [:]
    private var cadenceByDevice: [UUID: TimedSensorReading] = [:]
    private var powerByDevice: [UUID: PowerObservation] = [:]
    private var lastCrankByDevice: [UUID: (revolutions: UInt16, eventTime1024: UInt16)] = [:]

    /// Explicit per-channel source picks (persisted).
    private(set) var sourceSelection = SensorSourceSelection.load()

    // Calibration (power meters exposing the control point + feature bit).
    private(set) var calibrationFlows: [UUID: PowerCalibrationFlow] = [:]
    private var powerFeatureBits: [UUID: UInt32] = [:]
    private var controlPointsByDevice: [UUID: CBCharacteristic] = [:]
    private var calibrationTimeouts: [UUID: Task<Void, Never>] = [:]

    private var central: CBCentralManager?
    private var peripherals: [UUID: CBPeripheral] = [:]
    private var staleTimer: Timer?

    private struct StoredSensor: Codable {
        let id: UUID
        let name: String
        let kinds: [Sensor.Kind]
    }

    private static let storeKey = "br_paired_sensors"

    override private init() {
        super.init()
        myDevices = Self.loadStored().map {
            Sensor(id: $0.id, name: $0.name, kinds: $0.kinds, isConnected: false)
        }
    }

    /// Bring the central up (first use prompts the system Bluetooth
    /// permission) and reconnect paired devices.
    func activate() {
        #if DEBUG
        guard !renderFixtureFrozen else { return }
        #endif
        if central == nil {
            central = CBCentralManager(delegate: self, queue: .main)
        }
        startStaleTimer()
    }

    func startScanning() {
        activate()
        guard central?.state == .poweredOn, isScanning == false else { return }
        isScanning = true
        available = []
        central?.scanForPeripherals(withServices: Self.scannedServices, options: nil)
    }

    func stopScanning() {
        isScanning = false
        central?.stopScan()
    }

    func pair(_ sensor: Sensor) {
        guard let peripheral = peripherals[sensor.id] else { return }
        available.removeAll { $0.id == sensor.id }
        if !myDevices.contains(where: { $0.id == sensor.id }) {
            myDevices.append(sensor)
        }
        persist()
        central?.connect(peripheral, options: nil)
    }

    func forget(_ sensor: Sensor) {
        if let peripheral = peripherals[sensor.id] {
            central?.cancelPeripheralConnection(peripheral)
        }
        myDevices.removeAll { $0.id == sensor.id }
        persist()
        // A forgotten device holds no priority and no testimony.
        sourceSelection.removeDevice(sensor.id)
        sourceSelection.save()
        dropDeviceTestimony(sensor.id)
        republishResolvedValues()
    }

    func removeAccountData() throws {
        stopScanning()
        for peripheral in peripherals.values {
            central?.cancelPeripheralConnection(peripheral)
        }
        for timeout in calibrationTimeouts.values { timeout.cancel() }
        calibrationTimeouts.removeAll()
        myDevices.removeAll()
        available.removeAll()
        peripherals.removeAll()
        heartRateByDevice.removeAll()
        cadenceByDevice.removeAll()
        powerByDevice.removeAll()
        lastCrankByDevice.removeAll()
        calibrationFlows.removeAll()
        powerFeatureBits.removeAll()
        controlPointsByDevice.removeAll()
        liveHeartRateReading = nil
        liveCadenceReading = nil
        livePowerObservation = nil
        sourceSelection = SensorSourceSelection()
        UserDefaults.standard.removeObject(forKey: Self.storeKey)
        UserDefaults.standard.removeObject(forKey: SensorSourceSelection.storeKey)
        guard UserDefaults.standard.object(forKey: Self.storeKey) == nil,
              UserDefaults.standard.object(forKey: SensorSourceSelection.storeKey) == nil
        else { throw AccountDeletionLocalCleanupError.verificationFailed }
    }

    // MARK: Source resolution (deterministic, never last-callback-wins)

    /// Connected devices currently able to provide a channel, in paired
    /// order (paired order is the persisted priority). A power meter that
    /// has delivered crank cadence counts as a cadence provider even though
    /// it never advertised the CSC service.
    func connectedProviders(of kind: Sensor.Kind) -> [Sensor] {
        myDevices.filter { device in
            guard device.isConnected else { return false }
            if device.kinds.contains(kind) { return true }
            switch kind {
            case .cadence: return cadenceByDevice[device.id] != nil
            case .heartRate: return heartRateByDevice[device.id] != nil
            case .power: return powerByDevice[device.id] != nil
            }
        }
    }

    func resolvedSourceID(for kind: Sensor.Kind) -> UUID? {
        SensorSourceResolver.resolve(
            explicitSelection: sourceSelection[kind],
            connectedProvidersInPairedOrder: connectedProviders(of: kind).map(\.id)
        )
    }

    /// Channels where two or more connected devices overlap right now —
    /// exactly where the Sensors room shows an explicit picker.
    var conflictedKinds: [Sensor.Kind] {
        [.power, .heartRate, .cadence].filter { connectedProviders(of: $0).count >= 2 }
    }

    func selectSource(_ deviceID: UUID, for kind: Sensor.Kind) {
        sourceSelection[kind] = deviceID
        sourceSelection.save()
        republishResolvedValues()
    }

    private func republishResolvedValues(now: Date = .now) {
        liveHeartRateReading = resolvedReading(
            .heartRate,
            from: heartRateByDevice,
            holdMaxS: SensorStreamPolicy.heartRateHoldMaxS,
            now: now
        )
        liveCadenceReading = resolvedReading(
            .cadence,
            from: cadenceByDevice,
            holdMaxS: SensorStreamPolicy.cadenceHoldMaxS,
            now: now
        )
        if
            let sourceID = resolvedSourceID(for: .power),
            let observation = powerByDevice[sourceID],
            now.timeIntervalSince(observation.timestamp) <= SensorStreamPolicy.powerAssociationMaxAgeS
        {
            livePowerObservation = observation
        } else {
            livePowerObservation = nil
        }
    }

    private func resolvedReading(
        _ kind: Sensor.Kind,
        from testimony: [UUID: TimedSensorReading],
        holdMaxS: TimeInterval,
        now: Date
    ) -> TimedSensorReading? {
        guard
            let sourceID = resolvedSourceID(for: kind),
            let reading = testimony[sourceID],
            now.timeIntervalSince(reading.timestamp) <= holdMaxS
        else { return nil }
        return reading
    }

    private func dropDeviceTestimony(_ id: UUID) {
        heartRateByDevice[id] = nil
        cadenceByDevice[id] = nil
        powerByDevice[id] = nil
        lastCrankByDevice[id] = nil
    }

    // MARK: Reconnect

    private func reconnectKnown() {
        guard let central, central.state == .poweredOn else { return }
        let ids = myDevices.map(\.id)
        guard !ids.isEmpty else { return }
        for peripheral in central.retrievePeripherals(withIdentifiers: ids) {
            peripherals[peripheral.identifier] = peripheral
            peripheral.delegate = self
            if peripheral.state != .connected {
                central.connect(peripheral, options: nil)
            }
        }
    }

    // MARK: Live-value staleness — a sensor that stops notifying stops
    // reporting; the policy windows in SensorStreamPolicy bound every hold.

    private func startStaleTimer() {
        guard staleTimer == nil else { return }
        staleTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in self?.dropStale() }
        }
    }

    private func dropStale() {
        let now = Date.now
        heartRateByDevice = heartRateByDevice.filter {
            now.timeIntervalSince($0.value.timestamp) <= SensorStreamPolicy.heartRateHoldMaxS
        }
        cadenceByDevice = cadenceByDevice.filter {
            now.timeIntervalSince($0.value.timestamp) <= SensorStreamPolicy.cadenceHoldMaxS
        }
        powerByDevice = powerByDevice.filter {
            now.timeIntervalSince($0.value.timestamp) <= SensorStreamPolicy.powerAssociationMaxAgeS
        }
        republishResolvedValues(now: now)
    }

    // MARK: Calibration (zero offset)

    /// True when the connected device exposes the Cycling Power Control
    /// Point and its feature bitfield confirms offset compensation. No
    /// control appears on any weaker evidence.
    func supportsCalibration(_ id: UUID) -> Bool {
        #if DEBUG
        if renderFixtureCalibrationSupport.contains(id) { return true }
        #endif
        guard myDevices.first(where: { $0.id == id })?.isConnected == true else { return false }
        guard controlPointsByDevice[id] != nil else { return false }
        guard let bits = powerFeatureBits[id] else { return false }
        return bits & PowerCalibrationGATT.featureOffsetCompensationBit != 0
    }

    func calibrationState(_ id: UUID) -> PowerCalibrationFlow.State {
        calibrationFlows[id]?.state ?? .idle
    }

    func startCalibration(_ id: UUID) {
        guard
            supportsCalibration(id),
            let peripheral = peripherals[id],
            let controlPoint = controlPointsByDevice[id]
        else { return }
        var flow = calibrationFlows[id] ?? PowerCalibrationFlow()
        let effect = flow.begin()
        calibrationFlows[id] = flow
        guard effect != .none else { return }
        scheduleCalibrationTimeout(id)
        // Indications may already be live from a previous run.
        if effect == .enableIndications, controlPoint.isNotifying {
            advanceCalibration(id) { $0.indicationsReady() }
        } else {
            perform(effect, on: peripheral, controlPoint: controlPoint)
        }
    }

    private func perform(
        _ effect: PowerCalibrationFlow.Effect,
        on peripheral: CBPeripheral,
        controlPoint: CBCharacteristic
    ) {
        switch effect {
        case .none:
            break
        case .enableIndications:
            peripheral.setNotifyValue(true, for: controlPoint)
        case .writeStartOffsetCompensation:
            peripheral.writeValue(
                Data([PowerCalibrationGATT.opStartOffsetCompensation]),
                for: controlPoint,
                type: .withResponse
            )
        }
    }

    private func advanceCalibration(
        _ id: UUID,
        _ event: (inout PowerCalibrationFlow) -> PowerCalibrationFlow.Effect
    ) {
        guard var flow = calibrationFlows[id] else { return }
        let effect = event(&flow)
        calibrationFlows[id] = flow
        if !flow.isInFlight { cancelCalibrationTimeout(id) }
        guard
            effect != .none,
            let peripheral = peripherals[id],
            let controlPoint = controlPointsByDevice[id]
        else { return }
        perform(effect, on: peripheral, controlPoint: controlPoint)
    }

    private func applyCalibrationEvent(
        _ id: UUID,
        _ event: (inout PowerCalibrationFlow) -> Void
    ) {
        advanceCalibration(id) { flow in
            event(&flow)
            return .none
        }
    }

    private func scheduleCalibrationTimeout(_ id: UUID) {
        calibrationTimeouts[id]?.cancel()
        calibrationTimeouts[id] = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(SensorStreamPolicy.calibrationTimeoutS))
            guard !Task.isCancelled else { return }
            self?.applyCalibrationEvent(id) { $0.timedOut() }
        }
    }

    private func cancelCalibrationTimeout(_ id: UUID) {
        calibrationTimeouts[id]?.cancel()
        calibrationTimeouts[id] = nil
    }

    // MARK: Persistence

    private func persist() {
        let stored = myDevices.map { StoredSensor(id: $0.id, name: $0.name, kinds: $0.kinds) }
        if let data = try? JSONEncoder().encode(stored) {
            UserDefaults.standard.set(data, forKey: Self.storeKey)
        }
    }

    private static func loadStored() -> [StoredSensor] {
        guard let data = UserDefaults.standard.data(forKey: storeKey) else { return [] }
        return (try? JSONDecoder().decode([StoredSensor].self, from: data)) ?? []
    }

    private func setConnected(_ id: UUID, _ connected: Bool) {
        guard let index = myDevices.firstIndex(where: { $0.id == id }) else { return }
        myDevices[index].isConnected = connected
    }

    private static func kinds(fromAdvertised services: [CBUUID]) -> [Sensor.Kind] {
        var kinds: [Sensor.Kind] = []
        if services.contains(heartRateService) { kinds.append(.heartRate) }
        if services.contains(powerService) { kinds.append(.power) }
        if services.contains(cadenceService) { kinds.append(.cadence) }
        return kinds
    }

    #if DEBUG
    // Render-fixture seeding only (Debug/*RenderFixture.swift): deterministic
    // Sensors-room states in the radio-less simulator, screenshots labeled
    // simulated. Freezing prevents CoreBluetooth activation and persistence;
    // never compiled into release builds.
    private var renderFixtureFrozen = false
    private var renderFixtureCalibrationSupport: Set<UUID> = []

    func debugSeedRenderFixture(
        devices: [Sensor],
        calibrationFlows: [UUID: PowerCalibrationFlow] = [:],
        calibrationSupport: Set<UUID> = []
    ) {
        renderFixtureFrozen = true
        myDevices = devices
        self.calibrationFlows = calibrationFlows
        renderFixtureCalibrationSupport = calibrationSupport
    }
    #endif
}

// MARK: - CBCentralManagerDelegate

extension SensorManager: CBCentralManagerDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        let state = central.state
        Task { @MainActor in
            self.bluetoothState = state
            if state == .poweredOn {
                self.reconnectKnown()
                if self.isScanning {
                    central.scanForPeripherals(withServices: Self.scannedServices, options: nil)
                }
            } else {
                for index in self.myDevices.indices { self.myDevices[index].isConnected = false }
                self.heartRateByDevice = [:]
                self.cadenceByDevice = [:]
                self.powerByDevice = [:]
                self.lastCrankByDevice = [:]
                self.republishResolvedValues()
                for id in Array(self.calibrationFlows.keys) {
                    self.applyCalibrationEvent(id) { $0.deviceDisconnected() }
                }
            }
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let advertised = (advertisementData[CBAdvertisementDataServiceUUIDsKey] as? [CBUUID]) ?? []
        let name = (advertisementData[CBAdvertisementDataLocalNameKey] as? String)
            ?? peripheral.name ?? "Sensor"
        Task { @MainActor in
            self.peripherals[peripheral.identifier] = peripheral
            peripheral.delegate = self
            let kinds = Self.kinds(fromAdvertised: advertised)
            if self.myDevices.contains(where: { $0.id == peripheral.identifier }) {
                // A paired device reappeared — reconnect it.
                if peripheral.state != .connected { central.connect(peripheral, options: nil) }
                return
            }
            guard !kinds.isEmpty else { return }
            if let index = self.available.firstIndex(where: { $0.id == peripheral.identifier }) {
                self.available[index].name = name
                self.available[index].kinds = kinds
            } else {
                self.available.append(
                    Sensor(id: peripheral.identifier, name: name, kinds: kinds, isConnected: false)
                )
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        Task { @MainActor in
            self.setConnected(peripheral.identifier, true)
            peripheral.delegate = self
            self.republishResolvedValues()
            peripheral.discoverServices(Self.scannedServices)
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?
    ) {
        Task { @MainActor in
            let id = peripheral.identifier
            self.setConnected(id, false)
            // Disconnected devices hold no live testimony; an in-flight
            // calibration reports the disconnect truthfully.
            self.dropDeviceTestimony(id)
            self.republishResolvedValues()
            self.applyCalibrationEvent(id) { $0.deviceDisconnected() }
            // Paired devices reconnect when they come back in range.
            if self.myDevices.contains(where: { $0.id == id }) {
                central.connect(peripheral, options: nil)
            }
        }
    }

    nonisolated func centralManager(
        _ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?
    ) {
        Task { @MainActor in
            self.setConnected(peripheral.identifier, false)
        }
    }
}

// MARK: - CBPeripheralDelegate

extension SensorManager: CBPeripheralDelegate {
    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        let services = peripheral.services ?? []
        Task { @MainActor in
            for service in services {
                peripheral.discoverCharacteristics(
                    [
                        Self.heartRateMeasurement,
                        Self.powerMeasurement,
                        Self.powerFeature,
                        Self.powerControlPoint,
                        Self.cscMeasurement,
                    ],
                    for: service
                )
            }
        }
    }

    nonisolated func peripheral(
        _ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?
    ) {
        let characteristics = service.characteristics ?? []
        Task { @MainActor in
            for characteristic in characteristics {
                switch characteristic.uuid {
                case Self.heartRateMeasurement, Self.powerMeasurement, Self.cscMeasurement:
                    peripheral.setNotifyValue(true, for: characteristic)
                case Self.powerFeature:
                    peripheral.readValue(for: characteristic)
                case Self.powerControlPoint:
                    self.controlPointsByDevice[peripheral.identifier] = characteristic
                default:
                    break
                }
            }
        }
    }

    nonisolated func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        let uuid = characteristic.uuid
        let deviceID = peripheral.identifier
        let failed = error != nil
        Task { @MainActor in
            guard uuid == Self.powerControlPoint else { return }
            if failed {
                self.applyCalibrationEvent(deviceID) { $0.indicationsFailed() }
            } else {
                self.advanceCalibration(deviceID) { $0.indicationsReady() }
            }
        }
    }

    nonisolated func peripheral(
        _ peripheral: CBPeripheral,
        didWriteValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        let uuid = characteristic.uuid
        let deviceID = peripheral.identifier
        let failed = error != nil
        Task { @MainActor in
            guard uuid == Self.powerControlPoint, failed else { return }
            self.applyCalibrationEvent(deviceID) { $0.writeFailed() }
        }
    }

    nonisolated func peripheral(
        _ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?
    ) {
        guard let data = characteristic.value, error == nil else { return }
        let uuid = characteristic.uuid
        let deviceID = peripheral.identifier
        Task { @MainActor in
            switch uuid {
            case Self.heartRateMeasurement:
                self.readHeartRate(data, from: deviceID)
            case Self.powerMeasurement:
                self.readPower(data, from: deviceID)
            case Self.cscMeasurement:
                self.readCSC(data, from: deviceID)
            case Self.powerFeature:
                if let bits = PowerCalibrationGATT.featureBits(data) {
                    self.powerFeatureBits[deviceID] = bits
                }
            case Self.powerControlPoint:
                self.applyCalibrationEvent(deviceID) { $0.indication(data) }
            default:
                break
            }
        }
    }

    // MARK: GATT parsers (Bluetooth SIG characteristic formats)

    /// Heart Rate Measurement 0x2A37: flags byte, then uint8 or uint16 bpm.
    private func readHeartRate(_ data: Data, from deviceID: UUID) {
        guard data.count >= 2 else { return }
        let flags = data[0]
        let bpm: Int
        if flags & 0x01 == 0 {
            bpm = Int(data[1])
        } else {
            guard data.count >= 3 else { return }
            bpm = Int(UInt16(data[1]) | (UInt16(data[2]) << 8))
        }
        guard bpm > 0 else { return }
        heartRateByDevice[deviceID] = TimedSensorReading(
            value: bpm,
            timestamp: .now,
            sourceID: deviceID
        )
        republishResolvedValues()
    }

    /// Cycling Power Measurement 0x2A63: flags uint16, instantaneous power
    /// sint16 at offset 2. Crank revolution data (flag bit 5) also yields
    /// cadence when present.
    private func readPower(_ data: Data, from deviceID: UUID) {
        guard data.count >= 4 else { return }
        let flags = UInt16(data[0]) | (UInt16(data[1]) << 8)
        let raw = UInt16(data[2]) | (UInt16(data[3]) << 8)
        let watts = Int(Int16(bitPattern: raw))
        if watts >= 0 {
            powerByDevice[deviceID] = PowerObservation(
                watts: watts,
                timestamp: .now,
                sourceID: deviceID
            )
        }

        // Walk the optional fields preceding crank data.
        var offset = 4
        if flags & 0x0001 != 0 { offset += 1 }   // pedal power balance
        if flags & 0x0004 != 0 { offset += 2 }   // accumulated torque
        if flags & 0x0010 != 0 { offset += 6 }   // wheel revolution data
        if flags & 0x0020 != 0, data.count >= offset + 4 {
            let revolutions = UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
            let eventTime = UInt16(data[offset + 2]) | (UInt16(data[offset + 3]) << 8)
            updateCadence(revolutions: revolutions, eventTime1024: eventTime, from: deviceID)
        }
        republishResolvedValues()
    }

    /// CSC Measurement 0x2A5B: crank revolution data (flag bit 1) — cumulative
    /// crank revolutions uint16 + last crank event time uint16 (1/1024 s).
    private func readCSC(_ data: Data, from deviceID: UUID) {
        guard data.count >= 1 else { return }
        let flags = data[0]
        var offset = 1
        if flags & 0x01 != 0 { offset += 6 }   // wheel revolution data
        guard flags & 0x02 != 0, data.count >= offset + 4 else { return }
        let revolutions = UInt16(data[offset]) | (UInt16(data[offset + 1]) << 8)
        let eventTime = UInt16(data[offset + 2]) | (UInt16(data[offset + 3]) << 8)
        updateCadence(revolutions: revolutions, eventTime1024: eventTime, from: deviceID)
        republishResolvedValues()
    }

    private func updateCadence(
        revolutions: UInt16,
        eventTime1024: UInt16,
        from deviceID: UUID
    ) {
        defer { lastCrankByDevice[deviceID] = (revolutions, eventTime1024) }
        guard let last = lastCrankByDevice[deviceID] else { return }
        let revDelta = revolutions &- last.revolutions
        let timeDelta = eventTime1024 &- last.eventTime1024
        guard revDelta > 0, timeDelta > 0 else { return }
        let seconds = Double(timeDelta) / 1024.0
        let rpm = Double(revDelta) / seconds * 60.0
        guard rpm < 300 else { return }
        cadenceByDevice[deviceID] = TimedSensorReading(
            value: Int(rpm.rounded()),
            timestamp: .now,
            sourceID: deviceID
        )
    }
}
