"""Production bake for the numbered rank marks (ranks 4 through 50).

Every rank bakes exactly one designed state: its tab wash derives from rank
alone under the ratified Halo tab codex (2026-08-31). There are no charge
steps.

Run from the repository root:

    /Applications/Blender.app/Contents/MacOS/Blender -b -P tools/rankmarks/bake.py

Arguments for focused validation may be supplied after ``--``. The default
invocation is the production bake and always emits the complete asset set.
"""

import argparse
import importlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import zlib

import bpy
import numpy as np


# Placeholder rank split from boulderroller-v2-dtgj1.1. Rank-math
# ratification changes this block only; rendering and manifest code derive all
# assignments from it.
BANDS = (
    dict(name='iron', rank_min=43, rank_max=50, hex='6E6A63', hardness=1.00,
         corner_hex='9C6234'),
    dict(name='bronze', rank_min=35, rank_max=42, hex='9C6234', hardness=0.85,
         corner_hex='447A4E'),
    dict(name='green', rank_min=27, rank_max=34, hex='447A4E', hardness=0.68,
         corner_hex='4F8BC9'),
    dict(name='cobalt', rank_min=19, rank_max=26, hex='4F8BC9', hardness=0.52,
         corner_hex='7743AB'),
    dict(name='plum', rank_min=11, rank_max=18, hex='7743AB', hardness=0.36,
         corner_hex='AC3F3A'),
    dict(name='crimson', rank_min=4, rank_max=10, hex='AC3F3A', hardness=0.20,
         corner_hex='AC3F3A'),
)

SCALES = (('1x', 120), ('2x', 240), ('3x', 360))

# Ratified tab codex (2026-08-31, final form after the band-aligned detour):
# tab count and band color are two INDEPENDENT cycles — the interleave is
# what makes every rank unique, per the Halo 2 reference. Tab tiers map
# Halo's ascending thresholds (2 tabs at 16, 3 at 28, full at 40) onto our
# descending ladder: clean 50-45, one tab 44-36, two tabs 35-24, three
# tabs 23-12, full flood 11-4. Rotation advances every 3 ranks. Wash is
# always the next band's color; crimson washes in its own red.
ROT1 = (('TL',), ('TR',), ('BR',), ('BL',))
ROT2 = (('TL', 'TR'), ('TR', 'BR'), ('BR', 'BL'), ('BL', 'TL'))
ROT3 = (
    ('TL', 'TR', 'BR'), ('TR', 'BR', 'BL'),
    ('BR', 'BL', 'TL'), ('BL', 'TL', 'TR'),
)


