"""
Dev Dashboard v3 - Cartographic Mission Control
Modern tile visualization and pattern testing environment with full interactivity.

Features:
- Interactive elevation profile (Chart.js) synced with map
- Pattern cards with click-to-zoom
- Tile click for road attribution
- Road overlay from OSM database
- Multi-file support with per-file toggles
- Algorithm Debug Panel - shows WHY climbs were detected
- Rejected Segments Panel - shows near-misses
- Gradient Overlay on elevation profile
"""

DASHBOARD_HTML_V3 = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tile Mission Control · Boulder Roller</title>

    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

    <!-- Leaflet -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <!-- Leaflet.Editable for rectangle editing -->
    <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.editable/1.3.0/Leaflet.Editable.min.js"></script>

    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>

    <style>
        /* ============================================
           CSS CUSTOM PROPERTIES - CARTOGRAPHIC THEME
           ============================================ */
        :root {
            --font-mono: 'Berkeley Mono', 'JetBrains Mono', 'Fira Code', monospace;

            /* Base colors */
            --bg-primary: #0a0f14;
            --bg-secondary: #111820;
            --bg-tertiary: #1a232e;
            --bg-elevated: #212d3b;

            /* Contour pattern */
            --contour-line: rgba(255, 255, 255, 0.04);

            /* Text */
            --text-primary: #e8edf3;
            --text-secondary: #8b9bb0;
            --text-tertiary: #5a6a7d;
            --text-label: #4a5a6d;

            /* Accent colors */
            --accent-climb: #f59e0b;
            --accent-climb-soft: rgba(245, 158, 11, 0.15);
            --accent-steady: #06b6d4;
            --accent-steady-soft: rgba(6, 182, 212, 0.15);
            --accent-explore: #8b5cf6;
            --accent-explore-soft: rgba(139, 92, 246, 0.15);
            --accent-tile: #22d3ee;
            --accent-road: #34d399;
            --accent-track: #f472b6;
            --accent-rejected: #ef4444;
            --accent-rejected-soft: rgba(239, 68, 68, 0.15);

            /* Status */
            --success: #10b981;
            --warning: #f59e0b;
            --error: #ef4444;

            /* Borders */
            --border-subtle: rgba(255, 255, 255, 0.06);
            --border-default: rgba(255, 255, 255, 0.1);
            --border-strong: rgba(255, 255, 255, 0.15);

            /* Spacing */
            --space-xs: 4px;
            --space-sm: 8px;
            --space-md: 12px;
            --space-lg: 16px;
            --space-xl: 24px;

            /* Radius */
            --radius-sm: 4px;
            --radius-md: 6px;
            --radius-lg: 8px;

            /* Shadows */
            --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
            --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
        }

        /* ============================================
           BASE
           ============================================ */
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; overflow: hidden; }

        body {
            font-family: var(--font-mono);
            font-size: 13px;
            line-height: 1.5;
            color: var(--text-primary);
            background: var(--bg-primary);
            -webkit-font-smoothing: antialiased;
        }

        body::before {
            content: '';
            position: fixed;
            inset: 0;
            background:
                repeating-linear-gradient(0deg, var(--contour-line) 0px, var(--contour-line) 1px, transparent 1px, transparent 40px),
                repeating-linear-gradient(90deg, var(--contour-line) 0px, var(--contour-line) 1px, transparent 1px, transparent 40px);
            pointer-events: none;
            z-index: 0;
        }

        /* ============================================
           LAYOUT
           ============================================ */
        .app {
            display: grid;
            grid-template-rows: auto 1fr 180px;
            height: 100vh;
            height: 100dvh;
            position: relative;
            z-index: 1;
        }

        .main-content {
            display: grid;
            grid-template-columns: 320px 1fr 400px;
            gap: 1px;
            background: var(--border-subtle);
            overflow: hidden;
            min-height: 0;
        }

        /* ============================================
           HEADER
           ============================================ */
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--space-md) var(--space-xl);
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-subtle);
        }

        .header-left {
            display: flex;
            align-items: center;
            gap: var(--space-lg);
        }

        .logo {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            font-weight: 600;
            font-size: 14px;
        }

        .logo-icon {
            width: 28px;
            height: 28px;
            background: linear-gradient(135deg, var(--accent-climb) 0%, var(--accent-tile) 100%);
            border-radius: var(--radius-md);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
        }

        .system-badge {
            font-size: 10px;
            font-weight: 500;
            color: var(--text-tertiary);
            background: var(--bg-tertiary);
            padding: 2px 8px;
            border-radius: 99px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .dev-link {
            font-size: 11px;
            color: var(--text-secondary);
            text-decoration: none;
            border: 1px solid var(--border-default);
            border-radius: var(--radius-sm);
            padding: 4px 8px;
            background: rgba(255, 255, 255, 0.03);
        }

        .dev-link:hover {
            color: var(--text-primary);
            border-color: var(--accent-climb);
        }

        .header-stats {
            display: flex;
            gap: var(--space-xl);
        }

        .stat-item {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
        }

        .stat-value {
            font-size: 18px;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }

        .stat-label {
            font-size: 10px;
            color: var(--text-tertiary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        /* ============================================
           CONTROL PANEL
           ============================================ */
        .control-panel {
            background: var(--bg-secondary);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .panel-section {
            padding: var(--space-lg);
            border-bottom: 1px solid var(--border-subtle);
            flex-shrink: 0;
        }

        .panel-section.scrollable {
            flex: 1;
            overflow-y: auto;
            min-height: 0;
        }

        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: var(--space-md);
        }

        .section-title {
            font-size: 10px;
            font-weight: 600;
            color: var(--text-tertiary);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        .section-badge {
            font-size: 10px;
            color: var(--text-label);
            background: var(--bg-tertiary);
            padding: 2px 6px;
            border-radius: var(--radius-sm);
        }

        /* Upload Zone */
        .upload-zone {
            border: 2px dashed var(--border-default);
            border-radius: var(--radius-lg);
            padding: var(--space-xl);
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            background: var(--bg-tertiary);
        }

        .upload-zone:hover, .upload-zone.dragover {
            border-color: var(--accent-tile);
            background: rgba(34, 211, 238, 0.05);
        }

        .upload-icon { font-size: 32px; margin-bottom: var(--space-sm); opacity: 0.6; }
        .upload-text { font-size: 12px; color: var(--text-secondary); }
        .upload-hint { font-size: 10px; color: var(--text-tertiary); margin-top: var(--space-xs); }

        /* File List */
        .file-list {
            display: flex;
            flex-direction: column;
            gap: var(--space-sm);
            max-height: 160px;
            overflow-y: auto;
            margin-top: var(--space-md);
        }

        .file-item {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            padding: var(--space-sm) var(--space-md);
            background: var(--bg-tertiary);
            border-radius: var(--radius-md);
            cursor: pointer;
            border: 1px solid transparent;
            transition: all 0.15s ease;
        }

        .file-item:hover { background: var(--bg-elevated); }
        .file-item.active { border-color: var(--accent-tile); background: rgba(34, 211, 238, 0.1); }

        .file-color { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
        .file-name { flex: 1; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .file-meta { font-size: 10px; color: var(--text-tertiary); }
        .file-remove { opacity: 0; color: var(--text-tertiary); cursor: pointer; transition: all 0.15s ease; }
        .file-item:hover .file-remove { opacity: 1; }
        .file-remove:hover { color: var(--error); }

        /* Threshold Controls */
        .threshold-group { margin-bottom: var(--space-lg); }
        .threshold-group:last-child { margin-bottom: 0; }

        .threshold-header {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            margin-bottom: var(--space-md);
        }

        .threshold-icon {
            width: 20px;
            height: 20px;
            border-radius: var(--radius-sm);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
        }

        .threshold-icon.climb { background: var(--accent-climb-soft); color: var(--accent-climb); }
        .threshold-icon.explore { background: var(--accent-explore-soft); color: var(--accent-explore); }

        .threshold-label { font-size: 11px; font-weight: 500; color: var(--text-secondary); }

        .control-row {
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: center;
            gap: var(--space-md);
            margin-bottom: var(--space-sm);
        }

        .control-label { font-size: 10px; color: var(--text-tertiary); }
        .control-value {
            font-size: 11px;
            font-weight: 500;
            background: var(--bg-tertiary);
            padding: 2px 8px;
            border-radius: var(--radius-sm);
            min-width: 60px;
            text-align: center;
            font-variant-numeric: tabular-nums;
        }

        input[type="range"] {
            width: 100%;
            height: 4px;
            background: var(--bg-tertiary);
            border-radius: 2px;
            appearance: none;
            cursor: pointer;
            margin-bottom: var(--space-sm);
        }

        input[type="range"]::-webkit-slider-thumb {
            appearance: none;
            width: 14px;
            height: 14px;
            background: var(--accent-tile);
            border-radius: 50%;
            cursor: pointer;
        }

        /* Algorithm Toggle */
        .algo-toggle-row {
            display: flex;
            gap: 6px;
            margin-bottom: var(--space-sm);
        }
        .algo-btn {
            flex: 1;
            padding: 6px 10px;
            font-size: 10px;
            font-weight: 500;
            font-family: var(--font-mono);
            background: var(--bg-tertiary);
            border: 1px solid var(--border-default);
            border-radius: var(--radius-sm);
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.15s ease;
        }
        .algo-btn:hover {
            background: var(--bg-elevated);
            border-color: var(--border-strong);
        }
        .algo-btn.active {
            background: var(--accent-climb);
            color: #000;
            border-color: var(--accent-climb);
        }

        /* Resolution Select */
        select {
            width: 100%;
            padding: var(--space-sm) var(--space-md);
            background: var(--bg-tertiary);
            border: 1px solid var(--border-default);
            border-radius: var(--radius-md);
            color: var(--text-primary);
            font-family: var(--font-mono);
            font-size: 11px;
            cursor: pointer;
        }

        /* Buttons */
        .actions { display: flex; flex-direction: column; gap: var(--space-sm); }

        .btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: var(--space-sm);
            padding: var(--space-md) var(--space-lg);
            border: none;
            border-radius: var(--radius-md);
            font-family: var(--font-mono);
            font-size: 11px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-primary { background: var(--accent-tile); color: var(--bg-primary); }
        .btn-primary:hover { background: #67e8f9; }
        .btn-secondary { background: var(--bg-tertiary); color: var(--text-secondary); border: 1px solid var(--border-default); }
        .btn-secondary:hover { background: var(--bg-elevated); color: var(--text-primary); }

        /* ============================================
           MAP VIEW
           ============================================ */
        .map-container {
            position: relative;
            background: var(--bg-primary);
        }

        #map { width: 100%; height: 100%; }

        .map-controls {
            position: absolute;
            top: var(--space-lg);
            left: var(--space-lg);
            display: flex;
            flex-direction: column;
            gap: var(--space-sm);
            z-index: 1000;
        }

        .map-toggle {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            padding: var(--space-sm) var(--space-md);
            background: var(--bg-secondary);
            border: 1px solid var(--border-default);
            border-radius: var(--radius-md);
            font-size: 11px;
            color: var(--text-secondary);
            cursor: pointer;
            box-shadow: var(--shadow-md);
            transition: all 0.15s ease;
        }

        .map-toggle:hover { background: var(--bg-tertiary); color: var(--text-primary); }
        .map-toggle.active { background: var(--bg-tertiary); border-color: var(--accent-tile); color: var(--accent-tile); }

        .toggle-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--text-tertiary);
        }

        .map-toggle.active .toggle-indicator {
            background: var(--accent-tile);
            box-shadow: 0 0 8px var(--accent-tile);
        }

        .map-coords {
            position: absolute;
            bottom: var(--space-lg);
            left: var(--space-lg);
            padding: var(--space-sm) var(--space-md);
            background: var(--bg-secondary);
            border: 1px solid var(--border-subtle);
            border-radius: var(--radius-md);
            font-size: 10px;
            color: var(--text-tertiary);
            font-variant-numeric: tabular-nums;
            box-shadow: var(--shadow-sm);
            z-index: 1000;
        }

        /* Tile Popup */
        .tile-popup {
            font-family: var(--font-mono);
            font-size: 11px;
        }

        .tile-popup .tile-id {
            font-size: 9px;
            color: var(--text-tertiary);
            margin-bottom: 4px;
            word-break: break-all;
        }

        .tile-popup .road-name {
            font-weight: 600;
            color: var(--accent-road);
            margin-bottom: 2px;
        }

        .tile-popup .road-info {
            color: var(--text-secondary);
        }

        /* ============================================
           PATTERN INSPECTOR
           ============================================ */
        .inspector {
            background: var(--bg-secondary);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .inspector-header {
            padding: var(--space-lg);
            border-bottom: 1px solid var(--border-subtle);
            flex-shrink: 0;
        }

        .inspector-title { font-size: 12px; font-weight: 600; margin-bottom: var(--space-xs); }
        .inspector-subtitle { font-size: 10px; color: var(--text-tertiary); }

        /* Tab Navigation */
        .inspector-tabs {
            display: flex;
            border-bottom: 1px solid var(--border-subtle);
            background: var(--bg-tertiary);
            flex-shrink: 0;
        }

        .inspector-tab {
            flex: 1;
            padding: var(--space-sm) var(--space-md);
            font-size: 10px;
            font-weight: 500;
            text-align: center;
            color: var(--text-tertiary);
            background: transparent;
            border: none;
            cursor: pointer;
            transition: all 0.15s ease;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .inspector-tab:hover { color: var(--text-secondary); background: var(--bg-elevated); }
        .inspector-tab.active { color: var(--accent-tile); background: var(--bg-secondary); border-bottom: 2px solid var(--accent-tile); }

        .inspector-tab .tab-count {
            margin-left: 4px;
            font-size: 9px;
            background: var(--bg-elevated);
            padding: 1px 5px;
            border-radius: 8px;
        }

        .inspector-tab.active .tab-count { background: rgba(34, 211, 238, 0.2); }

        /* Tab Content */
        .tab-content {
            display: none;
            flex: 1;
            overflow-y: auto;
            min-height: 0;
        }

        .tab-content.active { display: flex; flex-direction: column; }

        .pattern-list {
            flex: 1;
            overflow-y: auto;
            padding: var(--space-md);
            display: flex;
            flex-direction: column;
            gap: var(--space-md);
        }

        /* Pattern Card */
        .pattern-card {
            background: var(--bg-tertiary);
            border-radius: var(--radius-lg);
            border: 1px solid var(--border-subtle);
            overflow: hidden;
            cursor: pointer;
            transition: all 0.15s ease;
            flex-shrink: 0;
        }

        .pattern-card:hover { border-color: var(--border-default); box-shadow: var(--shadow-sm); }
        .pattern-card.selected { border-color: var(--accent-tile); box-shadow: 0 0 0 1px var(--accent-tile); }

        .pattern-header {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            padding: var(--space-md);
            border-bottom: 1px solid var(--border-subtle);
            flex-wrap: wrap;
        }

        .pattern-type {
            display: flex;
            align-items: center;
            gap: var(--space-xs);
            font-size: 11px;
            font-weight: 600;
            flex: 1;
            min-width: 0;
        }

        .pattern-type.climb { color: var(--accent-climb); }
        .pattern-type.steady { color: var(--accent-steady); }
        .pattern-type.explore { color: var(--accent-explore); }
        .pattern-type.rejected { color: var(--accent-rejected); }

        /* Vault edit button */
        .vault-edit-btn {
            background: transparent;
            border: 1px solid var(--border-subtle);
            border-radius: 4px;
            color: var(--text-secondary);
            cursor: pointer;
            padding: 2px 6px;
            font-size: 12px;
            transition: all 0.15s;
            flex-shrink: 0;
        }
        .vault-edit-btn:hover {
            background: var(--bg-elevated);
            border-color: var(--text-secondary);
            color: var(--text-primary);
        }
        .pattern-card.editing {
            background: rgba(250, 204, 21, 0.1);
        }
        .pattern-card.editing .vault-edit-btn {
            background: #facc15;
            border-color: #facc15;
            color: #000;
        }

        /* Vault edit corner handles */
        .vault-edit-corner {
            width: 16px !important;
            height: 16px !important;
            background: #facc15;
            border: 2px solid #000;
            border-radius: 3px;
            cursor: move;
            box-shadow: 0 2px 6px rgba(0,0,0,0.5);
        }
        .vault-edit-corner:hover {
            background: #fde047;
            transform: scale(1.2);
        }

        .pattern-time {
            font-size: 10px;
            color: var(--text-tertiary);
            font-variant-numeric: tabular-nums;
            flex-shrink: 0;
        }

        .pattern-body { padding: var(--space-md); }

        .pattern-metrics {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: var(--space-sm);
            margin-bottom: var(--space-md);
        }

        .metric { display: flex; flex-direction: column; min-width: 0; }
        .metric-value { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; }
        .metric-label { font-size: 9px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }

        /* Road Attribution */
        .attribution {
            background: var(--bg-elevated);
            border-radius: var(--radius-md);
            padding: var(--space-md);
            border-left: 3px solid var(--accent-road);
        }

        .attribution-header {
            display: flex;
            align-items: center;
            gap: var(--space-sm);
            margin-bottom: var(--space-sm);
        }

        .attribution-label { font-size: 9px; color: var(--text-tertiary); text-transform: uppercase; letter-spacing: 0.05em; }
        .attribution-road { font-size: 13px; font-weight: 600; color: var(--accent-road); margin-bottom: var(--space-xs); }

        .attribution-details {
            display: flex;
            gap: var(--space-lg);
            font-size: 10px;
            color: var(--text-secondary);
        }

        .attribution-stat { display: flex; align-items: center; gap: var(--space-xs); }

        /* Debug Panel (expandable) */
        .debug-toggle {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--space-sm) var(--space-md);
            background: var(--bg-elevated);
            border-radius: var(--radius-sm);
            cursor: pointer;
            font-size: 10px;
            color: var(--text-tertiary);
            margin-top: var(--space-sm);
            transition: all 0.15s ease;
        }

        .debug-toggle:hover { background: var(--bg-secondary); color: var(--text-secondary); }
        .debug-toggle .chevron { transition: transform 0.2s ease; }
        .debug-toggle.expanded .chevron { transform: rotate(180deg); }

        .debug-content {
            display: none;
            background: var(--bg-elevated);
            border-radius: var(--radius-sm);
            padding: var(--space-md);
            margin-top: var(--space-sm);
            font-size: 10px;
        }

        .debug-content.expanded { display: block; }

        .debug-row {
            display: flex;
            justify-content: space-between;
            padding: 3px 0;
            border-bottom: 1px solid var(--border-subtle);
        }

        .debug-row:last-child { border-bottom: none; }
        .debug-key { color: var(--text-tertiary); }
        .debug-value { color: var(--text-primary); font-weight: 500; font-variant-numeric: tabular-nums; }

        /* Rejected Segment Card */
        .rejected-card {
            background: var(--bg-tertiary);
            border-radius: var(--radius-lg);
            border: 1px solid var(--accent-rejected-soft);
            border-left: 3px solid var(--accent-rejected);
            overflow: hidden;
            flex-shrink: 0;
        }

        .rejected-reason {
            display: inline-block;
            background: var(--accent-rejected-soft);
            color: var(--accent-rejected);
            padding: 2px 6px;
            border-radius: var(--radius-sm);
            font-size: 9px;
            font-weight: 600;
            text-transform: uppercase;
            margin-left: auto;
        }

        /* Empty State */
        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: var(--space-xl);
            text-align: center;
        }

        .empty-icon { font-size: 48px; opacity: 0.3; margin-bottom: var(--space-md); }
        .empty-title { font-size: 12px; color: var(--text-secondary); margin-bottom: var(--space-xs); }
        .empty-hint { font-size: 10px; color: var(--text-tertiary); }

        /* ============================================
           ELEVATION PANEL (Chart.js)
           ============================================ */
        .elevation-panel {
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-subtle);
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
        }

        .elevation-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: var(--space-sm) var(--space-lg);
            border-bottom: 1px solid var(--border-subtle);
            flex-shrink: 0;
        }

        .elevation-title {
            font-size: 10px;
            font-weight: 600;
            color: var(--text-tertiary);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }

        .elevation-stats {
            display: flex;
            gap: var(--space-xl);
            font-size: 10px;
        }

        .elev-stat { display: flex; align-items: center; gap: var(--space-xs); color: var(--text-secondary); }
        .elev-stat-value { font-weight: 600; color: var(--text-primary); }

        .elevation-chart {
            flex: 1;
            padding: var(--space-sm) var(--space-lg);
            position: relative;
            min-height: 0;
        }

        #elevationChart { width: 100% !important; height: 100% !important; }

        /* ============================================
           LEAFLET OVERRIDES
           ============================================ */
        .leaflet-container { background: var(--bg-primary); font-family: var(--font-mono); }
        .leaflet-control-zoom { border: none !important; box-shadow: var(--shadow-md) !important; }
        .leaflet-control-zoom a { background: var(--bg-secondary) !important; color: var(--text-primary) !important; border: 1px solid var(--border-default) !important; }
        .leaflet-control-zoom a:hover { background: var(--bg-tertiary) !important; }
        .leaflet-control-attribution { background: rgba(10, 15, 20, 0.8) !important; color: var(--text-tertiary) !important; font-size: 9px !important; }
        .leaflet-popup-content-wrapper { background: var(--bg-secondary); color: var(--text-primary); border-radius: var(--radius-md); box-shadow: var(--shadow-md); }
        .leaflet-popup-tip { background: var(--bg-secondary); }
        .leaflet-popup-content { margin: 10px 12px; }

        /* ============================================
           SCROLLBAR
           ============================================ */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: var(--bg-tertiary); }
        ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-tertiary); }

        /* ============================================
           RESPONSIVE
           ============================================ */
        @media (max-width: 1400px) {
            .main-content { grid-template-columns: 280px 1fr 360px; }
        }

        @media (max-width: 1200px) {
            .main-content { grid-template-columns: 260px 1fr 320px; }
            .header-stats { display: none; }
        }

        /* Category Badge */
        .cat-badge {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 600;
            margin-left: 6px;
            color: #fff;
        }
    </style>
