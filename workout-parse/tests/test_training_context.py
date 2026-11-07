"""Synthetic FIT clock/indoor evidence, excluded from canonical ride identity."""

import os
import struct
import subprocess
import sys

import pytest
import workout_parse as wp


def crc(data):
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xA001 if value & 1 else 0)
    return value


def fit_context(
    *,
    offset=None,
    sub_sport=None,
    manufacturer=None,
    trainer=False,
    position=(40.0, -75.2),
):
    # 2026-10-07 23:00Z = 19:00 Philadelphia. No real rider data.
    start = 1_791_414_000 - 631_065_600
    body = bytearray()

    def definition(local, global_id, fields):
        body.extend(struct.pack("<BBBHB", 0x40 | local, 0, 0, global_id, len(fields)))
        for field in fields:
            body.extend(bytes(field))

    definition(
        0,
        20,
        [
            (253, 4, 0x86),
            (0, 4, 0x85),
            (1, 4, 0x85),
            (7, 2, 0x84),
            (6, 2, 0x84),
            (3, 1, 2),
        ],
    )
    lat, lon = [round(v * (2**31) / 180) for v in position]
    for t in range(60):
        body.extend(struct.pack("<BIiiHHB", 0, start + t, lat, lon, 200, 5000, 150))
    if offset is not None:
        definition(1, 34, [(253, 4, 0x86), (5, 4, 0x86)])
        body.extend(struct.pack("<BII", 1, start + 59, start + 59 + offset))
    if sub_sport is not None:
        definition(2, 18, [(6, 1, 0), (5, 1, 0)])
        body.extend(bytes([2, sub_sport, 2]))
    if manufacturer is not None or trainer:
        definition(3, 23, [(2, 2, 0x84), (1, 1, 2), (25, 1, 0)])
        body.extend(
            struct.pack("<BHBB", 3, manufacturer or 1, 17 if trainer else 255, 1)
        )
    header = struct.pack("<BBHI4s", 14, 0x10, 2100, len(body), b".FIT")
    header += struct.pack("<H", crc(header))
    data = header + body
    return data + struct.pack("<H", crc(data))


@pytest.mark.parametrize("offset", [-43200, -14400, 0, 19800, 50400])
def test_fit_activity_local_clock_is_retained_without_changing_identity(offset):
    bare = wp.parse_bytes(fit_context())
    timed = wp.parse_bytes(fit_context(offset=offset))
    assert timed.training_context["utc_offset_s"] == offset
    assert wp.hash_canonical_ride(bare) == wp.hash_canonical_ride(timed)
    assert wp.compute_metrics(bare, 250).tss == wp.compute_metrics(timed, 250).tss


@pytest.mark.parametrize("host_zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_device_offset_does_not_depend_on_server_timezone(host_zone):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            'import workout_parse as w,sys; print(w.parse_bytes(sys.stdin.buffer.read()).training_context["utc_offset_s"])',
        ],
        input=fit_context(offset=-14400),
        capture_output=True,
        check=True,
        env={**os.environ, "TZ": host_zone},
    )
    assert result.stdout.strip() == b"-14400"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sub_sport": 58},
        {"sub_sport": 6},
        {"sub_sport": 5},
        {"manufacturer": 260},
        {"trainer": True},
    ],
)
def test_fit_virtual_and_trainer_flags_survive_parsing(kwargs):
    activity = wp.parse_bytes(fit_context(**kwargs))
    assert activity.training_context["indoor_or_virtual"] is True
    assert activity.training_context["utc_offset_s"] is None
    assert wp.hash_canonical_ride(activity) == wp.hash_canonical_ride(
        wp.parse_bytes(fit_context())
    )


def test_gpx_virtual_creator_prevents_using_a_real_city_map_as_rider_location():
    raw = b'<gpx version="1.1" creator="Zwift"><trk><trkseg><trkpt lat="51.5" lon="-0.1"><time>2026-10-07T23:00:00Z</time></trkpt></trkseg></trk></gpx>'
    virtual = wp.parse_file_bytes(raw, "gpx")
    assert virtual.training_context["indoor_or_virtual"] is True
    outdoor = wp.parse_file_bytes(raw.replace(b"Zwift", b"GPS"), "gpx")
    assert outdoor.training_context["indoor_or_virtual"] is False
    assert wp.hash_canonical_ride(virtual) == wp.hash_canonical_ride(outdoor)
