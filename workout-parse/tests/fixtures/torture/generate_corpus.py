#!/usr/bin/env python3
"""Generate the synthetic workout-parse torture corpus.

Every observation is invented in this file. No rider data is used. The binary
FIT cases use a tiny protocol writer so regeneration does not depend on a
vendor SDK or network access.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import struct
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


CORPUS_DIR = Path(__file__).resolve().parent
FIT_EPOCH_UNIX_S = 631_065_600
FIT_CRC_TABLE = (
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
)


@dataclass(frozen=True)
class Case:
    case_id: str
    filename: str
    file_type: str
    category: str
    outcome: str
    purpose: str
    payload: bytes
    expected: dict[str, Any] = field(default_factory=dict)


def fit_crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        tmp = FIT_CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ FIT_CRC_TABLE[byte & 0xF]
        tmp = FIT_CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc ^= tmp ^ FIT_CRC_TABLE[(byte >> 4) & 0xF]
    return crc


def fit_definition(
    local_message: int,
    global_message: int,
    fields: list[tuple[int, int, int]],
    *,
    architecture: int = 0,
    developer_fields: list[tuple[int, int, int]] | None = None,
) -> bytes:
    developer_fields = developer_fields or []
    endian = ">" if architecture == 1 else "<"
    header = 0x40 | local_message
    if developer_fields:
        header |= 0x20
    output = bytearray((header, 0, architecture))
    output.extend(struct.pack(f"{endian}H", global_message))
    output.append(len(fields))
    for number, size, base_type in fields:
        output.extend((number, size, base_type))
    if developer_fields:
        output.append(len(developer_fields))
        for number, size, developer_index in developer_fields:
            output.extend((number, size, developer_index))
    return bytes(output)


def fit_data(local_message: int, values: bytes) -> bytes:
    return bytes((local_message,)) + values


def semicircles(degrees: float) -> int:
    return round(degrees * (2**31) / 180.0)


def fit_timestamp(iso_timestamp: str) -> int:
    unix_seconds = int(datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00")).timestamp())
    return unix_seconds - FIT_EPOCH_UNIX_S


def wrap_fit(data: bytes) -> bytes:
    header = bytearray(14)
    header[0] = 14
    header[1] = 2
    header[2:4] = struct.pack("<H", 21_200)
    header[4:8] = struct.pack("<I", len(data))
    header[8:12] = b".FIT"
    header[12:14] = struct.pack("<H", fit_crc(bytes(header[:12])))
    body = bytes(header) + data
    return body + struct.pack("<H", fit_crc(body))


def replace_fit_file_crc(payload: bytes) -> bytes:
    return payload[:-2] + struct.pack("<H", fit_crc(payload[:-2]))


def standard_fit() -> bytes:
    fields = [
        (253, 4, 0x86),  # timestamp, uint32
        (0, 4, 0x85),  # position_lat, sint32
        (1, 4, 0x85),  # position_long, sint32
        (2, 2, 0x84),  # altitude, uint16
        (7, 2, 0x84),  # power, uint16
    ]
    output = bytearray(fit_definition(0, 20, fields))
    for timestamp, lat, lon, altitude_m, power_w in [
        ("2026-08-31T12:00:00Z", 39.9500, -75.1600, 10.0, 250),
        ("2026-08-31T12:00:01Z", 39.9501, -75.1599, 11.0, 260),
    ]:
        values = struct.pack(
            "<IiiHH",
            fit_timestamp(timestamp),
            semicircles(lat),
            semicircles(lon),
            round((altitude_m + 500.0) * 5.0),
            power_w,
        )
        output.extend(fit_data(0, values))
    return wrap_fit(bytes(output))


def developer_noise_fit() -> bytes:
    developer_id = bytes(range(16))
    application_id = bytes(reversed(range(16)))
    developer_data_definition = fit_definition(
        0,
        207,
        [(0, 16, 0x0D), (1, 16, 0x0D), (2, 2, 0x84), (3, 1, 0x02)],
    )
    developer_data = fit_data(
        0,
        developer_id + application_id + struct.pack("<HB", 255, 0),
    )

    field_name = b"vendor_noise\0"
    units = b"opaque\0"
    field_description_definition = fit_definition(
        1,
        206,
        [
            (0, 1, 0x02),
            (1, 1, 0x02),
            (2, 1, 0x02),
            (3, len(field_name), 0x07),
            (8, len(units), 0x07),
        ],
    )
    field_description = fit_data(1, bytes((0, 0, 0x84)) + field_name + units)

    record_fields = [
        (253, 4, 0x86),
        (0, 4, 0x85),
        (1, 4, 0x85),
        (7, 2, 0x84),
    ]
    record_definition = fit_definition(
        2,
        20,
        record_fields,
        developer_fields=[(0, 2, 0)],
    )
    records = bytearray()
    for timestamp, lat, lon, power_w, noise in [
        ("2026-08-31T13:00:00Z", 39.9510, -75.1610, 275, 60_000),
        ("2026-08-31T13:00:01Z", 39.9511, -75.1609, 280, 60_001),
    ]:
        records.extend(
            fit_data(
                2,
                struct.pack(
                    "<IiiHH",
                    fit_timestamp(timestamp),
                    semicircles(lat),
                    semicircles(lon),
                    power_w,
                    noise,
                ),
            )
        )
    return wrap_fit(
        developer_data_definition
        + developer_data
        + field_description_definition
        + field_description
        + record_definition
        + bytes(records)
    )


def gpx(points: list[dict[str, Any]], *, creator: str = "Synthetic Torture Rig") -> bytes:
    rows = []
    for point in points:
        attributes = f'lat="{point["lat"]}" lon="{point["lon"]}"'
        if point.get("point_attrs"):
            attributes += f' {point["point_attrs"]}'
        children = []
        if "ele" in point:
            ele_attrs = f' {point["ele_attrs"]}' if point.get("ele_attrs") else ""
            children.append(f'<ele{ele_attrs}>{point["ele"]}</ele>')
        if "time" in point:
            children.append(f'<time>{point["time"]}</time>')
        children.extend(point.get("extra", []))
        rows.append(f'<trkpt {attributes}>{"".join(children)}</trkpt>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<gpx version="1.1" creator="{creator}" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1" '
        'xmlns:br="https://boulderroller.xyz/xmlschemas/ride/v1">'
        f'<trk><trkseg>{"".join(rows)}</trkseg></trk></gpx>'
    ).encode("utf-8")


def tcx(points: list[dict[str, Any]], *, creator: str = "Synthetic Torture Rig") -> bytes:
    rows = []
    for point in points:
        children = []
        if "time" in point:
            children.append(f'<Time>{point["time"]}</Time>')
        if "lat" in point or "lon" in point:
            position = []
            if "lat" in point:
                position.append(f'<LatitudeDegrees>{point["lat"]}</LatitudeDegrees>')
            if "lon" in point:
                position.append(f'<LongitudeDegrees>{point["lon"]}</LongitudeDegrees>')
            children.append(f'<Position>{"".join(position)}</Position>')
        if "ele" in point:
            attrs = f' {point["ele_attrs"]}' if point.get("ele_attrs") else ""
            children.append(f'<AltitudeMeters{attrs}>{point["ele"]}</AltitudeMeters>')
        if "dist" in point:
            children.append(f'<DistanceMeters>{point["dist"]}</DistanceMeters>')
        if "hr" in point:
            children.append(f'<HeartRateBpm><Value>{point["hr"]}</Value></HeartRateBpm>')
        if "cad" in point:
            children.append(f'<Cadence>{point["cad"]}</Cadence>')
        if "power" in point:
            children.append(f'<Extensions><TPX><Watts>{point["power"]}</Watts></TPX></Extensions>')
        children.extend(point.get("extra", []))
        rows.append(f'<Trackpoint>{"".join(children)}</Trackpoint>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
        f'creator="{creator}"><Activities><Activity Sport="Biking"><Lap><Track>'
        f'{"".join(rows)}</Track></Lap></Activity></Activities></TrainingCenterDatabase>'
    ).encode("utf-8")


def point(lat: Any, lon: Any, time: str | None, ele: Any | None = None, **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"lat": lat, "lon": lon}
    if time is not None:
        value["time"] = time
    if ele is not None:
        value["ele"] = ele
    value.update(extra)
    return value


def timestamp_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def build_cases() -> list[Case]:
    base_fit = standard_fit()
    header_only = bytearray(base_fit[:14])
    header_only[4:8] = struct.pack("<I", 0)
    header_only[12:14] = struct.pack("<H", fit_crc(bytes(header_only[:12])))

    bad_header_crc = bytearray(base_fit)
    bad_header_crc[12] ^= 0x01
    bad_file_crc = bytearray(base_fit)
    bad_file_crc[-1] ^= 0x01
    wrong_architecture = bytearray(base_fit)
    wrong_architecture[16] = 2
    wrong_architecture = bytearray(replace_fit_file_crc(bytes(wrong_architecture)))
    oversized_declared = bytearray(base_fit[:14])
    oversized_declared[4:8] = struct.pack("<I", 0xFFFF_FFFF)
    oversized_declared[12:14] = struct.pack(
        "<H", fit_crc(bytes(oversized_declared[:12]))
    )
    oversized_declared.extend(struct.pack("<H", fit_crc(bytes(oversized_declared))))

    ordinary_start = "2026-08-31T12:00:00Z"
    ordinary_next = "2026-08-31T12:00:01Z"
    ordinary_third = "2026-08-31T12:00:02Z"
    cases: list[Case] = [
        Case("fit_empty", "fit_empty.fit", "fit", "malformed_fit", "reject", "Zero-byte FIT input must fail without panic.", b""),
        Case("fit_header_only", "fit_header_only.fit", "fit", "malformed_fit", "reject", "A valid-looking 14-byte header without the required data CRC is truncated.", bytes(header_only)),
        Case("fit_truncated_mid_record", "fit_truncated_mid_record.fit", "fit", "malformed_fit", "reject", "The declared FIT payload is cut through the first record.", base_fit[:42]),
        Case("fit_bad_header_crc", "fit_bad_header_crc.fit", "fit", "malformed_fit", "reject", "Header CRC corruption must be reported cleanly.", bytes(bad_header_crc)),
        Case("fit_bad_file_crc", "fit_bad_file_crc.fit", "fit", "malformed_fit", "reject", "Data CRC corruption must be reported cleanly.", bytes(bad_file_crc)),
        Case("fit_wrong_architecture", "fit_wrong_architecture.fit", "fit", "malformed_fit", "reject", "A definition with an architecture byte outside little/big endian is invalid even with a repaired CRC.", bytes(wrong_architecture)),
        Case("fit_oversized_declared", "fit_oversized_declared.fit", "fit", "enormous_input", "reject", "A tiny FIT claiming a four-gigabyte data section must not allocate or partially parse.", bytes(oversized_declared)),
        Case(
            "gps_teleport",
            "gps_teleport.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "A syntactically valid teleport is preserved exactly for the downstream integrity gate; parsing does not invent an interpolated path.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(-33.86, 151.20, ordinary_next, 11)]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "lat_e7": [399500000, -338600000]},
        ),
        Case(
            "gps_null_island",
            "gps_null_island.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "A (0,0) no-fix sample is syntactically valid device testimony preserved exactly; the ratified Null Island rejection (TRUTH_CONTRACT INV-DATA-1) is a per-sample downstream gate in is_valid_gps and sensor integrity, never whole-source parse rejection.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(0, 0, ordinary_next, 11)]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "lat_e7": [399500000, 0]},
        ),
        Case(
            "gps_impossible_speed",
            "gps_impossible_speed.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "A physically impossible but syntactically valid jump remains exact evidence for downstream abstention.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(39.96, -75.16, ordinary_next, 11)]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "lat_e7": [399500000, 399600000]},
        ),
        Case(
            "gps_altitude_spike",
            "gps_altitude_spike.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "An altitude spike is retained rather than smoothed or fabricated by the parser.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(39.9501, -75.1599, ordinary_next, 6000), point(39.9502, -75.1598, ordinary_third, 12)]),
            {"sample_count": 3, "duration_s": 2, "gps_count": 3, "elevation_m": [10.0, 6000.0, 12.0]},
        ),
        Case(
            "gps_altitude_dropout",
            "gps_altitude_dropout.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "Missing elevation remains missing, never sea level.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(39.9501, -75.1599, ordinary_next), point(39.9502, -75.1598, ordinary_third, 12)]),
            {"sample_count": 3, "duration_s": 2, "gps_count": 3, "elevation_m": [10.0, None, 12.0]},
        ),
        Case(
            "gps_duplicate_timestamps",
            "gps_duplicate_timestamps.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "Equal timestamps remain bounded same-clock observations; no time is fabricated between them.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(39.9501, -75.1599, ordinary_start, 11), point(39.9502, -75.1598, ordinary_next, 12)]),
            {"sample_count": 3, "duration_s": 1, "gps_count": 3},
        ),
        Case(
            "gps_out_of_order",
            "gps_out_of_order.gpx",
            "gpx",
            "gps_pathology",
            "reject",
            "A decreasing sample clock must reject the entire source.",
            gpx([point(39.95, -75.16, ordinary_next, 10), point(39.9501, -75.1599, ordinary_start, 11)]),
        ),
        Case(
            "gps_out_of_range",
            "gps_out_of_range.gpx",
            "gpx",
            "gps_pathology",
            "accept",
            "An out-of-range latitude that is exactly representable in e7 is preserved as device testimony for the per-sample downstream gate (TRUTH_CONTRACT INV-DATA-1): H3 projection and climb detection drop the sample without destroying the source.",
            gpx([point(91, -75.16, ordinary_start, 10)]),
            {"sample_count": 1, "duration_s": 0, "gps_count": 1, "lat_e7": [910000000]},
        ),
        Case(
            "gps_nonfinite",
            "gps_nonfinite.gpx",
            "gpx",
            "unit_and_encoding",
            "reject",
            "NaN coordinates must not saturate to zero and masquerade as real data.",
            gpx([point("NaN", -75.16, ordinary_start, 10)]),
        ),
        Case(
            "time_dst_spring_forward",
            "time_dst_spring_forward.gpx",
            "gpx",
            "time_pathology",
            "accept",
            "RFC3339 offsets make the US spring-forward transition a one-second UTC interval.",
            gpx([point(39.95, -75.16, "2026-03-08T01:59:59-05:00", 10), point(39.9501, -75.1599, "2026-03-08T03:00:00-04:00", 11)]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2},
        ),
        Case(
            "time_dst_fall_back",
            "time_dst_fall_back.gpx",
            "gpx",
            "time_pathology",
            "accept",
            "RFC3339 offsets disambiguate the repeated fall-back hour.",
            gpx([point(39.95, -75.16, "2026-11-01T01:59:59-04:00", 10), point(39.9501, -75.1599, "2026-11-01T01:00:00-05:00", 11)]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2},
        ),
        Case(
            "time_offset_change",
            "time_offset_change.tcx",
            "tcx",
            "time_pathology",
            "accept",
            "A timezone offset change mid-ride is normalized to one UTC timeline.",
            tcx([{"lat": 39.95, "lon": -75.16, "time": "2026-08-31T14:00:00+02:00", "ele": 10}, {"lat": 39.9501, "lon": -75.1599, "time": "2026-08-31T13:00:01+01:00", "ele": 11}]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2},
        ),
        Case(
            "time_non_monotonic",
            "time_non_monotonic.tcx",
            "tcx",
            "time_pathology",
            "reject",
            "A non-monotonic TCX clock is rejected rather than sorted.",
            tcx([{"lat": 39.95, "lon": -75.16, "time": ordinary_next}, {"lat": 39.9501, "lon": -75.1599, "time": ordinary_start}]),
        ),
        Case(
            "time_unix_epoch_zero",
            "time_unix_epoch_zero.gpx",
            "gpx",
            "time_pathology",
            "accept",
            "Unix epoch zero is a valid clock-domain start, not a missing-value sentinel.",
            gpx([point(39.95, -75.16, "1970-01-01T00:00:00Z", 10), point(39.9501, -75.1599, "1970-01-01T00:00:01Z", 11)]),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "started_at_ms": 0},
        ),
        Case(
            "time_year_zero",
            "time_year_zero.gpx",
            "gpx",
            "time_pathology",
            "reject",
            "Chrono can represent year zero but the Python binding contract cannot; reject before adapter conversion.",
            gpx([point(39.95, -75.16, "0000-01-01T00:00:00Z", 10)]),
        ),
        Case(
            "time_invalid_timestamp",
            "time_invalid_timestamp.gpx",
            "gpx",
            "time_pathology",
            "reject",
            "One corrupt timestamp must not silently delete its point while later points survive.",
            gpx([point(39.95, -75.16, "not-a-time", 10), point(39.9501, -75.1599, ordinary_next, 11)]),
        ),
        Case(
            "device_wahoo_sparse_power",
            "device_wahoo_sparse_power.gpx",
            "gpx",
            "device_quirk",
            "accept",
            "Wahoo-shaped sparse power preserves the unpaired-sensor gap as missing.",
            gpx([point(39.95, -75.16, ordinary_start, 10, extra=["<extensions><power>250</power></extensions>"]), point(39.9501, -75.1599, ordinary_next, 11), point(39.9502, -75.1598, ordinary_third, 12, extra=["<extensions><power>260</power></extensions>"])], creator="Wahoo ELEMNT synthetic"),
            {"sample_count": 3, "duration_s": 2, "gps_count": 3, "pwr_w": [250, None, 260]},
        ),
        Case(
            "device_garmin_hr_cadence",
            "device_garmin_hr_cadence.tcx",
            "tcx",
            "device_quirk",
            "accept",
            "Garmin-shaped TCX with HR/cadence and no power keeps field availability exact.",
            tcx([{"lat": 39.95, "lon": -75.16, "time": ordinary_start, "ele": 10, "hr": 145, "cad": 86}, {"lat": 39.9501, "lon": -75.1599, "time": ordinary_next, "ele": 11, "hr": 146, "cad": 87}], creator="Garmin synthetic"),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "hr_bpm": [145, 146], "cadence_rpm": [86, 87], "pwr_w": None},
        ),
        Case(
            "device_hammerhead_developer_noise",
            "device_hammerhead_developer_noise.fit",
            "fit",
            "device_quirk",
            "accept",
            "Hammerhead-shaped FIT developer fields are ignored without shifting standard record fields.",
            developer_noise_fit(),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "pwr_w": [275, 280]},
        ),
        Case(
            "device_apple_watch_hr_only",
            "device_apple_watch_hr_only.gpx",
            "gpx",
            "device_quirk",
            "accept",
            "Apple-Watch-shaped HR-only GPX does not invent power or cadence.",
            gpx([point(39.95, -75.16, ordinary_start, 10, extra=["<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>138</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>"]), point(39.9501, -75.1599, ordinary_next, 11, extra=["<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>140</gpxtpx:hr></gpxtpx:TrackPointExtension></extensions>"])], creator="Apple Watch synthetic"),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "hr_bpm": [138, 140], "pwr_w": None, "cadence_rpm": None},
        ),
        Case(
            "device_phone_only",
            "device_phone_only.gpx",
            "gpx",
            "device_quirk",
            "accept",
            "Phone-only GPS remains a valid sensor-free activity.",
            gpx([point(39.95, -75.16, ordinary_start, 10), point(39.9501, -75.1599, ordinary_next, 11)], creator="Phone GPS synthetic"),
            {"sample_count": 2, "duration_s": 1, "gps_count": 2, "pwr_w": None, "hr_bpm": None, "cadence_rpm": None},
        ),
        Case(
            "unit_semicircles_as_degrees",
            "unit_semicircles_as_degrees.gpx",
            "gpx",
            "unit_and_encoding",
            "reject",
            "FIT semicircles pasted into degree-valued GPX attributes must not saturate i32 coordinates.",
            gpx([point(476_741_369, -896_789_201, ordinary_start, 10)]),
        ),
        Case(
            "unit_imperial_elevation",
            "unit_imperial_elevation.gpx",
            "gpx",
            "unit_and_encoding",
            "reject",
            "A non-standard feet marker on GPX elevation must not be silently treated as meters.",
            gpx([point(39.95, -75.16, ordinary_start, 1000, ele_attrs='unit="ft"')]),
        ),
        Case(
            "encoding_utf16",
            "encoding_utf16.gpx",
            "gpx",
            "unit_and_encoding",
            "reject",
            "UTF-16 input is unsupported by the byte-oriented XML parser and must fail cleanly.",
            '<?xml version="1.0" encoding="UTF-16"?><gpx><trk/></gpx>'.encode("utf-16"),
        ),
        Case(
            "encoding_invalid_utf8",
            "encoding_invalid_utf8.gpx",
            "gpx",
            "unit_and_encoding",
            "reject",
            "Invalid UTF-8 text must not be skipped around an otherwise valid point.",
            b'<gpx><metadata><name>bad-\xff-name</name></metadata><trk><trkseg><trkpt lat="39.95" lon="-75.16"><time>2026-08-31T12:00:00Z</time></trkpt></trkseg></trk></gpx>',
        ),
        Case(
            "zero_length_stream",
            "zero_length_stream.gpx",
            "gpx",
            "empty_input",
            "reject",
            "A structurally present but empty track stream has no activity to parse.",
            b'<gpx><trk><trkseg></trkseg></trk></gpx>',
        ),
        Case(
            "xml_truncated_after_trackpoint",
            "xml_truncated_after_trackpoint.gpx",
            "gpx",
            "truncated_xml",
            "reject",
            "EOF after a complete point but before closing ancestors is still a truncated document.",
            b'<gpx><trk><trkseg><trkpt lat="39.95" lon="-75.16"><time>2026-08-31T12:00:00Z</time></trkpt>',
        ),
        Case(
            "tcx_truncated_after_trackpoint",
            "tcx_truncated_after_trackpoint.tcx",
            "tcx",
            "truncated_xml",
            "reject",
            "TCX EOF after one complete Trackpoint must not yield a partial ride.",
            b'<TrainingCenterDatabase><Activities><Activity><Lap><Track><Trackpoint><Time>2026-08-31T12:00:00Z</Time></Trackpoint>',
        ),
        Case(
            "tcx_half_coordinate",
            "tcx_half_coordinate.tcx",
            "tcx",
            "unit_and_encoding",
            "reject",
            "A TCX position with only latitude must not become half-valid GPS evidence.",
            tcx([{"lat": 39.95, "time": ordinary_start, "hr": 140}]),
        ),
    ]

    enormous_xml = b'<gpx><metadata><name>' + (b"A" * (101 * 1024 * 1024)) + b'</name></metadata></gpx>'
    enormous_gzip = gzip.compress(enormous_xml, compresslevel=9, mtime=0)
    cases.append(
        Case(
            "enormous_gzip_bomb",
            "enormous_gzip_bomb.gpx.gz",
            "gpx",
            "enormous_input",
            "reject",
            "A small gzip expanding past the 100 MiB limit must stop before parser allocation.",
            enormous_gzip,
        )
    )
    return cases


def main() -> None:
    cases = build_cases()
    manifest_cases = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for case in cases:
        if case.case_id in seen_ids or case.filename in seen_files:
            raise ValueError(f"duplicate corpus case: {case.case_id} / {case.filename}")
        seen_ids.add(case.case_id)
        seen_files.add(case.filename)
        path = CORPUS_DIR / case.filename
        path.write_bytes(case.payload)
        manifest_cases.append(
            {
                "id": case.case_id,
                "file": case.filename,
                "file_type": case.file_type,
                "category": case.category,
                "outcome": case.outcome,
                "purpose": case.purpose,
                "sha256": hashlib.sha256(case.payload).hexdigest(),
                "byte_length": len(case.payload),
                "expected": case.expected,
            }
        )
    manifest = {
        "schema": "boulderroller.workout_parse_torture.v1",
        "privacy": "fully synthetic; no rider data",
        "generator": "generate_corpus.py",
        "case_count": len(manifest_cases),
        "cases": manifest_cases,
    }
    (CORPUS_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
