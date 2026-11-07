"""Render all retained elevation samples, splitting every gap longer than30 seconds."""
import argparse, io, json, tempfile
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from fontTools.ttLib import TTFont
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, required=True)
parser.add_argument('--org', type=Path, default=Path(__file__).resolve().parent.parent,
                    help='Org source directory; default supports installation in org/terrain-source.')
args = parser.parse_args()
org = args.org.expanduser().resolve()
data = json.loads((org.parent/'portal/workshop/data/in-the-bag.json').read_text())
points = [p for p in data['ride']['samples'] if p['elevation'] is not None]
climb = next(c for c in data['climbs'] if c['id'] == '43f15658')
selected = [p for p in points if climb['start'] <= p['t'] <= climb['end']]
x = np.array([p['d']/1000 for p in points]); y = np.array([p['elevation'] for p in points])
sx = np.array([p['d']/1000 for p in selected]); sy = np.array([p['elevation'] for p in selected])
cuts = np.flatnonzero(np.diff([p['t'] for p in points]) > 30) + 1
args.output_dir.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as scratch:
    font_file = Path(scratch)/'Geist-Regular.ttf'
    font = TTFont(org/'src/app/fonts/Geist-Regular.woff2'); font.flavor = None; font.save(font_file)
    for mobile in (False, True):
        fig, ax = plt.subplots(figsize=(4, 1.25) if mobile else (7.5, 1.2), dpi=200)
        fig.patch.set_alpha(0); ax.set_facecolor('none')
        for run in np.split(np.arange(len(points)), cuts):
            ax.fill_between(x[run], y[run], 0, color='#afb6a7', linewidth=0)
            ax.plot(x[run], y[run], color='#7b8575', linewidth=.45)
        ax.fill_between(sx, sy, 0, color='#59684b', linewidth=0)
        ax.plot(sx, sy, color='#456ca0', linewidth=.75)
        ax.set_xlim(0, x[-1]); ax.set_ylim(0, 175)
        ticks = [0, 25, 50, 75, 100, x[-1]]; ax.set_xticks(ticks)
        ax.set_xticklabels([f'{v:.1f} km' if i == len(ticks)-1 else f'{v:g}' for i,v in enumerate(ticks)])
        ax.get_xticklabels()[-1].set_ha('right'); ax.get_xticklabels()[0].set_ha('left')
        if mobile: ax.get_xticklabels()[-2].set_ha('right')
        ax.set_yticks([0,175]); ax.set_yticklabels(['0 m','175 m'])
        ax.tick_params(axis='both', colors='#687062', length=0, pad=5)
        fp = FontProperties(fname=str(font_file), size=12 if mobile else 14)
        for label in ax.get_xticklabels()+ax.get_yticklabels(): label.set_fontproperties(fp)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.axhline(0, color='#9aa191', linewidth=.45)
        fig.subplots_adjust(left=.10 if mobile else .085, right=.994, top=.88, bottom=.23)
        if mobile:
            # Keep the larger top label within the image without moving any data axes.
            fig.canvas.draw()
            top_label = ax.get_yticklabels()[-1]
            left_edge = top_label.get_window_extent(fig.canvas.get_renderer()).x0
            top_label.set_x(top_label.get_position()[0] + max(0, 6-left_edge)/ax.bbox.width)
        buffer = io.BytesIO(); fig.savefig(buffer, format='png', transparent=True, dpi=200); plt.close(fig)
        Image.open(buffer).save(args.output_dir/('ride-elevation-mobile.webp' if mobile else 'ride-elevation.webp'),
                                format='WEBP', lossless=True, exact=True, method=6)
print({'samples':len(points), 'climb_samples':len(selected), 'gaps':len(cuts), 'distance_km':x[-1]})