</head>
<body>
    <div class="app">
        <!-- Header -->
        <header class="header">
            <div class="header-left">
                <div class="logo">
                    <div class="logo-icon">&#9968;</div>
                    <span>Boulder Rollers</span>
                </div>
                <span class="system-badge">Tile Mission Control v3</span>
                <a class="dev-link" href="/dev/climb-lab">ClimbLab</a>
            </div>
            <div class="header-stats">
                <div class="stat-item">
                    <span class="stat-value" id="statTiles">0</span>
                    <span class="stat-label">H3 Tiles</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value" id="statPatterns">0</span>
                    <span class="stat-label">Patterns</span>
                </div>
                <div class="stat-item">
                    <span class="stat-value" id="statDistance">0</span>
                    <span class="stat-label">km</span>
                </div>
            </div>
        </header>

        <!-- Main 3-Panel Layout -->
        <main class="main-content">
            <!-- Left: Controls -->
            <aside class="control-panel">
                <section class="panel-section">
                    <div class="section-header">
                        <span class="section-title">Files</span>
                        <span class="section-badge" id="fileCount">0 loaded</span>
                    </div>

                    <div class="upload-zone" id="uploadZone">
                        <div class="upload-icon">&#128193;</div>
                        <div class="upload-text">Drop FIT, GPX, or TCX files</div>
                        <div class="upload-hint">or click to browse</div>
                        <input type="file" id="fileInput" multiple accept=".fit,.gpx,.tcx" style="display: none;">
                    </div>

                    <div class="file-list" id="fileList"></div>
                </section>

                <section class="panel-section">
                    <div class="section-header">
                        <span class="section-title">H3 Resolution</span>
                    </div>
                    <select id="h3Resolution">
                        <option value="8">Res 8 - ~500m (Area)</option>
                        <option value="9">Res 9 - ~200m (Block)</option>
                        <option value="10" selected>Res 10 - ~66m (Street)</option>
                        <option value="11">Res 11 - ~25m (Precise)</option>
                    </select>
                </section>

                <section class="panel-section scrollable">
                    <div class="section-header">
                        <span class="section-title">Detection Thresholds</span>
                    </div>

                    <div class="threshold-group">
                        <div class="threshold-header">
                            <div class="threshold-icon climb">&#9968;</div>
                            <span class="threshold-label">Climb Detection</span>
                        </div>
                        <div class="control-row">
                            <span class="control-label">Min Vertical</span>
                            <span class="control-value" id="climbVertVal">50m</span>
                        </div>
                        <input type="range" id="climbVert" min="5" max="500" value="50" step="5">
                        <div class="control-row">
                            <span class="control-label">Min Duration</span>
                            <span class="control-value" id="climbTimeMinVal">2min</span>
                        </div>
                        <input type="range" id="climbTimeMin" min="0" max="30" value="2" step="1">
                        <div class="control-row">
                            <span class="control-label">Max Duration</span>
                            <span class="control-value" id="climbTimeMaxVal">60min</span>
                        </div>
                        <input type="range" id="climbTimeMax" min="5" max="180" value="60" step="5">
                        <div class="control-row">
                            <span class="control-label">Drop Tolerance</span>
                            <span class="control-value" id="climbDropVal">30m</span>
                        </div>
                        <input type="range" id="climbDrop" min="1" max="200" value="30" step="1">
                        <div class="control-row" style="margin-top: 12px;">
                            <span class="control-label">Algorithm</span>
                            <span class="control-value" id="climbAlgoVal">legacy</span>
                        </div>
                        <div class="algo-toggle-row">
                            <button type="button" id="algoLegacy" class="algo-btn active" onclick="setAlgorithm('legacy')">Legacy</button>
                            <button type="button" id="algoMomentum" class="algo-btn" onclick="setAlgorithm('momentum')">Momentum</button>
                        </div>
                        <div class="control-row" style="margin-top: 8px;">
                            <span class="control-label">Smart Trim</span>
                            <span class="control-value" id="smartTrimVal">off</span>
                        </div>
                        <div class="algo-toggle-row">
                            <button type="button" id="trimSimple" class="algo-btn active" onclick="setSmartTrim(false)">Simple</button>
                            <button type="button" id="trimSmart" class="algo-btn" onclick="setSmartTrim(true)">Convolution</button>
                        </div>
                        <div class="control-row" style="margin-top: 8px;">
                            <span class="control-label">Signatures</span>
                            <span class="control-value" id="signaturesVal">off</span>
                        </div>
                        <div class="algo-toggle-row">
                            <button type="button" id="sigOff" class="algo-btn active" onclick="setSignatures(false)">Off</button>
                            <button type="button" id="sigOn" class="algo-btn" onclick="setSignatures(true)">Generate</button>
                        </div>
                    </div>

                    <div class="threshold-group">
                        <div class="threshold-header">
                            <div class="threshold-icon explore">&#128506;</div>
                            <span class="threshold-label">Exploration</span>
                        </div>
                        <div class="control-row">
                            <span class="control-label">Min New Tiles</span>
                            <span class="control-value" id="exploreMinVal">50</span>
                        </div>
                        <input type="range" id="exploreMin" min="1" max="500" value="50" step="5">
                    </div>
                </section>

                <section class="panel-section">
                    <div class="actions">
                        <button class="btn btn-primary" id="btnRedetect">
                            <span>&#8635;</span>
                            <span>Re-detect Patterns</span>
                        </button>
                        <button class="btn btn-secondary" id="btnClear">
                            <span>&#10005;</span>
                            <span>Clear All</span>
                        </button>
                    </div>
                </section>
            </aside>

            <!-- Center: Map -->
            <div class="map-container">
                <div id="map"></div>

                <div class="map-controls">
                    <button class="map-toggle active" id="toggleTiles">
                        <div class="toggle-indicator"></div>
                        <span>H3 Tiles</span>
                    </button>
                    <button class="map-toggle active" id="toggleTrack">
                        <div class="toggle-indicator"></div>
                        <span>GPS Track</span>
                    </button>
                    <button class="map-toggle active" id="toggleClimbs">
                        <div class="toggle-indicator"></div>
                        <span>Climb Segments</span>
                    </button>
                    <button class="map-toggle" id="toggleRejected">
                        <div class="toggle-indicator"></div>
                        <span>Rejected Segments</span>
                    </button>
                    <div style="display: flex; flex-direction: column; gap: 4px;">
                        <button class="map-toggle" id="toggleVault" style="border-color: var(--accent-explore);">
                            <div class="toggle-indicator" style="background: var(--accent-explore);"></div>
                            <span>Vault Climbs</span>
                        </button>
                        <div id="vaultModeToggle" style="display: none; margin-left: 4px;">
                            <div style="display: flex; border-radius: 4px; overflow: hidden; border: 1px solid var(--border-subtle);">
                                <button id="vaultModeRect" class="vault-mode-btn active" style="padding: 4px 8px; font-size: 10px; background: var(--bg-elevated); border: none; color: var(--text-secondary); cursor: pointer;">&#9634; Boxes</button>
                                <button id="vaultModeTiles" class="vault-mode-btn" style="padding: 4px 8px; font-size: 10px; background: var(--bg-tertiary); border: none; color: var(--text-tertiary); cursor: pointer;">&#11042; Tiles</button>
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 4px;">
                        <button class="map-toggle active" id="toggleClimbTiles" style="border-color: var(--accent-climb);">
                            <div class="toggle-indicator" style="background: var(--accent-climb);"></div>
                            <span>Climb Tiles</span>
                        </button>
                    </div>
                </div>

                <div class="map-coords" id="mapCoords">39.9526&#176; N, 75.1652&#176; W</div>
            </div>

            <!-- Right: Inspector -->
            <aside class="inspector">
                <div class="inspector-header">
                    <div class="inspector-title">Pattern Inspector</div>
                    <div class="inspector-subtitle" id="inspectorSubtitle">No file selected</div>
                </div>

                <!-- Tab Navigation -->
                <div class="inspector-tabs">
                    <button class="inspector-tab active" data-tab="patterns">
                        Patterns<span class="tab-count" id="tabPatternsCount">0</span>
                    </button>
                    <button class="inspector-tab" data-tab="rejected">
                        Rejected<span class="tab-count" id="tabRejectedCount">0</span>
                    </button>
                    <button class="inspector-tab" data-tab="vault" style="color: var(--accent-explore);">
                        Vault<span class="tab-count" id="tabVaultCount">0</span>
                    </button>
                </div>

                <!-- Patterns Tab -->
                <div class="tab-content active" id="tabPatterns">
                    <div class="pattern-list" id="patternList">
                        <div class="empty-state">
                            <div class="empty-icon">&#128202;</div>
                            <div class="empty-title">No patterns detected</div>
                            <div class="empty-hint">Upload a ride file to analyze</div>
                        </div>
                    </div>
                </div>

                <!-- Rejected Tab -->
                <div class="tab-content" id="tabRejected">
                    <div class="pattern-list" id="rejectedList">
                        <div class="empty-state">
                            <div class="empty-icon">&#128683;</div>
                            <div class="empty-title">No rejected segments</div>
                            <div class="empty-hint">Segments that didn't meet thresholds appear here</div>
                        </div>
                    </div>
                </div>

                <!-- Vault Tab -->
                <div class="tab-content" id="tabVault">
                    <div class="pattern-list" id="vaultList">
                        <div class="empty-state">
                            <div class="empty-icon">&#127956;</div>
                            <div class="empty-title">Vault Climbs</div>
                            <div class="empty-hint">Toggle "Vault Climbs" on map to load</div>
                        </div>
                    </div>
                </div>
            </aside>
        </main>

        <!-- Bottom: Elevation Chart -->
        <footer class="elevation-panel">
            <div class="elevation-header">
                <span class="elevation-title">Elevation Profile</span>
                <div class="elevation-stats">
                    <div class="elev-stat"><span>&#8593;</span><span class="elev-stat-value" id="elevGain">0m</span><span>gain</span></div>
                    <div class="elev-stat"><span>&#8595;</span><span class="elev-stat-value" id="elevLoss">0m</span><span>loss</span></div>
                    <div class="elev-stat"><span>&#11014;</span><span class="elev-stat-value" id="elevMax">0m</span><span>max</span></div>
                    <div class="elev-stat"><span>&#11015;</span><span class="elev-stat-value" id="elevMin">0m</span><span>min</span></div>
                </div>
            </div>
            <div class="elevation-chart">
                <canvas id="elevationChart"></canvas>
            </div>
        </footer>
    </div>

    <script>
        // ============================================
        // STATE
        // ============================================
        const state = {
            files: [],
            activeFile: null,
            selectedPattern: null,
            rejectedSegments: [],
            hoverMarker: null,
            thresholds: {
                climb_vert_min_m: 50,
                climb_time_min_s: 120,
                climb_time_max_s: 3600,
                climb_drop_tolerance_m: 30,
                climb_smoothing_window: 5,
                climb_algorithm: 'legacy',
                climb_smart_trim: false,
                climb_generate_signatures: false,
                exploration_new_tile_min: 50
            },
            mapLayers: {
                tiles: true,
                track: true,
                climbs: true,
                climbtiles: true,  // Show detected climb tile sequences
                rejected: false,
                vault: false
            },
            vaultClimbs: [],
            matchedVaultIds: new Set(),
            editingVaultClimb: null,  // ID of vault climb being edited
            editingRect: null,        // Leaflet rectangle being dragged
            vaultAsTiles: false       // Show vault climbs as tile sequences instead of rectangles
        };

        const FILE_COLORS = ['#f472b6', '#22d3ee', '#a78bfa', '#34d399', '#fbbf24', '#fb7185', '#60a5fa', '#4ade80'];

        // ============================================
        // MAP INIT
        // ============================================
        const map = L.map('map', {
            center: [39.9526, -75.1652],
            zoom: 11,
            zoomControl: true,
            editable: true  // Enable Leaflet.Editable for vault bounds editing
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO',
            subdomains: 'abcd',
            maxZoom: 19
        }).addTo(map);

        const mapLayers = {
            tiles: L.layerGroup().addTo(map),
            track: L.layerGroup().addTo(map),
            climbs: L.layerGroup().addTo(map),
            climbtiles: L.layerGroup().addTo(map),  // Detected climb tile sequences
            rejected: L.layerGroup(),
            vault: L.layerGroup(),
            hover: L.layerGroup().addTo(map)
        };

        map.on('mousemove', e => {
            document.getElementById('mapCoords').textContent =
                `${e.latlng.lat.toFixed(4)}° N, ${Math.abs(e.latlng.lng).toFixed(4)}° W`;
        });

        // ============================================
        // CHART INIT
        // ============================================
        let elevationChart = null;

        function initChart() {
            const ctx = document.getElementById('elevationChart').getContext('2d');

            // Gradient overlay plugin
            const gradientOverlayPlugin = {
                id: 'gradientOverlay',
                beforeDatasetsDraw(chart) {
                    const file = state.activeFile;
                    if (!file?.enrichedTrack) return;

                    const { ctx: c, scales: { x, y } } = chart;
                    const track = file.enrichedTrack;

                    // Draw gradient colored segments
                    c.save();
                    for (let i = 1; i < track.length; i++) {
                        const pt = track[i];
                        const prevPt = track[i - 1];
                        if (pt.grade == null || prevPt.dist_km == null) continue;

                        const x1 = x.getPixelForValue(prevPt.dist_km);
                        const x2 = x.getPixelForValue(pt.dist_km);
                        const y1 = y.getPixelForValue(prevPt.elevation_m || 0);
                        const y2 = y.getPixelForValue(pt.elevation_m || 0);

                        // Color by gradient
                        let color;
                        const grade = pt.grade;
                        if (grade >= 10) color = 'rgba(220, 38, 38, 0.6)';       // Red - steep
                        else if (grade >= 6) color = 'rgba(234, 88, 12, 0.5)';   // Orange
                        else if (grade >= 3) color = 'rgba(234, 179, 8, 0.4)';   // Yellow
                        else if (grade >= 0) color = 'rgba(34, 197, 94, 0.3)';   // Green - flat/gentle
                        else color = 'rgba(59, 130, 246, 0.3)';                   // Blue - descent

                        c.strokeStyle = color;
                        c.lineWidth = 3;
                        c.beginPath();
                        c.moveTo(x1, y1);
                        c.lineTo(x2, y2);
                        c.stroke();
                    }
                    c.restore();
                }
            };

            // Climb segments overlay plugin
            const climbSegmentsPlugin = {
                id: 'climbSegments',
                beforeDatasetsDraw(chart) {
                    const file = state.activeFile;
                    if (!file?.enrichedTrack || !file?.patterns?.climb_patterns) return;

                    const { ctx: c, scales: { x, y } } = chart;
                    const climbs = file.patterns.climb_patterns;

                    climbs.forEach((climb, idx) => {
                        const startKm = getDistanceAtTime(file.enrichedTrack, climb.start_offset_s || climb.start_time_offset_s || 0);
                        const endKm = getDistanceAtTime(file.enrichedTrack, climb.end_offset_s || climb.end_time_offset_s || 0);
                        if (startKm === null || endKm === null) return;

                        const left = x.getPixelForValue(Math.min(startKm, endKm));
                        const right = x.getPixelForValue(Math.max(startKm, endKm));

                        // Color based on UCI category
                        const cat = climb.category || 'UC';
                        const colors = {
                            'HC': 'rgba(220, 38, 38, 0.25)',
                            '1': 'rgba(234, 88, 12, 0.25)',
                            '2': 'rgba(234, 179, 8, 0.22)',
                            '3': 'rgba(34, 197, 94, 0.20)',
                            '4': 'rgba(59, 130, 246, 0.18)',
                            'UC': 'rgba(148, 163, 184, 0.12)'
                        };

                        c.save();
                        c.fillStyle = colors[cat] || colors['UC'];
                        c.fillRect(left, y.top, right - left, y.bottom - y.top);

                        // Draw category label at top
                        if (right - left > 20) {
                            c.fillStyle = '#fff';
                            c.font = '9px JetBrains Mono';
                            c.textAlign = 'center';
                            const label = cat === 'UC' ? '' : (cat === 'HC' ? 'HC' : `C${cat}`);
                            if (label) c.fillText(label, (left + right) / 2, y.top + 12);
                        }
                        c.restore();
                    });
                }
            };

            // Rejected segments overlay (dashed red)
            const rejectedSegmentsPlugin = {
                id: 'rejectedSegments',
                beforeDatasetsDraw(chart) {
                    const file = state.activeFile;
                    if (!file?.enrichedTrack || !state.rejectedSegments?.length) return;
                    if (!state.mapLayers.rejected) return;

                    const { ctx: c, scales: { x, y } } = chart;

                    state.rejectedSegments.forEach((seg) => {
                        const startKm = getDistanceAtTime(file.enrichedTrack, seg.start_time_s || 0);
                        const endKm = getDistanceAtTime(file.enrichedTrack, seg.end_time_s || 0);
                        if (startKm === null || endKm === null) return;

                        const left = x.getPixelForValue(Math.min(startKm, endKm));
                        const right = x.getPixelForValue(Math.max(startKm, endKm));

                        c.save();
                        c.fillStyle = 'rgba(239, 68, 68, 0.12)';
                        c.fillRect(left, y.top, right - left, y.bottom - y.top);
                        c.setLineDash([4, 4]);
                        c.strokeStyle = 'rgba(239, 68, 68, 0.4)';
                        c.lineWidth = 1;
                        c.strokeRect(left, y.top, right - left, y.bottom - y.top);
                        c.restore();
                    });
                }
            };

            // Selected pattern highlight plugin
            const patternShadePlugin = {
                id: 'patternShade',
                beforeDatasetsDraw(chart) {
                    if (!state.selectedPattern) return;
                    const file = state.activeFile;
                    if (!file?.enrichedTrack) return;

                    const climb = state.selectedPattern;
                    const startKm = getDistanceAtTime(file.enrichedTrack, climb.start_offset_s || climb.start_time_offset_s || 0);
                    const endKm = getDistanceAtTime(file.enrichedTrack, climb.end_offset_s || climb.end_time_offset_s || 0);
                    if (startKm === null || endKm === null) return;

                    const { ctx: c, scales: { x, y } } = chart;
                    const left = x.getPixelForValue(Math.min(startKm, endKm));
                    const right = x.getPixelForValue(Math.max(startKm, endKm));

                    c.save();
                    c.fillStyle = 'rgba(34, 211, 238, 0.25)';
                    c.fillRect(left, y.top, right - left, y.bottom - y.top);
                    c.strokeStyle = 'rgba(34, 211, 238, 0.6)';
                    c.lineWidth = 2;
                    c.strokeRect(left, y.top, right - left, y.bottom - y.top);
                    c.restore();
                }
            };

            elevationChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: [{
                        label: 'Elevation',
                        data: [],
                        borderColor: '#f59e0b',
                        backgroundColor: 'rgba(245, 158, 11, 0.1)',
                        borderWidth: 2,
                        fill: true,
                        tension: 0.2,
                        pointRadius: 0,
                        pointHoverRadius: 5,
                        pointHoverBackgroundColor: '#f59e0b'
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#111820',
                            titleFont: { family: "'JetBrains Mono', monospace", size: 10 },
                            bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                            padding: 10,
                            cornerRadius: 6,
                            callbacks: {
                                title: ctx => {
                                    const pt = ctx[0]?.raw;
                                    if (!pt) return '';
                                    return `${pt.x.toFixed(2)} km`;
                                },
                                label: ctx => {
                                    const pt = ctx.raw;
                                    if (!pt) return '';
                                    const lines = [`Elev: ${Math.round(pt.y)}m`];
                                    if (pt.power) lines.push(`Power: ${pt.power}W`);
                                    if (pt.hr) lines.push(`HR: ${pt.hr} bpm`);
                                    if (pt.grade !== undefined && pt.grade !== null) lines.push(`Grade: ${pt.grade.toFixed(1)}%`);
                                    return lines;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            type: 'linear',
                            title: { display: true, text: 'Distance (km)', color: '#5a6a7d', font: { size: 10 } },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#5a6a7d', font: { size: 9 } }
                        },
                        y: {
                            title: { display: true, text: 'Elevation (m)', color: '#5a6a7d', font: { size: 10 } },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#5a6a7d', font: { size: 9 } }
                        }
                    },
                    onHover: (event, activeEls, chart) => {
                        if (!activeEls.length) {
                            mapLayers.hover.clearLayers();
                            return;
                        }
                        const pt = chart.data.datasets[0].data[activeEls[0].index];
                        if (pt?.lat && pt?.lon) {
                            mapLayers.hover.clearLayers();
                            L.circleMarker([pt.lat, pt.lon], {
                                radius: 6,
                                color: '#f59e0b',
                                fillColor: '#f59e0b',
                                fillOpacity: 1,
                                weight: 2
                            }).addTo(mapLayers.hover);
                        }
                    },
                    onClick: (event, activeEls, chart) => {
                        if (!activeEls.length) return;
                        const pt = chart.data.datasets[0].data[activeEls[0].index];
                        if (pt?.lat && pt?.lon) {
                            map.setView([pt.lat, pt.lon], 15);
                        }
                    }
                },
                plugins: [gradientOverlayPlugin, rejectedSegmentsPlugin, climbSegmentsPlugin, patternShadePlugin]
            });
        }

        initChart();

        // ============================================
        // UTILITIES
        // ============================================
        function haversineKm(lat1, lon1, lat2, lon2) {
            const R = 6371;
            const dLat = (lat2 - lat1) * Math.PI / 180;
            const dLon = (lon2 - lon1) * Math.PI / 180;
            const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
            return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        }

        function enrichTrackWithDistance(track) {
            if (!track?.length) return [];
            const sorted = [...track].sort((a, b) => (a.t || 0) - (b.t || 0));
            let dist = 0;
            return sorted.map((pt, i) => {
                if (i > 0) {
                    const prev = sorted[i - 1];
                    if (pt.lat != null && pt.lon != null && prev.lat != null && prev.lon != null) {
                        dist += haversineKm(prev.lat, prev.lon, pt.lat, pt.lon);
                    }
                }
                // Calculate grade
                let grade = null;
                if (i > 0 && pt.elevation_m != null && sorted[i-1].elevation_m != null) {
                    const dElev = pt.elevation_m - sorted[i-1].elevation_m;
                    const dDist = haversineKm(sorted[i-1].lat, sorted[i-1].lon, pt.lat, pt.lon) * 1000;
                    if (dDist > 0) grade = (dElev / dDist) * 100;
                }
                return { ...pt, dist_km: dist, grade };
            });
        }

        function getDistanceAtTime(enrichedTrack, timeS) {
            if (!enrichedTrack?.length) return null;
            const pt = enrichedTrack.find(p => p.t >= timeS);
            return pt ? pt.dist_km : null;
        }

        function formatTime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
            return `${m}:${String(s).padStart(2, '0')}`;
        }

        // ============================================
        // TAB NAVIGATION
        // ============================================
        document.querySelectorAll('.inspector-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.inspector-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

                tab.classList.add('active');
                const tabId = tab.dataset.tab;
                document.getElementById('tab' + tabId.charAt(0).toUpperCase() + tabId.slice(1)).classList.add('active');
            });
        });

        // ============================================
        // FILE HANDLING
        // ============================================
        const uploadZone = document.getElementById('uploadZone');
        const fileInput = document.getElementById('fileInput');

        uploadZone.addEventListener('click', () => fileInput.click());
        uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('dragover'); });
        uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('dragover'));
        uploadZone.addEventListener('drop', e => {
            e.preventDefault();
            uploadZone.classList.remove('dragover');
            handleFiles(e.dataTransfer.files);
        });
        fileInput.addEventListener('change', e => handleFiles(e.target.files));

        async function handleFiles(files) {
            const resolution = document.getElementById('h3Resolution').value;

            for (const file of files) {
                const ext = file.name.split('.').pop().toLowerCase();
                if (!['fit', 'gpx', 'tcx'].includes(ext)) continue;

                const color = FILE_COLORS[state.files.length % FILE_COLORS.length];
                const fileData = {
                    id: Date.now() + Math.random(),
                    name: file.name,
                    type: ext,
                    color,
                    file,
                    processed: null,
                    patterns: null,
                    enrichedTrack: null,
                    tileSamples: null
                };

                state.files.push(fileData);
                await processFile(fileData, resolution);
            }

            renderFileList();
            if (state.files.length && !state.activeFile) {
                selectFile(state.files[0]);
            }
        }

        async function processFile(fileData, resolution) {
            const formData = new FormData();
            formData.append('file', fileData.file);

            try {
                const response = await fetch(`/dev/tiles/upload?resolution=${resolution}`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) throw new Error(await response.text());

                const data = await response.json();

                fileData.processed = {
                    tiles: data.tiles.map(t => ({
                        tile_id: t.tile_id,
                        center: [t.center.lat, t.center.lon],
                        boundary: t.boundary.map(b => [b.lat, b.lon])
                    })),
                    gps_track: data.gps_track,
                    bounds: data.bounds
                };

                fileData.patterns = data.patterns;
                fileData.tileSamples = data.tile_samples;
                fileData.enrichedTrack = enrichTrackWithDistance(data.gps_track);

                if (state.activeFile?.id === fileData.id) {
                    renderPatterns();
                    renderElevationChart();
                    updateStats();
                }
            } catch (err) {
                console.error('Process error:', err);
            }
        }

        function renderFileList() {
            const count = state.files.length;
            document.getElementById('fileCount').textContent = `${count} loaded`;
            const list = document.getElementById('fileList');

            if (!count) {
                list.innerHTML = '';
                return;
            }

            list.innerHTML = state.files.map(f => `
                <div class="file-item ${state.activeFile?.id === f.id ? 'active' : ''}" data-id="${f.id}">
                    <div class="file-color" style="background: ${f.color}"></div>
                    <span class="file-name">${f.name}</span>
                    <span class="file-meta">${f.type.toUpperCase()}</span>
                    <span class="file-remove" onclick="removeFile(${f.id}); event.stopPropagation();">&#10005;</span>
                </div>
            `).join('');

            list.querySelectorAll('.file-item').forEach(el => {
                el.addEventListener('click', () => {
                    const file = state.files.find(f => f.id == el.dataset.id);
                    if (file) selectFile(file);
                });
            });
        }

        function selectFile(file) {
            state.activeFile = file;
            state.selectedPattern = null;
            state.rejectedSegments = [];
            renderFileList();
            renderMap();
            renderPatterns();
            renderRejected();
            renderElevationChart();
            updateStats();
            document.getElementById('inspectorSubtitle').textContent = file.name;
            // Update vault overlay to show match status for this file
            if (state.vaultClimbs.length) {
                renderVaultClimbs();
                renderVaultBrowser();
            }
        }

        function removeFile(id) {
            state.files = state.files.filter(f => f.id !== id);
            if (state.activeFile?.id === id) {
                state.activeFile = state.files[0] || null;
            }
            renderFileList();
            renderMap();
            renderPatterns();
            renderRejected();
            renderElevationChart();
            updateStats();
        }

        // ============================================
        // MAP RENDERING
        // ============================================
        function renderMap() {
            const file = state.activeFile;
            clearMapLayers();
            if (!file?.processed) return;

            const bounds = L.latLngBounds();
            const tiles = file.processed.tiles || [];
            const track = file.enrichedTrack || [];

            // Tiles
            tiles.forEach(t => {
                if (!t.boundary) return;
                const coords = t.boundary;
                coords.forEach(c => bounds.extend(c));

                const polygon = L.polygon(coords, {
                    color: '#22d3ee',
                    weight: 1,
                    opacity: 0.6,
                    fillColor: '#22d3ee',
                    fillOpacity: 0.15
                });

                polygon.on('click', () => fetchTileAttribution(t.tile_id, t.center));
                polygon.addTo(mapLayers.tiles);
            });

            // Track
            const trackCoords = track.filter(p => p.lat != null && p.lon != null).map(p => {
                bounds.extend([p.lat, p.lon]);
                return [p.lat, p.lon];
            });

            if (trackCoords.length > 1) {
                L.polyline(trackCoords, {
                    color: file.color || '#f472b6',
                    weight: 3,
                    opacity: 0.9
                }).addTo(mapLayers.track);
            }

            // Climb segments
            renderClimbSegments();
            renderClimbTiles();

            // Rejected segments
            renderRejectedOnMap();

            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [50, 50] });
            }

            updateLayerVisibility();
        }

        function renderClimbSegments() {
            const file = state.activeFile;
            mapLayers.climbs.clearLayers();
            if (!file?.patterns?.climb_patterns || !file.enrichedTrack) return;

            file.patterns.climb_patterns.forEach((climb, idx) => {
                const startT = climb.start_offset_s || climb.start_time_offset_s || 0;
                const endT = climb.end_offset_s || climb.end_time_offset_s || 0;

                const coords = file.enrichedTrack
                    .filter(p => p.t >= startT && p.t <= endT && p.lat != null)
                    .map(p => [p.lat, p.lon]);

                if (coords.length > 1) {
                    const isSelected = state.selectedPattern?.start_time_offset_s === climb.start_time_offset_s;
                    const poly = L.polyline(coords, {
                        color: isSelected ? '#fff' : '#f59e0b',
                        weight: isSelected ? 6 : 4,
                        opacity: 0.9
                    });

                    poly.on('click', () => selectPattern(climb, idx));
                    poly.addTo(mapLayers.climbs);
                }
            });
        }

        function renderClimbTiles() {
            mapLayers.climbtiles.clearLayers();
            const file = state.activeFile;
            if (!file?.patterns?.climb_patterns) return;

            // Get the processed tiles with boundaries from the file
            const allTiles = file.processed?.tiles || [];
            const tileMap = new Map();
            allTiles.forEach(t => tileMap.set(t.tile_id, t.boundary));

            file.patterns.climb_patterns.forEach((climb, idx) => {
                const tileSeq = climb.tile_ids || [];
                if (!tileSeq.length) return;

                const isSelected = state.selectedPattern?.start_time_offset_s === climb.start_time_offset_s;
                const baseColor = isSelected ? '#fff' : '#f59e0b';

                tileSeq.forEach((tileId, i) => {
                    const boundary = tileMap.get(tileId);
                    if (!boundary || !boundary.length) return;

                    // Gradient: lighter at start, darker at summit
                    const progress = tileSeq.length > 1 ? i / (tileSeq.length - 1) : 0.5;
                    const fillOpacity = 0.15 + (progress * 0.35);

                    // boundary is already [[lat, lon], ...] format
                    const polygon = L.polygon(boundary, {
                        color: baseColor,
                        weight: isSelected ? 2 : 1,
                        opacity: 0.8,
                        fillColor: baseColor,
                        fillOpacity
                    });

                    polygon.on('click', () => selectPattern(climb, idx));
                    polygon.addTo(mapLayers.climbtiles);
                });
            });
        }

        function renderRejectedOnMap() {
            mapLayers.rejected.clearLayers();
            const file = state.activeFile;
            if (!file?.enrichedTrack || !state.rejectedSegments?.length) return;

            state.rejectedSegments.forEach((seg) => {
                const startT = seg.start_time_s || 0;
                const endT = seg.end_time_s || 0;

                const coords = file.enrichedTrack
                    .filter(p => p.t >= startT && p.t <= endT && p.lat != null)
                    .map(p => [p.lat, p.lon]);

                if (coords.length > 1) {
                    const poly = L.polyline(coords, {
                        color: '#ef4444',
                        weight: 3,
                        opacity: 0.6,
                        dashArray: '5, 5'
                    });

                    poly.bindPopup(`<div class="tile-popup">
                        <div class="road-name" style="color:#ef4444">Rejected</div>
                        <div class="road-info">Reason: ${seg.rejection_reason}</div>
                        <div class="road-info">Vert: ${Math.round(seg.vert_m)}m | VAM: ${Math.round(seg.vam)}</div>
                    </div>`);
                    poly.addTo(mapLayers.rejected);
                }
            });
        }

        function clearMapLayers() {
            Object.values(mapLayers).forEach(layer => layer.clearLayers());
        }

        function updateLayerVisibility() {
            ['tiles', 'track', 'climbs', 'climbtiles', 'rejected', 'vault'].forEach(key => {
                if (state.mapLayers[key]) map.addLayer(mapLayers[key]);
                else map.removeLayer(mapLayers[key]);
            });
        }

        async function fetchTileAttribution(tileId, center) {
            try {
                const res = await fetch(`/dev/tiles/attribution?tile_ids=${tileId}`);
                const data = await res.json();
                const attr = data[tileId] || {};

                const popup = L.popup()
                    .setLatLng(center)
                    .setContent(`
                        <div class="tile-popup">
                            <div class="tile-id">${tileId}</div>
                            ${attr.road_name ? `<div class="road-name">${attr.road_name}</div>` : '<div class="road-name" style="color:#8b9bb0">No road data</div>'}
                            ${attr.road_class ? `<div class="road-info">Class: ${attr.road_class}</div>` : ''}
                            ${attr.road_grade ? `<div class="road-info">Grade: ${attr.road_grade.toFixed(1)}%</div>` : ''}
                        </div>
                    `)
                    .openOn(map);
            } catch (e) {
                console.error('Attribution fetch error:', e);
            }
        }

        // ============================================
        // VAULT CLIMBS
        // ============================================
        async function fetchVaultClimbs() {
            try {
                const res = await fetch('/dev/tiles/vault-climbs');
                const data = await res.json();
                if (data.climbs) {
                    state.vaultClimbs = data.climbs;
                    console.log(`[Vault] Loaded ${data.climbs.length} climbs`);
                    renderVaultClimbs();
                    renderVaultBrowser();
                }
            } catch (e) {
                console.error('Vault fetch error:', e);
            }
        }

        function renderVaultClimbs() {
            mapLayers.vault.clearLayers();
            if (!state.vaultClimbs.length) return;

            // Track which vault climbs were matched by current ride
            state.matchedVaultIds.clear();
            const file = state.activeFile;
            if (file?.patterns?.climb_patterns) {
                file.patterns.climb_patterns.forEach(climb => {
                    if (climb.vault_match?.id) {
                        state.matchedVaultIds.add(climb.vault_match.id);
                    }
                });
            }

            state.vaultClimbs.forEach(vc => {
                // Skip the climb being edited (it has its own editable rectangle)
                if (state.editingVaultClimb === vc.id) return;

                const isMatched = state.matchedVaultIds.has(vc.id);
                const isInView = file?.processed?.bounds && boundsOverlap(vc.bounds, file.processed.bounds);

                // Color based on match status
                let baseColor;
                if (isMatched) {
                    baseColor = '#10b981';  // Green - matched!
                } else if (isInView) {
                    baseColor = '#f59e0b';  // Orange - in area
                } else {
                    baseColor = '#8b5cf6';  // Purple - other
                }

                // Render as tiles if toggle enabled and tiles available
                if (state.vaultAsTiles && vc.tiles && vc.tiles.length > 0) {
                    renderVaultAsTiles(vc, baseColor, isMatched);
                } else {
                    renderVaultAsRectangle(vc, baseColor, isMatched);
                }
            });
        }

        function renderVaultAsTiles(vc, baseColor, isMatched) {
            const tileCount = vc.tiles.length;

            vc.tiles.forEach((tile, index) => {
                // Gradient from light (start) to dark (summit) based on position in sequence
                const progress = tileCount > 1 ? index / (tileCount - 1) : 0.5;
                const fillOpacity = 0.2 + (progress * 0.4);  // 0.2 at start, 0.6 at end

                const coords = tile.boundary.map(b => [b.lat, b.lon]);
                const polygon = L.polygon(coords, {
                    color: baseColor,
                    weight: 1,
                    opacity: 0.9,
                    fillColor: baseColor,
                    fillOpacity
                });

                // Only add popup to first tile
                if (index === 0) {
                    polygon.bindPopup(`
                        <div class="tile-popup">
                            <div class="road-name" style="color:${baseColor}">${vc.name}</div>
                            <div class="road-info">${vc.stats.vert_m}m | ${vc.stats.avg_gradient_pct?.toFixed(1) || '?'}% avg</div>
                            <div class="road-info">${tileCount} tiles in sequence</div>
                            <div class="road-info" style="color:#8b9bb0; font-size:10px;">${vc.source} | ${vc.region || ''}</div>
                            ${isMatched ? '<div style="color:#10b981; font-weight:600; margin-top:4px;">&#10003; Matched this ride!</div>' : ''}
                        </div>
                    `);
                }

                polygon.addTo(mapLayers.vault);
            });
        }

        function renderVaultAsRectangle(vc, baseColor, isMatched) {
            const bounds = [
                [vc.bounds.min_lat, vc.bounds.min_lon],
                [vc.bounds.max_lat, vc.bounds.max_lon]
            ];

            const fillOpacity = isMatched ? 0.25 : 0.1;

            const rect = L.rectangle(bounds, {
                color: baseColor,
                weight: 2,
                opacity: 0.8,
                fillColor: baseColor,
                fillOpacity,
                dashArray: isMatched ? null : '4, 4'
            });

            rect.bindPopup(`
                <div class="tile-popup">
                    <div class="road-name" style="color:${baseColor}">${vc.name}</div>
                    <div class="road-info">${vc.stats.vert_m}m | ${vc.stats.avg_gradient_pct?.toFixed(1) || '?'}% avg</div>
                    <div class="road-info">${vc.stats.distance_m ? (vc.stats.distance_m/1000).toFixed(2) + 'km' : ''}</div>
                    <div class="road-info" style="color:#8b9bb0; font-size:10px;">${vc.source} | ${vc.region || ''}</div>
                    ${vc.tile_count ? `<div class="road-info" style="color:var(--text-tertiary);">${vc.tile_count} tiles (toggle to view)</div>` : '<div class="road-info" style="color:var(--accent-rejected);">No tile sequence</div>'}
                    ${isMatched ? '<div style="color:#10b981; font-weight:600; margin-top:4px;">&#10003; Matched this ride!</div>' : ''}
                </div>
            `);

            rect.addTo(mapLayers.vault);
        }

        function boundsOverlap(vaultBounds, rideBounds) {
            // Check if vault climb bounding box overlaps with ride bounding box
            if (!rideBounds) return false;
            const rb = rideBounds;
            const vb = vaultBounds;
            return !(vb.max_lat < rb.min_lat || vb.min_lat > rb.max_lat ||
                     vb.max_lon < rb.min_lon || vb.min_lon > rb.max_lon);
        }

        function renderVaultBrowser() {
            const list = document.getElementById('vaultList');
            if (!list) return;

            const climbs = state.vaultClimbs;
            document.getElementById('tabVaultCount').textContent = climbs.length;

            if (!climbs.length) {
                list.innerHTML = `<div class="empty-state"><div class="empty-icon">&#127956;</div><div class="empty-title">Vault empty</div><div class="empty-hint">No canonical climbs loaded</div></div>`;
                return;
            }

            // Add "Draw New Climb" button at top
            const headerHtml = `
                <div style="margin-bottom: 12px;">
                    <button id="drawNewClimbBtn" style="width: 100%; padding: 10px; background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
                            border: none; border-radius: 8px; color: white; cursor: pointer; font-weight: 600; font-size: 13px;">
                        &#10010; Draw New Climb
                    </button>
                </div>
            `;

            list.innerHTML = headerHtml + climbs.map(vc => {
                const isMatched = state.matchedVaultIds.has(vc.id);
                const isEditing = state.editingVaultClimb === vc.id;
                return `
                    <div class="pattern-card ${isEditing ? 'editing' : ''}" data-vault-id="${vc.id}" style="border-left: 3px solid ${isEditing ? '#facc15' : isMatched ? '#10b981' : '#8b5cf6'};">
                        <div class="pattern-header">
                            <span class="pattern-type" style="color: ${isEditing ? '#facc15' : isMatched ? '#10b981' : '#8b5cf6'};">
                                ${isEditing ? '&#9998;' : isMatched ? '&#10003;' : '&#127956;'} ${vc.name}
                            </span>
                            <div style="display: flex; gap: 4px;">
                                <button class="vault-rename-btn" data-vault-id="${vc.id}" data-vault-name="${vc.name}" title="Rename" style="background: transparent; border: 1px solid var(--border-subtle); border-radius: 4px; color: var(--text-secondary); cursor: pointer; padding: 2px 6px; font-size: 11px;">
                                    Aa
                                </button>
                                <button class="vault-edit-btn" data-vault-id="${vc.id}" title="${isEditing ? 'Cancel Edit' : 'Edit Bounds'}">
                                    ${isEditing ? '&#10006;' : '&#9998;'}
                                </button>
                            </div>
                        </div>
                        <div class="pattern-body">
                            <div class="pattern-metrics">
                                <div class="metric"><span class="metric-value">${Math.round(vc.stats.vert_m)}m</span><span class="metric-label">Vert</span></div>
                                <div class="metric"><span class="metric-value">${vc.stats.avg_gradient_pct?.toFixed(1) || '?'}%</span><span class="metric-label">Grade</span></div>
                                <div class="metric"><span class="metric-value">${vc.stats.distance_m ? (vc.stats.distance_m/1000).toFixed(1) + 'km' : '?'}</span><span class="metric-label">Dist</span></div>
                            </div>
                            ${isEditing ? `
                            <div class="vault-edit-actions" style="margin-top: 8px; display: flex; gap: 8px;">
                                <button class="vault-save-btn" data-vault-id="${vc.id}" style="flex:1; padding: 6px 12px; background: #10b981; border: none; border-radius: 4px; color: white; cursor: pointer; font-weight: 600;">
                                    &#10003; Save Bounds
                                </button>
                            </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            }).join('');

            // Add click handlers to zoom to vault climb
            list.querySelectorAll('.pattern-card[data-vault-id]').forEach(card => {
                card.addEventListener('click', (e) => {
                    // Ignore clicks on buttons
                    if (e.target.closest('.vault-edit-btn, .vault-save-btn, .vault-rename-btn')) return;
                    const vc = state.vaultClimbs.find(c => c.id === card.dataset.vaultId);
                    if (vc) {
                        const bounds = L.latLngBounds([
                            [vc.bounds.min_lat, vc.bounds.min_lon],
                            [vc.bounds.max_lat, vc.bounds.max_lon]
                        ]);
                        map.fitBounds(bounds, { padding: [50, 50] });
                    }
                });
            });

            // Add edit button handlers
            list.querySelectorAll('.vault-edit-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const vaultId = btn.dataset.vaultId;
                    if (state.editingVaultClimb === vaultId) {
                        cancelVaultEdit();
                    } else {
                        startVaultEdit(vaultId);
                    }
                });
            });

            // Add save button handlers
            list.querySelectorAll('.vault-save-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    saveVaultBounds(btn.dataset.vaultId);
                });
            });

            // Add rename button handlers
            list.querySelectorAll('.vault-rename-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    showRenameModal(btn.dataset.vaultId, btn.dataset.vaultName);
                });
            });

            // Add draw new climb handler
            const drawBtn = document.getElementById('drawNewClimbBtn');
            if (drawBtn) {
                drawBtn.addEventListener('click', startDrawNewClimb);
            }
        }

        // ============================================
        // VAULT BOUNDS EDITING (with draggable corners)
        // ============================================
        const editCorners = [];  // Corner markers for editing

        function startVaultEdit(vaultId) {
            const vc = state.vaultClimbs.find(c => c.id === vaultId);
            if (!vc) return;

            // Cancel any existing edit
            if (state.editingVaultClimb) {
                cancelVaultEdit();
            }

            state.editingVaultClimb = vaultId;

            // Create editable rectangle
            const bounds = L.latLngBounds([
                [vc.bounds.min_lat, vc.bounds.min_lon],
                [vc.bounds.max_lat, vc.bounds.max_lon]
            ]);

            state.editingRect = L.rectangle(bounds, {
                color: '#facc15',
                weight: 3,
                opacity: 1,
                fillColor: '#facc15',
                fillOpacity: 0.25,
                dashArray: null,
                interactive: true
            }).addTo(map);

            // Create draggable corner markers
            createEditCorners();

            // Zoom to the rectangle
            map.fitBounds(bounds, { padding: [100, 100] });

            // Re-render vault layer and browser
            renderVaultClimbs();
            renderVaultBrowser();

            console.log(`[Vault] Started editing: ${vc.name} - drag yellow corners to resize`);
        }

        function createEditCorners() {
            // Clear existing corners
            editCorners.forEach(m => map.removeLayer(m));
            editCorners.length = 0;

            if (!state.editingRect) return;

            const bounds = state.editingRect.getBounds();
            const corners = [
                { pos: bounds.getSouthWest(), type: 'sw' },
                { pos: bounds.getNorthWest(), type: 'nw' },
                { pos: bounds.getNorthEast(), type: 'ne' },
                { pos: bounds.getSouthEast(), type: 'se' }
            ];

            const cornerIcon = L.divIcon({
                className: 'vault-edit-corner',
                iconSize: [16, 16],
                iconAnchor: [8, 8]
            });

            corners.forEach(({ pos, type }) => {
                const marker = L.marker(pos, {
                    icon: cornerIcon,
                    draggable: true,
                    zIndexOffset: 1000
                }).addTo(map);

                marker._cornerType = type;

                marker.on('drag', (e) => {
                    updateRectFromCorners(type, e.target.getLatLng());
                });

                marker.on('dragend', () => {
                    createEditCorners(); // Recreate to sync positions
                });

                editCorners.push(marker);
            });
        }

        function updateRectFromCorners(draggedCorner, newPos) {
            if (!state.editingRect) return;

            const bounds = state.editingRect.getBounds();
            let sw = bounds.getSouthWest();
            let ne = bounds.getNorthEast();

            switch (draggedCorner) {
                case 'sw':
                    sw = L.latLng(newPos.lat, newPos.lng);
                    break;
                case 'nw':
                    sw = L.latLng(sw.lat, newPos.lng);
                    ne = L.latLng(newPos.lat, ne.lng);
                    break;
                case 'ne':
                    ne = L.latLng(newPos.lat, newPos.lng);
                    break;
                case 'se':
                    sw = L.latLng(newPos.lat, sw.lng);
                    ne = L.latLng(ne.lat, newPos.lng);
                    break;
            }

            state.editingRect.setBounds(L.latLngBounds(sw, ne));
        }

        function cancelVaultEdit() {
            // Remove corner markers
            editCorners.forEach(m => map.removeLayer(m));
            editCorners.length = 0;

            if (state.editingRect) {
                map.removeLayer(state.editingRect);
                state.editingRect = null;
            }
            state.editingVaultClimb = null;
            renderVaultClimbs();
            renderVaultBrowser();
            console.log('[Vault] Edit cancelled');
        }

        async function saveVaultBounds(vaultId) {
            if (!state.editingRect || state.editingVaultClimb !== vaultId) {
                console.error('[Vault] No active edit for this climb');
                return;
            }

            const vc = state.vaultClimbs.find(c => c.id === vaultId);
            const bounds = state.editingRect.getBounds();

            const newBounds = {
                min_lat: bounds.getSouth(),
                max_lat: bounds.getNorth(),
                min_lon: bounds.getWest(),
                max_lon: bounds.getEast()
            };

            console.log(`[Vault] Saving bounds for ${vc?.name}:`, newBounds);

            try {
                const response = await fetch(`/dev/tiles/vault-climbs/${vaultId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bounds: newBounds })
                });

                const result = await response.json();

                if (result.success) {
                    // Update local state
                    const idx = state.vaultClimbs.findIndex(c => c.id === vaultId);
                    if (idx !== -1) {
                        state.vaultClimbs[idx].bounds = newBounds;
                    }

                    console.log(`[Vault] Saved bounds for ${vc?.name}`);
                    alert(`Bounds saved for ${vc?.name}!`);

                    // Clean up edit mode
                    cancelVaultEdit();
                } else {
                    console.error('[Vault] Save failed:', result.error);
                    alert(`Save failed: ${result.error}`);
                }
            } catch (e) {
                console.error('[Vault] Save error:', e);
                alert(`Save error: ${e.message}`);
            }
        }

        // ============================================
        // RENAME VAULT CLIMB
        // ============================================
        function showRenameModal(vaultId, currentName) {
            const modal = document.createElement('div');
            modal.id = 'renameVaultModal';
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.8); display: flex; align-items: center;
                justify-content: center; z-index: 10000;
            `;

            modal.innerHTML = `
                <div style="background: var(--bg-secondary); border-radius: 12px; padding: 24px;
                            width: 350px; max-width: 90vw; border: 1px solid var(--border-default);">
                    <h3 style="margin: 0 0 16px 0; color: var(--text-primary); font-size: 16px;">
                        Rename Climb
                    </h3>
                    <div style="margin-bottom: 16px;">
                        <input type="text" id="renameInput" value="${currentName}"
                               style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                      border: 1px solid var(--border-default); border-radius: 6px;
                                      color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                    </div>
                    <div style="display: flex; gap: 12px;">
                        <button id="cancelRename" style="flex: 1; padding: 10px; background: var(--bg-tertiary);
                                border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-primary);
                                cursor: pointer; font-size: 13px;">Cancel</button>
                        <button id="confirmRename" style="flex: 1; padding: 10px; background: #8b5cf6;
                                border: none; border-radius: 6px; color: white; cursor: pointer; font-weight: 600; font-size: 13px;">
                            Rename
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            document.getElementById('renameInput').focus();
            document.getElementById('renameInput').select();

            document.getElementById('cancelRename').addEventListener('click', () => modal.remove());
            modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });

            document.getElementById('confirmRename').addEventListener('click', async () => {
                const newName = document.getElementById('renameInput').value.trim();
                if (!newName) { alert('Please enter a name'); return; }
                if (newName === currentName) { modal.remove(); return; }
                await renameVaultClimb(vaultId, newName);
                modal.remove();
            });

            document.getElementById('renameInput').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') document.getElementById('confirmRename').click();
                if (e.key === 'Escape') modal.remove();
            });
        }

        async function renameVaultClimb(vaultId, newName) {
            try {
                const response = await fetch(`/dev/tiles/vault-climbs/${vaultId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: newName })
                });

                const result = await response.json();

                if (result.success) {
                    const idx = state.vaultClimbs.findIndex(c => c.id === vaultId);
                    if (idx !== -1) {
                        state.vaultClimbs[idx].name = newName;
                    }
                    console.log(`[Vault] Renamed to: ${newName}`);
                    renderVaultBrowser();
                    renderVaultClimbs();
                } else {
                    alert(`Rename failed: ${result.error}`);
                }
            } catch (e) {
                alert(`Rename error: ${e.message}`);
            }
        }

        // ============================================
        // DRAW NEW CLIMB
        // ============================================
        let drawingNewClimb = false;
        let newClimbRect = null;

        function startDrawNewClimb() {
            if (drawingNewClimb) {
                // If already drawing, show the save modal
                showNewClimbSaveModal();
                return;
            }

            drawingNewClimb = true;
            const btn = document.getElementById('drawNewClimbBtn');
            btn.innerHTML = '&#10003; Done - Save Climb';
            btn.style.background = 'linear-gradient(135deg, #10b981 0%, #059669 100%)';

            // Create a rectangle at the map center
            const center = map.getCenter();
            const offset = 0.005;  // ~500m
            const bounds = L.latLngBounds(
                [center.lat - offset, center.lng - offset],
                [center.lat + offset, center.lng + offset]
            );

            newClimbRect = L.rectangle(bounds, {
                color: '#8b5cf6',
                weight: 3,
                opacity: 1,
                fillColor: '#8b5cf6',
                fillOpacity: 0.25,
            }).addTo(map);

            // Add corner handles for the new rectangle
            state.editingRect = newClimbRect;
            createEditCorners();

            console.log('[Vault] Drawing new climb - drag corners to position, then click "Done" to save');
        }

        function cancelDrawNewClimb() {
            drawingNewClimb = false;
            const btn = document.getElementById('drawNewClimbBtn');
            if (btn) {
                btn.innerHTML = '&#10010; Draw New Climb';
                btn.style.background = 'linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)';
            }

            editCorners.forEach(m => map.removeLayer(m));
            editCorners.length = 0;

            if (newClimbRect) {
                map.removeLayer(newClimbRect);
                newClimbRect = null;
            }
            state.editingRect = null;
        }

        function showNewClimbSaveModal() {
            if (!newClimbRect) return;

            const bounds = newClimbRect.getBounds();
            const modal = document.createElement('div');
            modal.id = 'newClimbModal';
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.8); display: flex; align-items: center;
                justify-content: center; z-index: 10000;
            `;

            modal.innerHTML = `
                <div style="background: var(--bg-secondary); border-radius: 12px; padding: 24px;
                            width: 400px; max-width: 90vw; border: 1px solid var(--border-default);">
                    <h3 style="margin: 0 0 16px 0; color: var(--text-primary); font-size: 16px;">
                        &#10010; Create New Vault Climb
                    </h3>
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px;">
                            Climb Name *
                        </label>
                        <input type="text" id="newClimbName" placeholder="e.g. Manayunk Wall"
                               style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                      border: 1px solid var(--border-default); border-radius: 6px;
                                      color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                    </div>
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px;">
                            Region
                        </label>
                        <input type="text" id="newClimbRegion" value="Philadelphia"
                               style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                      border: 1px solid var(--border-default); border-radius: 6px;
                                      color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px;">
                        <div>
                            <label style="display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px;">
                                Elevation (m)
                            </label>
                            <input type="number" id="newClimbVert" value="50" min="0"
                                   style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                          border: 1px solid var(--border-default); border-radius: 6px;
                                          color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                        </div>
                        <div>
                            <label style="display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px;">
                                Avg Gradient (%)
                            </label>
                            <input type="number" id="newClimbGrade" value="5" min="0" step="0.1"
                                   style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                          border: 1px solid var(--border-default); border-radius: 6px;
                                          color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                        </div>
                    </div>
                    <div style="display: flex; gap: 12px;">
                        <button id="cancelNewClimb" style="flex: 1; padding: 10px; background: var(--bg-tertiary);
                                border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-primary);
                                cursor: pointer; font-size: 13px;">Cancel</button>
                        <button id="confirmNewClimb" style="flex: 1; padding: 10px; background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
                                border: none; border-radius: 6px; color: white; cursor: pointer; font-weight: 600; font-size: 13px;">
                            Create Climb
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            document.getElementById('newClimbName').focus();

            document.getElementById('cancelNewClimb').addEventListener('click', () => {
                modal.remove();
                cancelDrawNewClimb();
            });

            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.remove();
                    cancelDrawNewClimb();
                }
            });

            document.getElementById('confirmNewClimb').addEventListener('click', async () => {
                const name = document.getElementById('newClimbName').value.trim();
                const region = document.getElementById('newClimbRegion').value.trim();
                const vert = parseFloat(document.getElementById('newClimbVert').value) || 50;
                const grade = parseFloat(document.getElementById('newClimbGrade').value) || 5;

                if (!name) { alert('Please enter a name'); return; }

                await createNewVaultClimb(name, region, vert, grade, bounds);
                modal.remove();
                cancelDrawNewClimb();
            });
        }

        async function createNewVaultClimb(name, region, vert, grade, bounds) {
            const payload = {
                name,
                region,
                bounds: {
                    min_lat: bounds.getSouth(),
                    max_lat: bounds.getNorth(),
                    min_lon: bounds.getWest(),
                    max_lon: bounds.getEast()
                },
                stats: {
                    vert_m: vert,
                    avg_gradient_pct: grade,
                    max_gradient_pct: grade * 1.5,
                    distance_m: (vert / grade) * 100 || 1000
                },
                description: `${vert}m elevation, ${grade}% avg grade`
            };

            try {
                const response = await fetch('/dev/tiles/vault-climbs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (result.success) {
                    console.log('[Vault] Created new climb:', result.created);
                    alert(`"${name}" created!`);
                    await fetchVaultClimbs();
                } else {
                    alert(`Create failed: ${result.error}`);
                }
            } catch (e) {
                alert(`Create error: ${e.message}`);
            }
        }

        // ============================================
        // SAVE DETECTED CLIMB TO VAULT
        // ============================================
        function showSaveToVaultModal(climb, index) {
            const modal = document.createElement('div');
            modal.id = 'saveVaultModal';
            modal.style.cssText = `
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.8); display: flex; align-items: center;
                justify-content: center; z-index: 10000;
            `;

            const suggestedName = climb.road_name || `Climb ${index + 1}`;

            modal.innerHTML = `
                <div style="background: var(--bg-secondary); border-radius: 12px; padding: 24px;
                            width: 400px; max-width: 90vw; border: 1px solid var(--border-default);">
                    <h3 style="margin: 0 0 16px 0; color: var(--text-primary); font-size: 16px;">
                        &#128190; Save to Vault
                    </h3>
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px;">
                            Climb Name *
                        </label>
                        <input type="text" id="vaultClimbName" value="${suggestedName}"
                               style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                      border: 1px solid var(--border-default); border-radius: 6px;
                                      color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                    </div>
                    <div style="margin-bottom: 16px;">
                        <label style="display: block; margin-bottom: 6px; color: var(--text-secondary); font-size: 12px;">
                            Region
                        </label>
                        <input type="text" id="vaultClimbRegion" value="Philadelphia"
                               style="width: 100%; padding: 10px 12px; background: var(--bg-tertiary);
                                      border: 1px solid var(--border-default); border-radius: 6px;
                                      color: var(--text-primary); font-size: 14px; box-sizing: border-box;" />
                    </div>
                    <div style="background: var(--bg-tertiary); border-radius: 6px; padding: 12px; margin-bottom: 16px;">
                        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; text-align: center;">
                            <div>
                                <div style="font-size: 18px; font-weight: 600; color: var(--accent-climb);">${Math.round(climb.vert_m)}m</div>
                                <div style="font-size: 10px; color: var(--text-tertiary);">Elevation</div>
                            </div>
                            <div>
                                <div style="font-size: 18px; font-weight: 600; color: var(--accent-climb);">${climb.avg_gradient_pct?.toFixed(1) || '?'}%</div>
                                <div style="font-size: 10px; color: var(--text-tertiary);">Gradient</div>
                            </div>
                            <div>
                                <div style="font-size: 18px; font-weight: 600; color: var(--accent-climb);">${(climb.distance_m/1000).toFixed(1)}km</div>
                                <div style="font-size: 10px; color: var(--text-tertiary);">Distance</div>
                            </div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 12px;">
                        <button id="cancelVaultSave" style="flex: 1; padding: 10px; background: var(--bg-tertiary);
                                border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-primary);
                                cursor: pointer; font-size: 13px;">Cancel</button>
                        <button id="confirmVaultSave" style="flex: 1; padding: 10px; background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
                                border: none; border-radius: 6px; color: white; cursor: pointer; font-weight: 600; font-size: 13px;">
                            Save to Vault
                        </button>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);
            document.getElementById('vaultClimbName').focus();
            document.getElementById('vaultClimbName').select();

            document.getElementById('cancelVaultSave').addEventListener('click', () => modal.remove());
            modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });

            document.getElementById('confirmVaultSave').addEventListener('click', async () => {
                const name = document.getElementById('vaultClimbName').value.trim();
                const region = document.getElementById('vaultClimbRegion').value.trim();
                if (!name) { alert('Please enter a name'); return; }
                await saveDetectedClimbToVault(climb, name, region);
                modal.remove();
            });

            document.getElementById('vaultClimbName').addEventListener('keydown', (e) => {
                if (e.key === 'Enter') document.getElementById('confirmVaultSave').click();
            });
        }

        async function saveDetectedClimbToVault(climb, name, region) {
            // Calculate bounds from GPS track using climb's time offsets
            const file = state.activeFile;
            const gpsTrack = file?.processed?.gps_track || [];
            const startOffset = climb.start_offset_s || climb.start_time_offset_s || 0;
            const endOffset = climb.end_offset_s || climb.end_time_offset_s || 0;

            // Filter GPS points within the climb's time range
            const climbPoints = gpsTrack.filter(p => p.t >= startOffset && p.t <= endOffset);

            let bounds;
            if (climbPoints.length > 0) {
                bounds = {
                    min_lat: Math.min(...climbPoints.map(p => p.lat)),
                    max_lat: Math.max(...climbPoints.map(p => p.lat)),
                    min_lon: Math.min(...climbPoints.map(p => p.lon)),
                    max_lon: Math.max(...climbPoints.map(p => p.lon))
                };
            } else {
                // Fallback to file bounds if no GPS track
                bounds = file?.processed?.bounds || { min_lat: 0, max_lat: 0, min_lon: 0, max_lon: 0 };
                console.warn('[Vault] No GPS points for climb, using file bounds');
            }

            const payload = {
                name, region, bounds,
                tile_sequence: climb.tile_ids || [],  // Store canonical tile sequence
                stats: {
                    vert_m: climb.vert_m,
                    avg_gradient_pct: climb.avg_gradient_pct,
                    max_gradient_pct: climb.max_gradient_pct || (climb.avg_gradient_pct ? climb.avg_gradient_pct * 1.5 : 0),
                    distance_m: climb.distance_m || 0
                },
                signature_hex: climb.signature_hex || null,
                description: `${Math.round(climb.vert_m)}m elevation, ${climb.avg_gradient_pct?.toFixed(1) || '?'}% avg grade`
            };

            console.log('[Vault] Payload being sent:', JSON.stringify(payload, null, 2));
            console.log('[Vault] Climb object keys:', Object.keys(climb));
            console.log('[Vault] Climb tile_ids:', climb.tile_ids, 'length:', climb.tile_ids?.length);
            console.log('[Vault] tile_sequence in payload:', payload.tile_sequence?.length);

            try {
                const response = await fetch('/dev/tiles/vault-climbs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                const result = await response.json();

                if (result.success) {
                    console.log('[Vault] Created:', result.created);
                    alert(`"${name}" saved to vault!`);
                    await fetchVaultClimbs();
                    renderPatterns();
                } else {
                    alert(`Save failed: ${result.error}`);
                }
            } catch (e) {
                alert(`Save error: ${e.message}`);
            }
        }

        // ============================================
        // PATTERN RENDERING
        // ============================================
        function renderPatterns() {
            const list = document.getElementById('patternList');
            const file = state.activeFile;
            const patterns = file?.patterns;

            let patternCount = 0;

            if (!patterns) {
                list.innerHTML = `<div class="empty-state"><div class="empty-icon">&#128202;</div><div class="empty-title">No patterns detected</div><div class="empty-hint">Upload a ride file to analyze</div></div>`;
                document.getElementById('tabPatternsCount').textContent = '0';
                return;
            }

            const cards = [];

            (patterns.climb_patterns || []).forEach((climb, i) => {
                cards.push(renderClimbCard(climb, i));
                patternCount++;
            });

            if (patterns.steady_pattern) {
                cards.push(renderSteadyCard(patterns.steady_pattern));
                patternCount++;
            }

            if (patterns.exploration_pattern) {
                cards.push(renderExplorationCard(patterns.exploration_pattern));
                patternCount++;
            }

            document.getElementById('tabPatternsCount').textContent = patternCount;

            if (!cards.length) {
                list.innerHTML = `<div class="empty-state"><div class="empty-icon">&#128269;</div><div class="empty-title">No patterns found</div><div class="empty-hint">Try adjusting thresholds</div></div>`;
                return;
            }

            list.innerHTML = cards.join('');

            // Add click handlers
            list.querySelectorAll('.pattern-card[data-kind="climb"]').forEach(card => {
                card.addEventListener('click', (e) => {
                    // Don't trigger if clicking debug toggle or save-to-vault button
                    if (e.target.closest('.debug-toggle, .save-to-vault-btn')) return;

                    const idx = parseInt(card.dataset.index);
                    const climb = patterns.climb_patterns[idx];
                    selectPattern(climb, idx);
                });
            });

            // Debug toggle handlers
            list.querySelectorAll('.debug-toggle').forEach(toggle => {
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggle.classList.toggle('expanded');
                    const content = toggle.nextElementSibling;
                    content.classList.toggle('expanded');
                });
            });

            // Save to vault button handlers
            list.querySelectorAll('.save-to-vault-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const idx = parseInt(btn.dataset.climbIndex);
                    const climb = patterns.climb_patterns[idx];
                    showSaveToVaultModal(climb, idx);
                });
            });
        }

        function renderClimbCard(climb, index) {
            const isSelected = state.selectedPattern?.start_time_offset_s === climb.start_time_offset_s;
            const startTime = formatTime(climb.start_offset_s || climb.start_time_offset_s || 0);
            const endTime = formatTime(climb.end_offset_s || climb.end_time_offset_s || 0);
            const hasAttribution = !!climb.road_name;

            const vertM = climb.vert_m != null ? Math.round(climb.vert_m) : '?';
            const timeMin = climb.time_s != null ? Math.floor(climb.time_s / 60) : '?';
            const vamVal = climb.debug?.vam || (climb.time_s > 0 ? Math.round((climb.vert_m / climb.time_s) * 3600) : null);
            const distKm = climb.distance_m != null ? (climb.distance_m / 1000).toFixed(1) : null;
            const gradePct = climb.avg_gradient_pct != null ? climb.avg_gradient_pct.toFixed(1) : null;

            const cat = climb.category || 'UC';
            const catColors = { 'HC': '#dc2626', '1': '#ea580c', '2': '#eab308', '3': '#22c55e', '4': '#3b82f6', 'UC': '#64748b' };
            const catLabel = cat === 'UC' ? '' : (cat === 'HC' ? 'HC' : `Cat ${cat}`);
            const catBadge = catLabel ? `<span class="cat-badge" style="background:${catColors[cat]}">${catLabel}</span>` : '';

            const climbTitle = hasAttribution ? climb.road_name : `Climb ${index + 1}`;

            // Debug info
            const debug = climb.debug;
            let debugHtml = '';
            if (debug) {
                debugHtml = `
                    <div class="debug-toggle">
                        <span>Algorithm Debug</span>
                        <span class="chevron">&#9660;</span>
                    </div>
                    <div class="debug-content">
                        <div class="debug-row"><span class="debug-key">VAM</span><span class="debug-value">${Math.round(debug.vam)} m/hr</span></div>
                        <div class="debug-row"><span class="debug-key">Gradient Start Idx</span><span class="debug-value">${debug.gradient_start_idx}</span></div>
                        <div class="debug-row"><span class="debug-key">Peak Idx</span><span class="debug-value">${debug.peak_idx}</span></div>
                        <div class="debug-row"><span class="debug-key">Drop Triggered</span><span class="debug-value">${debug.drop_triggered_at_idx ?? 'N/A (end of ride)'}</span></div>
                        <div class="debug-row"><span class="debug-key">Samples Trimmed</span><span class="debug-value">${debug.trimmed_samples}</span></div>
                        <div class="debug-row"><span class="debug-key">Sub-segment Extracted</span><span class="debug-value">${debug.subsegment_extracted ? 'Yes' : 'No'}</span></div>
                        <div class="debug-row"><span class="debug-key">Min Vert Threshold</span><span class="debug-value">${debug.thresholds_used?.vert_min_m}m</span></div>
                        <div class="debug-row"><span class="debug-key">Min VAM Threshold</span><span class="debug-value">${debug.thresholds_used?.min_vam}</span></div>
                    </div>
                `;
            }

            return `
                <div class="pattern-card ${isSelected ? 'selected' : ''}" data-kind="climb" data-index="${index}">
                    <div class="pattern-header">
                        <span class="pattern-type climb">&#9968; ${climbTitle}${catBadge}</span>
                        <span class="pattern-time">${startTime} &#8594; ${endTime}</span>
                    </div>
                    <div class="pattern-body">
                        <div class="pattern-metrics">
                            <div class="metric"><span class="metric-value">${vertM}m</span><span class="metric-label">Elevation</span></div>
                            ${distKm ? `<div class="metric"><span class="metric-value">${distKm}km</span><span class="metric-label">Distance</span></div>` : ''}
                            ${gradePct ? `<div class="metric"><span class="metric-value">${gradePct}%</span><span class="metric-label">Gradient</span></div>` : ''}
                            <div class="metric"><span class="metric-value">${timeMin}min</span><span class="metric-label">Duration</span></div>
                            ${vamVal ? `<div class="metric"><span class="metric-value">${vamVal}</span><span class="metric-label">VAM</span></div>` : ''}
                            ${climb.avg_power_w ? `<div class="metric"><span class="metric-value">${Math.round(climb.avg_power_w)}W</span><span class="metric-label">Avg Power</span></div>` : ''}
                        </div>
                        ${hasAttribution && climb.road_coverage_pct ? `
                        <div class="attribution">
                            <div class="attribution-details">
                                <span class="attribution-stat">&#128205; ${Math.round(climb.road_coverage_pct)}% on this road</span>
                            </div>
                        </div>
                        ` : ''}
                        ${climb.vault_match ? `
                        <div class="vault-match" style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 8px 12px; border-radius: 8px; margin-top: 8px;">
                            <div style="font-weight: 600; font-size: 13px;">&#127942; Matched: ${climb.vault_match.name}</div>
                            <div style="font-size: 11px; opacity: 0.9; margin-top: 2px;">
                                ${Math.round(climb.vault_match.similarity * 100)}% similarity
                                ${climb.vault_match.is_strong_match ? ' &#9989; Verified' : ''}
                            </div>
                        </div>
                        ` : `
                        <div class="vault-save" style="margin-top: 8px;">
                            <button class="save-to-vault-btn" data-climb-index="${index}"
                                    style="width: 100%; padding: 8px 12px; background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
                                           border: none; border-radius: 8px; color: white; cursor: pointer; font-weight: 600; font-size: 12px;">
                                &#128190; Save to Vault
                            </button>
                        </div>
                        `}
                        ${debugHtml}
                    </div>
                </div>
            `;
        }

        function renderSteadyCard(steady) {
            return `
                <div class="pattern-card" data-kind="steady" data-index="0">
                    <div class="pattern-header">
                        <span class="pattern-type steady">&#128168; Steady State</span>
                    </div>
                    <div class="pattern-body">
                        <div class="pattern-metrics">
                            <div class="metric"><span class="metric-value">${Math.floor(steady.duration_s / 60)}min</span><span class="metric-label">Duration</span></div>
                            ${steady.avg_power_w ? `<div class="metric"><span class="metric-value">${Math.round(steady.avg_power_w)}W</span><span class="metric-label">Avg Power</span></div>` : ''}
                            ${steady.intensity_index ? `<div class="metric"><span class="metric-value">${(steady.intensity_index * 100).toFixed(0)}%</span><span class="metric-label">Intensity</span></div>` : ''}
                        </div>
                    </div>
                </div>
            `;
        }

        function renderExplorationCard(exp) {
            return `
                <div class="pattern-card" data-kind="explore" data-index="0">
                    <div class="pattern-header">
                        <span class="pattern-type explore">&#128506; Exploration</span>
                    </div>
                    <div class="pattern-body">
                        <div class="pattern-metrics">
                            <div class="metric"><span class="metric-value">${exp.new_tiles_wallet}</span><span class="metric-label">New Tiles</span></div>
                            <div class="metric"><span class="metric-value">${exp.total_tiles}</span><span class="metric-label">Total Tiles</span></div>
                            <div class="metric"><span class="metric-value">${((exp.new_tiles_wallet / (exp.total_tiles || 1)) * 100).toFixed(0)}%</span><span class="metric-label">Discovery</span></div>
                        </div>
                    </div>
                </div>
            `;
        }

        // ============================================
        // REJECTED SEGMENTS RENDERING
        // ============================================
        function renderRejected() {
            const list = document.getElementById('rejectedList');
            const rejected = state.rejectedSegments || [];

            document.getElementById('tabRejectedCount').textContent = rejected.length;

            if (!rejected.length) {
                list.innerHTML = `<div class="empty-state"><div class="empty-icon">&#128683;</div><div class="empty-title">No rejected segments</div><div class="empty-hint">Segments that didn't meet thresholds appear here</div></div>`;
                return;
            }

            const reasonLabels = {
                'time_too_short': 'Duration < Min',
                'time_too_long': 'Duration > Max',
                'vert_too_low': 'Vert < Min',
                'vam_too_low': 'VAM < Min'
            };

            list.innerHTML = rejected.map((seg, i) => {
                const startTime = formatTime(seg.start_time_s || 0);
                const endTime = formatTime(seg.end_time_s || 0);
                const reasonLabel = reasonLabels[seg.rejection_reason] || seg.rejection_reason;

                return `
                    <div class="rejected-card">
                        <div class="pattern-header">
                            <span class="pattern-type rejected">&#128683; Segment ${i + 1}</span>
                            <span class="rejected-reason">${reasonLabel}</span>
                        </div>
                        <div class="pattern-body">
                            <div class="pattern-metrics">
                                <div class="metric"><span class="metric-value">${Math.round(seg.vert_m)}m</span><span class="metric-label">Elevation</span></div>
                                <div class="metric"><span class="metric-value">${Math.floor(seg.time_s / 60)}min</span><span class="metric-label">Duration</span></div>
                                <div class="metric"><span class="metric-value">${Math.round(seg.vam)}</span><span class="metric-label">VAM</span></div>
                                ${seg.avg_gradient_pct ? `<div class="metric"><span class="metric-value">${seg.avg_gradient_pct.toFixed(1)}%</span><span class="metric-label">Gradient</span></div>` : ''}
                            </div>
                            <div class="debug-content expanded" style="margin-top: 0;">
                                ${Object.entries(seg.rejection_details || {}).map(([k, v]) => `
                                    <div class="debug-row"><span class="debug-key">${k}</span><span class="debug-value">${typeof v === 'number' ? v.toFixed(1) : v}</span></div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }

        function selectPattern(climb, index) {
            state.selectedPattern = climb;
            renderPatterns();
            renderClimbSegments();
            renderClimbTiles();

            // Zoom to pattern
            const file = state.activeFile;
            if (file?.enrichedTrack) {
                const startT = climb.start_offset_s || climb.start_time_offset_s || 0;
                const endT = climb.end_offset_s || climb.end_time_offset_s || 0;
                const coords = file.enrichedTrack
                    .filter(p => p.t >= startT && p.t <= endT && p.lat != null)
                    .map(p => [p.lat, p.lon]);

                if (coords.length) {
                    const bounds = L.latLngBounds(coords);
                    map.fitBounds(bounds, { padding: [80, 80] });
                }
            }

            if (elevationChart) elevationChart.update();
        }

        // ============================================
        // ELEVATION CHART
        // ============================================
        function renderElevationChart() {
            const file = state.activeFile;
            const track = file?.enrichedTrack;

            if (!track?.length) {
                elevationChart.data.datasets[0].data = [];
                elevationChart.update();
                document.getElementById('elevGain').textContent = '0m';
                document.getElementById('elevLoss').textContent = '0m';
                document.getElementById('elevMax').textContent = '0m';
                document.getElementById('elevMin').textContent = '0m';
                return;
            }

            const points = track.filter(p => p.elevation_m != null);
            if (points.length < 2) return;

            let gain = 0, loss = 0;
            for (let i = 1; i < points.length; i++) {
                const d = points[i].elevation_m - points[i - 1].elevation_m;
                if (d > 0) gain += d;
                else loss += Math.abs(d);
            }

            const elevs = points.map(p => p.elevation_m);
            const minElev = Math.min(...elevs);
            const maxElev = Math.max(...elevs);

            document.getElementById('elevGain').textContent = Math.round(gain) + 'm';
            document.getElementById('elevLoss').textContent = Math.round(loss) + 'm';
            document.getElementById('elevMax').textContent = Math.round(maxElev) + 'm';
            document.getElementById('elevMin').textContent = Math.round(minElev) + 'm';

            const chartData = points.map(p => ({
                x: p.dist_km,
                y: p.elevation_m,
                lat: p.lat,
                lon: p.lon,
                t: p.t,
                power: p.power_w,
                hr: p.hr_bpm,
                grade: p.grade
            }));

            elevationChart.data.datasets[0].data = chartData;
            elevationChart.update();
        }

        // ============================================
        // STATS
        // ============================================
        function updateStats() {
            const file = state.activeFile;
            const tiles = file?.processed?.tiles || [];
            const patterns = file?.patterns;
            const track = file?.enrichedTrack || [];

            document.getElementById('statTiles').textContent = tiles.length;

            let patternCount = 0;
            if (patterns) {
                patternCount += (patterns.climb_patterns || []).length;
                if (patterns.steady_pattern) patternCount++;
                if (patterns.exploration_pattern) patternCount++;
            }
            document.getElementById('statPatterns').textContent = patternCount;

            const dist = track.length ? track[track.length - 1].dist_km : 0;
            document.getElementById('statDistance').textContent = dist.toFixed(1);
        }

        // ============================================
        // THRESHOLD CONTROLS
        // ============================================
        const thresholdConfig = {
            climbVert: { key: 'climb_vert_min_m', suffix: 'm', display: 'climbVertVal' },
            climbTimeMin: { key: 'climb_time_min_s', suffix: 'min', display: 'climbTimeMinVal', mult: 60 },
            climbTimeMax: { key: 'climb_time_max_s', suffix: 'min', display: 'climbTimeMaxVal', mult: 60 },
            climbDrop: { key: 'climb_drop_tolerance_m', suffix: 'm', display: 'climbDropVal' },
            exploreMin: { key: 'exploration_new_tile_min', suffix: '', display: 'exploreMinVal' }
        };

        Object.entries(thresholdConfig).forEach(([id, cfg]) => {
            const input = document.getElementById(id);
            const display = document.getElementById(cfg.display);
            input?.addEventListener('input', () => {
                const val = parseInt(input.value);
                state.thresholds[cfg.key] = cfg.mult ? val * cfg.mult : val;
                display.textContent = val + cfg.suffix;
            });
        });

        // Algorithm toggle
        function setAlgorithm(algo) {
            state.thresholds.climb_algorithm = algo;
            document.getElementById('climbAlgoVal').textContent = algo;
            document.getElementById('algoLegacy').classList.toggle('active', algo === 'legacy');
            document.getElementById('algoMomentum').classList.toggle('active', algo === 'momentum');
        }
        window.setAlgorithm = setAlgorithm;

        // Smart trim toggle
        function setSmartTrim(enabled) {
            state.thresholds.climb_smart_trim = enabled;
            document.getElementById('smartTrimVal').textContent = enabled ? 'on' : 'off';
            document.getElementById('trimSimple').classList.toggle('active', !enabled);
            document.getElementById('trimSmart').classList.toggle('active', enabled);
        }
        window.setSmartTrim = setSmartTrim;

        // Signature generation toggle
        function setSignatures(enabled) {
            state.thresholds.climb_generate_signatures = enabled;
            document.getElementById('signaturesVal').textContent = enabled ? 'on' : 'off';
            document.getElementById('sigOff').classList.toggle('active', !enabled);
            document.getElementById('sigOn').classList.toggle('active', enabled);
        }
        window.setSignatures = setSignatures;

        // ============================================
        // LAYER TOGGLES
        // ============================================
        ['toggleTiles', 'toggleTrack', 'toggleClimbs', 'toggleClimbTiles', 'toggleRejected', 'toggleVault'].forEach(id => {
            const btn = document.getElementById(id);
            const key = id.replace('toggle', '').toLowerCase();
            btn?.addEventListener('click', () => {
                state.mapLayers[key] = !state.mapLayers[key];
                btn.classList.toggle('active', state.mapLayers[key]);
                updateLayerVisibility();
                if (elevationChart) elevationChart.update();
                // Fetch vault climbs on first toggle
                if (key === 'vault' && state.mapLayers.vault && !state.vaultClimbs.length) {
                    fetchVaultClimbs();
                }
                // Show/hide vault mode toggle
                if (key === 'vault') {
                    document.getElementById('vaultModeToggle').style.display =
                        state.mapLayers.vault ? 'block' : 'none';
                }
            });
        });

        // Vault mode buttons (Boxes vs Tiles)
        document.getElementById('vaultModeRect')?.addEventListener('click', () => {
            state.vaultAsTiles = false;
            document.getElementById('vaultModeRect').classList.add('active');
            document.getElementById('vaultModeRect').style.background = 'var(--bg-elevated)';
            document.getElementById('vaultModeRect').style.color = 'var(--text-secondary)';
            document.getElementById('vaultModeTiles').classList.remove('active');
            document.getElementById('vaultModeTiles').style.background = 'var(--bg-tertiary)';
            document.getElementById('vaultModeTiles').style.color = 'var(--text-tertiary)';
            renderVaultClimbs();
        });

        document.getElementById('vaultModeTiles')?.addEventListener('click', () => {
            state.vaultAsTiles = true;
            document.getElementById('vaultModeTiles').classList.add('active');
            document.getElementById('vaultModeTiles').style.background = 'var(--bg-elevated)';
            document.getElementById('vaultModeTiles').style.color = 'var(--text-secondary)';
            document.getElementById('vaultModeRect').classList.remove('active');
            document.getElementById('vaultModeRect').style.background = 'var(--bg-tertiary)';
            document.getElementById('vaultModeRect').style.color = 'var(--text-tertiary)';
            renderVaultClimbs();
        });

        // ============================================
        // ACTION BUTTONS
        // ============================================
        document.getElementById('btnRedetect')?.addEventListener('click', async () => {
            const file = state.activeFile;
            if (!file?.tileSamples) {
                console.warn('No tile samples available for redetect');
                return;
            }

            try {
                const res = await fetch('/dev/tiles/redetect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        tile_samples: file.tileSamples,
                        thresholds: state.thresholds,
                        wallet_tile_history: []
                    })
                });

                if (!res.ok) {
                    throw new Error(await res.text());
                }

                const data = await res.json();
                file.patterns = data.patterns;
                state.rejectedSegments = data.rejected_segments || [];
                state.selectedPattern = null;
                renderPatterns();
                renderRejected();
                renderClimbSegments();
                renderClimbTiles();
                renderRejectedOnMap();
                updateStats();
                if (elevationChart) elevationChart.update();
            } catch (e) {
                console.error('Redetect error:', e);
            }
        });

        document.getElementById('btnClear')?.addEventListener('click', () => {
            state.files = [];
            state.activeFile = null;
            state.selectedPattern = null;
            state.rejectedSegments = [];
            renderFileList();
            clearMapLayers();
            renderPatterns();
            renderRejected();
            renderElevationChart();
            updateStats();
            document.getElementById('inspectorSubtitle').textContent = 'No file selected';
        });

        // Handle resize
        window.addEventListener('resize', () => {
            if (elevationChart) elevationChart.resize();
        });
    </script>
</body>
</html>
"""
