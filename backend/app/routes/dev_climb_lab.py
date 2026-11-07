"""HTML shell for the dev-only ClimbLab workbench."""

from __future__ import annotations


CLIMB_LAB_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ClimbLab · Boulder Roller</title>
    <link
        rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        crossorigin=""
    >
    <style>
        :root {
            --bg: #0b0e11;
            --panel: #141a20;
            --panel-2: #18212a;
            --line: rgba(255, 255, 255, 0.09);
            --line-strong: rgba(255, 255, 255, 0.18);
            --text: #f3f6f7;
            --muted: #aeb8c2;
            --faint: #62707c;
            --amber: #f3a712;
            --green: #4ade80;
            --blue: #38bdf8;
            --red: #f87171;
            --radius: 8px;
        }

        * { box-sizing: border-box; }
        html, body { margin: 0; min-height: 100%; }
        body {
            background:
                linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px) 0 0 / 48px 48px,
                linear-gradient(0deg, rgba(255,255,255,0.03) 1px, transparent 1px) 0 0 / 48px 48px,
                var(--bg);
            color: var(--text);
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
            font-size: 14px;
            line-height: 1.55;
        }

        a { color: inherit; }
        .shell {
            display: grid;
            grid-template-rows: auto 1fr;
            min-height: 100vh;
        }

        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding: 16px 22px;
            background: rgba(20, 26, 32, 0.92);
            border-bottom: 1px solid var(--line);
            position: relative;
            z-index: 1;
            backdrop-filter: blur(16px);
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }

        .mark {
            display: grid;
            place-items: center;
            width: 32px;
            height: 32px;
            border: 1px solid rgba(243, 167, 18, 0.45);
            border-radius: var(--radius);
            background: linear-gradient(135deg, rgba(243, 167, 18, 0.28), rgba(56, 189, 248, 0.16));
            color: var(--amber);
            font-weight: 800;
        }

        h1, h2, h3, p { margin: 0; }
        h1 { font-size: 21px; line-height: 1.15; }
        h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
        h3 { font-size: 14px; line-height: 1.3; }
        .subtle { color: var(--muted); }
        .faint { color: var(--faint); }

        .top-actions {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            justify-content: flex-end;
        }

        .button {
            border: 1px solid var(--line-strong);
            border-radius: 6px;
            color: var(--text);
            background: rgba(255, 255, 255, 0.04);
            padding: 8px 11px;
            text-decoration: none;
            font-size: 12px;
        }

        .button:hover { border-color: rgba(243, 167, 18, 0.55); }

        main {
            display: grid;
            grid-template-columns: minmax(310px, 390px) minmax(0, 1fr) minmax(300px, 390px);
            gap: 1px;
            background: var(--line);
            min-height: calc(100vh - 61px);
        }

        .column {
            background: rgba(11, 14, 17, 0.82);
            min-width: 0;
        }

        .panel {
            padding: 20px;
            border-bottom: 1px solid var(--line);
        }

        .panel-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 14px;
        }

        .badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            border: 1px solid var(--line-strong);
            border-radius: 999px;
            padding: 3px 8px;
            color: var(--muted);
            font-size: 11px;
            white-space: nowrap;
        }

        .dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--faint);
        }

        .dot.good { background: var(--green); }
        .dot.wait { background: var(--amber); }
        .dot.none { background: var(--red); }

        .metrics {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
        }

        .metric, .source-card, .stage-card, .guard-card {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(20, 26, 32, 0.82);
        }

        .lede {
            max-width: 780px;
            color: var(--muted);
            font-size: 15px;
            line-height: 1.7;
        }

        .lede strong { color: var(--text); font-weight: 700; }

        .readout-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
            margin-top: 16px;
        }

        .readout-card {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(20, 26, 32, 0.72);
            padding: 14px;
        }

        .readout-card span {
            display: block;
            color: var(--amber);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 7px;
        }

        .readout-card p { color: var(--muted); }

        .metric { padding: 14px; min-height: 92px; }
        .metric strong {
            display: block;
            font-size: 25px;
            line-height: 1.1;
            font-variant-numeric: tabular-nums;
        }
        .metric span {
            display: block;
            margin-top: 5px;
            color: var(--muted);
            font-size: 11px;
        }
        .metric small {
            display: block;
            margin-top: 8px;
            color: var(--faint);
            font-size: 11px;
            line-height: 1.35;
        }

        .source-list, .stage-list, .guard-list {
            display: grid;
            gap: 10px;
        }

        .source-card, .stage-card, .guard-card { padding: 15px; }
        .source-card { overflow: hidden; }
        .source-title, .stage-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 8px;
        }

        .kv {
            display: grid;
            grid-template-columns: 92px minmax(0, 1fr);
            gap: 6px 10px;
            color: var(--muted);
            font-size: 12px;
        }

        .kv code {
            color: var(--text);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .source-summary {
            color: var(--muted);
            margin-bottom: 12px;
            font-size: 13px;
            line-height: 1.5;
        }

        .source-path {
            color: var(--faint);
            font-size: 11px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            margin-bottom: 12px;
        }

        .source-stats {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 12px;
        }

        .source-stat {
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 6px;
            padding: 8px;
            background: rgba(255, 255, 255, 0.025);
        }

        .source-stat span {
            display: block;
            color: var(--faint);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            margin-bottom: 3px;
        }

        .source-stat strong {
            display: block;
            color: var(--text);
            font-size: 12px;
            overflow: hidden;
            text-overflow: ellipsis;
            overflow-wrap: anywhere;
            white-space: normal;
            line-height: 1.35;
        }

        .recent-title {
            color: var(--faint);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            margin-bottom: 8px;
        }

        .timeline {
            position: relative;
            display: grid;
            gap: 10px;
        }

        .stage-card {
            display: grid;
            grid-template-columns: 30px minmax(0, 1fr);
            gap: 10px;
        }

        .stage-index {
            width: 28px;
            height: 28px;
            border-radius: 6px;
            display: grid;
            place-items: center;
            border: 1px solid var(--line-strong);
            color: var(--amber);
            font-weight: 700;
        }

        .stage-copy p {
            color: var(--muted);
            margin-top: 5px;
        }

        .stage-status {
            color: var(--blue);
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .map-placeholder {
            min-height: 330px;
            display: grid;
            place-items: center;
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background:
                radial-gradient(circle at 34% 28%, rgba(243, 167, 18, 0.13), transparent 24%),
                radial-gradient(circle at 75% 66%, rgba(56, 189, 248, 0.12), transparent 28%),
                repeating-linear-gradient(132deg, rgba(255,255,255,0.06) 0 1px, transparent 1px 22px),
                var(--panel);
            color: var(--muted);
            text-align: center;
            padding: 24px;
        }

        .map-placeholder strong {
            display: block;
            color: var(--text);
            margin-bottom: 10px;
            font-size: 17px;
        }

        .map-placeholder p {
            max-width: 560px;
            margin: 0 auto;
            font-size: 14px;
            line-height: 1.65;
        }

        .file-list {
            display: grid;
            gap: 6px;
            margin-top: 10px;
        }

        .file-row {
            display: block;
            color: var(--muted);
            font-size: 12px;
        }

        .file-row span:first-child {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .empty {
            border: 1px dashed var(--line-strong);
            border-radius: var(--radius);
            padding: 16px;
            color: var(--muted);
            background: rgba(255, 255, 255, 0.025);
        }

        .stage-question {
            margin-top: 10px;
            padding-top: 10px;
            border-top: 1px solid rgba(255, 255, 255, 0.07);
            color: var(--text);
            font-size: 12px;
        }

        .stage-system-label {
            color: var(--faint);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 2px;
        }

        .calibration-headline {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
            margin-bottom: 14px;
        }

        .calibration-stat {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(20, 26, 32, 0.72);
            padding: 12px;
            min-width: 0;
        }

        .calibration-stat span {
            display: block;
            color: var(--faint);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 5px;
        }

        .calibration-stat strong {
            display: block;
            color: var(--text);
            font-size: 18px;
            line-height: 1.2;
            overflow-wrap: anywhere;
        }

        .calibration-note {
            color: var(--muted);
            margin-bottom: 14px;
            font-size: 13px;
            line-height: 1.55;
        }

        .cache-line {
            color: var(--faint);
            margin-bottom: 14px;
            font-size: 11px;
            line-height: 1.45;
        }

        .ride-list {
            display: grid;
            gap: 8px;
        }

        .ride-row {
            display: grid;
            grid-template-columns: minmax(74px, 0.55fr) minmax(0, 1.35fr) minmax(104px, 0.75fr);
            gap: 10px;
            align-items: center;
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(20, 26, 32, 0.72);
            padding: 11px;
        }

        .ride-row.error {
            grid-template-columns: minmax(0, 1fr);
            align-items: start;
        }

        .ride-main,
        .ride-fact {
            min-width: 0;
        }

        .ride-main {
            grid-column: 1 / -1;
        }

        .ride-name {
            display: block;
            max-width: 100%;
            color: var(--text);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .ride-date,
        .ride-use,
        .ride-label {
            color: var(--faint);
            font-size: 11px;
        }

        .ride-use {
            display: block;
            margin-top: 4px;
            line-height: 1.35;
        }

        .ride-label {
            display: block;
            text-transform: uppercase;
            letter-spacing: 0.07em;
            margin-bottom: 4px;
        }

        .ride-value {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.35;
        }

        .sensor-list {
            display: flex;
            gap: 5px;
            flex-wrap: wrap;
            grid-column: 1 / -1;
        }

        .sensor-chip,
        .gain-chip {
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--line-strong);
            border-radius: 999px;
            padding: 2px 7px;
            font-size: 10px;
            color: var(--muted);
            white-space: nowrap;
        }

        .sensor-chip.on { color: var(--text); border-color: rgba(74, 222, 128, 0.36); }
        .gain-chip.large { color: var(--green); border-color: rgba(74, 222, 128, 0.44); }
        .gain-chip.calibration { color: var(--amber); border-color: rgba(243, 167, 18, 0.42); }
        .gain-chip.light { color: var(--blue); border-color: rgba(56, 189, 248, 0.38); }
        .gain-chip.low { color: var(--faint); }

        .signal-list {
            display: grid;
            gap: 9px;
        }

        .signal-row {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(20, 26, 32, 0.76);
            padding: 12px;
        }

        .signal-main {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
        }

        .signal-name {
            display: block;
            color: var(--text);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            max-width: 100%;
        }

        .signal-meta {
            display: block;
            color: var(--faint);
            font-size: 11px;
            margin-top: 3px;
        }

        .signal-facts {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
        }

        .signal-fact {
            min-width: 0;
        }

        .confidence-chip {
            display: inline-flex;
            align-items: center;
            border: 1px solid var(--line-strong);
            border-radius: 999px;
            padding: 3px 8px;
            color: var(--muted);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            white-space: nowrap;
        }

        .confidence-chip.high { color: var(--green); border-color: rgba(74, 222, 128, 0.44); }
        .confidence-chip.medium { color: var(--amber); border-color: rgba(243, 167, 18, 0.42); }
        .confidence-chip.approved { color: var(--green); border-color: rgba(74, 222, 128, 0.48); }
        .confidence-chip.needs-work { color: var(--amber); border-color: rgba(243, 167, 18, 0.48); }
        .confidence-chip.suppressed,
        .confidence-chip.low { color: #ff8a8a; border-color: rgba(248, 113, 113, 0.46); }
        .confidence-chip.pending { color: var(--muted); border-color: var(--line-strong); }

        .review-workbench {
            position: sticky;
            top: 12px;
            z-index: 5;
            align-self: start;
            display: grid;
            gap: 12px;
            margin-bottom: 14px;
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(20, 26, 32, 0.96);
            box-shadow: 0 18px 36px rgba(0, 0, 0, 0.28);
            padding: 12px;
        }

        .review-detail-head {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
        }

        .review-detail-title {
            display: block;
            color: var(--text);
            font-size: 15px;
            line-height: 1.3;
        }

        .review-detail-subtitle,
        .review-detail-meta {
            color: var(--muted);
            font-size: 11px;
            line-height: 1.5;
        }

        .review-decision-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 8px;
        }

        .review-decision-button {
            border: 1px solid var(--line-strong);
            border-radius: 6px;
            background: rgba(255, 255, 255, 0.04);
            color: var(--text);
            min-height: 38px;
            padding: 8px 9px;
            font: inherit;
            font-size: 12px;
            font-weight: 700;
            cursor: pointer;
        }

        .review-decision-button:hover,
        .review-decision-button.active {
            border-color: rgba(243, 167, 18, 0.62);
            background: rgba(243, 167, 18, 0.11);
        }

        .review-decision-button.approve.active {
            color: var(--green);
            border-color: rgba(74, 222, 128, 0.58);
            background: rgba(74, 222, 128, 0.09);
        }

        .review-decision-button.suppress.active {
            color: #ff8a8a;
            border-color: rgba(248, 113, 113, 0.58);
            background: rgba(248, 113, 113, 0.09);
        }

        .review-note-input {
            width: 100%;
            min-height: 54px;
            resize: vertical;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: rgba(11, 14, 17, 0.74);
            color: var(--text);
            padding: 9px 10px;
            font: inherit;
            font-size: 12px;
            line-height: 1.35;
        }

        .review-note-input:focus {
            outline: none;
            border-color: rgba(243, 167, 18, 0.64);
        }

        .review-save-state {
            color: var(--muted);
            font-size: 11px;
            min-height: 16px;
        }

        .review-map {
            height: 320px;
            min-height: 320px;
            border: 1px solid var(--line-strong);
            border-radius: var(--radius);
            overflow: hidden;
            background: var(--panel);
        }

        .review-map-empty {
            display: grid;
            place-items: center;
            height: 100%;
            color: var(--muted);
            padding: 18px;
            text-align: center;
        }

        .review-profile {
            border: 1px solid var(--line);
            border-radius: var(--radius);
            background: rgba(11, 14, 17, 0.76);
            padding: 10px;
            min-height: 154px;
        }

        .review-profile svg {
            display: block;
            width: 100%;
            height: 132px;
        }

        .review-candidate-row {
            width: 100%;
            scroll-margin-top: 640px;
            appearance: none;
            border: 1px solid var(--line);
            text-align: left;
            color: inherit;
            font: inherit;
            cursor: pointer;
        }

        .review-candidate-row:hover,
        .review-candidate-row.active {
            border-color: rgba(243, 167, 18, 0.58);
            background: rgba(243, 167, 18, 0.08);
        }

        .review-candidate-row.approved {
            border-color: rgba(74, 222, 128, 0.26);
        }

        .review-candidate-row.suppressed {
            opacity: 0.68;
        }

        .leaflet-container {
            background: #111820;
            font-family: inherit;
            overflow: hidden;
            position: relative;
        }

        .leaflet-pane,
        .leaflet-tile,
        .leaflet-marker-icon,
        .leaflet-marker-shadow,
        .leaflet-tile-container,
        .leaflet-pane > svg,
        .leaflet-pane > canvas,
        .leaflet-zoom-box,
        .leaflet-image-layer,
        .leaflet-layer {
            position: absolute;
            left: 0;
            top: 0;
        }

        .leaflet-tile {
            width: 256px;
            height: 256px;
            user-select: none;
            -webkit-user-drag: none;
        }

        .leaflet-control-attribution {
            font-size: 10px;
        }

        .leaflet-top,
        .leaflet-bottom {
            position: absolute;
            z-index: 1000;
            pointer-events: none;
        }

        .leaflet-top { top: 0; }
        .leaflet-bottom { bottom: 0; }
        .leaflet-left { left: 0; }
        .leaflet-right { right: 0; }
        .leaflet-control {
            position: relative;
            z-index: 800;
            pointer-events: auto;
        }

        @media (max-width: 1100px) {
            main { grid-template-columns: 1fr; }
            .topbar { align-items: flex-start; flex-direction: column; }
            .top-actions { justify-content: flex-start; }
            .readout-grid { grid-template-columns: 1fr; }
            .source-stats { grid-template-columns: 1fr 1fr; }
        }

        @media (max-width: 520px) {
            body { font-size: 13px; }
            h1 { font-size: 18px; }
            .topbar, .panel { padding: 15px; }
            .metrics { gap: 8px; }
            .metric { min-height: 88px; padding: 12px; }
            .metric strong { font-size: 23px; }
            .source-stats { grid-template-columns: 1fr; }
            .calibration-headline { grid-template-columns: 1fr 1fr; }
            .ride-row { grid-template-columns: 1fr 1fr; align-items: start; }
            .ride-main { grid-column: 1 / -1; }
            .sensor-list { grid-column: 1 / -1; }
            .signal-main { display: block; }
            .signal-main .confidence-chip { margin-top: 8px; }
            .signal-facts { grid-template-columns: 1fr 1fr; }
            .review-workbench { top: 8px; }
            .review-detail-head { display: block; }
            .review-detail-head .confidence-chip { margin-top: 8px; }
            .review-map { height: 260px; min-height: 260px; }
        }
    </style>
</head>
<body>
    <div class="shell">
        <header class="topbar">
            <div class="brand">
                <div class="mark">CL</div>
                <div>
                    <h1>ClimbLab</h1>
                    <p class="subtle">A private workbench for turning roads, terrain, and ride evidence into climb candidates.</p>
                </div>
            </div>
            <nav class="top-actions" aria-label="Development navigation">
                <a class="button" href="/dev/tiles/dashboard-v3">Tile Mission Control</a>
                <a class="button" href="/dev/climb-lab/corpus">Corpus JSON</a>
                <a class="button" href="/dev/climb-lab/calibration">Calibration JSON</a>
                <a class="button" href="/dev/climb-lab/elevation-signals">Signals JSON</a>
                <a class="button" href="/dev/climb-lab/road-graph">Road Graph JSON</a>
                <a class="button" href="/dev/climb-lab/road-signals">Road Signals JSON</a>
                <a class="button" href="/dev/climb-lab/pipeline-results">Pipeline JSON</a>
                <a class="button" href="/dev/climb-lab/scan-results">Scan JSON</a>
                <a class="button" href="/dev/climb-lab/review">Review Workbench</a>
                <a class="button" href="/dev/climb-lab/review-candidates">Review JSON</a>
                <a class="button" href="/dev/climb-lab/review-state">Review State</a>
            </nav>
        </header>

        <main>
            <section class="column">
                <div class="panel">
                    <div class="panel-head">
                        <h2>Corpus</h2>
                        <span class="badge" id="scopeBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <div class="metrics">
                        <div class="metric">
                            <strong id="activityCount">0</strong>
                            <span>activity files</span>
                            <small id="activityMeaning">Waiting for corpus.</small>
                        </div>
                        <div class="metric">
                            <strong id="sourceCount">0</strong>
                            <span>active sources</span>
                            <small>Mounted folders with ride files.</small>
                        </div>
                        <div class="metric">
                            <strong id="sizeCount">0 MB</strong>
                            <span>metadata inventory</span>
                            <small>No coordinates shown here.</small>
                        </div>
                        <div class="metric">
                            <strong id="candidateStatus">none</strong>
                            <span>candidate layer</span>
                            <small>Terrain candidates are still separate from production climbs.</small>
                        </div>
                    </div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Sources</h2>
                    </div>
                    <div class="source-list" id="sourceList"></div>
                </div>
            </section>

            <section class="column">
                <div class="panel">
                    <div class="panel-head">
                        <h2>Readout</h2>
                        <span class="badge"><span class="dot wait"></span> Experimental</span>
                    </div>
                    <p class="lede">
                        <strong>ClimbLab is not matching rides yet.</strong>
                        It is the parallel place where we can see the raw evidence for a future climb layer:
                        roads, elevation shape, Garmin confirmation, and expert review.
                    </p>
                    <div class="readout-grid">
                        <div class="readout-card">
                            <span>Use it for</span>
                            <p>Seeing whether the land and real rides agree before anything becomes official.</p>
                        </div>
                        <div class="readout-card">
                            <span>Current signal</span>
                            <p id="currentSignal">Loading the local activity corpus.</p>
                        </div>
                        <div class="readout-card">
                            <span>Next useful view</span>
                            <p>Road-edge climb signal with Garmin traces as confidence, not source of truth.</p>
                        </div>
                    </div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Calibration Inventory</h2>
                        <span class="badge" id="calibrationBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="calibrationNote">
                        Reading local activity files into ride-level evidence only. No coordinates, GPS tracks, or raw samples are shown.
                    </p>
                    <div class="cache-line" id="calibrationCache">Cache waiting.</div>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Parsed</span>
                            <strong id="parsedRideCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Elevation</span>
                            <strong id="elevationRideCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Gain candidates</span>
                            <strong id="gainCandidateCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Naive gain</span>
                            <strong id="naiveGainCount">0 m</strong>
                        </div>
                    </div>
                    <div id="calibrationList" class="empty">Loading ride summaries.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Elevation Signals</h2>
                        <span class="badge" id="signalBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="signalNote">
                        Scanning ride elevation, distance, and time for sustained uphill intervals. No coordinates or raw point arrays are shown.
                    </p>
                    <div class="cache-line" id="signalCache">Cache waiting.</div>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Signals</span>
                            <strong id="signalCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Rides</span>
                            <strong id="signalRideCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Top gain</span>
                            <strong id="topSignalGain">0 m</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Signal gain</span>
                            <strong id="signalGainTotal">0 m</strong>
                        </div>
                    </div>
                    <div id="signalList" class="empty">Loading elevation signals.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Road Graph</h2>
                        <span class="badge" id="roadGraphBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="roadGraphNote">
                        Normalizing OSM-like roads into intersection-to-intersection edges. Coordinates and raw geometry stay out of the dashboard payload.
                    </p>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Edges</span>
                            <strong id="roadGraphEdgeCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Intersections</span>
                            <strong id="roadGraphIntersectionCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Elevation-ready</span>
                            <strong id="roadGraphReadyCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Model</span>
                            <strong id="roadGraphModelCount">v0</strong>
                        </div>
                    </div>
                    <div id="roadGraphList" class="empty">Loading road graph.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Road-Edge Signals</h2>
                        <span class="badge" id="roadSignalBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="roadSignalNote">
                        Scoring directed intersection-to-intersection road edges by gain, grade, and how much of each edge carries climb signal.
                    </p>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Edges</span>
                            <strong id="roadSignalCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Strings</span>
                            <strong id="roadStringCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Bearing gain</span>
                            <strong id="roadBearingGain">0 m</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Model</span>
                            <strong id="roadModelCount">v0</strong>
                        </div>
                    </div>
                    <div id="roadSignalList" class="empty">Loading road-edge signals.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Pipeline Results</h2>
                        <span class="badge" id="pipelineResultBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="pipelineResultNote">
                        Running road graph edges through signal scoring and stringing into lab-only candidate climb results.
                    </p>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Candidates</span>
                            <strong id="pipelineCandidateCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Top gain</span>
                            <strong id="pipelineTopGain">0 m</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Total gain</span>
                            <strong id="pipelineTotalGain">0 m</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Status</span>
                            <strong id="pipelineStatus">none</strong>
                        </div>
                    </div>
                    <div id="pipelineResultList" class="empty">Loading pipeline results.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Bounded Scan</h2>
                        <span class="badge" id="scanResultBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="scanResultNote">
                        Fetching a capped Boulder foothills road graph, attaching elevation, and running the candidate pipeline.
                    </p>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Candidates</span>
                            <strong id="scanCandidateCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Selected roads</span>
                            <strong id="scanSelectedRoadCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Elevated nodes</span>
                            <strong id="scanElevationNodeCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Top gain</span>
                            <strong id="scanTopGain">0 m</strong>
                        </div>
                    </div>
                    <div id="scanResultList" class="empty">Loading bounded scan results.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Candidate Map</h2>
                        <span class="badge" id="reviewCandidateBadge"><span class="dot wait"></span> Loading</span>
                    </div>
                    <p class="calibration-note" id="reviewCandidateNote">
                        Loading the dev-only canon ratification queue.
                    </p>
                    <div class="calibration-headline">
                        <div class="calibration-stat">
                            <span>Reviewable</span>
                            <strong id="reviewCandidateCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Approved</span>
                            <strong id="reviewApprovedCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Needs work</span>
                            <strong id="reviewNeedsWorkCount">0</strong>
                        </div>
                        <div class="calibration-stat">
                            <span>Suppressed</span>
                            <strong id="reviewSuppressedCount">0</strong>
                        </div>
                    </div>
                    <div class="review-workbench" aria-live="polite">
                        <div class="review-detail-head">
                            <div>
                                <span class="review-detail-title" id="reviewSelectedName">Select a candidate</span>
                                <span class="review-detail-subtitle" id="reviewSelectedSummary">The selected road line and elevation profile will render here.</span>
                            </div>
                            <span class="confidence-chip" id="reviewSelectedState">waiting</span>
                        </div>
                        <div id="reviewMap" class="review-map">
                            <div class="review-map-empty">Select a candidate to draw its centerline.</div>
                        </div>
                        <div class="review-profile">
                            <svg id="reviewProfile" viewBox="0 0 640 150" role="img" aria-label="Selected candidate elevation profile"></svg>
                        </div>
                        <div class="review-decision-grid" aria-label="Review decisions">
                            <button type="button" class="review-decision-button approve" data-review-decision="approve">Approve</button>
                            <button type="button" class="review-decision-button needs-work" data-review-decision="needs_work">Needs work</button>
                            <button type="button" class="review-decision-button suppress" data-review-decision="suppress">Suppress</button>
                            <button type="button" class="review-decision-button pending" data-review-decision="pending">Clear</button>
                        </div>
                        <textarea id="reviewDecisionNote" class="review-note-input" maxlength="500" placeholder="Boundary note"></textarea>
                        <div id="reviewDecisionSaveState" class="review-save-state"></div>
                        <div class="review-detail-meta" id="reviewSelectedMeta">Map detail loads one candidate at a time; the queue payload stays geometry-redacted.</div>
                    </div>
                    <div id="reviewCandidateList" class="empty">Loading review candidates.</div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Pipeline</h2>
                    </div>
                    <div class="timeline" id="pipelineList"></div>
                </div>
            </section>

            <section class="column">
                <div class="panel">
                    <div class="panel-head">
                        <h2>Boundaries</h2>
                    </div>
                    <div class="guard-list" id="guardList"></div>
                </div>
                <div class="panel">
                    <div class="panel-head">
                        <h2>Review State</h2>
                        <span class="badge"><span class="dot good"></span> Local</span>
                    </div>
                    <div class="guard-list">
                        <div class="guard-card">Decisions save to local ClimbLab review state only.</div>
                        <div class="guard-card">Agents can inspect the same state through <a class="button" href="/dev/climb-lab/review-state">Review State</a>.</div>
                        <div class="guard-card">Canon publishing remains a separate explicit action.</div>
                    </div>
                </div>
            </section>
        </main>
    </div>

    <script
        src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin=""
    ></script>
    <script>
        const fmt = new Intl.NumberFormat();
        let reviewCandidates = [];
        let selectedReviewCandidateId = null;
        let reviewMap = null;
        let reviewLine = null;
        let reviewMarkers = [];
        const REVIEW_CANDIDATES_URL = "/dev/climb-lab/review-candidates?preset=philadelphia_manayunk_wall&max_ways=90&max_candidates=18&max_elevation_nodes=240";
        const escapeHtml = (value) => String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
        const bytesToHuman = (bytes) => {
            if (bytes === 0) return "0 KB";
            if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
            return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        };
        const dateRange = (source) => {
            const start = source.date_range?.start;
            const end = source.date_range?.end;
            if (start && end) return `${start} to ${end}`;
            return "not available";
        };
        const extensionSummary = (source) => {
            const entries = Object.entries(source.extensions || {});
            if (!entries.length) return "none";
            return entries.map(([ext, count]) => `${count} ${ext.toUpperCase()}`).join(", ");
        };
        const cacheSummary = (cache) => {
            if (!cache) return "Process cache unavailable";
            return `Process cache: ${fmt.format(cache.hits || 0)} hits, ${fmt.format(cache.misses || 0)} parsed, ${fmt.format(cache.entries || 0)} entries`;
        };

        function decodePolyline(encoded) {
            const points = [];
            let index = 0;
            let lat = 0;
            let lng = 0;
            while (index < encoded.length) {
                let result = 0;
                let shift = 0;
                let byte = null;
                do {
                    byte = encoded.charCodeAt(index++) - 63;
                    result |= (byte & 0x1f) << shift;
                    shift += 5;
                } while (byte >= 0x20 && index < encoded.length);
                lat += (result & 1) ? ~(result >> 1) : (result >> 1);

                result = 0;
                shift = 0;
                do {
                    byte = encoded.charCodeAt(index++) - 63;
                    result |= (byte & 0x1f) << shift;
                    shift += 5;
                } while (byte >= 0x20 && index < encoded.length);
                lng += (result & 1) ? ~(result >> 1) : (result >> 1);
                points.push([lat / 1e5, lng / 1e5]);
            }
            return points;
        }

        function setReviewStatus(message, state = "waiting") {
            const status = document.getElementById("reviewSelectedState");
            status.textContent = message;
            status.className = `confidence-chip ${state}`;
        }

        function reviewStateClass(value) {
            const normalized = String(value || "needs_review").toLowerCase();
            if (normalized.includes("approved")) return "approved";
            if (normalized.includes("suppressed") || normalized.includes("suppress")) return "suppressed";
            if (normalized.includes("needs_work") || normalized.includes("boundary") || normalized.includes("merge")) return "needs-work";
            return "pending";
        }

        function reviewStateLabel(candidate) {
            const label = candidate?.review_decision_label;
            if (label && label !== "Clear") return label;
            const state = String(candidate?.review_state || "needs_review").replaceAll("_", " ");
            if (state === "needs review") return "Pending";
            if (state === "approved for review") return "Approved";
            return state;
        }

        function setReviewDecisionControls(candidate) {
            const noteInput = document.getElementById("reviewDecisionNote");
            const saveState = document.getElementById("reviewDecisionSaveState");
            const decision = candidate?.review_decision || "pending";
            noteInput.value = candidate?.review_note || "";
            saveState.textContent = candidate?.review_updated_at
                ? `Saved ${new Date(candidate.review_updated_at).toLocaleString()}`
                : "";
            document.querySelectorAll("[data-review-decision]").forEach((button) => {
                const active = button.dataset.reviewDecision === decision
                    || (decision === "pending" && button.dataset.reviewDecision === "pending");
                button.classList.toggle("active", active);
                button.disabled = !selectedReviewCandidateId;
            });
        }

        function setReviewDecisionSaving(isSaving) {
            document.querySelectorAll("[data-review-decision]").forEach((button) => {
                button.disabled = isSaving || !selectedReviewCandidateId;
            });
        }

        async function refreshReviewCandidates() {
            const response = await fetch(REVIEW_CANDIDATES_URL, {
                headers: { "Accept": "application/json" },
            });
            if (!response.ok) throw new Error(`Review refresh failed: ${response.status}`);
            const reviewResults = await response.json();
            renderReviewResults(reviewResults);
        }

        async function saveReviewDecision(decision) {
            if (!selectedReviewCandidateId) return;
            const note = document.getElementById("reviewDecisionNote").value.trim();
            const saveState = document.getElementById("reviewDecisionSaveState");
            setReviewDecisionSaving(true);
            saveState.textContent = "Saving.";
            try {
                const response = await fetch(`/dev/climb-lab/review-candidates/${encodeURIComponent(selectedReviewCandidateId)}/decision`, {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ decision, note }),
                });
                if (!response.ok) {
                    const error = await response.text();
                    throw new Error(`Decision failed: ${response.status} ${error}`);
                }
                await refreshReviewCandidates();
                saveState.textContent = "Saved.";
            } catch (error) {
                saveState.textContent = error.message;
            } finally {
                setReviewDecisionSaving(false);
            }
        }

        function ensureReviewMap() {
            const mapElement = document.getElementById("reviewMap");
            if (!window.L) {
                mapElement.innerHTML = `<div class="review-map-empty">Map library did not load. Review JSON is still available.</div>`;
                return null;
            }
            if (reviewMap) return reviewMap;
            mapElement.innerHTML = "";
            reviewMap = L.map(mapElement, {
                zoomControl: true,
                scrollWheelZoom: false,
            });
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: "&copy; OpenStreetMap contributors",
            }).addTo(reviewMap);
            return reviewMap;
        }

        function settleReviewMapLayout() {
            if (!reviewMap || !reviewLine) return;
            reviewMap.invalidateSize();
            reviewMap.fitBounds(reviewLine.getBounds(), { padding: [28, 28] });
        }

        function renderReviewMap(detail) {
            const geometry = detail.geometry || {};
            const encoded = geometry.centerline_polyline || "";
            const map = ensureReviewMap();
            if (!map || !encoded) {
                setReviewStatus("no map", "low");
                return;
            }
            const points = decodePolyline(encoded);
            if (points.length < 2) {
                setReviewStatus("bad line", "low");
                return;
            }
            if (reviewLine) reviewLine.remove();
            reviewMarkers.forEach((marker) => marker.remove());
            reviewMarkers = [];
            reviewLine = L.polyline(points, {
                color: "#f3a712",
                weight: 6,
                opacity: 0.94,
            }).addTo(map);
            reviewMarkers.push(
                L.circleMarker(points[0], {
                    radius: 6,
                    color: "#4ade80",
                    fillColor: "#4ade80",
                    fillOpacity: 0.9,
                    weight: 2,
                }).addTo(map),
                L.circleMarker(points[points.length - 1], {
                    radius: 6,
                    color: "#38bdf8",
                    fillColor: "#38bdf8",
                    fillOpacity: 0.9,
                    weight: 2,
                }).addTo(map),
            );
            settleReviewMapLayout();
            requestAnimationFrame(settleReviewMapLayout);
            setTimeout(settleReviewMapLayout, 240);
        }

        function renderReviewProfile(detail) {
            const svg = document.getElementById("reviewProfile");
            const points = ((detail.profile || {}).points || [])
                .filter((point) => Number.isFinite(point.dist_m) && Number.isFinite(point.elev_m));
            if (points.length < 2) {
                svg.innerHTML = `<text x="24" y="80" fill="#aeb8c2">No profile points available.</text>`;
                return;
            }
            const width = 640;
            const height = 150;
            const padX = 28;
            const padY = 18;
            const maxDist = Math.max(...points.map((point) => point.dist_m), 1);
            const minElev = Math.min(...points.map((point) => point.elev_m));
            const maxElev = Math.max(...points.map((point) => point.elev_m));
            const elevRange = Math.max(maxElev - minElev, 1);
            const coords = points.map((point) => {
                const x = padX + (point.dist_m / maxDist) * (width - padX * 2);
                const y = height - padY - ((point.elev_m - minElev) / elevRange) * (height - padY * 2);
                return [x, y];
            });
            const path = coords.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
            const fillPath = `${path} L${(width - padX).toFixed(1)} ${(height - padY).toFixed(1)} L${padX} ${(height - padY).toFixed(1)} Z`;
            svg.innerHTML = `
                <path d="${fillPath}" fill="rgba(243,167,18,0.16)"></path>
                <path d="${path}" fill="none" stroke="#f3a712" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
                <line x1="${padX}" y1="${height - padY}" x2="${width - padX}" y2="${height - padY}" stroke="rgba(255,255,255,0.18)"></line>
                <text x="${padX}" y="14" fill="#aeb8c2">${fmt.format(minElev)} m</text>
                <text x="${width - padX - 92}" y="14" fill="#aeb8c2">${fmt.format(maxElev)} m</text>
                <text x="${padX}" y="${height - 3}" fill="#62707c">0 m</text>
                <text x="${width - padX - 80}" y="${height - 3}" fill="#62707c">${fmt.format(Math.round(maxDist))} m</text>
            `;
        }

        function setActiveReviewRow(candidateId) {
            document.querySelectorAll(".review-candidate-row").forEach((row) => {
                row.classList.toggle("active", row.dataset.candidateId === candidateId);
            });
        }

        async function selectReviewCandidate(candidateId) {
            if (!candidateId) return;
            selectedReviewCandidateId = candidateId;
            setActiveReviewRow(candidateId);
            const candidate = reviewCandidates.find((item) => item.candidate_id === candidateId) || {};
            document.getElementById("reviewSelectedName").textContent = candidate.display_name || candidateId;
            document.getElementById("reviewSelectedSummary").textContent = `${fmt.format(Math.round(candidate.distance_m || 0))} m · ${fmt.format(candidate.gain_m || 0)} m gain · ${fmt.format(candidate.avg_grade_pct || 0)}%`;
            document.getElementById("reviewSelectedMeta").textContent = "Loading map detail.";
            setReviewDecisionControls(candidate);
            setReviewStatus("loading", "medium");
            try {
                const response = await fetch(`/dev/climb-lab/review-candidates/${encodeURIComponent(candidateId)}/map-detail`, {
                    headers: { "Accept": "application/json" },
                });
                if (!response.ok) throw new Error(`Map detail failed: ${response.status}`);
                const detail = await response.json();
                renderReviewMap(detail);
                renderReviewProfile(detail);
                const detailCandidate = detail.candidate || {};
                const idx = reviewCandidates.findIndex((item) => item.candidate_id === candidateId);
                if (idx >= 0) reviewCandidates[idx] = { ...reviewCandidates[idx], ...detailCandidate };
                setReviewDecisionControls(detailCandidate);
                const preview = (detail.candidate || {}).canon_publish_preview || {};
                document.getElementById("reviewSelectedMeta").textContent = `${detail.privacy_mode} · ${fmt.format((detail.profile || {}).sample_count || 0)} profile samples · ${fmt.format(preview.corridor_cell_count || 0)} corridor cells`;
                setReviewStatus(reviewStateLabel(detailCandidate), reviewStateClass(detailCandidate.review_state || detailCandidate.review_decision));
            } catch (error) {
                document.getElementById("reviewSelectedMeta").textContent = error.message;
                setReviewStatus("error", "low");
            }
        }

        function badge(source) {
            const active = source.available && source.file_count > 0;
            const dot = active ? "good" : source.available ? "wait" : "none";
            const label = active ? "active" : source.available ? "empty" : "missing";
            return `<span class="badge"><span class="dot ${dot}"></span>${label}</span>`;
        }

        function renderSource(source) {
            const years = Object.entries(source.years || {})
                .map(([year, count]) => `${year}:${count}`)
                .join("  ");
            const files = (source.recent_files || [])
                .map((file) => `<div class="file-row"><span>${escapeHtml(file.name)}</span></div>`)
                .join("");
            return `
                <article class="source-card">
                    <div class="source-title">
                        <h3>${escapeHtml(source.label)}</h3>
                        ${badge(source)}
                    </div>
                    <p class="source-summary">${escapeHtml(source.summary)}</p>
                    <div class="source-path" title="${escapeHtml(source.path)}">${escapeHtml(source.path)}</div>
                    <div class="source-stats">
                        <div class="source-stat">
                            <span>Files</span>
                            <strong>${fmt.format(source.file_count)}</strong>
                        </div>
                        <div class="source-stat">
                            <span>Range</span>
                            <strong title="${dateRange(source)}">${dateRange(source)}</strong>
                        </div>
                        <div class="source-stat">
                            <span>Format</span>
                            <strong>${extensionSummary(source)}</strong>
                        </div>
                        <div class="source-stat">
                            <span>Size</span>
                            <strong>${bytesToHuman(source.total_bytes)}</strong>
                        </div>
                    </div>
                    ${years ? `<div class="source-path" title="${escapeHtml(years)}">Year spread: ${escapeHtml(years)}</div>` : ""}
                    ${files ? `<div class="recent-title">Recent files</div><div class="file-list">${files}</div>` : ""}
                </article>
            `;
        }

        function renderStage(stage, index) {
            return `
                <article class="stage-card">
                    <div class="stage-index">${index + 1}</div>
                    <div class="stage-copy">
                        <div class="stage-title">
                            <div>
                                <div class="stage-system-label">${escapeHtml(stage.label)}</div>
                                <h3>${escapeHtml(stage.plain_language || stage.label)}</h3>
                            </div>
                            <span class="stage-status">${escapeHtml(stage.status)}</span>
                        </div>
                        <p>${escapeHtml(stage.summary)}</p>
                        ${stage.decision ? `<div class="stage-question">${escapeHtml(stage.decision)}</div>` : ""}
                    </div>
                </article>
            `;
        }

        function renderRideSensors(ride) {
            const sensors = [
                ["GPS", ride.has_gps],
                ["Elev", ride.has_elevation],
                ["HR", ride.has_hr],
                ["Power", ride.has_power],
            ];
            return `<div class="sensor-list">${sensors
                .map(([label, active]) => `<span class="sensor-chip ${active ? "on" : ""}">${label}</span>`)
                .join("")}</div>`;
        }

        function renderRideRow(ride) {
            if (ride.status !== "parsed") {
                return `
                    <article class="ride-row error">
                        <div class="ride-main">
                            <span class="ride-name" title="${escapeHtml(ride.name)}">${escapeHtml(ride.name)}</span>
                            <span class="ride-date">${escapeHtml(ride.activity_date || "unknown date")}</span>
                            <span class="ride-use">${escapeHtml(ride.error || "Could not parse this file.")}</span>
                        </div>
                    </article>
                `;
            }
            const elevation = ride.elevation_min_m !== null && ride.elevation_max_m !== null
                ? `${fmt.format(ride.elevation_min_m)}-${fmt.format(ride.elevation_max_m)} m`
                : "none";
            return `
                <article class="ride-row">
                    <div class="ride-main">
                        <span class="ride-name" title="${escapeHtml(ride.name)}">${escapeHtml(ride.name)}</span>
                        <span class="ride-date">${escapeHtml(ride.activity_date || "unknown date")}</span>
                        <span class="ride-use">${escapeHtml(ride.calibration_use)}</span>
                    </div>
                    <div class="ride-fact">
                        <span class="ride-label">Time</span>
                        <span class="ride-value">${escapeHtml(ride.duration_label || "0m")}</span>
                    </div>
                    <div class="ride-fact">
                        <span class="ride-label">Elevation</span>
                        <span class="ride-value">${escapeHtml(elevation)} · ${fmt.format(ride.sample_count || 0)} samples</span>
                    </div>
                    <div class="ride-fact">
                        <span class="ride-label">Gain signal</span>
                        <span class="gain-chip ${escapeHtml(ride.gain_band)}">${fmt.format(ride.naive_gain_m || 0)} m</span>
                    </div>
                    ${renderRideSensors(ride)}
                </article>
            `;
        }

        function renderCalibration(data) {
            const totals = data.totals || {};
            const available = data.available && totals.rides_returned > 0;
            const errors = totals.errors || 0;
            document.getElementById("calibrationBadge").innerHTML = `<span class="dot ${available ? "good" : "wait"}"></span>${escapeHtml(data.privacy_mode)}`;
            document.getElementById("parsedRideCount").textContent = `${fmt.format(totals.parsed || 0)}/${fmt.format(totals.rides_returned || 0)}`;
            document.getElementById("elevationRideCount").textContent = fmt.format(totals.with_elevation || 0);
            document.getElementById("gainCandidateCount").textContent = fmt.format(totals.gain_candidates || 0);
            document.getElementById("naiveGainCount").textContent = `${fmt.format(Math.round(totals.naive_gain_m || 0))} m`;
            document.getElementById("calibrationNote").textContent = available
                ? `${fmt.format(totals.files_considered || 0)} local activity files are available. Showing the newest ${fmt.format(totals.rides_returned || 0)} as bounded ride summaries; ${fmt.format(errors)} parse errors stayed isolated. No coordinates, GPS tracks, or raw samples are shown.`
                : "No parseable ride summaries are available from this source yet.";
            document.getElementById("calibrationCache").textContent = cacheSummary(data.cache);
            const rides = data.rides || [];
            if (!rides.length) {
                document.getElementById("calibrationList").outerHTML = `<div id="calibrationList" class="empty">No ride summaries to show yet.</div>`;
                return;
            }
            document.getElementById("calibrationList").outerHTML = `
                <div id="calibrationList" class="ride-list">${rides.map(renderRideRow).join("")}</div>
            `;
        }

        function renderSignalRow(signal) {
            const range = signal.start_pct !== null && signal.end_pct !== null
                ? `${fmt.format(signal.start_pct)}-${fmt.format(signal.end_pct)}% of ride`
                : "ride position unavailable";
            return `
                <article class="signal-row">
                    <div class="signal-main">
                        <div>
                            <span class="signal-name" title="${escapeHtml(signal.ride_file)}">${escapeHtml(signal.ride_file)}</span>
                            <span class="signal-meta">${escapeHtml(signal.activity_date || "unknown date")} · ${escapeHtml(range)} · ${escapeHtml(signal.start_offset_label)} to ${escapeHtml(signal.end_offset_label)}</span>
                        </div>
                        <span class="confidence-chip ${escapeHtml(signal.confidence)}">${escapeHtml(signal.confidence)}</span>
                    </div>
                    <div class="signal-facts">
                        <div class="signal-fact">
                            <span class="ride-label">Gain</span>
                            <span class="gain-chip ${escapeHtml(signal.gain_band)}">${fmt.format(signal.gain_m || 0)} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Distance</span>
                            <span class="ride-value">${fmt.format(Math.round(signal.distance_m || 0))} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Grade</span>
                            <span class="ride-value">${fmt.format(signal.avg_grade_pct || 0)}%</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Time</span>
                            <span class="ride-value">${escapeHtml(signal.duration_label || "0m")}</span>
                        </div>
                    </div>
                </article>
            `;
        }

        function renderSignals(data) {
            const totals = data.totals || {};
            const available = data.available && totals.signals_returned > 0;
            document.getElementById("signalBadge").innerHTML = `<span class="dot ${available ? "good" : "wait"}"></span>${escapeHtml(data.privacy_mode)}`;
            document.getElementById("signalCount").textContent = fmt.format(totals.signals_returned || 0);
            document.getElementById("signalRideCount").textContent = fmt.format(totals.rides_with_signals || 0);
            document.getElementById("topSignalGain").textContent = `${fmt.format(Math.round(totals.top_gain_m || 0))} m`;
            document.getElementById("signalGainTotal").textContent = `${fmt.format(Math.round(totals.total_signal_gain_m || 0))} m`;
            document.getElementById("signalNote").textContent = available
                ? `Scanned ${fmt.format(totals.files_scanned || 0)} local ride files and found ${fmt.format(totals.signals_returned || 0)} bounded uphill intervals from elevation, distance, and time only. No coordinates or raw point arrays are shown.`
                : "No uphill elevation signals met the current scan threshold.";
            document.getElementById("signalCache").textContent = cacheSummary(data.cache);
            const signals = data.signals || [];
            if (!signals.length) {
                document.getElementById("signalList").outerHTML = `<div id="signalList" class="empty">No elevation signals to show yet.</div>`;
                return;
            }
            document.getElementById("signalList").outerHTML = `
                <div id="signalList" class="signal-list">${signals.map(renderSignalRow).join("")}</div>
            `;
        }

        function renderRoadSignalRow(signal) {
            const range = signal.climb_start_pct !== null && signal.climb_end_pct !== null
                ? `${fmt.format(signal.climb_start_pct)}-${fmt.format(signal.climb_end_pct)}% of edge`
                : "edge position unavailable";
            return `
                <article class="signal-row">
                    <div class="signal-main">
                        <div>
                            <span class="signal-name" title="${escapeHtml(signal.edge_id)}">${escapeHtml(signal.road_name || signal.edge_id)}</span>
                            <span class="signal-meta">${escapeHtml(signal.from_intersection)} to ${escapeHtml(signal.to_intersection)} · ${escapeHtml(signal.direction)} · ${escapeHtml(range)}</span>
                        </div>
                        <span class="confidence-chip ${escapeHtml(signal.confidence)}">${escapeHtml(signal.signal_band)}</span>
                    </div>
                    <div class="signal-facts">
                        <div class="signal-fact">
                            <span class="ride-label">Gain</span>
                            <span class="gain-chip ${signal.is_climb_bearing ? "calibration" : "low"}">${fmt.format(signal.gain_m || 0)} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Edge share</span>
                            <span class="ride-value">${fmt.format(signal.climb_pct || 0)}%</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Grade</span>
                            <span class="ride-value">${fmt.format(signal.avg_grade_pct || 0)}%</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Distance</span>
                            <span class="ride-value">${fmt.format(Math.round(signal.distance_m || 0))} m</span>
                        </div>
                    </div>
                </article>
            `;
        }

        function renderRoadStringRow(candidate) {
            return `
                <article class="signal-row">
                    <div class="signal-main">
                        <div>
                            <span class="signal-name">${escapeHtml(candidate.road_names.join(" / ") || candidate.string_id)}</span>
                            <span class="signal-meta">${escapeHtml(candidate.from_intersection)} to ${escapeHtml(candidate.to_intersection)} · ${fmt.format(candidate.edge_count || 0)} edges</span>
                        </div>
                        <span class="confidence-chip ${escapeHtml(candidate.confidence)}">candidate string</span>
                    </div>
                    <div class="signal-facts">
                        <div class="signal-fact">
                            <span class="ride-label">Gain</span>
                            <span class="gain-chip calibration">${fmt.format(candidate.gain_m || 0)} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Distance</span>
                            <span class="ride-value">${fmt.format(Math.round(candidate.distance_m || 0))} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Grade</span>
                            <span class="ride-value">${fmt.format(candidate.avg_grade_pct || 0)}%</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Edges</span>
                            <span class="ride-value">${escapeHtml(candidate.edge_ids.join(" + "))}</span>
                        </div>
                    </div>
                </article>
            `;
        }

        function renderRoadGraphEdge(edge) {
            const distances = (edge.sample_distances_m || [])
                .map((distance) => fmt.format(Math.round(distance || 0)))
                .join(" / ");
            return `
                <article class="signal-row">
                    <div class="signal-main">
                        <div>
                            <span class="signal-name" title="${escapeHtml(edge.edge_id)}">${escapeHtml(edge.road_name || edge.edge_id)}</span>
                            <span class="signal-meta">${escapeHtml(edge.from_intersection)} to ${escapeHtml(edge.to_intersection)} · ${escapeHtml(edge.highway || "road")}</span>
                        </div>
                        <span class="confidence-chip ${edge.elevation_profile_status === "ready" ? "medium" : "exploratory"}">${escapeHtml(edge.elevation_profile_status)}</span>
                    </div>
                    <div class="signal-facts">
                        <div class="signal-fact">
                            <span class="ride-label">Distance</span>
                            <span class="ride-value">${fmt.format(Math.round(edge.distance_m || 0))} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Nodes</span>
                            <span class="ride-value">${fmt.format(edge.node_count || 0)}</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Samples</span>
                            <span class="ride-value">${fmt.format(edge.profile_sample_count || 0)}</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Sample m</span>
                            <span class="ride-value">${escapeHtml(distances || "none")}</span>
                        </div>
                    </div>
                </article>
            `;
        }

        function renderRoadGraph(data) {
            const totals = data.totals || {};
            const edgeCount = totals.normalized_edges || 0;
            document.getElementById("roadGraphBadge").innerHTML = `<span class="dot ${edgeCount ? "good" : "wait"}"></span>${escapeHtml(data.model)}`;
            document.getElementById("roadGraphEdgeCount").textContent = fmt.format(edgeCount);
            document.getElementById("roadGraphIntersectionCount").textContent = fmt.format(totals.intersections || 0);
            document.getElementById("roadGraphReadyCount").textContent = `${fmt.format(totals.elevation_ready_edges || 0)}/${fmt.format(edgeCount)}`;
            document.getElementById("roadGraphModelCount").textContent = "v0";
            document.getElementById("roadGraphNote").textContent = edgeCount
                ? `${fmt.format(totals.ways || 0)} fixture ways normalized into ${fmt.format(edgeCount)} intersection-to-intersection edges. Coordinates and raw geometry are redacted from this payload.`
                : "No road graph edges are available yet.";
            const edges = (data.edges || []).map(renderRoadGraphEdge).join("");
            if (!edges) {
                document.getElementById("roadGraphList").outerHTML = `<div id="roadGraphList" class="empty">No road graph edges to show yet.</div>`;
                return;
            }
            document.getElementById("roadGraphList").outerHTML = `
                <div id="roadGraphList" class="signal-list">${edges}</div>
            `;
        }

        function renderRoadSignals(data) {
            const totals = data.totals || {};
            const bearing = totals.climb_bearing_edges || 0;
            document.getElementById("roadSignalBadge").innerHTML = `<span class="dot ${bearing ? "good" : "wait"}"></span>${escapeHtml(data.model)}`;
            document.getElementById("roadSignalCount").textContent = `${fmt.format(bearing)}/${fmt.format(totals.directed_edges_scored || 0)}`;
            document.getElementById("roadStringCount").textContent = fmt.format(totals.candidate_strings || 0);
            document.getElementById("roadBearingGain").textContent = `${fmt.format(Math.round(totals.total_climb_bearing_gain_m || 0))} m`;
            document.getElementById("roadModelCount").textContent = "v0";
            document.getElementById("roadSignalNote").textContent = bearing
                ? `${fmt.format(totals.fixture_edges || 0)} fixture road edges produced ${fmt.format(bearing)} directed climb-bearing edges and ${fmt.format(totals.candidate_strings || 0)} candidate strings. This is fixture model output, not official climb creation.`
                : "No fixture road edges passed the current climb-bearing threshold.";
            const strings = (data.candidate_strings || []).map(renderRoadStringRow).join("");
            const signals = (data.signals || [])
                .filter((signal) => signal.is_climb_bearing)
                .map(renderRoadSignalRow)
                .join("");
            if (!strings && !signals) {
                document.getElementById("roadSignalList").outerHTML = `<div id="roadSignalList" class="empty">No road-edge signals to show yet.</div>`;
                return;
            }
            document.getElementById("roadSignalList").outerHTML = `
                <div id="roadSignalList" class="signal-list">${strings}${signals}</div>
            `;
        }

        function renderPipelineCandidate(candidate) {
            const actions = (candidate.next_review_actions || [])
                .slice(0, 4)
                .map((action) => action.replaceAll("_", " "))
                .join(" · ");
            return `
                <article class="signal-row">
                    <div class="signal-main">
                        <div>
                            <span class="signal-name" title="${escapeHtml(candidate.candidate_id)}">${escapeHtml(candidate.display_name || candidate.candidate_id)}</span>
                            <span class="signal-meta">${escapeHtml(candidate.candidate_type)} · ${fmt.format(candidate.edge_count || 0)} edges · ${escapeHtml(candidate.result || "candidate")}</span>
                        </div>
                        <span class="confidence-chip ${escapeHtml(candidate.confidence || "exploratory")}">${escapeHtml(candidate.review_priority || "review")}</span>
                    </div>
                    <div class="signal-facts">
                        <div class="signal-fact">
                            <span class="ride-label">Gain</span>
                            <span class="gain-chip calibration">${fmt.format(candidate.gain_m || 0)} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Distance</span>
                            <span class="ride-value">${fmt.format(Math.round(candidate.distance_m || 0))} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Grade</span>
                            <span class="ride-value">${fmt.format(candidate.avg_grade_pct || 0)}%</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Review</span>
                            <span class="ride-value">${escapeHtml(actions || "open candidate")}</span>
                        </div>
                    </div>
                </article>
            `;
        }

        function renderReviewCandidate(candidate) {
            const preview = candidate.canon_publish_preview || {};
            const stateClass = reviewStateClass(candidate.review_state || candidate.review_decision);
            const stateLabel = reviewStateLabel(candidate);
            return `
                <button type="button" class="signal-row review-candidate-row ${stateClass}" data-candidate-id="${escapeHtml(candidate.candidate_id)}">
                    <div class="signal-main">
                        <div>
                            <span class="signal-name" title="${escapeHtml(candidate.candidate_id)}">${escapeHtml(candidate.display_name || candidate.candidate_id)}</span>
                            <span class="signal-meta">${escapeHtml(preview.gate_start_label || "start")} to ${escapeHtml(preview.gate_end_label || "finish")} · ${escapeHtml(preview.publish_status || "review")}</span>
                        </div>
                        <span class="confidence-chip ${stateClass}">${escapeHtml(stateLabel)}</span>
                    </div>
                    <div class="signal-facts">
                        <div class="signal-fact">
                            <span class="ride-label">Gain</span>
                            <span class="gain-chip calibration">${fmt.format(candidate.gain_m || 0)} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Distance</span>
                            <span class="ride-value">${fmt.format(Math.round(candidate.distance_m || 0))} m</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Grade</span>
                            <span class="ride-value">${fmt.format(candidate.avg_grade_pct || 0)}%</span>
                        </div>
                        <div class="signal-fact">
                            <span class="ride-label">Priority</span>
                            <span class="ride-value">${escapeHtml(candidate.review_priority || "review")}</span>
                        </div>
                    </div>
                </button>
            `;
        }

        function renderPipelineResults(data) {
            const totals = data.totals || {};
            const count = totals.candidate_climbs || 0;
            document.getElementById("pipelineResultBadge").innerHTML = `<span class="dot ${count ? "good" : "wait"}"></span>${escapeHtml(data.model)}`;
            document.getElementById("pipelineCandidateCount").textContent = fmt.format(count);
            document.getElementById("pipelineTopGain").textContent = `${fmt.format(Math.round(totals.top_candidate_gain_m || 0))} m`;
            document.getElementById("pipelineTotalGain").textContent = `${fmt.format(Math.round(totals.total_candidate_gain_m || 0))} m`;
            document.getElementById("pipelineStatus").textContent = escapeHtml((data.pipeline_status || "none").replaceAll("_", " "));
            document.getElementById("pipelineResultNote").textContent = count
                ? `${fmt.format(totals.road_edges || 0)} road edges and ${fmt.format(totals.climb_bearing_edges || 0)} climb-bearing directed edges produced ${fmt.format(count)} lab-only candidate climb results. Nothing here is promoted.`
                : "The current pipeline run did not produce candidate climb results.";
            const candidates = (data.candidates || []).map(renderPipelineCandidate).join("");
            if (!candidates) {
                document.getElementById("pipelineResultList").outerHTML = `<div id="pipelineResultList" class="empty">No pipeline candidates to show yet.</div>`;
                return;
            }
            document.getElementById("pipelineResultList").outerHTML = `
                <div id="pipelineResultList" class="signal-list">${candidates}</div>
            `;
        }

        function renderScanResults(data) {
            const totals = data.totals || {};
            const count = totals.candidate_climbs || 0;
            const error = data.pipeline_status === "scan_fetch_error";
            document.getElementById("scanResultBadge").innerHTML = `<span class="dot ${count ? "good" : error ? "none" : "wait"}"></span>${escapeHtml(data.pipeline_status || "scan")}`;
            document.getElementById("scanCandidateCount").textContent = fmt.format(count);
            document.getElementById("scanSelectedRoadCount").textContent = fmt.format(totals.selected_ways || 0);
            document.getElementById("scanElevationNodeCount").textContent = fmt.format(totals.elevation_attached_nodes || 0);
            document.getElementById("scanTopGain").textContent = `${fmt.format(Math.round(totals.top_candidate_gain_m || 0))} m`;
            const areaLabel = data.area_label || "Bounded scan";
            const fetchStatus = data.fetch_status || "unknown";
            const elevationStatus = totals.elevation_status || "unknown";
            document.getElementById("scanResultNote").textContent = error
                ? `The bounded scan did not complete: ${data.error || "unknown error"}`
                : `${areaLabel} ranked ${fmt.format(totals.scan_road_ways || 0)} named roads, selected ${fmt.format(totals.selected_ways || 0)} under a ${fmt.format(totals.max_elevation_nodes || 0)}-node elevation cap, and produced ${fmt.format(count)} lab-only candidates. Source: ${fetchStatus} / ${elevationStatus}.`;
            const candidates = (data.candidates || []).map(renderPipelineCandidate).join("");
            if (!candidates) {
                document.getElementById("scanResultList").outerHTML = `<div id="scanResultList" class="empty">No bounded scan candidates to show yet.</div>`;
                return;
            }
            document.getElementById("scanResultList").outerHTML = `
                <div id="scanResultList" class="signal-list">${candidates}</div>
            `;
        }

        function renderReviewResults(data) {
            const totals = data.totals || {};
            const contract = data.publish_contract || {};
            const count = totals.reviewable_candidates || 0;
            document.getElementById("reviewCandidateBadge").innerHTML = `<span class="dot ${count ? "good" : "wait"}"></span>${escapeHtml(data.pipeline_status || "review")}`;
            document.getElementById("reviewCandidateCount").textContent = fmt.format(count);
            document.getElementById("reviewApprovedCount").textContent = fmt.format(totals.approved_for_review || totals.approved_for_canon_climbs_v1 || 0);
            document.getElementById("reviewNeedsWorkCount").textContent = fmt.format(totals.needs_work || 0);
            document.getElementById("reviewSuppressedCount").textContent = fmt.format(totals.suppressed || 0);
            document.getElementById("reviewCandidateNote").textContent = count
                ? `${fmt.format(count)} candidates are ready for map and profile review. Decisions save locally; canon inserts stay behind the separate ${contract.schema_gate || "schema"} gate.`
                : "No candidates reached the review queue for this preset.";
            reviewCandidates = data.candidates || [];
            const candidates = (data.candidates || []).map(renderReviewCandidate).join("");
            if (!candidates) {
                document.getElementById("reviewCandidateList").outerHTML = `<div id="reviewCandidateList" class="empty">No review candidates to show yet.</div>`;
                return;
            }
            document.getElementById("reviewCandidateList").outerHTML = `
                <div id="reviewCandidateList" class="signal-list">${candidates}</div>
            `;
            document.querySelectorAll(".review-candidate-row").forEach((row) => {
                row.addEventListener("click", () => selectReviewCandidate(row.dataset.candidateId));
            });
            selectReviewCandidate(selectedReviewCandidateId || reviewCandidates[0]?.candidate_id);
        }

        async function loadClimbLab() {
            const [corpusResponse, calibrationResponse, signalResponse, roadGraphResponse, roadSignalResponse, pipelineResponse, scanResponse, reviewResponse] = await Promise.all([
                fetch("/dev/climb-lab/corpus", { headers: { "Accept": "application/json" } }),
                fetch("/dev/climb-lab/calibration?limit=18", { headers: { "Accept": "application/json" } }),
                fetch("/dev/climb-lab/elevation-signals?file_limit=12&signal_limit=12&min_gain_m=45", { headers: { "Accept": "application/json" } }),
                fetch("/dev/climb-lab/road-graph", { headers: { "Accept": "application/json" } }),
                fetch("/dev/climb-lab/road-signals", { headers: { "Accept": "application/json" } }),
                fetch("/dev/climb-lab/pipeline-results", { headers: { "Accept": "application/json" } }),
                fetch("/dev/climb-lab/scan-results?preset=boulder_foothills_north&max_ways=80&max_candidates=16&max_elevation_nodes=210", { headers: { "Accept": "application/json" } }),
                fetch(REVIEW_CANDIDATES_URL, { headers: { "Accept": "application/json" } }),
            ]);
            if (!corpusResponse.ok) throw new Error(`Corpus request failed: ${corpusResponse.status}`);
            if (!calibrationResponse.ok) throw new Error(`Calibration request failed: ${calibrationResponse.status}`);
            if (!signalResponse.ok) throw new Error(`Signal request failed: ${signalResponse.status}`);
            if (!roadGraphResponse.ok) throw new Error(`Road graph request failed: ${roadGraphResponse.status}`);
            if (!roadSignalResponse.ok) throw new Error(`Road signal request failed: ${roadSignalResponse.status}`);
            if (!pipelineResponse.ok) throw new Error(`Pipeline request failed: ${pipelineResponse.status}`);
            if (!scanResponse.ok) throw new Error(`Scan request failed: ${scanResponse.status}`);
            if (!reviewResponse.ok) throw new Error(`Review request failed: ${reviewResponse.status}`);
            const data = await corpusResponse.json();
            const calibration = await calibrationResponse.json();
            const signals = await signalResponse.json();
            const roadGraph = await roadGraphResponse.json();
            const roadSignals = await roadSignalResponse.json();
            const pipelineResults = await pipelineResponse.json();
            const scanResults = await scanResponse.json();
            const reviewResults = await reviewResponse.json();
            document.getElementById("scopeBadge").innerHTML = `<span class="dot good"></span>${data.scope}`;
            document.getElementById("activityCount").textContent = fmt.format(data.totals.activity_files);
            document.getElementById("sourceCount").textContent = `${data.totals.active_sources}/${data.totals.configured_sources}`;
            document.getElementById("sizeCount").textContent = bytesToHuman(data.totals.total_bytes);
            document.getElementById("candidateStatus").textContent = data.candidate_layer_status.replaceAll("_", " ");
            document.getElementById("activityMeaning").textContent = data.totals.activity_files > 0
                ? "Enough local evidence for the first calibration view."
                : "Mount or point ClimbLab at local activity files.";
            document.getElementById("currentSignal").textContent = data.totals.activity_files > 0
                ? `${fmt.format(data.totals.activity_files)} local activity files are visible as metadata-only evidence.`
                : "No local activity files are visible yet.";
            document.getElementById("sourceList").innerHTML = data.sources.map(renderSource).join("");
            document.getElementById("pipelineList").innerHTML = data.pipeline.map(renderStage).join("");
            document.getElementById("guardList").innerHTML = data.guardrails
                .map((guard) => `<div class="guard-card">${escapeHtml(guard)}</div>`)
                .join("");
            renderCalibration(calibration);
            renderSignals(signals);
            renderRoadGraph(roadGraph);
            renderRoadSignals(roadSignals);
            renderPipelineResults(pipelineResults);
            renderScanResults(scanResults);
            renderReviewResults(reviewResults);
        }

        document.querySelectorAll("[data-review-decision]").forEach((button) => {
            button.addEventListener("click", () => saveReviewDecision(button.dataset.reviewDecision));
        });
        window.addEventListener("resize", settleReviewMapLayout);
        setReviewDecisionSaving(false);

        loadClimbLab().catch((error) => {
            document.getElementById("scopeBadge").innerHTML = `<span class="dot none"></span>Error`;
            document.getElementById("sourceList").innerHTML = `<div class="empty">${error.message}</div>`;
        });
    </script>
