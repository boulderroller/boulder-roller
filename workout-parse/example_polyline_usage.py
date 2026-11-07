#!/usr/bin/env python3
"""
Example usage of the Rust polyline encoding/decoding module.
Demonstrates how to use the module in real-world scenarios.
"""

import workout_parse
import json


def example_1_basic_polyline():
    """Example 1: Basic polyline encoding for a simple route."""
    print("Example 1: Basic Polyline Encoding")
    print("=" * 60)

    # Define a simple route (San Francisco to Oakland)
    route = [
        (37.7749, -122.4194),  # San Francisco
        (37.8044, -122.2712),  # Oakland
        (37.8272, -122.2913),  # Berkeley
    ]

    # Encode
    encoded = workout_parse.py_encode_polyline(route, precision=5)
    print(f"Route with {len(route)} points")
    print(f"Encoded: {encoded}")
    print(f"Length: {len(encoded)} characters")

    # Decode
    decoded = workout_parse.py_decode_polyline(encoded, precision=5)
    print(f"\nDecoded {len(decoded)} points:")
    for i, (lat, lon) in enumerate(decoded):
        print(f"  {i+1}. ({lat:.4f}, {lon:.4f})")

    print()


def example_2_full_gps_track():
    """Example 2: Full GPS track encoding for workout storage."""
    print("Example 2: Full GPS Track Encoding")
    print("=" * 60)

    # Simulate a workout with GPS data
    workout_points = []
    base_lat, base_lon = 37.7749, -122.4194
    base_elev = 15.0

    for i in range(20):
        workout_points.append({
            "sequence_num": i,
            "latitude": base_lat + i * 0.001,
            "longitude": base_lon + i * 0.001,
            "elevation_m": base_elev + i * 2.5,
            "timestamp": i * 5,  # Every 5 seconds
            "distance_m": i * 50.0,  # 50m between points
        })

    # Encode
    track = workout_parse.py_encode_gps_track(workout_points, precision=5)

    print(f"Workout with {len(workout_points)} GPS points")
    print(f"\nEncoded track:")
    print(f"  Polyline: {track['polyline'][:50]}...")
    print(f"  Elevations: {track['elevations'][:5]}... (delta-encoded)")
    print(f"  Timestamps: {track['timestamps'][:5]}... (delta-encoded)")
    print(f"  Distances: {track['distances'][:5]}... (delta-encoded)")
    print(f"  Precision: {track['precision']}")
    print(f"  Version: {track['version']}")

    # Calculate sizes
    raw_size = len(json.dumps(workout_points))
    encoded_size = len(json.dumps(track))
    compression = (1 - encoded_size / raw_size) * 100

    print(f"\nStorage comparison:")
    print(f"  Raw JSON: {raw_size:,} bytes")
    print(f"  Encoded: {encoded_size:,} bytes")
    print(f"  Compression: {compression:.1f}%")

    # Decode
    decoded = workout_parse.py_decode_gps_track(track)
    print(f"\nDecoded {len(decoded)} points")
    print(f"First point: {decoded[0]}")
    print(f"Last point: {decoded[-1]}")

    print()


def example_3_database_storage():
    """Example 3: Database storage simulation."""
    print("Example 3: Database Storage Simulation")
    print("=" * 60)

    # Simulate receiving GPS data from a workout upload
    gps_data = [
        {"latitude": 37.7749, "longitude": -122.4194, "elevation_m": 10.0, "timestamp": 0, "distance_m": 0.0},
        {"latitude": 37.7750, "longitude": -122.4195, "elevation_m": 11.5, "timestamp": 2, "distance_m": 25.3},
        {"latitude": 37.7751, "longitude": -122.4196, "elevation_m": 13.2, "timestamp": 4, "distance_m": 50.1},
    ]

    # Encode for storage
    track = workout_parse.py_encode_gps_track(gps_data, precision=5)

    # Simulate storing to JSONB
    print("Storing to database (JSONB):")
    print(f"  rides.gps_track = {json.dumps(track, indent=2)}")

    # Simulate retrieving from database
    print("\nRetrieving from database:")
    retrieved_track = track  # In real code: db.query("SELECT gps_track FROM rides...")

    # Decode for processing
    points = workout_parse.py_decode_gps_track(retrieved_track)
    print(f"  Retrieved {len(points)} GPS points")
    print(f"  Ready for analysis, mapping, etc.")

    print()


