#!/usr/bin/env python3
"""
Visual climb detection review tool.

Generates an interactive HTML page with:
1. Elevation profile — hover to see position dot on map
2. Map with ride polyline + climb segments colored
3. Per-climb stats table — click row to zoom map to that climb
4. Tooltip with elevation, gradient, power, time at cursor

Usage:
    # From a .fit file:
    source backend/venv/bin/activate
    python tools/climb_visual_review.py /path/to/ride.fit

    # From corpus DB by activity ID:
    python tools/climb_visual_review.py --corpus-id 10151587338

    # Philly rides (default training set):
    python tools/climb_visual_review.py --philly 6

    # Sample rides across terrain types:
    python tools/climb_visual_review.py --sample 3 --terrain rolling
"""

import argparse
import html as html_mod
import json
import sqlite3
import sys
from pathlib import Path

try:
    import workout_parse as wp
except ImportError:
    print("ERROR: workout_parse not available. Build it first:")
    print("  cd workout-parse && cargo build --release && maturin develop")
    sys.exit(1)

CORPUS_DB = str(Path(__file__).parent / "corpus" / "corpus.db")
ACTIVITIES_DIR = "/Users/gabetemp/Downloads/Code/export_440100/activities"

# Philly-area H3 res-10 prefixes (covers greater Philadelphia + surrounding counties)
PHILLY_H3_PREFIXES = ("8a2a1", "8a2a0", "8a2a2")

CLIMB_COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#2980b9", "#c0392b", "#27ae60",
    "#8e44ad", "#d35400", "#16a085", "#f1c40f", "#7f8c8d",
]


def parse_fit_file(filepath: str):
    """Parse a ride file and return activity + samples."""
    activity = wp.parse_file(filepath)
    n = len(activity.time_ms)
    if n == 0:
        return None, []

    start_ms = activity.time_ms[0]
    h3_strs = None
    if activity.lat_e7 is not None and len(activity.lat_e7) > 0:
        try:
            h3_strs = wp.get_h3_strings(activity.lat_e7, activity.lon_e7, 10)
        except Exception:
            pass

    samples = []
    for i in range(n):
        s = {"t": int((activity.time_ms[i] - start_ms) / 1000)}
        if activity.elevation_m is not None and i < len(activity.elevation_m):
            s["elevation_m"] = float(activity.elevation_m[i])
        if activity.lat_e7 is not None and i < len(activity.lat_e7):
            lat = float(activity.lat_e7[i]) / 1e7
            lon = float(activity.lon_e7[i]) / 1e7
            if abs(lat) <= 90 and abs(lon) <= 180 and not (lat == 0 and lon == 0):
                s["lat"] = lat
                s["lon"] = lon
        if activity.pwr_w is not None and i < len(activity.pwr_w):
            pw = int(activity.pwr_w[i])
            if 0 < pw < 5000:
                s["power_w"] = pw
        if activity.hr_bpm is not None and i < len(activity.hr_bpm):
            hr = int(activity.hr_bpm[i])
            if 0 < hr < 255:
                s["hr_bpm"] = hr
        if h3_strs is not None and i < len(h3_strs):
            s["tile_id"] = h3_strs[i]
        samples.append(s)

    return activity, samples


def detect_climbs(samples, weight_kg=75.0):
    """Run persistence detector and road enrichment, return climbs."""
    climbs = wp.detect_climbs_persistence(samples, user_weight_kg=weight_kg)

    # Run road enrichment
    enrichments = None
    try:
        import sys, os
        backend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
        if backend_dir not in sys.path:
            sys.path.insert(0, backend_dir)
        from app.services.road_enrichment import enrich_climbs
        enrichments = enrich_climbs(climbs, samples)
    except Exception as e:
        print(f"  Road enrichment skipped: {e}")

    results = []
    for i, c in enumerate(climbs):
        d = {
            "idx": i,
            "vert_m": round(c.vert_m, 1),
            "time_s": c.time_s,
            "distance_m": round(c.distance_m, 1),
            "avg_gradient_pct": round(c.avg_gradient_pct, 1),
            "persistence": round(c.persistence, 1),
            "is_essential": c.is_essential,
            "effort_start_idx": c.effort_start_idx,
            "effort_end_idx": c.effort_end_idx,
            "birth_idx": c.birth_idx,
            "death_idx": c.death_idx,
            "start_lat": c.start_lat,
            "start_lon": c.start_lon,
            "end_lat": c.end_lat,
            "end_lon": c.end_lon,
            "avg_power_w": c.avg_power_w,
            "avg_hr": c.avg_hr,
            "vam": round(c.vert_m / c.time_s * 3600, 0) if c.time_s > 0 else 0,
        }
        # Attach enrichment data
        if enrichments and i < len(enrichments):
            e = enrichments[i]
            d["road_name"] = e.road_name
            d["road_names_seq"] = e.road_names_sequence
            d["bridge_pct"] = round(e.bridge_pct, 2) if e.bridge_pct else 0
            d["suppressed"] = e.suppressed
            d["suppression_reason"] = e.suppression_reason
            d["n_splits"] = len(e.split_candidates)
            d["start_boundary_source"] = e.start_boundary_source
            d["end_boundary_source"] = e.end_boundary_source
            d["refined_start"] = e.refined_start
            d["refined_end"] = e.refined_end
            # Collect nearby intersection coords for map markers
            d["intersections"] = []
            if e.start_intersection:
                d["intersections"].append(e.start_intersection)
            if e.end_intersection:
                d["intersections"].append(e.end_intersection)
            for sc in e.split_candidates:
                d["intersections"].append({
                    "osm_id": sc.intersection.osm_id,
                    "name": sc.intersection.name,
                    "lat": sc.intersection.lat,
                    "lon": sc.intersection.lon,
                    "type": "split",
                })
        results.append(d)
    return results


def _generate_html_template():
    """Return the HTML template string with {placeholders}."""
    # NOTE: This template uses textContent-based DOM construction (see buildTable)
    # to avoid innerHTML with untrusted data.
    return r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; }
