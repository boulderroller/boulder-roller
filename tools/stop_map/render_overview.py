"""Render published aggregate spots and public canon using local OSM and DEM."""
import argparse
from pathlib import Path
import ijson
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LightSource
from matplotlib.lines import Line2D
import numpy as np
import rasterio
from rasterio.merge import merge
from shapely import from_wkb, from_wkt
from tools.stop_map.gate_checks import load_assessment
from tools.stop_map.stop_map import TO_LL

STYLE = {'mapped control': ('#146b61', 'o'), 'likely unmapped control': ('#bb5314', '^'),
         'not a control': ('#5e458d', 's'), 'unresolved': ('#606b78', 'D')}
INK = '#1d303b'


def overlaps(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def extent(points, pad):
    lo, hi = np.min(points, axis=0)-pad, np.max(points, axis=0)+pad
    return [lo[0], lo[1], hi[0], hi[1]]


def terrain(ax, bounds, paths):
    tiles = []
    for path in paths:
        tile = rasterio.open(path)
        if overlaps(tile.bounds, bounds):
            tiles.append(tile)
        else:
            tile.close()
    if not tiles:
        return
    res = max(.00009, (bounds[2]-bounds[0])/1000, (bounds[3]-bounds[1])/1000)
    try:
        data, tr = merge(tiles, bounds=bounds, res=res, indexes=[1])
        nodata = tiles[0].nodata
    finally:
        for tile in tiles:
            tile.close()
    heights = data[0].astype(float)
    missing = ~np.isfinite(heights) | (heights == nodata)
    if missing.all():
        return
    mask = missing.copy()
    for axis in (0, 1):
        mask |= np.roll(missing, 1, axis) | np.roll(missing, -1, axis)
    work = np.where(missing, np.median(heights[~missing]), heights)
    shade = LightSource(azdeg=315, altdeg=40).hillshade(work, vert_exag=1,
        dx=res*111195*np.cos(np.radians((bounds[1]+bounds[3])/2)), dy=res*111195)
    ax.imshow(np.ma.array(shade, mask=mask), extent=(tr.c, tr.c+heights.shape[1]*tr.a,
              tr.f+heights.shape[0]*tr.e, tr.f), cmap='Greys', alpha=.3, vmin=0, vmax=1)


def basemap(ax, bounds, roads, dems, scale):
    ax.set_facecolor('#faf9f5')
    terrain(ax, bounds, dems)
    ax.add_collection(LineCollection(roads, colors='#8c9499', linewidths=.35, alpha=.55))
    ax.set(xlim=(bounds[0], bounds[2]), ylim=(bounds[1], bounds[3]))
    ax.set_aspect(1/np.cos(np.radians((bounds[1]+bounds[3])/2)))
    ax.tick_params(labelsize=7)
    ax.ticklabel_format(axis='both', style='plain', useOffset=False)
    ax.grid(alpha=.12)
    x, y = bounds[0]+.06*(bounds[2]-bounds[0]), bounds[1]+.07*(bounds[3]-bounds[1])
    width = scale/(111195*np.cos(np.radians(y)))
    ax.plot([x, x+width], [y, y], color=INK, linewidth=3)
    ax.text(x+width/2, y+.02*(bounds[3]-bounds[1]), f'{scale/1000:g} km' if scale >= 1000 else f'{scale:g} m',
            ha='center', fontsize=8, bbox={'facecolor': '#faf9f5', 'alpha': .8, 'edgecolor': 'none', 'pad': 1})
    ax.annotate('N', xy=(.95, .95), xytext=(.95, .82), xycoords='axes fraction', ha='center', fontsize=9,
                arrowprops={'arrowstyle': '->', 'color': INK})


def draw_spots(ax, spots, size=20, annotate=()):
    for kind, (color, marker) in STYLE.items():
        selected = [s for s in spots if s['class'] == kind]
        if selected:
            ax.scatter([s['position']['lon'] for s in selected], [s['position']['lat'] for s in selected],
                       s=size, c=color, marker=marker, edgecolors='#faf9f5', linewidths=.4, zorder=5)
    for s in spots:
        if s['spot_id'] in annotate:
            lon, lat = s['position']['lon'], s['position']['lat']
            ax.annotate(s['spot_id'], (lon, lat), xytext=(9, 9), textcoords='offset points', fontsize=9,
                        bbox={'facecolor': 'white', 'alpha': .85, 'edgecolor': 'none'})
            r = np.radians(s['direction']['bearing_deg'])
            ax.annotate('', xy=(lon+np.sin(r)*.0002, lat+np.cos(r)*.00015), xytext=(lon, lat),
                        arrowprops={'arrowstyle': '->', 'color': INK}, zorder=6)


def legend():
    return [Line2D([], [], color=c, marker=m, linestyle='', label=k, markersize=7) for k, (c, m) in STYLE.items()]


def render(a):
    results, registry, diff, checks, control_points = load_assessment(a.results, a.registry, a.gate_diff, a.candidates, a.topology, include_control_points=True)
    spots = results['spots']
    positions = [[s['position']['lon'], s['position']['lat']] for s in spots]
    climbs = [np.asarray(from_wkb(bytes.fromhex(r['centerline_geom'])).coords) for r in registry]
    panels = {'all': extent(positions, .035), 'Philadelphia canon': extent(np.concatenate(climbs), .009)}
    gates = []
    for row in checks:
        for field, kind in [('starts', 'start'), ('finishes', 'finish')]:
            if row[field]:
                lon, lat = TO_LL.transform(*row['line_xy'].coords[0 if kind == 'start' else -1])
                name = f"{row['registry_id']}-{row['version']}-{kind}"
                panels[name] = [lon-.00165, lat-.0013, lon+.00165, lat+.0013]
                gates.append((name, row, field, kind))
    roads = {name: [] for name in panels}
    with a.roads.open('rb') as f:
        for road in ijson.items(f, 'item', use_float=True):
            p = np.asarray(road['geometry'])
            if len(p) < 2:
                continue
            bounds = [*p.min(axis=0), *p.max(axis=0)]
            for name, box in panels.items():
                if name == 'all' and road['road_class'] not in {'Primary', 'Secondary'}:
                    continue
                if overlaps(bounds, box):
                    roads[name].append(p)
    a.output.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(15, 9.5), facecolor='#faf9f5')
    top = fig.add_axes([.055, .15, .54, .70])
    basemap(top, panels['all'], roads['all'], a.dem, 10000)
    draw_spots(top, spots, 26)
    top.set_title(f"All {len(spots)} published spots • Philadelphia region", fontsize=12, loc='left')
    for name, box in [('Philadelphia canon', [.65, .38, .30, .46])]:
        ax = fig.add_axes(box)
        basemap(ax, panels[name], roads[name], a.dem, 2000)
        ax.add_collection(LineCollection(climbs, colors='#263f57', linewidths=1, alpha=.85))
        draw_spots(ax, spots, 22)
        count = sum(panels[name][0] <= s['position']['lon'] <= panels[name][2] and panels[name][1] <= s['position']['lat'] <= panels[name][3] for s in spots)
        ax.set_title(f'{name}: {count} spots\n57 public climb centrelines', fontsize=11, loc='left')
    panel = fig.add_axes([.65, .15, .30, .17]); panel.axis('off')
    panel.text(0, 1, '\n'.join(f'{results["classification_counts"][k]:3d}  {k}' for k in STYLE),
               va='top', fontsize=12, linespacing=1.6, color=INK)
    panel.text(0, -.05, 'Classifications are inferred.\nEmpty areas do not establish an absence of stops.', fontsize=10, color=INK)
    fig.text(.055, .955, 'Where this rider repeatedly stops', fontsize=25, weight='bold', color=INK)
    fig.text(.055, .921, 'At least 3 distinct rides on 3 calendar days • endpoint exclusions applied • local/offline research', fontsize=11, color=INK)
    fig.legend(handles=legend(), loc='upper center', bbox_to_anchor=(.5, .905), ncol=4, frameon=False, fontsize=10)
    fig.text(.055, .035, 'OpenStreetMap contributors (ODbL), compiler reader export. Local USGS 3DEP terrain only where available; absent DEM stays blank.\nRounded aggregate spots only; no ride paths or endpoint masks. Overlapping marks can hide one another. No external tiles.', fontsize=9, color=INK)
    fig.savefig(a.output/'overview.png', dpi=145, facecolor=fig.get_facecolor()); plt.close(fig)
    by_id = {r['id']: r for r in registry}
    diffs = {r['registry_id']: r for r in diff['climbs']}
    by_spot = {s['spot_id']: s for s in spots}
    for name, row, field, kind in gates:
        fig, ax = plt.subplots(figsize=(10, 8.5), facecolor='#faf9f5')
        fig.subplots_adjust(left=.09, right=.96, bottom=.24, top=.85)
        basemap(ax, panels[name], roads[name], a.dem, 50)
        reg = by_id[row['registry_id']]
        p = np.asarray(from_wkb(bytes.fromhex(reg['centerline_geom'])).coords)
        ax.plot(p[:, 0], p[:, 1], color='#304d6a', linewidth=2, alpha=.7)
        p = np.asarray(from_wkb(bytes.fromhex(reg['gate_start_line' if kind == 'start' else 'gate_end_line'])).coords)
        ax.plot(p[:, 0], p[:, 1], color='#b32f40', linewidth=3, label='Original gate', zorder=6)
        d = diffs[row['registry_id']]
        if kind == 'finish' and d['finish_moved']:
            p = np.asarray(from_wkt(d['new']['gate_end_wkt']).coords)
            ax.plot(p[:, 0], p[:, 1], color='#1267a1', linewidth=3, label='Moved gate', zorder=6)
        draw_spots(ax, spots, 65, [i['spot_id'] for i in row[field]])
        for item in row[field]:
            control = by_spot[item['spot_id']]['matched_control']
            if control and control['osm_node_id'] in control_points:
                lon, lat = TO_LL.transform(*control_points[control['osm_node_id']])
                ax.scatter([lon], [lat], c=INK, marker='x', s=60, zorder=7, label='Matched OSM control')
                ax.annotate('OSM '+control['kind'], (lon, lat), xytext=(30, -30), textcoords='offset points', fontsize=9,
                            arrowprops={'arrowstyle': '-', 'color': INK, 'linewidth': .8},
                            bbox={'facecolor': 'white', 'alpha': .8, 'edgecolor': 'none'})
        fig.suptitle(f"{row['name']} — {row['version']} {kind}", fontsize=19, x=.09, ha='left', y=.96, weight='bold')
        fig.text(.09, .905, f"Canon {row['canon_id']} • {row['registry_id']}", fontsize=9, color=INK)
        descriptions = []
        for item in row[field]:
            s = by_spot[item['spot_id']]
            dist = item['from_start_m'] if kind == 'start' else item['past_finish_m']
            descriptions.append(f"{s['spot_id']}: {dist:+.1f} m from {kind}; {s['ride_count']} rides / {s['day_count']} days; median {s['median_length_s']:g} s; {s['class']}")
        fig.text(.09, .19, '\n'.join(descriptions), fontsize=9, linespacing=1.6)
        handles, _ = ax.get_legend_handles_labels()
        fig.legend(handles=handles+legend(), loc='lower center', bbox_to_anchor=(.5, .068), ncol=3, frameon=False, fontsize=9)
        fig.text(.09, .025, 'OSM contributors / local USGS 3DEP. Rounded spot medians; no ride tracks. A flag is a review lead, not a surveyed stop line.', fontsize=8)
        fig.savefig(a.output/(name+'.png'), dpi=145, facecolor=fig.get_facecolor()); plt.close(fig)
    total = sum(p.stat().st_size for p in a.output.glob('*.png'))
    assert total < 20_000_000, f'Render budget exceeded: {total}'
    print(f'Wrote overview and {len(gates)} gate close-ups; {total:,} bytes total')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['results', 'registry', 'gate-diff', 'candidates', 'topology', 'roads', 'output']:
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--dem', type=Path, action='append', required=True)
    render(p.parse_args())