def example_4_different_precisions():
    """Example 4: Different precision levels."""
    print("Example 4: Precision Comparison")
    print("=" * 60)

    point = (37.7749295, -122.4194155)  # Golden Gate Bridge
    print(f"Original coordinate: {point}")

    precisions = [
        (3, "~100m"),
        (4, "~10m"),
        (5, "~1m (default)"),
        (6, "~0.1m"),
        (7, "~0.01m"),
    ]

    print("\nPrecision level comparison:")
    for prec, accuracy in precisions:
        encoded = workout_parse.py_encode_polyline([point], precision=prec)
        decoded = workout_parse.py_decode_polyline(encoded, precision=prec)[0]
        error = ((point[0] - decoded[0])**2 + (point[1] - decoded[1])**2)**0.5 * 111000  # Approx meters

        print(f"  Precision {prec} ({accuracy}):")
        print(f"    Encoded: {encoded}")
        print(f"    Decoded: ({decoded[0]:.7f}, {decoded[1]:.7f})")
        print(f"    Error: ~{error:.1f}m")

    print()


def example_5_real_world_ride():
    """Example 5: Simulating a real-world cycling ride."""
    print("Example 5: Real-World Cycling Ride Simulation")
    print("=" * 60)

    import random
    random.seed(42)

    # Simulate a 1-hour ride with 1 point per second
    ride_points = []
    start_lat, start_lon = 37.7749, -122.4194
    elevation = 15.0
    distance = 0.0

    print("Generating 3,600-point ride (1 hour @ 1 Hz)...")

    for i in range(3600):
        # Simulate movement (vary lat/lon slightly)
        lat = start_lat + (i * 0.00005) + (random.random() - 0.5) * 0.00001
        lon = start_lon + (i * 0.00005) + (random.random() - 0.5) * 0.00001

        # Simulate elevation change (climbing and descending)
        elevation += (random.random() - 0.5) * 2.0

        # Simulate distance (avg 6 m/s = 21.6 km/h)
        distance += 5.5 + random.random() * 1.0

        ride_points.append({
            "sequence_num": i,
            "latitude": lat,
            "longitude": lon,
            "elevation_m": elevation,
            "timestamp": i,
            "distance_m": distance,
        })

    # Encode
    import time
    start = time.perf_counter()
    track = workout_parse.py_encode_gps_track(ride_points, precision=5)
    encode_time = time.perf_counter() - start

    # Calculate sizes
    raw_size = len(json.dumps(ride_points))
    encoded_size = len(json.dumps(track))

    print(f"\nRide statistics:")
    print(f"  Duration: 1 hour")
    print(f"  Points: {len(ride_points):,}")
    print(f"  Distance: {distance / 1000:.1f} km")
    print(f"  Elevation gain: {max(p['elevation_m'] for p in ride_points) - min(p['elevation_m'] for p in ride_points):.0f}m")

    print(f"\nStorage efficiency:")
    print(f"  Raw JSON: {raw_size:,} bytes ({raw_size / len(ride_points):.1f} bytes/point)")
    print(f"  Encoded: {encoded_size:,} bytes ({encoded_size / len(ride_points):.1f} bytes/point)")
    print(f"  Compression: {(1 - encoded_size / raw_size) * 100:.1f}%")
    print(f"  Encoding time: {encode_time * 1000:.1f}ms")

    print()


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Polyline Encoding/Decoding Usage Examples")
    print("=" * 60 + "\n")

    example_1_basic_polyline()
    example_2_full_gps_track()
    example_3_database_storage()
    example_4_different_precisions()
    example_5_real_world_ride()

    print("=" * 60)
    print("Examples complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