.header { padding: 12px 24px; background: #16213e; border-bottom: 1px solid #333; display: flex; align-items: center; justify-content: space-between; }
.header h1 { font-size: 16px; font-weight: 600; }
.header .meta { font-size: 12px; color: #888; }
.header .meta span { margin-left: 16px; }
.container { display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 420px auto; gap: 0; height: calc(100vh - 48px); }
#chart { grid-column: 1; grid-row: 1; background: #0a1628; position: relative; cursor: crosshair; }
#map { grid-column: 2; grid-row: 1; }
.table-panel { grid-column: 1 / -1; grid-row: 2; overflow-y: auto; padding: 12px 16px; background: #1a1a2e; }
canvas { width: 100%; height: 100%; display: block; }
#tooltip { position: absolute; background: rgba(10,22,40,0.92); border: 1px solid #334; border-radius: 6px; padding: 8px 12px; font-size: 12px; font-family: monospace; pointer-events: none; display: none; z-index: 10; white-space: nowrap; }
#tooltip .val { color: #fff; font-weight: 600; }
#tooltip .lbl { color: #889; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; padding: 6px 10px; background: #16213e; border-bottom: 1px solid #333; font-weight: 600; color: #aaa; position: sticky; top: 0; }
td { padding: 5px 10px; border-bottom: 1px solid #222; }
tr { cursor: pointer; transition: background 0.1s; }
tr:hover { background: #16213e; }
tr.active { background: #1a3050 !important; }
.color-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.sig { color: #2ecc71; }
.noise { color: #555; }
.verdict { padding: 3px 7px; border-radius: 4px; font-size: 10px; font-weight: 700; letter-spacing: 0.3px; }
.verdict-solid { background: #1a472a; color: #2ecc71; }
.verdict-noise { background: #3d1f1f; color: #e74c3c; }
.verdict-borderline { background: #3d3a1f; color: #f39c12; }
/* Annotation mode */
#annotBar { display: none; padding: 8px 24px; background: #2d1b4e; border-bottom: 1px solid #6c3483; font-size: 13px; }
#annotBar.active { display: flex; align-items: center; gap: 16px; }
#annotBar .status { color: #bb8fce; flex: 1; }
#annotBar button { padding: 4px 12px; border: 1px solid #6c3483; background: #1a1a2e; color: #e0e0e0; border-radius: 4px; cursor: pointer; font-size: 12px; }
#annotBar button:hover { background: #2d1b4e; }
#annotBar button.primary { background: #6c3483; border-color: #8e44ad; }
.annot-marker { position: absolute; width: 2px; top: 0; bottom: 0; pointer-events: none; z-index: 5; }
.annot-marker.start { background: #2ecc71; }
.annot-marker.end { background: #e74c3c; }
.annot-marker-label { position: absolute; top: 2px; font-size: 9px; padding: 1px 4px; border-radius: 2px; white-space: nowrap; pointer-events: none; z-index: 6; }
.annot-marker-label.start { background: #1a472a; color: #2ecc71; left: 4px; }
.annot-marker-label.end { background: #3d1f1f; color: #e74c3c; right: 4px; }
#annotToggle { padding: 4px 10px; border: 1px solid #6c3483; background: #1a1a2e; color: #bb8fce; border-radius: 4px; cursor: pointer; font-size: 11px; margin-left: 12px; }
#annotToggle:hover { background: #2d1b4e; }
#annotToggle.on { background: #6c3483; color: #fff; }
</style>
</head>
<body>
<div class="header">
    <h1 id="pageTitle"></h1>
    <div class="meta" id="pageMeta"></div>
    <button id="annotToggle" onclick="toggleAnnotate()">Annotate</button>
</div>
<div id="annotBar">
    <span class="status" id="annotStatus">Click chart to set START for climb #1</span>
    <button onclick="annotPrev()">Prev Climb</button>
    <button onclick="annotNext()">Next Climb</button>
    <button onclick="annotSkip()">Skip</button>
    <button onclick="annotUndo()">Undo</button>
    <button class="primary" onclick="annotExport()">Export JSON</button>
</div>
<div class="container">
    <div id="chart">
        <canvas id="elevCanvas"></canvas>
        <div id="tooltip"></div>
    </div>
    <div id="map"></div>
    <div class="table-panel">
        <table>
            <thead>
                <tr>
                    <th>#</th><th>Road</th><th>Vert</th><th>Grad</th><th>Time</th><th>Dist</th>
                    <th>VAM</th><th>Persist</th><th>Pwr</th><th>HR</th><th>Bounds</th><th>Verdict</th>
                </tr>
            </thead>
            <tbody id="climbTable"></tbody>
        </table>
    </div>
</div>

<script>
// Data injected by Python
const DATA = __DATA_JSON__;

const elevations = DATA.elevations;
const times = DATA.times;
const powers = DATA.powers;
const sampleCoords = DATA.sampleCoords;
const climbRanges = DATA.climbRanges;
const rideCoords = DATA.rideCoords;
const climbMapSegments = DATA.climbMapSegments;
const climbs = DATA.climbs;
const title = DATA.title;
const terrainLabel = DATA.terrainLabel;
const nSig = DATA.nSig;

// Set header text safely
document.getElementById('pageTitle').textContent = title;
const metaEl = document.getElementById('pageMeta');
['Terrain: ' + terrainLabel, 'Climbs: ' + climbs.length + ' (' + nSig + ' sig)', 'Detector: persistence'].forEach(function(t) {
    var s = document.createElement('span'); s.textContent = t; metaEl.appendChild(s);
});

// ===================== MAP =====================
var mapObj = null, cursorMarker = null, climbLayers = [];
(function() {
    try {
        if (rideCoords.length === 0 || typeof L === 'undefined') return;
        mapObj = L.map('map', { zoomControl: true }).fitBounds(rideCoords, { padding: [20, 20] });
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png', {
            maxZoom: 19, attribution: '\u00a9 OSM \u00a9 CARTO'
        }).addTo(mapObj);

        L.polyline(rideCoords, { color: '#ffffff', weight: 2, opacity: 0.6 }).addTo(mapObj);

        for (var si = 0; si < climbMapSegments.length; si++) {
            var seg = climbMapSegments[si];
            if (seg.coords.length > 1) {
                var layer = L.polyline(seg.coords, { color: seg.color, weight: 5, opacity: 0.85 })
                    .bindTooltip(seg.label, { sticky: true })
                    .addTo(mapObj);
                climbLayers.push({ idx: seg.idx, layer: layer, coords: seg.coords });
            }
            L.circleMarker(seg.coords[0], { radius: 4, color: seg.color, fillColor: seg.color, fillOpacity: 1, weight: 0 }).addTo(mapObj);
            L.circleMarker(seg.coords[seg.coords.length - 1], { radius: 4, color: seg.color, fillColor: '#fff', fillOpacity: 0.8, weight: 1 }).addTo(mapObj);
        }

        // Add intersection markers from road enrichment
        for (var ci2 = 0; ci2 < climbs.length; ci2++) {
            var ixns = climbs[ci2].intersections || [];
            for (var xi = 0; xi < ixns.length; xi++) {
                var ix = ixns[xi];
                if (ix.lat && ix.lon) {
                    var ixColor = ix.type === 'split' ? '#f39c12' : '#e74c3c';
                    var ixLabel = (ix.name || 'intersection') + (ix.type === 'split' ? ' [split]' : '');
                    L.circleMarker([ix.lat, ix.lon], {
                        radius: 6, color: '#fff', fillColor: ixColor, fillOpacity: 0.9, weight: 2
                    }).bindTooltip(ixLabel, { sticky: true }).addTo(mapObj);
                }
            }
        }

        cursorMarker = L.circleMarker([0, 0], {
            radius: 7, color: '#fff', fillColor: '#e74c3c', fillOpacity: 1, weight: 2
        }).addTo(mapObj);
        cursorMarker.setOpacity(0);
    } catch(e) { console.warn('Map init failed:', e); }
})();

function moveCursorToSample(idx) {
    if (!cursorMarker || typeof cursorMarker.setLatLng !== 'function') return;
    var coord = sampleCoords[idx];
    if (!coord) return;
    cursorMarker.setLatLng(coord);
    cursorMarker.setOpacity(1);
}

function zoomToClimb(climbIdx) {
    if (!mapObj) return;
    for (var i = 0; i < climbLayers.length; i++) {
        if (climbLayers[i].idx === climbIdx && climbLayers[i].coords.length > 1) {
            mapObj.fitBounds(climbLayers[i].coords, { padding: [40, 40], maxZoom: 16 });
            return;
        }
    }
}

// ===================== CHART =====================
function initChart() {
    var canvas = document.getElementById('elevCanvas');
    var container = canvas.parentElement;
    var tooltip = document.getElementById('tooltip');
    var dpr = window.devicePixelRatio || 1;

    // Wait for layout if container has no dimensions yet
    if (container.clientWidth < 10 || container.clientHeight < 10) {
        requestAnimationFrame(initChart);
        return;
    }

    canvas.width = container.clientWidth * dpr;
    canvas.height = container.clientHeight * dpr;
    canvas.style.width = container.clientWidth + 'px';
    canvas.style.height = container.clientHeight + 'px';

    var ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);
    var W = container.clientWidth;
    var H = container.clientHeight;
    var pad = { top: 20, right: 20, bottom: 30, left: 55 };
    var plotW = W - pad.left - pad.right;
    var plotH = H - pad.top - pad.bottom;

    var validElev = elevations.filter(function(e) { return e !== null; });
    if (validElev.length === 0) return;
    var eMin = DATA.eMin;
    var eMax = DATA.eMax;
    var N = elevations.length;
    var tMin = times[0];
    var tMax = times[N - 1];
    var tRange = tMax - tMin || 1;

    function xPos(i) { return pad.left + ((times[i] - tMin) / tRange) * plotW; }
    function yPos(e) { return pad.top + plotH - ((e - eMin) / (eMax - eMin)) * plotH; }
    function idxFromX(px) {
        var tTarget = tMin + ((px - pad.left) / plotW) * tRange;
        var best = 0;
        var bestDist = Math.abs(times[0] - tTarget);
        for (var i = 1; i < N; i++) {
            var d = Math.abs(times[i] - tTarget);
            if (d < bestDist) { bestDist = d; best = i; }
        }
        return best;
    }

    // --- Draw static chart ---

    // Elevation fill
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top + plotH);
    for (var i = 0; i < N; i++) {
        if (elevations[i] === null) continue;
        ctx.lineTo(xPos(i), yPos(elevations[i]));
    }
    ctx.lineTo(xPos(N - 1), pad.top + plotH);
    ctx.closePath();
    ctx.fillStyle = 'rgba(15,52,96,0.4)';
    ctx.fill();

    // Grid
    ctx.strokeStyle = '#1a2a3c';
    ctx.lineWidth = 0.5;
    var gridStep = Math.max(25, Math.pow(10, Math.floor(Math.log10(eMax - eMin))));
    for (var e = Math.ceil(eMin / gridStep) * gridStep; e <= eMax; e += gridStep) {
        ctx.beginPath(); ctx.moveTo(pad.left, yPos(e)); ctx.lineTo(W - pad.right, yPos(e)); ctx.stroke();
        ctx.fillStyle = '#556';
        ctx.font = '10px monospace';
        ctx.textAlign = 'right';
        ctx.fillText(Math.round(e) + 'm', pad.left - 4, yPos(e) + 3);
    }

    // Climb bands
    for (var ci = 0; ci < climbRanges.length; ci++) {
        var cr = climbRanges[ci];
        ctx.fillStyle = cr.color + '18';
        ctx.fillRect(xPos(cr.start_idx), pad.top, xPos(cr.end_idx) - xPos(cr.start_idx), plotH);
    }

    // Base elevation line
    ctx.strokeStyle = '#556';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    var started = false;
    for (var i = 0; i < N; i++) {
        if (elevations[i] === null) continue;
        if (!started) { ctx.moveTo(xPos(i), yPos(elevations[i])); started = true; }
        else { ctx.lineTo(xPos(i), yPos(elevations[i])); }
    }
    ctx.stroke();

    // Climb segments (colored)
    for (var ci = 0; ci < climbRanges.length; ci++) {
        var cr = climbRanges[ci];
        ctx.strokeStyle = cr.color;
        ctx.lineWidth = 3;
        ctx.beginPath();
        var first = true;
        for (var i = cr.start_idx; i <= cr.end_idx && i < N; i++) {
            if (elevations[i] === null) continue;
            if (first) { ctx.moveTo(xPos(i), yPos(elevations[i])); first = false; }
            else { ctx.lineTo(xPos(i), yPos(elevations[i])); }
        }
        ctx.stroke();

        // Vert label
        var sliceElev = elevations.slice(cr.start_idx, cr.end_idx + 1).filter(function(e) { return e !== null; });
        if (sliceElev.length > 0) {
            var topE = eMin;
            for (var ei = 0; ei < sliceElev.length; ei++) { if (sliceElev[ei] > topE) topE = sliceElev[ei]; }
            var midIdx = Math.floor((cr.start_idx + cr.end_idx) / 2);
            ctx.fillStyle = cr.color;
            ctx.font = 'bold 11px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(cr.vert_m + 'm', xPos(midIdx), yPos(topE) - 8);
        }
    }

    var chartImage = ctx.getImageData(0, 0, canvas.width, canvas.height);

    // --- Hover ---
    canvas.addEventListener('mousemove', function(ev) {
        var rect = canvas.getBoundingClientRect();
        var mx = ev.clientX - rect.left;
        var my = ev.clientY - rect.top;

        if (mx < pad.left || mx > W - pad.right || my < pad.top || my > pad.top + plotH) {
            tooltip.style.display = 'none';
            if (cursorMarker && cursorMarker.setOpacity) cursorMarker.setOpacity(0);
            ctx.putImageData(chartImage, 0, 0);
            return;
        }

        var idx = Math.max(0, Math.min(N - 1, idxFromX(mx)));
        var elev = elevations[idx];
        if (elev === null) return;

        ctx.putImageData(chartImage, 0, 0);

        ctx.save();
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        // Vertical crosshair
        ctx.strokeStyle = 'rgba(255,255,255,0.25)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(xPos(idx), pad.top);
        ctx.lineTo(xPos(idx), pad.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);

        // Cursor dot
        ctx.fillStyle = '#fff';
        ctx.beginPath();
        ctx.arc(xPos(idx), yPos(elev), 5, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#e74c3c';
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.restore();

        // Which climb?
        var inClimb = null;
        for (var ci = 0; ci < climbRanges.length; ci++) {
            if (idx >= climbRanges[ci].start_idx && idx <= climbRanges[ci].end_idx) {
                inClimb = climbRanges[ci]; break;
            }
        }

        // Local gradient
        var gw = 5;
        var gradient = null;
        if (idx >= gw && idx < N - gw) {
            var dElev = (elevations[idx + gw] || elev) - (elevations[idx - gw] || elev);
            var dTime = (times[idx + gw] || times[idx]) - (times[idx - gw] || times[idx]);
            if (dTime > 0) { gradient = (dElev / (dTime * 5)) * 100; }
        }

        // Time format
        var t = times[idx];
        var hrs = Math.floor(t / 3600);
        var mins = Math.floor((t % 3600) / 60);
        var secs = t % 60;
        var timeStr = hrs > 0 ? hrs + ':' + String(mins).padStart(2,'0') + ':' + String(secs).padStart(2,'0') : mins + ':' + String(secs).padStart(2,'0');

        // Build tooltip via DOM (safe)
        while (tooltip.firstChild) tooltip.removeChild(tooltip.firstChild);
        function addLine(label, value, color) {
            var lbl = document.createElement('span'); lbl.className = 'lbl'; lbl.textContent = label + ': ';
            var val = document.createElement('span'); val.className = 'val'; val.textContent = value;
            if (color) val.style.color = color;
            tooltip.appendChild(lbl); tooltip.appendChild(val); tooltip.appendChild(document.createElement('br'));
        }
        addLine('Time', timeStr);
        addLine('Elev', Math.round(elev) + 'm');
        if (gradient !== null) addLine('Grade', gradient.toFixed(1) + '%');
        if (powers[idx]) addLine('Power', powers[idx] + 'w');
        if (inClimb) {
            var cSpan = document.createElement('span');
            cSpan.style.color = inClimb.color;
            cSpan.style.fontWeight = '700';
            cSpan.textContent = inClimb.label;
            tooltip.appendChild(cSpan);
        }

        tooltip.style.display = 'block';
        var tx = mx + 16, ty = my - 10;
        if (tx + 180 > W) tx = mx - 180;
        if (ty < 10) ty = 10;
        tooltip.style.left = tx + 'px';
        tooltip.style.top = ty + 'px';

        moveCursorToSample(idx);
    });

    canvas.addEventListener('mouseleave', function() {
        tooltip.style.display = 'none';
        if (cursorMarker && cursorMarker.setOpacity) cursorMarker.setOpacity(0);
        ctx.putImageData(chartImage, 0, 0);
    });
}
// Kick off chart after layout settles
requestAnimationFrame(initChart);

// ===================== TABLE (safe DOM construction) =====================
(function() {
    var tbody = document.getElementById('climbTable');

    function makeCell(text, className) {
        var td = document.createElement('td');
        td.textContent = text;
        if (className) td.className = className;
        return td;
    }

    for (var ci = 0; ci < climbs.length; ci++) {
        var c = climbs[ci];
        var isSig = c.vert_m >= 20;
        var verdict, vclass;
        if (c.vert_m >= 50 && c.avg_gradient_pct >= 3) { verdict = 'SOLID'; vclass = 'verdict-solid'; }
        else if (c.vert_m >= 20 && c.avg_gradient_pct >= 2) { verdict = 'OK'; vclass = 'verdict-borderline'; }
        else if (c.vert_m >= 20) { verdict = 'SOFT'; vclass = 'verdict-borderline'; }
        else { verdict = 'NOISE'; vclass = 'verdict-noise'; }

        var color = climbRanges[c.idx] ? climbRanges[c.idx].color : '#666';
        var tr = document.createElement('tr');
        tr.className = isSig ? 'sig' : 'noise';
        tr.dataset.climbIdx = c.idx;

        // # column with color dot
        var tdNum = document.createElement('td');
        var dot = document.createElement('span');
        dot.className = 'color-dot';
        dot.style.background = color;
        tdNum.appendChild(dot);
        tdNum.appendChild(document.createTextNode('#' + (c.idx + 1)));
        tr.appendChild(tdNum);

        // Road name column
        var roadText = c.road_name || '-';
        if (c.bridge_pct > 0) roadText += ' [' + Math.round(c.bridge_pct * 100) + '% bridge]';
        if (c.suppressed) roadText += ' SUPPRESSED';
        if (c.n_splits > 0) roadText += ' [' + c.n_splits + ' split' + (c.n_splits > 1 ? 's' : '') + ']';
        var tdRoad = makeCell(roadText);
        tdRoad.style.maxWidth = '200px';
        tdRoad.style.overflow = 'hidden';
        tdRoad.style.textOverflow = 'ellipsis';
        tdRoad.title = (c.road_names_seq || []).join(' \u2192 ');
        if (c.suppressed) tdRoad.style.color = '#e74c3c';
        else if (c.road_name) tdRoad.style.color = '#3498db';
        tr.appendChild(tdRoad);

        tr.appendChild(makeCell(c.vert_m + 'm'));
        tr.appendChild(makeCell(c.avg_gradient_pct + '%'));

        var tMin = Math.floor(c.time_s / 60);
        var tSec = c.time_s % 60;
        tr.appendChild(makeCell(tMin + ':' + String(tSec).padStart(2, '0')));

        var distStr = c.distance_m >= 1000 ? (c.distance_m / 1000).toFixed(1) + 'km' : Math.round(c.distance_m) + 'm';
        tr.appendChild(makeCell(distStr));
        tr.appendChild(makeCell(String(Math.round(c.vam))));
        tr.appendChild(makeCell(c.persistence + 'm'));
        tr.appendChild(makeCell(c.avg_power_w ? Math.round(c.avg_power_w) + 'w' : '-'));
        tr.appendChild(makeCell(c.avg_hr ? String(c.avg_hr) : '-'));

        // Boundary source column
        var bndSrc = '';
        if (c.start_boundary_source) bndSrc += c.start_boundary_source.charAt(0).toUpperCase();
        bndSrc += '/';
        if (c.end_boundary_source) bndSrc += c.end_boundary_source.charAt(0).toUpperCase();
        var tdBnd = makeCell(bndSrc);
        tdBnd.title = 'Start: ' + (c.start_boundary_source || 'gradient') + ' / End: ' + (c.end_boundary_source || 'gradient');
        if (c.start_boundary_source !== 'gradient' || c.end_boundary_source !== 'gradient') tdBnd.style.color = '#2ecc71';
        tr.appendChild(tdBnd);

        var tdV = document.createElement('td');
        var vSpan = document.createElement('span');
        vSpan.className = 'verdict ' + vclass;
        vSpan.textContent = verdict;
        tdV.appendChild(vSpan);
        tr.appendChild(tdV);

        tr.addEventListener('click', function() {
            document.querySelectorAll('tr.active').forEach(function(r) { r.classList.remove('active'); });
            this.classList.add('active');
            zoomToClimb(parseInt(this.dataset.climbIdx));
        });
        tbody.appendChild(tr);
    }
})();

// ===================== ANNOTATION MODE =====================
var annotMode = false;
var annotClimbIdx = 0;
var annotPhase = 'start'; // 'start' or 'end'
var annotations = {}; // { climbIdx: { start: sampleIdx, end: sampleIdx } }
var annotMarkers = []; // DOM elements to clean up

function toggleAnnotate() {
    annotMode = !annotMode;
    var btn = document.getElementById('annotToggle');
    var bar = document.getElementById('annotBar');
    if (annotMode) {
        btn.classList.add('on');
        btn.textContent = 'Annotating';
        bar.classList.add('active');
        annotClimbIdx = 0;
        annotPhase = 'start';
        updateAnnotStatus();
        // Highlight first climb in table
        highlightClimbRow(0);
    } else {
        btn.classList.remove('on');
        btn.textContent = 'Annotate';
        bar.classList.remove('active');
        clearAnnotMarkers();
    }
}

function updateAnnotStatus() {
    var el = document.getElementById('annotStatus');
    var c = climbs[annotClimbIdx];
    var road = c.road_name ? ' (' + c.road_name + ')' : '';
    var done = Object.keys(annotations).length;
    el.textContent = 'Click chart to set ' + annotPhase.toUpperCase() + ' for climb #' + (annotClimbIdx + 1) + road + '  [' + done + '/' + climbs.length + ' annotated]';
}

function highlightClimbRow(idx) {
    document.querySelectorAll('tr.active').forEach(function(r) { r.classList.remove('active'); });
    var rows = document.querySelectorAll('tr[data-climb-idx]');
    for (var i = 0; i < rows.length; i++) {
        if (parseInt(rows[i].dataset.climbIdx) === idx) {
            rows[i].classList.add('active');
            rows[i].scrollIntoView({ block: 'nearest' });
            break;
        }
    }
    zoomToClimb(idx);
}

function annotNext() {
    if (annotClimbIdx < climbs.length - 1) {
        annotClimbIdx++;
        annotPhase = 'start';
        updateAnnotStatus();
        highlightClimbRow(annotClimbIdx);
    }
}

function annotPrev() {
    if (annotClimbIdx > 0) {
        annotClimbIdx--;
        annotPhase = 'start';
        updateAnnotStatus();
        highlightClimbRow(annotClimbIdx);
    }
}

function annotSkip() {
    annotNext();
}

function annotUndo() {
    if (annotPhase === 'end' && annotations[annotClimbIdx] && annotations[annotClimbIdx].start !== undefined) {
        delete annotations[annotClimbIdx].start;
        annotPhase = 'start';
    } else if (annotPhase === 'start' && annotClimbIdx > 0) {
        annotClimbIdx--;
        if (annotations[annotClimbIdx]) delete annotations[annotClimbIdx];
        annotPhase = 'start';
        highlightClimbRow(annotClimbIdx);
    }
    redrawAnnotMarkers();
    updateAnnotStatus();
}

function addAnnotMarker(sampleIdx, type) {
    var chart = document.getElementById('chart');
    var canvas = document.getElementById('elevCanvas');
    var w = canvas.width / (window.devicePixelRatio || 1);
    var padL = 50, padR = 20;
    var plotW = w - padL - padR;
    var n = elevations.length;
    var x = padL + (sampleIdx / (n - 1)) * plotW;

    var marker = document.createElement('div');
    marker.className = 'annot-marker ' + type;
    marker.style.left = x + 'px';
    chart.appendChild(marker);
    annotMarkers.push(marker);

    var label = document.createElement('div');
    label.className = 'annot-marker-label ' + type;
    label.textContent = type === 'start' ? 'S' + (annotClimbIdx + 1) : 'E' + (annotClimbIdx + 1);
    label.style.left = x + 'px';
    label.style.top = '4px';
    label.style.position = 'absolute';
    label.style.zIndex = '6';
    chart.appendChild(label);
    annotMarkers.push(label);
}

function clearAnnotMarkers() {
    annotMarkers.forEach(function(el) { el.remove(); });
    annotMarkers = [];
}

function redrawAnnotMarkers() {
    clearAnnotMarkers();
    for (var idx in annotations) {
        var a = annotations[idx];
        var savedIdx = annotClimbIdx;
        annotClimbIdx = parseInt(idx);
        if (a.start !== undefined) addAnnotMarker(a.start, 'start');
        if (a.end !== undefined) addAnnotMarker(a.end, 'end');
        annotClimbIdx = savedIdx;
    }
}

// Index mapping: chart index → original sample index
var idxMap = DATA.idxMap; // null if no downsampling

function chartIdxToOriginal(chartIdx) {
    if (idxMap && chartIdx >= 0 && chartIdx < idxMap.length) {
        return idxMap[chartIdx];
    }
    return chartIdx; // no downsampling, indices are 1:1
}

// Hook into chart click for annotation
var origChartClick = null;
document.getElementById('chart').addEventListener('click', function(e) {
    if (!annotMode) return;
    var canvas = document.getElementById('elevCanvas');
    var rect = canvas.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var w = rect.width;
    var padL = 50, padR = 20;
    var plotW = w - padL - padR;
    var frac = (mx - padL) / plotW;
    if (frac < 0 || frac > 1) return;
    var chartIdx = Math.round(frac * (elevations.length - 1));
    var sampleIdx = chartIdxToOriginal(chartIdx);

    if (!annotations[annotClimbIdx]) annotations[annotClimbIdx] = {};

    if (annotPhase === 'start') {
        annotations[annotClimbIdx].start = sampleIdx;
        annotations[annotClimbIdx].climbIdx = annotClimbIdx;
        addAnnotMarker(sampleIdx, 'start');
        annotPhase = 'end';
    } else {
        annotations[annotClimbIdx].end = sampleIdx;
        addAnnotMarker(sampleIdx, 'end');
        // Auto-advance to next climb
        if (annotClimbIdx < climbs.length - 1) {
            annotClimbIdx++;
            annotPhase = 'start';
            highlightClimbRow(annotClimbIdx);
        } else {
            annotPhase = 'done';
        }
    }
    updateAnnotStatus();
});

function annotExport() {
    var output = {
        title: title,
        annotated_at: new Date().toISOString(),
        climbs: []
    };
    for (var i = 0; i < climbs.length; i++) {
        var c = climbs[i];
        var a = annotations[i] || {};
        output.climbs.push({
            idx: i,
            road_name: c.road_name || null,
            vert_m: c.vert_m,
            detector_start: c.orig_effort_start_idx || c.effort_start_idx,
            detector_end: c.orig_effort_end_idx || c.effort_end_idx,
            annotated_start: a.start !== undefined ? a.start : null,
            annotated_end: a.end !== undefined ? a.end : null,
            skipped: a.start === undefined && a.end === undefined
        });
    }
    var json = JSON.stringify(output, null, 2);

    // Copy to clipboard
    navigator.clipboard.writeText(json).then(function() {
        document.getElementById('annotStatus').textContent = 'Copied to clipboard! Paste into tools/annotations/<ride_id>.json';
    }).catch(function() {
        // Fallback: download as file
        var blob = new Blob([json], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = title.replace(/[^a-zA-Z0-9]/g, '_') + '_annotations.json';
        a.click();
        URL.revokeObjectURL(url);
        document.getElementById('annotStatus').textContent = 'Downloaded! Save to tools/annotations/';
    });

    // Also log to console for easy access
    console.log('=== ANNOTATIONS ===');
    console.log(json);
}
</script>
</body>
</html>"""


def _downsample(samples, climbs, max_points=2500):
    """Downsample ride data while keeping full resolution in climb regions.

    Uses time-proportional spacing so the chart x-axis reflects real ride timing.
    Returns (ds_samples, ds_climbs) with remapped indices.
    """
    n = len(samples)
    if n <= max_points:
        return samples, climbs, None

    # Mark indices that must be kept
    keep = set()
    keep.add(0)
    keep.add(n - 1)

    # Keep all samples inside climb effort windows + padding for context
    pad = 20  # samples of context around each climb
    for c in climbs:
        for i in range(max(0, c["effort_start_idx"] - pad), min(n, c["effort_end_idx"] + pad + 1)):
            keep.add(i)

    # Fill remaining budget evenly across the full ride
    remaining = max(0, max_points - len(keep))
    if remaining > 0:
        step = max(1, n // remaining)
        for i in range(0, n, step):
            keep.add(i)

    keep_sorted = sorted(keep)
    old_to_new = {old: new for new, old in enumerate(keep_sorted)}

    ds_samples = [samples[i] for i in keep_sorted]
    ds_climbs = []
    for c in climbs:
        dc = dict(c)
        # Store original indices before remapping
        dc["orig_effort_start_idx"] = c["effort_start_idx"]
        dc["orig_effort_end_idx"] = c["effort_end_idx"]
        dc["effort_start_idx"] = old_to_new.get(c["effort_start_idx"],
            min(old_to_new.values(), key=lambda v: abs(keep_sorted[v] - c["effort_start_idx"])))
        dc["effort_end_idx"] = old_to_new.get(c["effort_end_idx"],
            min(old_to_new.values(), key=lambda v: abs(keep_sorted[v] - c["effort_end_idx"])))
        dc["birth_idx"] = old_to_new.get(c["birth_idx"], dc["effort_start_idx"])
        dc["death_idx"] = old_to_new.get(c["death_idx"], dc["effort_end_idx"])
        ds_climbs.append(dc)

    # Return index mapping: dsIndexToOriginal[ds_idx] = original_idx
    return ds_samples, ds_climbs, keep_sorted


def _climb_label(c):
    """Build a label string for a climb including road name if available."""
    base = "#" + str(c["idx"] + 1) + ": " + str(c["vert_m"]) + "m @ " + str(c["avg_gradient_pct"]) + "%"
    road = c.get("road_name")
    if road:
        base = "#" + str(c["idx"] + 1) + " " + road + ": " + str(c["vert_m"]) + "m @ " + str(c["avg_gradient_pct"]) + "%"
    return base


def generate_html(title, samples, climbs, terrain_class=None):
    """Generate a self-contained interactive HTML review page."""

    # Downsample large rides to keep HTML fast
    samples, climbs, idx_map = _downsample(samples, climbs, max_points=2000)

    elevations = []
    times = []
    coords = []  # [lat, lon] or None, index-aligned
    powers = []
    for s in samples:
        times.append(s.get("t", 0))
        elevations.append(s.get("elevation_m"))
        powers.append(s.get("power_w"))
        lat, lon = s.get("lat"), s.get("lon")
        if lat is not None and lon is not None:
            coords.append([round(lat, 6), round(lon, 6)])
        else:
            coords.append(None)

    # Fill null coords forward then backward
    last_valid = None
    for i in range(len(coords)):
        if coords[i] is not None:
            last_valid = coords[i]
        elif last_valid is not None:
            coords[i] = last_valid
    last_valid = None
    for i in range(len(coords) - 1, -1, -1):
        if coords[i] is not None:
            last_valid = coords[i]
        elif last_valid is not None:
            coords[i] = last_valid

    climb_ranges = []
    for c in climbs:
        climb_ranges.append({
            "start_idx": c["effort_start_idx"],
            "end_idx": c["effort_end_idx"],
            "color": CLIMB_COLORS[c["idx"] % len(CLIMB_COLORS)],
            "label": _climb_label(c),
            "vert_m": c["vert_m"],
            "idx": c["idx"],
        })

    ride_coords = [c for c in coords if c is not None]

    climb_map_segments = []
    for c in climbs:
        seg = []
        for i in range(c["effort_start_idx"], min(c["effort_end_idx"] + 1, len(coords))):
            if coords[i] is not None:
                seg.append(coords[i])
        if seg:
            climb_map_segments.append({
                "coords": seg,
                "color": CLIMB_COLORS[c["idx"] % len(CLIMB_COLORS)],
                "label": _climb_label(c),
                "idx": c["idx"],
            })

    terrain_label = terrain_class or "unknown"
    n_sig = sum(1 for c in climbs if c["vert_m"] >= 20)

    valid_elevs = [e for e in elevations if e is not None]
    elev_min = min(valid_elevs) - 5 if valid_elevs else 0
    elev_max = max(valid_elevs) + 20 if valid_elevs else 100

    # Round floats to reduce JSON size
    elevations = [round(e, 1) if e is not None else None for e in elevations]

    data_obj = {
        "elevations": elevations,
        "times": times,
        "powers": powers,
        "sampleCoords": coords,
        "climbRanges": climb_ranges,
        "rideCoords": ride_coords,
        "climbMapSegments": climb_map_segments,
        "climbs": climbs,
        "title": title,
        "terrainLabel": terrain_label,
        "nSig": n_sig,
        "eMin": round(elev_min, 1),
        "eMax": round(elev_max, 1),
        "idxMap": list(idx_map) if idx_map else None,
    }

    template = _generate_html_template()
    html_out = template.replace("__TITLE__", html_mod.escape(title))
    html_out = html_out.replace("__DATA_JSON__", json.dumps(data_obj))
    return html_out


def review_file(filepath, output=None):
    """Review a single ride file."""
    activity, samples = parse_fit_file(filepath)
    if not samples:
        print(f"ERROR: Could not parse {filepath}")
        return None

    climbs = detect_climbs(samples)

    try:
        tc = wp.classify_terrain(samples)
        terrain = tc.class_name if tc else "unknown"
    except Exception:
        terrain = "unknown"

    title = Path(filepath).name
    html_content = generate_html(title, samples, climbs, terrain)

    if output is None:
        output = f"/tmp/{Path(filepath).stem}_climb_review.html"

    with open(output, "w") as f:
        f.write(html_content)

    print(f"Review: {output}")
    print(f"  Terrain: {terrain}")
    print(f"  Climbs: {len(climbs)} ({sum(1 for c in climbs if c['vert_m'] >= 20)} significant)")
    return output


def review_corpus_ride(activity_id, output=None):
    """Review a ride from the corpus by activity ID."""
    candidates = [
        Path(ACTIVITIES_DIR) / f"{activity_id}.fit.gz",
        Path(ACTIVITIES_DIR) / f"{activity_id}.fit",
        Path(ACTIVITIES_DIR) / f"{activity_id}.gpx.gz",
        Path(ACTIVITIES_DIR) / f"{activity_id}.gpx",
        Path(ACTIVITIES_DIR) / f"{activity_id}.tcx.gz",
        Path(ACTIVITIES_DIR) / f"{activity_id}.tcx",
    ]

    filepath = None
    for c in candidates:
        if c.exists():
            filepath = str(c)
            break

    if filepath is None:
        print(f"ERROR: Could not find source file for {activity_id}")
        return None

    return review_file(filepath, output)


def sample_philly_rides(n=6):
    """Sample rides from the Philly corridor across terrain types."""
    conn = sqlite3.connect(CORPUS_DB)
    conn.row_factory = sqlite3.Row

    h3_where = " OR ".join(f"h3_index LIKE '{p}%'" for p in PHILLY_H3_PREFIXES)
    philly_ids = conn.execute(f"""
        SELECT DISTINCT activity_id FROM h3_cells WHERE {h3_where}
    """).fetchall()
    philly_set = set(row["activity_id"] for row in philly_ids)

    if not philly_set:
        print("No Philly rides found in corpus.")
        conn.close()
        return []

    rides = []
    per_terrain = max(1, n // 4)
    for tc in ["rolling", "hilly", "flat", "mountainous"]:
        placeholders = ",".join("?" * len(philly_set))
        r = conn.execute(f"""
            SELECT r.activity_id, r.filename, r.terrain_class, r.elevation_gain_m,
                   COUNT(c.id) as n_climbs,
                   SUM(CASE WHEN c.vert_m >= 20 THEN 1 ELSE 0 END) as n_sig
            FROM rides r
            LEFT JOIN climbs_v2 c ON r.activity_id = c.activity_id
            WHERE r.terrain_class = ? AND r.activity_id IN ({placeholders})
                  AND r.elevation_gain_m > 50
            GROUP BY r.activity_id
            ORDER BY RANDOM()
            LIMIT ?
        """, (tc, *philly_set, per_terrain + 1)).fetchall()
        rides.extend(r)

    rides = rides[:n]
    conn.close()

    outputs = []
    for ride in rides:
        aid = ride["activity_id"]
        n_sig = ride["n_sig"] or 0
        print(f"\n--- {aid} ({ride['terrain_class']}, {ride['elevation_gain_m']:.0f}m gain, {ride['n_climbs']} climbs, {n_sig} sig) ---")
        out = review_corpus_ride(aid)
        if out:
            outputs.append(out)

    return outputs


def sample_rides(n=3, terrain=None):
    """Sample rides from the corpus for review."""
    conn = sqlite3.connect(CORPUS_DB)
    conn.row_factory = sqlite3.Row

    if terrain:
        rides = conn.execute("""
            SELECT r.activity_id, r.filename, r.terrain_class, r.elevation_gain_m,
                   COUNT(c.id) as n_climbs
            FROM rides r
            LEFT JOIN climbs_v2 c ON r.activity_id = c.activity_id
            WHERE r.terrain_class = ? AND r.elevation_gain_m > 100
            GROUP BY r.activity_id
            ORDER BY RANDOM()
            LIMIT ?
        """, (terrain, n)).fetchall()
    else:
        rides = []
        for tc in ["flat", "rolling", "hilly", "mountainous"]:
            r = conn.execute("""
                SELECT r.activity_id, r.filename, r.terrain_class, r.elevation_gain_m,
                       COUNT(c.id) as n_climbs
                FROM rides r
                LEFT JOIN climbs_v2 c ON r.activity_id = c.activity_id
                WHERE r.terrain_class = ? AND r.elevation_gain_m > 50
                GROUP BY r.activity_id
                ORDER BY RANDOM()
                LIMIT ?
            """, (tc, max(1, n // 4 + 1))).fetchall()
            rides.extend(r)
        rides = rides[:n]

    conn.close()

    outputs = []
    for ride in rides:
        aid = ride["activity_id"]
        print(f"\n--- {aid} ({ride['terrain_class']}, {ride['elevation_gain_m']:.0f}m gain, {ride['n_climbs']} climbs) ---")
        out = review_corpus_ride(aid)
        if out:
            outputs.append(out)

    return outputs


def main():
    parser = argparse.ArgumentParser(description="Visual climb detection review")
    parser.add_argument("file", nargs="?", help="Path to .fit/.gpx/.tcx file")
    parser.add_argument("--corpus-id", help="Activity ID from corpus DB")
    parser.add_argument("--philly", type=int, metavar="N", help="Sample N Philly rides")
    parser.add_argument("--sample", type=int, help="Sample N rides from full corpus")
    parser.add_argument("--terrain", help="Filter terrain type for sampling")
    parser.add_argument("--output", "-o", help="Output HTML path")
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")
    args = parser.parse_args()

    outputs = []

    if args.file:
        out = review_file(args.file, args.output)
        if out:
            outputs.append(out)
    elif args.corpus_id:
        out = review_corpus_ride(args.corpus_id, args.output)
        if out:
            outputs.append(out)
    elif args.philly:
        outputs = sample_philly_rides(args.philly)
    elif args.sample:
        outputs = sample_rides(args.sample, args.terrain)
    else:
        parser.print_help()
        return

    if args.open or args.philly:
        import subprocess
        for out in outputs:
            subprocess.run(["open", out])


if __name__ == "__main__":
    main()
