/**
 * Cycling Power Control Point — characteristic 0x2A66.
 *
 * Indication-based request/response. Client must:
 *   1. Enable indications via CCCD (0x0002)
 *   2. Write request via writeWithResponse
 *   3. Receive response indication on the same characteristic
 *
 * Request wire format:  [opCode uint8][...parameters]
 * Response wire format: [0x20][requestOpCode uint8][resultCode uint8][...optional param]
 *
 * For the v1 build-to-spec sweep we ship these ops:
 *   0x03 Request Sensor Locations         → response param: uint8[] list of supported locations
 *   0x0C Start Offset Compensation        → response param: int16 offset (raw force/torque)
 *   0x10 Start Enhanced Offset Compensation → response param: int16 offset + uint16 mfg id + mfg data
 *   0x20 Response Code                    → response op code (response itself)
 *
 * Skipped (time-trial fitting, legacy chain-tension hardware): 0x04–0x0B, 0x0D–0x0F.
 */

export const POWER_CP_OPCODE = {
  SET_CUMULATIVE_VALUE: 0x01,
  UPDATE_SENSOR_LOCATION: 0x02,
  REQUEST_SENSOR_LOCATIONS: 0x03,
  SET_CRANK_LENGTH: 0x04,
  REQUEST_CRANK_LENGTH: 0x05,
  SET_CHAIN_LENGTH: 0x06,
  REQUEST_CHAIN_LENGTH: 0x07,
  SET_CHAIN_WEIGHT: 0x08,
  REQUEST_CHAIN_WEIGHT: 0x09,
  SET_SPAN_LENGTH: 0x0a,
  REQUEST_SPAN_LENGTH: 0x0b,
  START_OFFSET_COMPENSATION: 0x0c,
  MASK_CP_MEASUREMENT: 0x0d,
  REQUEST_SAMPLING_RATE: 0x0e,
  REQUEST_FACTORY_CAL_DATE: 0x0f,
  START_ENHANCED_OFFSET_COMPENSATION: 0x10,
  RESPONSE_CODE: 0x20,
} as const;

export const POWER_CP_RESULT = {
  SUCCESS: 0x01,
  OP_CODE_NOT_SUPPORTED: 0x02,
  INVALID_PARAMETER: 0x03,
  OPERATION_FAILED: 0x04,
} as const;

export interface PowerCPResponse {
  requestOpCode: number;
  resultCode: number;
  /** Optional parameter payload (response-op-code-specific). */
  parameter?: Uint8Array;
}

/**
 * Sensor Location enum values (char 0x2A5D).
 * Stored here for co-location with the op that reads them.
 */
export const SENSOR_LOCATION = {
  OTHER: 0,
  TOP_OF_SHOE: 1,
  IN_SHOE: 2,
  HIP: 3,
  FRONT_WHEEL: 4,
  LEFT_CRANK: 5,
  RIGHT_CRANK: 6,
  LEFT_PEDAL: 8,
  RIGHT_PEDAL: 9,
  FRONT_HUB: 10,
  REAR_DROPOUT: 11,
  CHAINSTAY: 12,
  REAR_WHEEL: 13,
  REAR_HUB: 14,
  CHEST: 15,
  SPIDER: 16,
  CHAIN_RING: 17,
} as const;

/** Build a request payload: [opCode, ...parameters] */
export function buildPowerCPRequest(opCode: number, parameter?: Uint8Array): Uint8Array {
  if (!parameter) return new Uint8Array([opCode]);
  const out = new Uint8Array(1 + parameter.byteLength);
  out[0] = opCode;
  out.set(parameter, 1);
  return out;
}

/** Parse a response indication: [0x20, requestOpCode, resultCode, ...param] */
export function parsePowerCPResponse(buf: Uint8Array): PowerCPResponse {
  if (buf.byteLength < 3) {
    throw new Error(`Power CP response too short: ${buf.byteLength} bytes (need ≥3)`);
  }
  if (buf[0] !== POWER_CP_OPCODE.RESPONSE_CODE) {
    throw new Error(
      `Power CP response does not begin with 0x20: got 0x${buf[0].toString(16).padStart(2, '0')}`,
    );
  }
  return {
    requestOpCode: buf[1],
    resultCode: buf[2],
    parameter: buf.byteLength > 3 ? buf.slice(3) : undefined,
  };
}

/** Parse int16 raw offset from a 0x0C Start Offset Compensation response parameter. */
export function parseOffsetCompensationResult(parameter: Uint8Array): number {
  if (parameter.byteLength < 2) {
    throw new Error(
      `Offset Compensation result too short: ${parameter.byteLength} bytes (need ≥2)`,
    );
  }
  const dv = new DataView(parameter.buffer, parameter.byteOffset, parameter.byteLength);
  return dv.getInt16(0, true);
}

/** Parse uint8[] list from a 0x03 Request Sensor Locations response parameter. */
export function parseSensorLocationsList(parameter: Uint8Array): number[] {
  return Array.from(parameter);
}

export interface EnhancedOffsetResult {
  /** Raw offset (int16). */
  offset: number;
  /** Bluetooth SIG manufacturer ID (uint16). */
  manufacturerId: number;
  /** Manufacturer-specific payload (variable length, may be empty). */
  manufacturerData: Uint8Array;
}

/** Parse 0x10 Enhanced Offset Compensation: [offset int16][mfgId uint16][mfg data…] */
export function parseEnhancedOffsetCompensationResult(
  parameter: Uint8Array,
): EnhancedOffsetResult {
  if (parameter.byteLength < 4) {
    throw new Error(
      `Enhanced Offset response too short: ${parameter.byteLength} bytes (need ≥4)`,
    );
  }
  const dv = new DataView(parameter.buffer, parameter.byteOffset, parameter.byteLength);
  return {
    offset: dv.getInt16(0, true),
    manufacturerId: dv.getUint16(2, true),
    manufacturerData: parameter.slice(4),
  };
}