</body>
</html>
"""


CLIMB_LAB_REVIEW_HTML = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>ClimbLab Review · Boulder Roller</title>
    <link
        rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        crossorigin=""
    >
    <style>
        :root {
            --bg: #0b0f12;
            --surface: #12181d;
            --surface-2: #182128;
            --line: rgba(203, 213, 225, 0.16);
            --line-strong: rgba(203, 213, 225, 0.28);
            --text: #ecf1f5;
            --muted: #96a3ad;
            --dim: #65737f;
            --accent: #f3a712;
            --approve: #46c486;
            --needs: #38a8e7;
            --suppress: #e05f5f;
            --radius: 8px;
        }

        * { box-sizing: border-box; }

        html,
        body {
            margin: 0;
            min-height: 100%;
            background: var(--bg);
            color: var(--text);
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            font-size: 14px;
            letter-spacing: 0;
        }

        body { overflow: hidden; }

        button,
        textarea {
            font: inherit;
        }

        a {
            color: inherit;
            text-decoration: none;
        }

        .app {
            display: grid;
            grid-template-rows: 64px minmax(0, 1fr);
            min-height: 100vh;
        }

        .topbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            border-bottom: 1px solid var(--line);
            background: rgba(11, 15, 18, 0.97);
            padding: 0 18px;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
            min-width: 0;
        }

        .mark {
            display: grid;
            place-items: center;
            width: 34px;
            height: 34px;
            border: 1px solid var(--line-strong);
            border-radius: 7px;
            color: var(--accent);
            font-weight: 800;
            background: #151b20;
        }

        h1 {
            margin: 0;
            font-size: 17px;
            line-height: 1.1;
            font-weight: 760;
        }

        .subtitle {
            display: block;
            margin-top: 3px;
            color: var(--muted);
            font-size: 12px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .nav-actions,
        .summary {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            justify-content: flex-end;
        }

        .link-button,
        .summary-pill {
            display: inline-flex;
            align-items: center;
            min-height: 32px;
            border: 1px solid var(--line);
            border-radius: 6px;
            background: #11171c;
            color: var(--text);
            padding: 0 10px;
            font-size: 12px;
        }

        .summary-pill strong {
            margin-right: 5px;
            color: #fff;
        }

        .review-layout {
            display: grid;
            grid-template-columns: minmax(312px, 380px) minmax(0, 1fr);
            min-height: 0;
            height: calc(100vh - 64px);
        }

        .queue-rail {
            display: grid;
            grid-template-rows: auto minmax(0, 1fr);
            min-height: 0;
            border-right: 1px solid var(--line);
            background: #0f1418;
        }

        .queue-head {
            border-bottom: 1px solid var(--line);
            padding: 14px;
        }

        .queue-title {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 10px;
        }

        .queue-title h2 {
            margin: 0;
            font-size: 13px;
            text-transform: uppercase;
            color: var(--muted);
            font-weight: 760;
        }

        .queue-status {
            color: var(--muted);
            font-size: 12px;
        }

        .progress-track {
            overflow: hidden;
            height: 7px;
            border-radius: 999px;
            background: #1d252b;
        }

        .progress-fill {
            width: 0%;
            height: 100%;
            background: linear-gradient(90deg, var(--approve), var(--accent));
        }

        .queue-list {
            min-height: 0;
            overflow: auto;
            padding: 10px;
        }

        .queue-row {
            width: 100%;
            appearance: none;
            display: grid;
            gap: 8px;
            border: 1px solid transparent;
            border-radius: 7px;
            background: transparent;
            color: inherit;
            text-align: left;
            padding: 11px 10px;
            cursor: pointer;
        }

        .queue-row:hover {
            background: rgba(255, 255, 255, 0.04);
        }

        .queue-row.active {
            border-color: rgba(243, 167, 18, 0.68);
            background: rgba(243, 167, 18, 0.11);
        }

        .queue-row.approve { border-left: 3px solid var(--approve); }
        .queue-row.needs_work { border-left: 3px solid var(--needs); }
        .queue-row.suppress { border-left: 3px solid var(--suppress); }
        .queue-row.pending { border-left: 3px solid rgba(150, 163, 173, 0.42); }

        .row-main {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            min-width: 0;
        }

        .row-name {
            display: block;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-weight: 720;
        }

        .row-index,
        .row-meta,
        .row-note {
            color: var(--muted);
            font-size: 12px;
            line-height: 1.35;
        }

        .row-note {
            color: #c1c9d0;
            overflow: hidden;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
        }

        .state-chip {
            flex: 0 0 auto;
            border: 1px solid var(--line);
            border-radius: 999px;
            padding: 3px 7px;
            color: var(--muted);
            font-size: 11px;
            line-height: 1;
            white-space: nowrap;
        }

        .state-chip.approve {
            border-color: rgba(70, 196, 134, 0.45);
            color: #9de5be;
        }

        .state-chip.needs_work {
            border-color: rgba(56, 168, 231, 0.45);
            color: #a6d9f6;
        }

        .state-chip.suppress {
            border-color: rgba(224, 95, 95, 0.42);
            color: #f1adad;
        }

        .detail-pane {
            display: grid;
            grid-template-rows: auto minmax(280px, 1fr) minmax(170px, 0.34fr) auto;
            min-width: 0;
            min-height: 0;
            background: #0b0f12;
        }

        .candidate-head {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 16px;
            border-bottom: 1px solid var(--line);
            padding: 16px 18px;
            background: #10161a;
            min-width: 0;
        }

        .candidate-title {
            min-width: 0;
        }

        .candidate-title h2 {
            margin: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-size: 24px;
            font-weight: 780;
        }

        .candidate-subtitle {
            margin-top: 5px;
            color: var(--muted);
            font-size: 13px;
        }

        .metrics {
            display: grid;
            grid-template-columns: repeat(4, minmax(82px, 1fr));
            gap: 8px;
            min-width: min(430px, 42vw);
        }

        .metric {
            border: 1px solid var(--line);
            border-radius: 7px;
            background: #12191e;
            padding: 8px 10px;
        }

        .metric span {
            display: block;
            color: var(--muted);
            font-size: 11px;
            margin-bottom: 3px;
        }

        .metric strong {
            font-size: 15px;
        }

        .map-wrap {
            min-height: 0;
            min-width: 0;
            border-bottom: 1px solid var(--line);
            background: #0e1317;
            padding: 12px;
        }

        .review-map {
            width: 100%;
            height: 100%;
            min-height: 280px;
            border: 1px solid var(--line-strong);
            border-radius: var(--radius);
            overflow: hidden;
            background: #111820;
        }

        .map-empty {
            display: grid;
            place-items: center;
            height: 100%;
            color: var(--muted);
            text-align: center;
            padding: 18px;
        }

        .profile-pane {
            min-height: 0;
            min-width: 0;
            border-bottom: 1px solid var(--line);
            background: #10161a;
            padding: 12px 18px 10px;
        }

        .profile-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: var(--muted);
            font-size: 12px;
            margin-bottom: 6px;
        }

        .profile-svg {
            display: block;
            width: 100%;
            height: calc(100% - 24px);
            min-height: 128px;
        }

        .decision-bar {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 14px;
            align-items: stretch;
            background: #0f1418;
            padding: 12px 18px;
            min-width: 0;
        }

        .note-field {
            width: 100%;
            min-height: 66px;
            resize: none;
            border: 1px solid var(--line);
            border-radius: 7px;
            background: #12191e;
            color: var(--text);
            padding: 10px 11px;
            line-height: 1.4;
        }

        .note-field:focus {
            outline: none;
            border-color: rgba(243, 167, 18, 0.7);
        }

        .decision-actions {
            display: grid;
            grid-template-columns: repeat(4, minmax(86px, 1fr));
            gap: 8px;
            align-content: start;
            min-width: 430px;
        }

        .decision-button {
            appearance: none;
            min-height: 66px;
            border: 1px solid var(--line);
            border-radius: 7px;
            background: #141b20;
            color: var(--text);
            cursor: pointer;
            font-weight: 760;
        }

        .decision-button:hover,
        .decision-button.active {
            border-color: rgba(243, 167, 18, 0.64);
            background: rgba(243, 167, 18, 0.11);
        }

        .decision-button.approve.active { border-color: var(--approve); }
        .decision-button.needs_work.active { border-color: var(--needs); }
        .decision-button.suppress.active { border-color: var(--suppress); }
        .decision-button:disabled { opacity: 0.5; cursor: not-allowed; }

        .save-state {
            grid-column: 1 / -1;
            min-height: 17px;
            color: var(--muted);
            font-size: 12px;
        }

        .leaflet-container {
            background: #111820;
            font-family: inherit;
            overflow: hidden;
            position: relative;
        }

        .leaflet-pane,
        .leaflet-tile,
        .leaflet-marker-icon,
        .leaflet-marker-shadow,
        .leaflet-tile-container,
        .leaflet-pane > svg,
        .leaflet-pane > canvas,
        .leaflet-zoom-box,
        .leaflet-image-layer,
        .leaflet-layer {
            position: absolute;
            left: 0;
            top: 0;
        }

        .leaflet-tile {
            width: 256px;
            height: 256px;
            user-select: none;
            -webkit-user-drag: none;
        }

        .leaflet-tile-pane { z-index: 200; }
        .leaflet-overlay-pane { z-index: 400; }
        .leaflet-shadow-pane { z-index: 500; }
        .leaflet-marker-pane { z-index: 600; }
        .leaflet-tooltip-pane { z-index: 650; }
        .leaflet-popup-pane { z-index: 700; }

        .leaflet-top,
        .leaflet-bottom {
            position: absolute;
            z-index: 1000;
            pointer-events: none;
        }

        .leaflet-top { top: 0; }
        .leaflet-bottom { bottom: 0; }
        .leaflet-left { left: 0; }
        .leaflet-right { right: 0; }
        .leaflet-control {
            position: relative;
            z-index: 800;
            pointer-events: auto;
        }

        .leaflet-control-attribution {
            font-size: 10px;
        }

        @media (max-width: 1100px) {
            .candidate-head { grid-template-columns: 1fr; }
            .metrics {
                min-width: 0;
                grid-template-columns: repeat(4, minmax(74px, 1fr));
            }
            .decision-bar { grid-template-columns: 1fr; }
            .decision-actions { min-width: 0; }
        }

        @media (max-width: 760px) {
            body { overflow: auto; }
            .app { min-height: auto; }
            .topbar { height: auto; min-height: 64px; padding: 12px 14px; align-items: flex-start; flex-direction: column; }
            .review-layout { grid-template-columns: 1fr; height: auto; }
            .queue-rail { border-right: 0; border-bottom: 1px solid var(--line); }
            .queue-list { max-height: 42vh; }
            .detail-pane { grid-template-rows: auto 430px 210px auto; }
        }

        @media (max-width: 560px) {
            .detail-pane { grid-template-rows: auto 340px 190px auto; }
            .candidate-title h2 { font-size: 20px; white-space: normal; }
            .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .decision-actions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .summary { justify-content: flex-start; }
        }
    </style>
</head>
<body>
    <div class="app">
        <header class="topbar">
            <div class="brand">
                <div class="mark">CL</div>
                <div>
                    <h1>ClimbLab Review</h1>
                    <span class="subtitle" id="sourceSubtitle">Loading candidate queue.</span>
                </div>
            </div>
            <div class="nav-actions">
                <div class="summary" id="summaryPills"></div>
                <a class="link-button" href="/dev/climb-lab">Lab</a>
                <a class="link-button" href="/dev/climb-lab/review-state">State</a>
            </div>
        </header>

        <main class="review-layout">
            <aside class="queue-rail">
                <div class="queue-head">
                    <div class="queue-title">
                        <h2>Queue</h2>
                        <span class="queue-status" id="queueStatus">Loading</span>
                    </div>
                    <div class="progress-track" aria-hidden="true">
                        <div class="progress-fill" id="progressFill"></div>
                    </div>
                </div>
                <div class="queue-list" id="queueList"></div>
            </aside>

            <section class="detail-pane">
                <header class="candidate-head">
                    <div class="candidate-title">
                        <h2 id="candidateName">Select a climb</h2>
                        <div class="candidate-subtitle" id="candidateSubtitle">Map and elevation profile load one candidate at a time.</div>
                    </div>
                    <div class="metrics">
                        <div class="metric"><span>Gain</span><strong id="metricGain">-</strong></div>
                        <div class="metric"><span>Distance</span><strong id="metricDistance">-</strong></div>
                        <div class="metric"><span>Grade</span><strong id="metricGrade">-</strong></div>
                        <div class="metric"><span>Score</span><strong id="metricScore">-</strong></div>
                    </div>
                </header>

                <div class="map-wrap">
                    <div class="review-map" id="reviewMap">
                        <div class="map-empty">Loading map.</div>
                    </div>
                </div>

                <div class="profile-pane">
                    <div class="profile-head">
                        <span id="profileLabel">Elevation profile</span>
                        <span id="detailMeta">No candidate selected</span>
                    </div>
                    <svg class="profile-svg" id="profileSvg" viewBox="0 0 900 180" role="img" aria-label="Selected candidate elevation profile"></svg>
                </div>

                <footer class="decision-bar">
                    <textarea id="decisionNote" class="note-field" maxlength="500" placeholder="Boundary note"></textarea>
                    <div class="decision-actions">
                        <button type="button" class="decision-button approve" data-decision="approve">Approve</button>
                        <button type="button" class="decision-button suppress" data-decision="suppress">Suppress</button>
                        <button type="button" class="decision-button needs_work" data-decision="needs_work">Needs work</button>
                        <button type="button" class="decision-button pending" data-decision="pending">Clear</button>
                        <div class="save-state" id="saveState"></div>
                    </div>
                </footer>
            </section>
        </main>
    </div>

    <script
        src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin=""
    ></script>
    <script>
        const fmt = new Intl.NumberFormat();
        const REVIEW_CANDIDATES_URL = "/dev/climb-lab/review-candidates?preset=philadelphia_manayunk_wall&max_ways=140&max_candidates=80&max_elevation_nodes=360";
        const decisionKeys = new Map([
            ["a", "approve"],
            ["s", "suppress"],
            ["w", "needs_work"],
            ["x", "pending"],
        ]);
        let candidates = [];
        let selectedId = null;
        let selectedDetail = null;
        let reviewMap = null;
        let lineLayer = null;
        let markersLayer = null;
        let reviewBounds = null;
        let saving = false;

        const escapeHtml = (value) => String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");

        function meters(value, digits = 0) {
            return `${fmt.format(Number(value || 0).toFixed(digits))} m`;
        }

        function grade(value) {
            return `${fmt.format(Number(value || 0).toFixed(1))}%`;
        }

        function decodePolyline(encoded) {
            const points = [];
            let index = 0;
            let lat = 0;
            let lng = 0;
            while (index < encoded.length) {
                let result = 0;
                let shift = 0;
                let byte = null;
                do {
                    byte = encoded.charCodeAt(index++) - 63;
                    result |= (byte & 0x1f) << shift;
                    shift += 5;
                } while (byte >= 0x20 && index < encoded.length);
                lat += (result & 1) ? ~(result >> 1) : (result >> 1);

                result = 0;
                shift = 0;
                do {
                    byte = encoded.charCodeAt(index++) - 63;
                    result |= (byte & 0x1f) << shift;
                    shift += 5;
                } while (byte >= 0x20 && index < encoded.length);
                lng += (result & 1) ? ~(result >> 1) : (result >> 1);
                points.push([lat / 1e5, lng / 1e5]);
            }
            return points;
        }

        function normalizedDecision(candidate) {
            const decision = String(candidate?.review_decision || "").toLowerCase();
            const state = String(candidate?.review_state || "").toLowerCase();
            if (decision === "approve" || state === "approved_for_review") return "approve";
            if (decision === "needs_work" || state === "needs_work") return "needs_work";
            if (decision === "suppress" || state === "suppressed") return "suppress";
            return "pending";
        }

        function decisionLabel(value) {
            if (value === "approve") return "Approved";
            if (value === "needs_work") return "Needs work";
            if (value === "suppress") return "Suppressed";
            return "Pending";
        }

        function activeIndex() {
            return candidates.findIndex((candidate) => candidate.candidate_id === selectedId);
        }

        function firstPendingIndex() {
            const index = candidates.findIndex((candidate) => normalizedDecision(candidate) === "pending");
            return index >= 0 ? index : 0;
        }

        function nextPendingIndex(fromIndex) {
            if (!candidates.length) return -1;
            for (let step = 1; step <= candidates.length; step += 1) {
                const index = (fromIndex + step) % candidates.length;
                if (normalizedDecision(candidates[index]) === "pending") return index;
            }
            return Math.min(fromIndex + 1, candidates.length - 1);
        }

        function setButtonsDisabled(disabled) {
            document.querySelectorAll("[data-decision]").forEach((button) => {
                button.disabled = disabled || !selectedId;
            });
        }

        function updateDecisionButtons(candidate) {
            const decision = normalizedDecision(candidate);
            document.querySelectorAll("[data-decision]").forEach((button) => {
                button.classList.toggle("active", button.dataset.decision === decision);
            });
        }

        function renderSummary(payload) {
            const totals = payload.totals || {};
            const decided = (totals.approved_for_review || 0) + (totals.needs_work || 0) + (totals.suppressed || 0);
            const total = totals.reviewable_candidates || candidates.length || 1;
            const pct = Math.max(0, Math.min(100, Math.round((decided / total) * 100)));
            const queued = payload.review_queue?.candidate_count || candidates.length;
            document.getElementById("summaryPills").innerHTML = `
                <span class="summary-pill"><strong>${fmt.format(total)}</strong> total</span>
                <span class="summary-pill"><strong>${fmt.format(totals.pending || 0)}</strong> pending</span>
                <span class="summary-pill"><strong>${fmt.format(totals.approved_for_review || 0)}</strong> approved</span>
                <span class="summary-pill"><strong>${fmt.format(totals.needs_work || 0)}</strong> work</span>
                <span class="summary-pill"><strong>${fmt.format(totals.suppressed || 0)}</strong> suppressed</span>
            `;
            document.getElementById("queueStatus").textContent = `${fmt.format(queued)} queued · ${pct}% decided`;
            document.getElementById("progressFill").style.width = `${pct}%`;
            document.getElementById("sourceSubtitle").textContent = `${payload.area_label || "Local compile report"} · ${payload.pipeline_status || "review"}`;
        }

        function renderQueue() {
            if (!candidates.length) {
                document.getElementById("queueList").innerHTML = `<div class="queue-row">No review candidates.</div>`;
                return;
            }
            document.getElementById("queueList").innerHTML = candidates.map((candidate, index) => {
                const decision = normalizedDecision(candidate);
                const note = candidate.review_note ? `<div class="row-note">${escapeHtml(candidate.review_note)}</div>` : "";
                const carry = candidate.review_carry?.requires_recheck ? " · boundary changed" : "";
                return `
                    <button type="button" class="queue-row ${decision} ${candidate.candidate_id === selectedId ? "active" : ""}" data-candidate-id="${escapeHtml(candidate.candidate_id)}">
                        <div class="row-main">
                            <span class="row-name" title="${escapeHtml(candidate.display_name || candidate.candidate_id)}">${escapeHtml(candidate.display_name || candidate.candidate_id)}</span>
                            <span class="state-chip ${decision}">${decisionLabel(decision)}</span>
                        </div>
                        <div class="row-meta">${index + 1} · ${meters(candidate.gain_m)} gain · ${grade(candidate.avg_grade_pct)} · ${escapeHtml(candidate.review_priority || "review")}${carry}</div>
                        ${note}
                    </button>
                `;
            }).join("");
            document.querySelectorAll(".queue-row[data-candidate-id]").forEach((row) => {
                row.addEventListener("click", () => selectCandidate(row.dataset.candidateId));
            });
        }

        function ensureMap() {
            const mapElement = document.getElementById("reviewMap");
            if (!window.L) {
                mapElement.innerHTML = `<div class="map-empty">Map library did not load.</div>`;
                return null;
            }
            if (reviewMap) return reviewMap;
            mapElement.innerHTML = "";
            reviewMap = L.map(mapElement, {
                zoomControl: true,
                scrollWheelZoom: true,
            });
            L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
                attribution: "&copy; OpenStreetMap contributors",
            }).addTo(reviewMap);
            lineLayer = L.layerGroup().addTo(reviewMap);
            markersLayer = L.layerGroup().addTo(reviewMap);
            return reviewMap;
        }

        function settleMapLayout() {
            if (!reviewMap) return;
            reviewMap.invalidateSize();
            if (reviewBounds && reviewBounds.isValid()) {
                reviewMap.fitBounds(reviewBounds, { padding: [34, 34] });
            }
        }

        function gradeColor(localGrade) {
            if (localGrade >= 14) return "#e05f5f";
            if (localGrade >= 9) return "#f3a712";
            if (localGrade >= 5) return "#46c486";
            return "#38a8e7";
        }

        function renderMap(detail) {
            const map = ensureMap();
            if (!map) return;
            lineLayer.clearLayers();
            markersLayer.clearLayers();
            const encoded = detail.geometry?.centerline_polyline || "";
            const points = encoded ? decodePolyline(encoded) : [];
            if (points.length < 2) {
                document.getElementById("detailMeta").textContent = "No geometry for this candidate.";
                return;
            }
            reviewBounds = L.latLngBounds(points);
            const profile = (detail.profile?.points || []).filter((point) => Number.isFinite(point.dist_m) && Number.isFinite(point.elev_m));
            L.polyline(points, {
                color: "#0b0f12",
                weight: 12,
                opacity: 0.88,
                interactive: false,
                lineCap: "round",
                lineJoin: "round",
            }).addTo(lineLayer);
            L.polyline(points, {
                color: "#f3a712",
                weight: 8,
                opacity: 0.96,
                interactive: false,
                lineCap: "round",
                lineJoin: "round",
            }).addTo(lineLayer);
            for (let index = 1; index < points.length; index += 1) {
                const priorProfile = profile[Math.min(index - 1, profile.length - 1)] || {};
                const nextProfile = profile[Math.min(index, profile.length - 1)] || {};
                const distDelta = Math.max((nextProfile.dist_m || 0) - (priorProfile.dist_m || 0), 1);
                const elevDelta = (nextProfile.elev_m || 0) - (priorProfile.elev_m || 0);
                const localGrade = (elevDelta / distDelta) * 100;
                L.polyline([points[index - 1], points[index]], {
                    color: gradeColor(localGrade),
                    weight: 5,
                    opacity: 0.95,
                    interactive: false,
                    lineCap: "round",
                }).addTo(lineLayer);
            }
            L.circleMarker(points[0], {
                radius: 7,
                color: "#0b0f12",
                fillColor: "#46c486",
                fillOpacity: 1,
                weight: 2,
            }).addTo(markersLayer);
            L.circleMarker(points[points.length - 1], {
                radius: 7,
                color: "#0b0f12",
                fillColor: "#38a8e7",
                fillOpacity: 1,
                weight: 2,
            }).addTo(markersLayer);
            settleMapLayout();
            requestAnimationFrame(settleMapLayout);
            setTimeout(settleMapLayout, 240);
        }

        function renderProfile(detail) {
            const svg = document.getElementById("profileSvg");
            const points = (detail.profile?.points || []).filter((point) => Number.isFinite(point.dist_m) && Number.isFinite(point.elev_m));
            if (points.length < 2) {
                svg.innerHTML = `<text x="24" y="92" fill="#96a3ad">No profile points available.</text>`;
                return;
            }
            const width = 900;
            const height = 180;
            const padX = 34;
            const padY = 22;
            const maxDist = Math.max(...points.map((point) => point.dist_m), 1);
            const minElev = Math.min(...points.map((point) => point.elev_m));
            const maxElev = Math.max(...points.map((point) => point.elev_m));
            const elevRange = Math.max(maxElev - minElev, 1);
            const coords = points.map((point) => {
                const x = padX + (point.dist_m / maxDist) * (width - padX * 2);
                const y = height - padY - ((point.elev_m - minElev) / elevRange) * (height - padY * 2);
                return [x, y];
            });
            const path = coords.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
            const fillPath = `${path} L${(width - padX).toFixed(1)} ${(height - padY).toFixed(1)} L${padX} ${(height - padY).toFixed(1)} Z`;
            svg.innerHTML = `
                <path d="${fillPath}" fill="rgba(243,167,18,0.14)"></path>
                <path d="${path}" fill="none" stroke="#f3a712" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"></path>
                <line x1="${padX}" y1="${height - padY}" x2="${width - padX}" y2="${height - padY}" stroke="rgba(255,255,255,0.18)"></line>
                <text x="${padX}" y="17" fill="#96a3ad">${meters(minElev)}</text>
                <text x="${width - padX - 96}" y="17" fill="#96a3ad">${meters(maxElev)}</text>
                <text x="${padX}" y="${height - 4}" fill="#65737f">0 m</text>
                <text x="${width - padX - 88}" y="${height - 4}" fill="#65737f">${meters(maxDist)}</text>
            `;
            document.getElementById("profileLabel").textContent = `${meters(maxElev - minElev)} gain over ${meters(maxDist)}`;
        }

        function renderDetail(candidate, detail = null) {
            document.getElementById("candidateName").textContent = candidate?.display_name || "Select a climb";
            document.getElementById("candidateSubtitle").textContent = candidate
                ? `${escapeHtml(candidate.canon_publish_preview?.gate_start_label || candidate.from_intersection || "start")} to ${escapeHtml(candidate.canon_publish_preview?.gate_end_label || candidate.to_intersection || "finish")}`
                : "Map and elevation profile load one candidate at a time.";
            document.getElementById("metricGain").textContent = candidate ? meters(candidate.gain_m) : "-";
            document.getElementById("metricDistance").textContent = candidate ? meters(candidate.distance_m) : "-";
            document.getElementById("metricGrade").textContent = candidate ? grade(candidate.avg_grade_pct) : "-";
            document.getElementById("metricScore").textContent = candidate ? fmt.format(Number(candidate.worthiness_score || 0).toFixed(1)) : "-";
            document.getElementById("decisionNote").value = candidate?.review_note || "";
            document.getElementById("saveState").textContent = candidate?.review_updated_at ? `Saved ${new Date(candidate.review_updated_at).toLocaleString()}` : "";
            updateDecisionButtons(candidate);
            if (detail) {
                const preview = detail.candidate?.canon_publish_preview || {};
                document.getElementById("detailMeta").textContent = `${detail.privacy_mode || "detail"} · ${fmt.format(detail.profile?.sample_count || 0)} samples · ${fmt.format(preview.corridor_cell_count || 0)} cells`;
            }
        }

        async function loadDetail(candidateId) {
            document.getElementById("detailMeta").textContent = "Loading detail.";
            const response = await fetch(`/dev/climb-lab/review-candidates/${encodeURIComponent(candidateId)}/map-detail`, {
                headers: { "Accept": "application/json" },
            });
            if (!response.ok) throw new Error(`Detail failed: ${response.status}`);
            return response.json();
        }

        async function selectCandidate(candidateId, options = {}) {
            if (!candidateId || saving) return;
            selectedId = candidateId;
            const candidate = candidates.find((item) => item.candidate_id === candidateId);
            setButtonsDisabled(true);
            renderQueue();
            renderDetail(candidate);
            const selectedRow = document.querySelector(`.queue-row[data-candidate-id="${CSS.escape(candidateId)}"]`);
            if (selectedRow && !options.skipScroll) {
                selectedRow.scrollIntoView({ block: "nearest" });
            }
            try {
                selectedDetail = await loadDetail(candidateId);
                const detailCandidate = selectedDetail.candidate || candidate;
                const index = candidates.findIndex((item) => item.candidate_id === candidateId);
                if (index >= 0) candidates[index] = { ...candidates[index], ...detailCandidate };
                renderDetail(candidates[index], selectedDetail);
                renderMap(selectedDetail);
                renderProfile(selectedDetail);
                setButtonsDisabled(false);
            } catch (error) {
                setButtonsDisabled(true);
                document.getElementById("detailMeta").textContent = error.message;
            }
        }

        function selectRelative(direction) {
            if (!candidates.length) return;
            const current = activeIndex();
            const next = Math.max(0, Math.min(candidates.length - 1, current + direction));
            selectCandidate(candidates[next]?.candidate_id);
        }

        async function loadQueue(preserveSelection = true) {
            const response = await fetch(REVIEW_CANDIDATES_URL, {
                headers: { "Accept": "application/json" },
            });
            if (!response.ok) throw new Error(`Queue failed: ${response.status}`);
            const payload = await response.json();
            const allCandidates = payload.candidates || [];
            const byId = new Map(allCandidates.map((candidate) => [candidate.candidate_id, candidate]));
            const queueIds = payload.review_queue?.candidate_ids || [];
            candidates = queueIds.length
                ? queueIds.map((candidateId) => byId.get(candidateId)).filter(Boolean)
                : allCandidates;
            renderSummary(payload);
            const existing = preserveSelection && candidates.find((candidate) => candidate.candidate_id === selectedId);
            selectedId = existing?.candidate_id || candidates[firstPendingIndex()]?.candidate_id || candidates[0]?.candidate_id || null;
            renderQueue();
            if (selectedId) await selectCandidate(selectedId, { skipScroll: true });
        }

        async function saveDecision(decision, autoAdvance = true) {
            if (!selectedId || saving) return;
            saving = true;
            setButtonsDisabled(true);
            const currentIndex = activeIndex();
            const note = document.getElementById("decisionNote").value.trim();
            document.getElementById("saveState").textContent = "Saving.";
            try {
                const response = await fetch(`/dev/climb-lab/review-candidates/${encodeURIComponent(selectedId)}/decision`, {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({ decision, note }),
                });
                if (!response.ok) {
                    const error = await response.text();
                    throw new Error(`Decision failed: ${response.status} ${error}`);
                }
                const result = await response.json();
                const index = candidates.findIndex((candidate) => candidate.candidate_id === selectedId);
                if (index >= 0) {
                    candidates[index] = {
                        ...candidates[index],
                        review_decision: result.decision,
                        review_decision_label: result.decision_label,
                        review_state: result.review_state,
                        review_note: result.note,
                        review_updated_at: result.updated_at,
                    };
                }
                renderQueue();
                renderDetail(candidates[index], selectedDetail);
                document.getElementById("saveState").textContent = "Saved.";
                if (autoAdvance && decision !== "pending" && candidates.length) {
                    const nextIndex = nextPendingIndex(currentIndex);
                    const nextCandidate = candidates[nextIndex];
                    if (nextCandidate?.candidate_id && nextCandidate.candidate_id !== selectedId) {
                        await selectCandidate(nextCandidate.candidate_id);
                    }
                }
                loadQueue(true).catch(() => {});
            } catch (error) {
                document.getElementById("saveState").textContent = error.message;
            } finally {
                saving = false;
                setButtonsDisabled(false);
            }
        }

        document.querySelectorAll("[data-decision]").forEach((button) => {
            button.addEventListener("click", () => saveDecision(button.dataset.decision, true));
        });

        document.addEventListener("keydown", (event) => {
            const target = event.target;
            const isTextEntry = target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement || target?.isContentEditable;
            if (isTextEntry) {
                if (event.key === "Escape") {
                    target.blur();
                    event.preventDefault();
                }
                return;
            }
            if (event.key === "j" || event.key === "ArrowDown") {
                event.preventDefault();
                selectRelative(1);
                return;
            }
            if (event.key === "k" || event.key === "ArrowUp") {
                event.preventDefault();
                selectRelative(-1);
                return;
            }
            if (event.key === "n") {
                event.preventDefault();
                document.getElementById("decisionNote").focus();
                return;
            }
            const decision = decisionKeys.get(event.key.toLowerCase());
            if (decision) {
                event.preventDefault();
                saveDecision(decision, true);
            }
        });

        window.addEventListener("resize", settleMapLayout);
        setButtonsDisabled(true);
        loadQueue(false).catch((error) => {
            document.getElementById("queueStatus").textContent = "Error";
            document.getElementById("queueList").innerHTML = `<div class="queue-row">${escapeHtml(error.message)}</div>`;
            document.getElementById("detailMeta").textContent = error.message;
        });
    </script>
</body>
</html>
"""
