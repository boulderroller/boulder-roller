#!/usr/bin/env python3
"""Test script to verify polyline encoding/decoding compatibility between Rust and Python implementations."""

import sys
import os

# Add parent directory to path to import both implementations
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.utils.polyline import (
    encode_polyline as py_encode_polyline,
    decode_polyline as py_decode_polyline,
    encode_gps_track as py_encode_gps_track,
    decode_gps_track as py_decode_gps_track,
)

# Import Rust implementation
import workout_parse

def test_encode_decode_polyline():
    """Test polyline encoding/decoding matches between Python and Rust."""
    print("Testing polyline encoding/decoding...")

    test_points = [
        (38.5, -120.2),
        (40.7, -120.95),
        (43.252, -126.453),
    ]

    # Python implementation
    py_encoded = py_encode_polyline(test_points, precision=5)
    py_decoded = py_decode_polyline(py_encoded, precision=5)

    # Rust implementation
    rust_encoded = workout_parse.py_encode_polyline(test_points, precision=5)
    rust_decoded = workout_parse.py_decode_polyline(rust_encoded, precision=5)

    # Compare encodings
    print(f"  Python encoded: {py_encoded}")
    print(f"  Rust encoded:   {rust_encoded}")
    assert py_encoded == rust_encoded, "Encodings don't match!"

    # Compare decodings
    for i, ((py_lat, py_lon), (rust_lat, rust_lon)) in enumerate(zip(py_decoded, rust_decoded)):
        assert abs(py_lat - rust_lat) < 0.00001, f"Latitude mismatch at index {i}"
        assert abs(py_lon - rust_lon) < 0.00001, f"Longitude mismatch at index {i}"

    print("  ✓ Polyline encoding/decoding matches!")


def test_gps_track_encoding():
    """Test GPS track encoding/decoding matches between Python and Rust."""
    print("\nTesting GPS track encoding/decoding...")

    test_points = [
        {
            "sequence_num": 0,
            "latitude": 37.7749,
            "longitude": -122.4194,
            "elevation_m": 10.5,
            "timestamp": 0,
            "distance_m": 0.0,
        },
        {
            "sequence_num": 1,
            "latitude": 37.7750,
            "longitude": -122.4195,
            "elevation_m": 11.2,
            "timestamp": 1,
            "distance_m": 15.3,
        },
        {
            "sequence_num": 2,
            "latitude": 37.7751,
            "longitude": -122.4196,
            "elevation_m": 12.8,
            "timestamp": 2,
            "distance_m": 30.1,
        },
    ]

    # Python implementation
    py_track = py_encode_gps_track(test_points, precision=5)
    py_decoded = py_decode_gps_track(py_track)

    # Rust implementation
    rust_track = workout_parse.py_encode_gps_track(test_points, precision=5)
    rust_decoded = workout_parse.py_decode_gps_track(rust_track)

    # Compare track structures
    print(f"  Python polyline: {py_track['polyline']}")
    print(f"  Rust polyline:   {rust_track['polyline']}")
    assert py_track['polyline'] == rust_track['polyline'], "Polylines don't match!"
    assert py_track['elevations'] == rust_track['elevations'], "Elevations don't match!"
    assert py_track['timestamps'] == rust_track['timestamps'], "Timestamps don't match!"
    assert py_track['distances'] == rust_track['distances'], "Distances don't match!"
    assert py_track['precision'] == rust_track['precision'], "Precision doesn't match!"
    assert py_track['version'] == rust_track['version'], "Version doesn't match!"

    print(f"  Encoded size: {len(str(py_track))} bytes for {len(test_points)} points")

    # Compare decoded points
    assert len(py_decoded) == len(rust_decoded), "Decoded length mismatch!"
    for i, (py_pt, rust_pt) in enumerate(zip(py_decoded, rust_decoded)):
        assert abs(py_pt['latitude'] - rust_pt['latitude']) < 0.00001, f"Latitude mismatch at {i}"
        assert abs(py_pt['longitude'] - rust_pt['longitude']) < 0.00001, f"Longitude mismatch at {i}"

        # Elevation can be None or 0 at sea level
        py_elev = py_pt['elevation_m'] if py_pt['elevation_m'] is not None else 0.0
        rust_elev = rust_pt['elevation_m'] if rust_pt['elevation_m'] is not None else 0.0
        assert abs(py_elev - rust_elev) < 0.1, f"Elevation mismatch at {i}: {py_elev} vs {rust_elev}"

    print("  ✓ GPS track encoding/decoding matches!")


def test_compression_ratio():
    """Test compression effectiveness with a larger dataset."""
    print("\nTesting compression ratio with larger dataset...")

    # Generate 1000 GPS points (simulating a ride)
    import random
    random.seed(42)

    points = []
    base_lat = 37.7749
    base_lon = -122.4194
    base_elev = 10.0
    base_dist = 0.0

    for i in range(1000):
        points.append({
            "sequence_num": i,
            "latitude": base_lat + (random.random() - 0.5) * 0.1,
            "longitude": base_lon + (random.random() - 0.5) * 0.1,
            "elevation_m": base_elev + random.random() * 100,
            "timestamp": i,
            "distance_m": base_dist + i * 15.5,
        })

    # Encode with Rust
    import json
    raw_size = len(json.dumps(points))
    rust_track = workout_parse.py_encode_gps_track(points, precision=5)
    encoded_size = len(json.dumps(rust_track))

    compression_ratio = (1 - encoded_size / raw_size) * 100

    print(f"  Raw JSON size:      {raw_size:,} bytes")
    print(f"  Encoded size:       {encoded_size:,} bytes")
    print(f"  Compression ratio:  {compression_ratio:.1f}%")
    print(f"  Bytes per point:    {encoded_size / len(points):.1f}")

    assert compression_ratio > 85, "Compression ratio should be >85%"
    print("  ✓ Compression is effective!")


def test_edge_cases():
    """Test edge cases."""
    print("\nTesting edge cases...")

    # Empty points
    empty_encoded = workout_parse.py_encode_polyline([], precision=5)
    assert empty_encoded == "", "Empty encoding should return empty string"

    empty_decoded = workout_parse.py_decode_polyline("", precision=5)
    assert len(empty_decoded) == 0, "Empty decoding should return empty list"

    # Single point
    single_point = [(37.7749, -122.4194)]
    single_encoded = workout_parse.py_encode_polyline(single_point, precision=5)
    single_decoded = workout_parse.py_decode_polyline(single_encoded, precision=5)
    assert len(single_decoded) == 1
    assert abs(single_decoded[0][0] - single_point[0][0]) < 0.00001
    assert abs(single_decoded[0][1] - single_point[0][1]) < 0.00001

    # Negative coordinates
    negative_points = [(-33.8688, 151.2093), (-35.0, 150.0)]  # Sydney area
    negative_encoded = workout_parse.py_encode_polyline(negative_points, precision=5)
    negative_decoded = workout_parse.py_decode_polyline(negative_encoded, precision=5)
    assert len(negative_decoded) == 2
    for i, (orig, dec) in enumerate(zip(negative_points, negative_decoded)):
        assert abs(orig[0] - dec[0]) < 0.00001, f"Lat mismatch at {i}"
        assert abs(orig[1] - dec[1]) < 0.00001, f"Lon mismatch at {i}"

    print("  ✓ Edge cases handled correctly!")


def main():
    print("=" * 60)
    print("Polyline Encoding/Decoding Compatibility Tests")
    print("=" * 60)

    test_encode_decode_polyline()
    test_gps_track_encoding()
    test_compression_ratio()
    test_edge_cases()

    print("\n" + "=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()
