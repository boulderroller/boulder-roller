"""THE LADDER — all 47 numbered marks, each with its codex-derived wash.

Tab state derives from rank alone (the committed Halo codex):
clean entry -> one tab rotating -> two -> three -> the lone four-tab
'surrounded' mark at 11 -> the pure crimson summit band.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy
import paramset
from paramset import mark, hexc, principled

OUT = os.path.dirname(os.path.abspath(__file__))

BANDS = [
    (range(43, 51), '6E6A63', 1.00, '9C6234'),   # iron 50-43
    (range(35, 43), '9C6234', 0.85, '447A4E'),   # bronze 42-35
    (range(27, 35), '447A4E', 0.68, '4F8BC9'),   # green 34-27
    (range(19, 27), '4F8BC9', 0.52, '7743AB'),   # cobalt 26-19
    (range(11, 19), '7743AB', 0.36, 'AC3F3A'),   # plum 18-11
    (range(4, 11),  'AC3F3A', 0.20, 'AC3F3A'),   # crimson 10-4: red flood
]

ROT1 = [['TL'], ['TR'], ['BR'], ['BL']]
ROT2 = [['TL', 'TR'], ['TR', 'BR'], ['BR', 'BL'], ['BL', 'TL']]
ROT3 = [['TL', 'TR', 'BR'], ['TR', 'BR', 'BL'], ['BR', 'BL', 'TL'], ['BL', 'TL', 'TR']]

def codex_tabs(rank):
    # Tab tier and band color are independent cycles (the interleave is the
    # design). Halo thresholds mapped descending: clean 50-45, one tab
    # 44-36, two 35-24, three 23-12, full flood 11-4.
    if rank >= 45: return None
    if rank >= 36: return ROT1[(44 - rank) // 3 % 4]
    if rank >= 24: return ROT2[(35 - rank) // 3 % 4]
    if rank >= 12: return ROT3[(23 - rank) // 3 % 4]
    return 'FULL'

def band_for(rank):
    for ranks, hexv, hard, corner in BANDS:
        if rank in ranks:
            return hexv, hard, corner
    raise ValueError(rank)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

bpy.ops.mesh.primitive_plane_add(size=120, location=(0, 0, -0.02))
g = bpy.context.object
gm = bpy.data.materials.new('g'); p = principled(gm)
p.inputs['Base Color'].default_value = hexc('0B0A09'); p.inputs['Roughness'].default_value = 0.9
g.data.materials.append(gm)

cols = 7
pitch = 3.1
for i, rank in enumerate(range(50, 3, -1)):
    r, c = divmod(i, cols)
    cx = (c - 3) * pitch
    cy = (3 - r) * pitch
    hexv, hard, corner = band_for(rank)
    mark(str(rank), hexv, None, hard, corner, cx, cy, tabs=codex_tabs(rank))

def area(loc, rot, size, energy, color=(1, 1, 1), spread=180):
    bpy.ops.object.light_add(type='AREA', location=loc, rotation=rot)
    L = bpy.context.object
    L.data.size = size; L.data.energy = energy; L.data.color = color
    try: L.data.spread = math.radians(spread)
    except Exception: pass
area((-14, 12, 30), (math.radians(-24), math.radians(-24), 0), 26, 9800, (1.0, 0.96, 0.88), 65)
area((20, -10, 20), (math.radians(22), math.radians(36), 0), 14, 4600, (0.82, 0.90, 1.0), 70)
area((2, -20, 26), (math.radians(30), 0, 0), 34, 1100)
sc.world = bpy.data.worlds.new('w'); sc.world.use_nodes = True
bg = sc.world.node_tree.nodes['Background']
bg.inputs['Color'].default_value = hexc('1A1A1E'); bg.inputs['Strength'].default_value = 0.55

bpy.ops.object.camera_add(location=(0, -1.8, 34), rotation=(math.radians(3), 0, 0))
cam = bpy.context.object
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 23.0
sc.camera = cam

sc.render.engine = 'CYCLES'
sc.cycles.samples = 128
sc.cycles.use_denoising = True
sc.render.resolution_x = 1800; sc.render.resolution_y = 1800
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'
    prefs.get_devices()
    for d in prefs.devices: d.use = True
    sc.cycles.device = 'GPU'
except Exception:
    sc.cycles.device = 'CPU'

sc.use_nodes = True
ct = sc.node_tree
for node in list(ct.nodes): ct.nodes.remove(node)
rl = ct.nodes.new('CompositorNodeRLayers')
glare = ct.nodes.new('CompositorNodeGlare')
glare.glare_type = 'FOG_GLOW'; glare.quality = 'HIGH'
glare.threshold = 2.2; glare.size = 6
try: glare.mix = -0.55
except Exception: pass
cc = ct.nodes.new('CompositorNodeColorCorrection')
cc.master_contrast = 1.07; cc.master_gain = 1.02; cc.master_lift = -0.005
comp = ct.nodes.new('CompositorNodeComposite')
ct.links.new(rl.outputs['Image'], glare.inputs['Image'])
ct.links.new(glare.outputs['Image'], cc.inputs['Image'])
ct.links.new(cc.outputs['Image'], comp.inputs['Image'])

sc.render.filepath = os.path.join(OUT, 'ladder_sheet.png')
bpy.ops.render.render(write_still=True)
print('RENDERED ladder')
