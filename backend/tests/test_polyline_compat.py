from app.utils.polyline import decode_gps_track, encode_gps_track


def test_decode_gps_track_polyline_format() -> None:
    track = encode_gps_track([
        {
            "sequence_num": 0,
            "latitude": 40.0101,
            "longitude": -105.2502,
            "elevation_m": 1600.0,
            "timestamp": 0,
            "distance_m": 0.0,
        },
        {
            "sequence_num": 1,
            "latitude": 40.0111,
            "longitude": -105.2512,
            "elevation_m": 1604.5,
            "timestamp": 5,
            "distance_m": 95.0,
        },
    ])

    decoded = decode_gps_track(track)
    assert len(decoded) == 2
    assert decoded[0]["latitude"] == 40.0101
    assert decoded[1]["distance_m"] == 95


def test_encode_decode_preserves_missing_elevation_without_losing_sea_level_zero() -> None:
    track = encode_gps_track([
        {
            "sequence_num": 0,
            "latitude": 40.0101,
            "longitude": -105.2502,
            "elevation_m": None,
            "timestamp": 0,
            "distance_m": 0.0,
        },
        {
            "sequence_num": 1,
            "latitude": 40.0111,
            "longitude": -105.2512,
            "elevation_m": 0.0,
            "timestamp": 5,
            "distance_m": 95.0,
        },
        {
            "sequence_num": 2,
            "latitude": 40.0121,
            "longitude": -105.2522,
            "elevation_m": 123.4,
            "timestamp": 10,
            "distance_m": 190.0,
        },
    ])

    decoded = decode_gps_track(track)
    assert track["version"] == 2
    assert [list(item) for item in track["elevation_missing_ranges"]] == [[0, 1]]
    assert [point["elevation_m"] for point in decoded] == [None, 0.0, 123.4]


def test_decode_gps_track_legacy_list_format() -> None:
    legacy_track = [
        {"lat": 40.0101, "lon": -105.2502, "ele": 1600.0, "t": 0},
        {"lat": 40.0111, "lon": -105.2512, "ele": 1604.5, "t": 5},
    ]

    decoded = decode_gps_track(legacy_track)
    assert len(decoded) == 2
    assert decoded[0]["latitude"] == 40.0101
    assert decoded[0]["longitude"] == -105.2502
    assert decoded[0]["elevation_m"] == 1600.0
    assert decoded[1]["timestamp"] == 5


def test_decode_gps_track_legacy_wrapped_points_format() -> None:
    legacy_track = {
        "points": [
            {"latitude": 40.0101, "longitude": -105.2502, "timestamp": "2020-07-18T10:00:00Z"},
            {"latitude": 40.0111, "longitude": -105.2512, "timestamp": "2020-07-18T10:00:05Z"},
        ]
    }

    decoded = decode_gps_track(legacy_track)
    assert len(decoded) == 2
    assert decoded[0]["sequence_num"] == 0
    assert decoded[1]["sequence_num"] == 1
    assert decoded[1]["timestamp"] >= decoded[0]["timestamp"]