def codex_tabs(rank):
    if rank >= 45:
        return None
    if rank >= 36:
        return list(ROT1[(44 - rank) // 3 % 4])
    if rank >= 24:
        return list(ROT2[(35 - rank) // 3 % 4])
    if rank >= 12:
        return list(ROT3[(23 - rank) // 3 % 4])
    return 'FULL'
DETAIL_SIZE = 1024
PRODUCTION_SAMPLES = 128
RANK_MIN = 4
RANK_MAX = 50

HERE = Path(__file__).resolve().parent
BUILD_DIR = HERE / 'build'
FONT_PATH = HERE / 'fonts' / 'archivo-black.ttf'
REFERENCE_SHEET = Path('docs/design/renderings/rankmarks/ladder_sheet.png')
REPO_ROOT = HERE.parent.parent

PODIUM_MARKS = (
    dict(
        rank=1,
        name='crown',
        tile_hex='0B0A0C',
        builder='build_crown',
        reference='docs/design/renderings/rankmarks/nt_crown.png',
    ),
    dict(
        rank=2,
        name='laurel',
        tile_hex='0E120E',
        builder='build_laurel',
        reference='docs/design/renderings/rankmarks/nt_laurel.png',
    ),
    dict(
        rank=3,
        name='cobble',
        tile_hex='121110',
        builder='build_cobble',
        reference='docs/design/renderings/rankmarks/nt_cobble.png',
    ),
)
PODIUM_IMPORT_SENTINEL = '--only=__rankmarks_bake_import__'
_podium_source = None

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paramset  # noqa: E402  (Blender-local shared mark geometry/materials)


def load_podium_source():
    """Load the accepted podium source without running its look-dev exports."""
    global _podium_source
    if _podium_source is not None:
        return _podium_source

    sys.argv.append(PODIUM_IMPORT_SENTINEL)
    try:
        _podium_source = importlib.import_module('podium_night')
    finally:
        if sys.argv[-1] == PODIUM_IMPORT_SENTINEL:
            sys.argv.pop()
        else:
            sys.argv.remove(PODIUM_IMPORT_SENTINEL)
    return _podium_source


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--output', type=Path, default=BUILD_DIR,
        help='Output directory (default: tools/rankmarks/build).',
    )
    parser.add_argument(
        '--ranks',
        help='Focused comma/range selection for validation, e.g. 45 or 45-39,4.',
    )
    parser.add_argument(
        '--samples', type=int, default=PRODUCTION_SAMPLES,
        help='Cycles samples. Production default is 128.',
    )
    parser.add_argument(
        '--validate-only', action='store_true',
        help='Validate config and exit without rendering.',
    )
    parser.add_argument(
        '--podium-only', action='store_true',
        help='Bake accepted ranks 1-3 and extend the numbered manifest/sheet.',
    )
    return parser.parse_args(argv)


def normalized_hex(value):
    return value.lstrip('#').upper()


def parse_rank_selection(raw):
    if not raw:
        return list(range(RANK_MAX, RANK_MIN - 1, -1))

    ranks = set()
    for part in raw.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            first, last = (int(value) for value in part.split('-', 1))
            low, high = sorted((first, last))
            ranks.update(range(low, high + 1))
        else:
            ranks.add(int(part))
    return sorted(ranks, reverse=True)


def band_for_rank(rank):
    matches = [
        band for band in BANDS
        if band['rank_min'] <= rank <= band['rank_max']
    ]
    if len(matches) != 1:
        raise ValueError(f'rank {rank} has {len(matches)} band assignments')
    return matches[0]


def validate_config(ranks, samples):
    if samples <= 0:
        raise ValueError('samples must be positive')
    if not FONT_PATH.is_file():
        raise FileNotFoundError(f'Archivo Black is missing: {FONT_PATH}')
    if not ranks:
        raise ValueError('at least one rank is required')
    if any(rank < RANK_MIN or rank > RANK_MAX for rank in ranks):
        raise ValueError(f'only numbered ranks {RANK_MIN}..{RANK_MAX} are allowed')

    band_names = set()
    for band in BANDS:
        if band['name'] in band_names:
            raise ValueError(f"duplicate band name: {band['name']}")
        band_names.add(band['name'])
        for key in ('hex', 'corner_hex'):
            value = normalized_hex(band[key])
            if len(value) != 6 or any(c not in '0123456789ABCDEF' for c in value):
                raise ValueError(f"invalid {key} for {band['name']}: {band[key]}")
        if not 0.0 <= band['hardness'] <= 1.0:
            raise ValueError(f"invalid hardness for {band['name']}")
        if band['rank_min'] > band['rank_max']:
            raise ValueError(f"inverted range for {band['name']}")

    expected = set(range(RANK_MIN, RANK_MAX + 1))
    assigned = []
    for band in BANDS:
        assigned.extend(range(band['rank_min'], band['rank_max'] + 1))
    if set(assigned) != expected or len(assigned) != len(expected):
        raise ValueError('BANDS must cover ranks %d..%d exactly once' % (RANK_MIN, RANK_MAX))
    for rank in ranks:
        band_for_rank(rank)


def validate_podium_config(samples):
    if samples <= 0:
        raise ValueError('samples must be positive')

    source = load_podium_source()
    accepted_scenes = {
        name: (tile_hex, builder.__name__)
        for name, tile_hex, builder in source.SCENES
    }
    for mark in PODIUM_MARKS:
        expected = (mark['tile_hex'], mark['builder'])
        actual = accepted_scenes.get(mark['name'])
        if actual != expected:
            raise ValueError(
                f"podium source drift for rank {mark['rank']}: "
                f'expected {expected}, found {actual}'
            )
        reference = REPO_ROOT / mark['reference']
        if not reference.is_file():
            raise FileNotFoundError(f'accepted podium render is missing: {reference}')


def add_area_light(location, rotation_degrees, size, energy,
                   color=(1.0, 1.0, 1.0), spread=180):
    rotation = tuple(math.radians(value) for value in rotation_degrees)
    bpy.ops.object.light_add(type='AREA', location=location, rotation=rotation)
    light = bpy.context.object
    light.data.size = size
    light.data.energy = energy
    light.data.color = color
    try:
        light.data.spread = math.radians(spread)
    except Exception:
        pass
    return light


def configure_single_mark_rig(scene):
    # Accepted single-mark poses/colors/spreads, with the numbered-bake energy
    # overrides ratified in boulderroller-v2-dtgj1.1.
    add_area_light(
        (-2.4, 1.9, 3.6), (-30, -30, 0), 2.6, 170,
        (1.0, 0.96, 0.88), 55,
    )
    add_area_light(
        (2.7, -1.2, 2.0), (24, 40, 0), 1.2, 90,
        (0.82, 0.90, 1.0), 60,
    )
    add_area_light((0.4, -2.6, 3.0), (35, 0, 0), 4.0, 24)

    scene.world = bpy.data.worlds.new('w')
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes['Background']
    background.inputs['Color'].default_value = paramset.hexc('1A1A1E')
    background.inputs['Strength'].default_value = 0.55

    bpy.ops.object.camera_add(
        location=(0, -0.5, 4.2),
        rotation=(math.radians(6.5), 0, 0),
    )
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = 2.5
    scene.camera = camera


def configure_cycles(scene, samples):
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.use_persistent_data = True

    try:
        preferences = bpy.context.preferences.addons['cycles'].preferences
        preferences.compute_device_type = 'METAL'
        preferences.get_devices()
        for device in preferences.devices:
            device.use = True
        scene.cycles.device = 'GPU'
    except Exception as error:
        scene.cycles.device = 'CPU'
        print(f'RANKMARKS: Metal unavailable; using CPU ({error})', flush=True)


def configure_alpha_output(scene):
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.image_settings.compression = 15


def configure_post(scene):
    # The production bakes keep the accepted glare and grade only. There is no
    # ground plane and no ellipse-mask vignette on the transparent sprites.
    scene.use_nodes = True
    tree = scene.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)

    render_layers = tree.nodes.new('CompositorNodeRLayers')
    glare = tree.nodes.new('CompositorNodeGlare')
    glare.glare_type = 'FOG_GLOW'
    glare.quality = 'HIGH'
    glare.threshold = 2.2
    glare.size = 6
    try:
        glare.mix = -0.55
    except Exception:
        pass

    color = tree.nodes.new('CompositorNodeColorCorrection')
    color.master_contrast = 1.07
    color.master_gain = 1.02
    color.master_lift = -0.005
    composite = tree.nodes.new('CompositorNodeComposite')

    tree.links.new(render_layers.outputs['Image'], glare.inputs['Image'])
    tree.links.new(glare.outputs['Image'], color.inputs['Image'])
    tree.links.new(color.outputs['Image'], composite.inputs['Image'])


def build_rank_scene(rank, band, samples):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene

    paramset.mark(
        str(rank), normalized_hex(band['hex']), None, band['hardness'],
        normalized_hex(band['corner_hex']), 0.0, 0.0,
        tabs=codex_tabs(rank),
    )

    configure_single_mark_rig(scene)
    configure_cycles(scene, samples)
    configure_alpha_output(scene)
    configure_post(scene)
    return scene


def build_podium_scene(mark, samples):
    """Adapt the accepted look-dev scene only at the production-output edge."""
    source = load_podium_source()
    builder = getattr(source, mark['builder'])
    source.build(mark['name'], mark['tile_hex'], builder)
    scene = bpy.context.scene

    # The accepted portrait has one 20x20 catcher plane behind the mark. The
    # production sprite keeps the mark's own tile but removes that ground.
    ground = bpy.data.objects.get('Plane')
    if (
        ground is None
        or ground.type != 'MESH'
        or ground.dimensions.x < 19.0
        or ground.dimensions.y < 19.0
    ):
        raise RuntimeError(f"accepted ground plane not found for {mark['name']}")
    bpy.data.objects.remove(ground, do_unlink=True)

    scene.cycles.samples = samples
    scene.render.use_persistent_data = True
    configure_alpha_output(scene)
    configure_post(scene)
    return scene


def rank_prefix(rank):
    return f'rank{rank:02d}'


def sprite_filename(rank, scale_name):
    return f'{rank_prefix(rank)}@{scale_name}.png'


def detail_filename(rank):
    return f'{rank_prefix(rank)}_detail.png'


def podium_prefix(mark):
    return f"rank{mark['rank']:02d}_{mark['name']}"


def podium_sprite_filename(mark, scale_name):
    return f'{podium_prefix(mark)}@{scale_name}.png'


def podium_detail_filename(mark):
    return f'{podium_prefix(mark)}_detail.png'


def render_png(scene, output_path, size):
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=True)
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError(f'render did not produce {output_path}')


def png_dimensions_and_type(path):
    with path.open('rb') as handle:
        signature = handle.read(8)
        if signature != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'not a PNG: {path}')
        length = struct.unpack('>I', handle.read(4))[0]
        kind = handle.read(4)
        payload = handle.read(length)
    if kind != b'IHDR' or len(payload) != 13:
        raise ValueError(f'missing PNG IHDR: {path}')
    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack('>IIBBBBB', payload)
    )
    if compression != 0 or filtering != 0 or interlace != 0:
        raise ValueError(f'unsupported PNG encoding: {path}')
    return width, height, bit_depth, color_type


def paeth_predictor(left, up, upper_left):
    estimate = left + up - upper_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    diagonal_distance = abs(estimate - upper_left)
    if left_distance <= up_distance and left_distance <= diagonal_distance:
        return left
    if up_distance <= diagonal_distance:
        return up
    return upper_left


def read_rgba_png(path):
    payloads = []
    width = height = None
    with path.open('rb') as handle:
        if handle.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'not a PNG: {path}')
        while True:
            length_bytes = handle.read(4)
            if not length_bytes:
                break
            length = struct.unpack('>I', length_bytes)[0]
            kind = handle.read(4)
            payload = handle.read(length)
            checksum = handle.read(4)
            expected_crc = struct.unpack('>I', checksum)[0]
            actual_crc = zlib.crc32(kind)
            actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                raise ValueError(f'PNG CRC mismatch: {path}')
            if kind == b'IHDR':
                width, height, depth, color_type, compression, filtering, interlace = (
                    struct.unpack('>IIBBBBB', payload)
                )
                if (depth, color_type, compression, filtering, interlace) != (8, 6, 0, 0, 0):
                    raise ValueError(f'expected non-interlaced 8-bit RGBA PNG: {path}')
            elif kind == b'IDAT':
                payloads.append(payload)
            elif kind == b'IEND':
                break

    if width is None or height is None or not payloads:
        raise ValueError(f'incomplete PNG: {path}')

    raw = zlib.decompress(b''.join(payloads))
    bytes_per_pixel = 4
    stride = width * bytes_per_pixel
    expected_length = height * (stride + 1)
    if len(raw) != expected_length:
        raise ValueError(f'unexpected PNG payload length: {path}')

    decoded = bytearray(height * stride)
    previous = bytearray(stride)
    offset = 0
    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset:offset + stride])
        offset += stride
        for x in range(stride):
            left = row[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
            up = previous[x]
            upper_left = previous[x - bytes_per_pixel] if x >= bytes_per_pixel else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = up
            elif filter_type == 3:
                predictor = (left + up) // 2
            elif filter_type == 4:
                predictor = paeth_predictor(left, up, upper_left)
            else:
                raise ValueError(f'unknown PNG filter {filter_type}: {path}')
            row[x] = (row[x] + predictor) & 0xFF
        start = y * stride
        decoded[start:start + stride] = row
        previous = row

    return np.frombuffer(decoded, dtype=np.uint8).reshape(height, width, 4).copy()


def png_chunk(kind, payload):
    crc = zlib.crc32(kind)
    crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', crc)


def write_rgba_png(path, pixels):
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 4:
        raise ValueError('contact sheet pixels must be uint8 RGBA')
    height, width, _ = pixels.shape
    scanlines = b''.join(
        b'\x00' + pixels[y].tobytes() for y in range(height)
    )
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    contents = (
        b'\x89PNG\r\n\x1a\n'
        + png_chunk(b'IHDR', ihdr)
        + png_chunk(b'sRGB', b'\x00')
        + png_chunk(b'IDAT', zlib.compress(scanlines, level=9))
        + png_chunk(b'IEND', b'')
    )
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(contents)
    os.replace(temporary, path)


def srgb_to_linear(values):
    values = values.astype(np.float32) / 255.0
    return np.where(
        values <= 0.04045,
        values / 12.92,
        ((values + 0.055) / 1.055) ** 2.4,
    )


def linear_to_srgb(values):
    values = np.clip(values, 0.0, 1.0)
    encoded = np.where(
        values <= 0.0031308,
        values * 12.92,
        1.055 * (values ** (1.0 / 2.4)) - 0.055,
    )
    return np.rint(encoded * 255.0).astype(np.uint8)


def composite_sprite(sprite, background_srgb):
    alpha = sprite[:, :, 3:4].astype(np.float32) / 255.0
    sprite_linear = srgb_to_linear(sprite[:, :, :3])
    background_linear = srgb_to_linear(background_srgb)
    composite_linear = (
        sprite_linear * alpha
        + background_linear.reshape(1, 1, 3) * (1.0 - alpha)
    )
    composite = np.empty_like(sprite)
    composite[:, :, :3] = linear_to_srgb(composite_linear)
    composite[:, :, 3] = 255
    return composite


def make_contact_sheet(output_dir, ranks):
    columns = min(7, len(ranks))
    rows = math.ceil(len(ranks) / columns)
    cell_size = SCALES[0][1]
    background_srgb = np.array([0x0B, 0x0A, 0x09], dtype=np.uint8)

    canvas = np.empty((rows * cell_size, columns * cell_size, 4), dtype=np.uint8)
    canvas[:, :, :3] = background_srgb
    canvas[:, :, 3] = 255

    for index, rank in enumerate(ranks):
        sprite = read_rgba_png(output_dir / sprite_filename(rank, '1x'))
        if sprite.shape != (cell_size, cell_size, 4):
            raise ValueError(f'unexpected contact-sheet sprite size for rank {rank}')

        composite = composite_sprite(sprite, background_srgb)

        row, column = divmod(index, columns)
        y = row * cell_size
        x = column * cell_size
        canvas[y:y + cell_size, x:x + cell_size] = composite

    output_path = output_dir / 'contact_sheet.png'
    write_rgba_png(output_path, canvas)
    return output_path


def numbered_manifest(output_dir):
    path = output_dir / 'manifest.json'
    if not path.is_file():
        raise FileNotFoundError(f'numbered manifest is missing: {path}')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    expected_ranks = {str(rank) for rank in range(RANK_MIN, RANK_MAX + 1)}
    if manifest.get('schema_version') != 2:
        raise ValueError('numbered manifest schema_version must be 2')
    if set(manifest.get('ranks', {})) != expected_ranks:
        raise ValueError(f'numbered manifest must contain ranks {RANK_MIN}..{RANK_MAX}')
    if manifest.get('counts', {}).get('ranks') != len(expected_ranks):
        raise ValueError('numbered manifest rank count is inconsistent')
    return manifest


def contact_sheet_cell(sheet, index, columns, cell_size):
    row, column = divmod(index, columns)
    y = row * cell_size
    x = column * cell_size
    if y + cell_size > sheet.shape[0] or x + cell_size > sheet.shape[1]:
        raise ValueError(f'contact sheet does not contain cell {index}')
    return sheet[y:y + cell_size, x:x + cell_size].copy()


def write_combined_contact_sheet(output_dir, manifest, podium_cells):
    contact = manifest['contact_sheet']
    columns = contact['columns']
    cell_size = SCALES[0][1]
    numbered_count = manifest['counts']['ranks']
    background_hex = contact['background_hex'].lstrip('#')
    background_srgb = np.array(
        [int(background_hex[index:index + 2], 16) for index in (0, 2, 4)],
        dtype=np.uint8,
    )

    source_path = output_dir / contact['file']
    source = read_rgba_png(source_path)
    if source.shape[1] != columns * cell_size:
        raise ValueError('numbered contact sheet width is inconsistent')

    total_count = numbered_count + len(podium_cells)
    rows = math.ceil(total_count / columns)
    canvas = np.empty((rows * cell_size, columns * cell_size, 4), dtype=np.uint8)
    canvas[:, :, :3] = background_srgb
    canvas[:, :, 3] = 255

    for index in range(numbered_count):
        cell = contact_sheet_cell(source, index, columns, cell_size)
        row, column = divmod(index, columns)
        y = row * cell_size
        x = column * cell_size
        canvas[y:y + cell_size, x:x + cell_size] = cell

    for offset, cell in enumerate(podium_cells):
        if cell.shape != (cell_size, cell_size, 4):
            raise ValueError('unexpected podium contact-sheet cell size')
        index = numbered_count + offset
        row, column = divmod(index, columns)
        y = row * cell_size
        x = column * cell_size
        canvas[y:y + cell_size, x:x + cell_size] = cell

    write_rgba_png(source_path, canvas)
    return source_path


def rendered_podium_contact_cells(output_dir, manifest):
    background_hex = manifest['contact_sheet']['background_hex'].lstrip('#')
    background_srgb = np.array(
        [int(background_hex[index:index + 2], 16) for index in (0, 2, 4)],
        dtype=np.uint8,
    )
    marks_descending = sorted(PODIUM_MARKS, key=lambda mark: mark['rank'], reverse=True)
    return [
        composite_sprite(
            read_rgba_png(output_dir / podium_sprite_filename(mark, '1x')),
            background_srgb,
        )
        for mark in marks_descending
    ]


def rank_manifest(rank, band):
    files = {
        scale_name: sprite_filename(rank, scale_name)
        for scale_name, _ in SCALES
    }
    files['detail'] = detail_filename(rank)
    tabs = codex_tabs(rank)
    return {
        'band': band['name'],
        'band_hex': f"#{normalized_hex(band['hex'])}",
        'hardness': band['hardness'],
        'corner_hex': f"#{normalized_hex(band['corner_hex'])}",
        'tabs': tabs,
        'files': files,
    }


def podium_rank_manifest(mark):
    files = {
        scale_name: podium_sprite_filename(mark, scale_name)
        for scale_name, _ in SCALES
    }
    files['detail'] = podium_detail_filename(mark)
    return {
        'name': mark['name'],
        'tile_hex': f"#{mark['tile_hex']}",
        'reference': mark['reference'],
        'files': files,
    }


def build_podium_manifest(samples):
    scale_sprite_count = len(PODIUM_MARKS) * len(SCALES)
    detail_count = len(PODIUM_MARKS)
    return {
        'design_authority': {
            'bead': 'boulderroller-v2-dtgj1.2',
            'source': 'tools/rankmarks/podium_night.py',
        },
        'rank_range': {'min': 1, 'max': 3, 'order': 'ascending'},
        'corner_charge': False,
        'scales': {name: pixels for name, pixels in SCALES},
        'detail_pixels': DETAIL_SIZE,
        'render': {
            'engine': 'CYCLES',
            'samples': samples,
            'denoise': True,
            'alpha': True,
            'ground_plane': False,
            'vignette': False,
            'glare': {'type': 'FOG_GLOW', 'threshold': 2.2, 'size': 6, 'mix': -0.55},
            'color_correction': {'contrast': 1.07, 'gain': 1.02, 'lift': -0.005},
        },
        'counts': {
            'ranks': len(PODIUM_MARKS),
            'scale_sprites': scale_sprite_count,
            'details': detail_count,
            'rank_assets': scale_sprite_count + detail_count,
        },
        'ranks': {
            str(mark['rank']): podium_rank_manifest(mark)
            for mark in PODIUM_MARKS
        },
    }


def add_podium_to_manifest(manifest, samples, podium=None):
    manifest['podium'] = podium or build_podium_manifest(samples)
    manifest['contact_sheet']['entries'] = (
        manifest['counts']['ranks'] + len(PODIUM_MARKS)
    )
    manifest['contact_sheet']['rank_range'] = {
        'min': 1,
        'max': RANK_MAX,
        'order': 'descending',
    }
    return manifest


def build_manifest(ranks, samples):
    sprite_count = len(ranks) * len(SCALES)
    detail_count = len(ranks)
    return {
        'schema_version': 2,
        'generator': 'tools/rankmarks/bake.py',
        'design_authority': {
            'bead': 'boulderroller-v2-dtgj1.1',
            'source': 'tools/rankmarks/paramset.py',
            'reference': str(REFERENCE_SHEET),
            'font': 'tools/rankmarks/fonts/archivo-black.ttf',
        },
        'rank_range': {'min': min(ranks), 'max': max(ranks), 'order': 'descending'},
        'codex': {
            'ratified': '2026-08-31',
            'derivation': 'tab state derives from rank alone; no charge steps',
            'tiers': {
                'clean': '50-45',
                'one_tab': '44-36',
                'two_tabs': '35-24',
                'three_tabs': '23-12',
                'flood': '11-4',
            },
            'rotation': 'every 3 ranks, TL->TR->BR->BL',
            'independence': 'tab tier and band color are independent cycles; '
                            'their interleave makes every rank unique',
            'wash': 'next band color; crimson washes in its own red',
        },
        'scales': {name: pixels for name, pixels in SCALES},
        'detail_pixels': DETAIL_SIZE,
        'render': {
            'engine': 'CYCLES',
            'samples': samples,
            'denoise': True,
            'alpha': True,
            'ground_plane': False,
            'vignette': False,
            'glare': {'type': 'FOG_GLOW', 'threshold': 2.2, 'size': 6, 'mix': -0.55},
            'color_correction': {'contrast': 1.07, 'gain': 1.02, 'lift': -0.005},
        },
        'counts': {
            'ranks': len(ranks),
            'scale_sprites': sprite_count,
            'details': detail_count,
            'rank_assets': sprite_count + detail_count,
        },
        'contact_sheet': {
            'file': 'contact_sheet.png',
            'scale': '1x',
            'columns': min(7, len(ranks)),
            'background_hex': '#0B0A09',
        },
        'ranks': {
            str(rank): rank_manifest(rank, band_for_rank(rank))
            for rank in ranks
        },
    }


def write_manifest(output_dir, manifest):
    output_path = output_dir / 'manifest.json'
    temporary = output_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, output_path)
    return output_path


