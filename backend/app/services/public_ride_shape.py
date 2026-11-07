"""Compact public relief; never interpolate across a hidden or incredible edge."""
from ..feed_contracts import _point_lat_lon, _point_timestamp_seconds, _edge_is_implausible
from .ride_list_shape import prepare_ride_shape_points, build_ride_list_shape, _interpolate


def build_public_ride_shape(ride: dict, raw: list[dict], projected: list[dict],
                            steps: list[dict], route: dict) -> dict:
    if not route or not route.get('segments'):
        return {}
    prepared = prepare_ride_shape_points(ride, raw)
    if len(prepared) != len(projected):
        return {}
    runs, run, previous = [], [], None
    unsafe_distances = []
    unknown_distance = False
    for point, visible in zip(prepared, projected):
        coords = _point_lat_lon(visible)
        distance, elevation = point['distance_m'], point['elevation_m']
        valid = coords is not None and not visible.get('redacted') and distance is not None and distance >= 0 and elevation is not None
        current = (*coords, _point_timestamp_seconds(visible)) if coords else None
        bad_edge = valid and previous is not None and _edge_is_implausible(previous, current)
        broken = not valid or bad_edge
        if not valid:
            if distance is None:
                unknown_distance = True
            else:
                unsafe_distances.append(distance)
        if bad_edge:
            unsafe_distances.extend([run[-1]['distance_m'], distance])
        if valid and run and distance < run[-1]['distance_m']:
            return {}  # A reset cannot locate frozen spans reliably.
        if broken:
            if len(run) >= 2:
                runs.append(run)
            run, previous = [], None
        if valid:
            if not run or distance > run[-1]['distance_m']:
                run.append(point)
            previous = current
    if len(run) >= 2:
        runs.append(run)
    if not runs or len(runs) > 32:
        return {}
    # Reserve both endpoints of each visible run, then distribute the remaining
    # sample budget without ever sampling a hidden interval.
    counts = [2] * len(runs)
    budget = min(64, sum(len(run) for run in runs)) - sum(counts)
    while budget > 0:
        candidates = [i for i, run in enumerate(runs) if counts[i] < len(run)]
        i = max(candidates, key=lambda i: (runs[i][-1]['distance_m'] - runs[i][0]['distance_m']) / counts[i])
        counts[i] += 1
        budget -= 1
    profile = []
    for index, (run, count) in enumerate(zip(runs, counts)):
        xs = [p['distance_m'] for p in run]
        ys = [p['elevation_m'] for p in run]
        for j in range(count):
            distance = xs[0] + (xs[-1] - xs[0]) * j / (count - 1)
            point = {'distance_m': distance, 'elevation_m': round(_interpolate(xs, ys, distance), 1)}
            if index and j == 0:
                point['break_before'] = True
            profile.append(point)
    authority = build_ride_list_shape(ride, raw, steps).get('counted_spans', [])
    # Distance can plateau across a hidden moment. Even a range contained in
    # a visible run is unsafe if any hidden sample shares that range. Missing
    # distance prevents proving containment, so suppress counted authority.
    spans = [span for span in authority if not unknown_distance and span.get('pattern_id')
        and not any(span['start_distance_m'] <= d <= span['end_distance_m'] for d in unsafe_distances)
        and any(
        run[0]['distance_m'] <= span['start_distance_m'] < span['end_distance_m'] <= run[-1]['distance_m']
        for run in runs)]
    return {'elevation_profile': profile, 'counted_spans': spans}
