import Foundation

/// Cycling Power Control Point (0x2A66) offset compensation — the standard
/// zero-offset flow Favero/4iiii/Garmin-class meters implement. Byte values
/// are Bluetooth SIG assigned numbers.
enum PowerCalibrationGATT {
    /// Request op code: Start Offset Compensation.
    static let opStartOffsetCompensation: UInt8 = 0x0C
    /// Indication op code: Response Code.
    static let opResponseCode: UInt8 = 0x20
    static let responseSuccess: UInt8 = 0x01
    static let responseNotSupported: UInt8 = 0x02
    static let responseInvalidParameter: UInt8 = 0x03
    static let responseOperationFailed: UInt8 = 0x04
    /// Cycling Power Feature (0x2A65) bit 4: Offset Compensation Supported.
    static let featureOffsetCompensationBit: UInt32 = 1 << 4

    /// The little-endian uint32 feature bitfield, or nil when malformed.
    static func featureBits(_ data: Data) -> UInt32? {
        guard data.count >= 4 else { return nil }
        return UInt32(data[data.startIndex])
            | (UInt32(data[data.startIndex + 1]) << 8)
            | (UInt32(data[data.startIndex + 2]) << 16)
            | (UInt32(data[data.startIndex + 3]) << 24)
    }
}

/// Pure zero-offset calibration state machine: CoreBluetooth events in,
/// effects out. The simulator has no radios, so every transition — success
/// with the meter's raw offset, rejection, timeout, disconnect — is provable
/// here without hardware; the thin `SensorManager` adapter only performs
/// effects and forwards events. Truthful result states only: the flow never
/// reports success it did not receive.
struct PowerCalibrationFlow: Equatable, Sendable {
    enum Failure: Equatable, Sendable {
        case notSupported
        case rejected
        case writeFailed
        case timedOut
        case disconnected
    }

    enum State: Equatable, Sendable {
        case idle
        /// Enabling control-point indications before the write.
        case preparing
        /// Write sent; the meter owes a Response Code indication.
        case awaitingResponse
        /// The meter confirmed offset compensation. `rawOffset` is the
        /// meter-reported calibration parameter when it sent one (sint16,
        /// device units).
        case succeeded(rawOffset: Int16?)
        case failed(Failure)
    }

    enum Effect: Equatable, Sendable {
        case none
        case enableIndications
        case writeStartOffsetCompensation
    }

    private(set) var state: State = .idle

    var isInFlight: Bool {
        state == .preparing || state == .awaitingResponse
    }

    /// Rider taps Calibrate. Re-runnable from any settled state.
    mutating func begin() -> Effect {
        guard !isInFlight else { return .none }
        state = .preparing
        return .enableIndications
    }

    /// Indications are live on the control point.
    mutating func indicationsReady() -> Effect {
        guard state == .preparing else { return .none }
        state = .awaitingResponse
        return .writeStartOffsetCompensation
    }

    mutating func indicationsFailed() {
        guard isInFlight else { return }
        state = .failed(.writeFailed)
    }

    mutating func writeFailed() {
        guard isInFlight else { return }
        state = .failed(.writeFailed)
    }

    /// A control-point indication arrived. Indications that are not the
    /// Response Code for Start Offset Compensation are ignored — they are
    /// answers to questions this flow did not ask.
    mutating func indication(_ data: Data) {
        guard state == .awaitingResponse else { return }
        let bytes = [UInt8](data)
        guard
            bytes.count >= 3,
            bytes[0] == PowerCalibrationGATT.opResponseCode,
            bytes[1] == PowerCalibrationGATT.opStartOffsetCompensation
        else { return }
        switch bytes[2] {
        case PowerCalibrationGATT.responseSuccess:
            var offset: Int16?
            if bytes.count >= 5 {
                offset = Int16(bitPattern: UInt16(bytes[3]) | (UInt16(bytes[4]) << 8))
            }
            state = .succeeded(rawOffset: offset)
        case PowerCalibrationGATT.responseNotSupported:
            state = .failed(.notSupported)
        default:
            state = .failed(.rejected)
        }
    }

    mutating func timedOut() {
        guard isInFlight else { return }
        state = .failed(.timedOut)
    }

    mutating func deviceDisconnected() {
        guard isInFlight else { return }
        state = .failed(.disconnected)
    }
}