def validate_outputs(output_dir, ranks):
    expected = {}
    for rank in ranks:
        for scale_name, pixels in SCALES:
            expected[output_dir / sprite_filename(rank, scale_name)] = pixels
        expected[output_dir / detail_filename(rank)] = DETAIL_SIZE

    for path, pixels in expected.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f'missing output: {path}')
        width, height, bit_depth, color_type = png_dimensions_and_type(path)
        if (width, height, bit_depth, color_type) != (pixels, pixels, 8, 6):
            raise RuntimeError(
                f'bad PNG contract for {path}: '
                f'{width}x{height}, depth={bit_depth}, color_type={color_type}'
            )

    # Check actual transparency rather than only the presence of an alpha
    # channel. One baseline sprite per rank also feeds the contact sheet.
    for rank in ranks:
        baseline = read_rgba_png(output_dir / sprite_filename(rank, '1x'))
        alpha = baseline[:, :, 3]
        if alpha[0, 0] > 8 or alpha[-1, -1] > 8:
            raise RuntimeError(f'rank {rank} sprite corners are not transparent')
        center = alpha[alpha.shape[0] // 2, alpha.shape[1] // 2]
        if center < 247:
            raise RuntimeError(f'rank {rank} sprite center is not opaque')
    return len(expected)


def validate_podium_outputs(output_dir):
    expected = {}
    for mark in PODIUM_MARKS:
        for scale_name, pixels in SCALES:
            expected[output_dir / podium_sprite_filename(mark, scale_name)] = pixels
        expected[output_dir / podium_detail_filename(mark)] = DETAIL_SIZE

    for path, pixels in expected.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f'missing output: {path}')
        width, height, bit_depth, color_type = png_dimensions_and_type(path)
        if (width, height, bit_depth, color_type) != (pixels, pixels, 8, 6):
            raise RuntimeError(
                f'bad PNG contract for {path}: '
                f'{width}x{height}, depth={bit_depth}, color_type={color_type}'
            )

    for mark in PODIUM_MARKS:
        baseline = read_rgba_png(
            output_dir / podium_sprite_filename(mark, '1x')
        )
        alpha = baseline[:, :, 3]
        if alpha[0, 0] > 8 or alpha[-1, -1] > 8:
            raise RuntimeError(
                f"rank {mark['rank']} {mark['name']} sprite corners are not transparent"
            )
        center = alpha[alpha.shape[0] // 2, alpha.shape[1] // 2]
        if center < 247:
            raise RuntimeError(
                f"rank {mark['rank']} {mark['name']} sprite center is not opaque"
            )
    return len(expected)


def bake(output_dir, ranks, samples):
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f'RANKMARKS: baking {len(ranks)} ranks '
        f'x {len(SCALES)} scales + detail at {samples} samples',
        flush=True,
    )

    for rank_index, rank in enumerate(ranks, start=1):
        band = band_for_rank(rank)
        scene = build_rank_scene(rank, band, samples)

        for scale_name, pixels in SCALES:
            render_png(
                scene,
                output_dir / sprite_filename(rank, scale_name),
                pixels,
            )
        render_png(scene, output_dir / detail_filename(rank), DETAIL_SIZE)
        print(
            f'RANKMARKS: rank {rank:02d} ({band["name"]}) '
            f'{rank_index}/{len(ranks)} complete',
            flush=True,
        )

    asset_count = validate_outputs(output_dir, ranks)
    contact_sheet = make_contact_sheet(output_dir, ranks)
    manifest = build_manifest(ranks, samples)
    manifest_path = write_manifest(output_dir, manifest)
    print(
        f'RANKMARKS: numbered complete — {asset_count} rank assets, '
        f'{contact_sheet.name}, {manifest_path.name}',
        flush=True,
    )


