import {
  buildPowerCPRequest,
  parsePowerCPResponse,
  parseOffsetCompensationResult,
  parseSensorLocationsList,
  parseEnhancedOffsetCompensationResult,
  POWER_CP_OPCODE,
  POWER_CP_RESULT,
  SENSOR_LOCATION,
} from '../ble/parsers/powerControlPoint';

function bytes(...parts: number[]): Uint8Array {
  return new Uint8Array(parts);
}
function s16le(v: number): [number, number] {
  const u = v < 0 ? v + 0x10000 : v;
  return [u & 0xff, (u >> 8) & 0xff];
}
function u16le(v: number): [number, number] {
  return [v & 0xff, (v >> 8) & 0xff];
}

describe('buildPowerCPRequest', () => {
  test('builds parameter-less request (Start Offset Compensation)', () => {
    const req = buildPowerCPRequest(POWER_CP_OPCODE.START_OFFSET_COMPENSATION);
    expect(Array.from(req)).toEqual([0x0c]);
  });

  test('builds request with parameter', () => {
    const param = new Uint8Array([0x01, 0x02, 0x03]);
    const req = buildPowerCPRequest(POWER_CP_OPCODE.SET_CUMULATIVE_VALUE, param);
    expect(Array.from(req)).toEqual([0x01, 0x01, 0x02, 0x03]);
  });
});

describe('parsePowerCPResponse', () => {
  test('parses success response for Start Offset Compensation with param', () => {
    // [0x20, 0x0C, 0x01, offset_lo, offset_hi]
    const buf = bytes(0x20, 0x0c, 0x01, ...s16le(42));
    const resp = parsePowerCPResponse(buf);
    expect(resp.requestOpCode).toBe(POWER_CP_OPCODE.START_OFFSET_COMPENSATION);
    expect(resp.resultCode).toBe(POWER_CP_RESULT.SUCCESS);
    expect(resp.parameter).toBeDefined();
    expect(parseOffsetCompensationResult(resp.parameter!)).toBe(42);
  });

  test('parses error response (Op Code Not Supported)', () => {
    const buf = bytes(0x20, 0x0c, POWER_CP_RESULT.OP_CODE_NOT_SUPPORTED);
    const resp = parsePowerCPResponse(buf);
    expect(resp.requestOpCode).toBe(0x0c);
    expect(resp.resultCode).toBe(POWER_CP_RESULT.OP_CODE_NOT_SUPPORTED);
    expect(resp.parameter).toBeUndefined();
  });

  test('parses response without parameter', () => {
    const buf = bytes(0x20, 0x0c, POWER_CP_RESULT.SUCCESS);
    const resp = parsePowerCPResponse(buf);
    expect(resp.resultCode).toBe(0x01);
    expect(resp.parameter).toBeUndefined();
  });

  test('throws on malformed response (missing Response Code opcode)', () => {
    const buf = bytes(0x1f, 0x0c, 0x01);
    expect(() => parsePowerCPResponse(buf)).toThrow(/does not begin with 0x20/);
  });

  test('throws on response too short', () => {
    expect(() => parsePowerCPResponse(bytes(0x20, 0x0c))).toThrow(/too short/);
  });
});

describe('parseOffsetCompensationResult', () => {
  test('parses positive offset', () => {
    expect(parseOffsetCompensationResult(bytes(...s16le(1234)))).toBe(1234);
  });

  test('parses negative offset', () => {
    expect(parseOffsetCompensationResult(bytes(...s16le(-50)))).toBe(-50);
  });

  test('throws on too-short parameter', () => {
    expect(() => parseOffsetCompensationResult(bytes(0x01))).toThrow(/too short/);
  });
});

describe('parseSensorLocationsList', () => {
  test('parses list of sensor location enums', () => {
    const param = bytes(
      SENSOR_LOCATION.LEFT_CRANK,
      SENSOR_LOCATION.RIGHT_CRANK,
      SENSOR_LOCATION.REAR_HUB,
    );
    expect(parseSensorLocationsList(param)).toEqual([5, 6, 14]);
  });

  test('handles empty list', () => {
    expect(parseSensorLocationsList(bytes())).toEqual([]);
  });
});

describe('parseEnhancedOffsetCompensationResult', () => {
  test('parses offset + mfgId + mfg data', () => {
    // offset=42, mfgId=0x00FF, mfgData=[0xAA, 0xBB]
    const param = bytes(...s16le(42), ...u16le(0x00ff), 0xaa, 0xbb);
    const result = parseEnhancedOffsetCompensationResult(param);
    expect(result.offset).toBe(42);
    expect(result.manufacturerId).toBe(0x00ff);
    expect(Array.from(result.manufacturerData)).toEqual([0xaa, 0xbb]);
  });

  test('parses with empty mfg data', () => {
    const param = bytes(...s16le(-10), ...u16le(0x0059));
    const result = parseEnhancedOffsetCompensationResult(param);
    expect(result.offset).toBe(-10);
    expect(result.manufacturerId).toBe(0x0059);
    expect(result.manufacturerData.byteLength).toBe(0);
  });

  test('throws on too-short parameter', () => {
    expect(() => parseEnhancedOffsetCompensationResult(bytes(0x00, 0x00, 0x01))).toThrow(
      /too short/,
    );
  });
});
