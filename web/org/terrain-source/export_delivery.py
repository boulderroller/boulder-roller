"""Encode the measured PNG master; explicit authoring task, never a web build step."""
import argparse, hashlib
from pathlib import Path
from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--master', type=Path, required=True)
parser.add_argument('--output-dir', type=Path, required=True)
args = parser.parse_args()
assert Image.__version__ == '11.3.0', 'Use the pinned authoring requirements'
master = Image.open(args.master).convert('RGBA')
assert master.size == (3080, 2170)
# PNG metadata may differ between Blender runs; validated RGBA pixels remain exact.
source_hash = hashlib.sha256(args.master.read_bytes()).hexdigest()[:8]
args.output_dir.mkdir(parents=True, exist_ok=True)
for width, height in [(968, 682), (1584, 1116), (3080, 2170)]:
    image = master if width == 3080 else master.resize((width, height), Image.Resampling.LANCZOS)
    stem = args.output_dir / f'wises-{source_hash}-{width}'
    image.save(stem.with_suffix('.avif'), format='AVIF', quality=90, speed=6,
               subsampling='4:4:4', max_threads=4, range='full', alpha_premultiplied=False)
    image.save(stem.with_suffix('.webp'), format='WEBP', quality=96, method=6, exact=True)
    print(width, 'encoded AVIF q90 and WebP q96')