def bake_podium(output_dir, samples):
    manifest = numbered_manifest(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(
        f'RANKMARKS: baking {len(PODIUM_MARKS)} podium ranks '
        f'x {len(SCALES)} scales + detail at {samples} samples',
        flush=True,
    )

    for mark_index, mark in enumerate(PODIUM_MARKS, start=1):
        scene = build_podium_scene(mark, samples)
        for scale_name, pixels in SCALES:
            render_png(
                scene,
                output_dir / podium_sprite_filename(mark, scale_name),
                pixels,
            )
        render_png(
            scene,
            output_dir / podium_detail_filename(mark),
            DETAIL_SIZE,
        )
        print(
            f"RANKMARKS: rank {mark['rank']:02d} ({mark['name']}) "
            f'{mark_index}/{len(PODIUM_MARKS)} complete',
            flush=True,
        )

    asset_count = validate_podium_outputs(output_dir)
    podium_cells = rendered_podium_contact_cells(output_dir, manifest)
    contact_sheet = write_combined_contact_sheet(
        output_dir, manifest, podium_cells
    )
    add_podium_to_manifest(manifest, samples)
    manifest_path = write_manifest(output_dir, manifest)
    print(
        f'RANKMARKS: podium complete — {asset_count} rank assets, '
        f'{contact_sheet.name}, {manifest_path.name}',
        flush=True,
    )


def main():
    args = parse_args()
    if args.podium_only and args.ranks:
        raise ValueError('--podium-only cannot be combined with --ranks')
    if args.podium_only:
        validate_podium_config(args.samples)
        if args.validate_only:
            print(
                f'RANKMARKS: podium config valid for {len(PODIUM_MARKS)} ranks; '
                f'{len(PODIUM_MARKS) * (len(SCALES) + 1)} rank assets',
                flush=True,
            )
            return
        bake_podium(args.output.resolve(), args.samples)
        return

    ranks = parse_rank_selection(args.ranks)
    validate_config(ranks, args.samples)
    full_production = args.ranks is None
    if full_production:
        validate_podium_config(args.samples)
    if args.validate_only:
        print(
            f'RANKMARKS: config valid for {len(ranks)} ranks; '
            f'{len(ranks) * (len(SCALES) + 1)} rank assets',
            flush=True,
        )
        if full_production:
            print(
                f'RANKMARKS: podium config valid for {len(PODIUM_MARKS)} ranks; '
                f'{len(PODIUM_MARKS) * (len(SCALES) + 1)} rank assets',
                flush=True,
            )
        return
    bake(args.output.resolve(), ranks, args.samples)
    if full_production:
        bake_podium(args.output.resolve(), args.samples)


if __name__ == '__main__':
    main()
