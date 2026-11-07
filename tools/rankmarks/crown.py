import bpy, math, os

OUT = os.path.dirname(os.path.abspath(__file__))

def hexc(h, alpha=1.0):
    h = h.lstrip('#')
    r, g, b = (int(h[i:i+2], 16)/255.0 for i in (0, 2, 4))
    def lin(c): return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
    return (lin(r), lin(g), lin(b), alpha)

def mixc(a, b, t):
    return tuple(a[i]*(1-t) + b[i]*t for i in range(3)) + (1.0,)

def principled(mat):
    mat.use_nodes = True
    return mat.node_tree.nodes.get('Principled BSDF')

def apply_mod(obj, mod):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)

def apply_scale(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

def smoothish(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    try:
        bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
    except Exception:
        bpy.ops.object.shade_smooth()

def brushed_metal(name, color_hex):
    # bead-blasted anodized: matte micro-grain, no liquid highlights
    m = bpy.data.materials.new(name); p = principled(m)
    p.inputs['Base Color'].default_value = hexc(color_hex)
    p.inputs['Metallic'].default_value = 1.0
    p.inputs['Roughness'].default_value = 0.42
    try: p.inputs['Anisotropic'].default_value = 0.15
    except Exception: pass
    nt = m.node_tree
    rn = nt.nodes.new('ShaderNodeTexNoise'); rn.inputs['Scale'].default_value = 90.0
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['To Min'].default_value = 0.36; mr.inputs['To Max'].default_value = 0.48
    nt.links.new(rn.outputs['Fac'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], nt.nodes['Principled BSDF'].inputs['Roughness'])
    grain = nt.nodes.new('ShaderNodeTexNoise'); grain.inputs['Scale'].default_value = 800.0
    gb = nt.nodes.new('ShaderNodeBump'); gb.inputs['Strength'].default_value = 0.025
    nt.links.new(grain.outputs['Fac'], gb.inputs['Height'])
    nt.links.new(gb.outputs['Normal'], nt.nodes['Principled BSDF'].inputs['Normal'])
    return m

def polished_metal(name, color_hex):
    # satin accent, not chrome
    m = bpy.data.materials.new(name); p = principled(m)
    p.inputs['Base Color'].default_value = hexc(color_hex)
    p.inputs['Metallic'].default_value = 1.0
    p.inputs['Roughness'].default_value = 0.30
    return m

def emissive(name, color_hex, strength):
    m = bpy.data.materials.new(name); m.use_nodes = True
    ng = m.node_tree
    for n in list(ng.nodes):
        if n.type != 'OUTPUT_MATERIAL': ng.nodes.remove(n)
    em = ng.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = hexc(color_hex)
    em.inputs['Strength'].default_value = strength
    ng.links.new(em.outputs['Emission'], ng.nodes['Material Output'].inputs['Surface'])
    return m

def rounded_rect_path(half, rad, n=14):
    # rad == half degenerates to a pure circle; small rad approaches a square.
    rad = min(rad, half)
    cs = [(half-rad, half-rad), (-(half-rad), half-rad),
          (-(half-rad), -(half-rad)), (half-rad, -(half-rad))]
    a0s = [0, math.pi/2, math.pi, 3*math.pi/2]
    order = [0, 1, 2, 3]
    path = []
    for idx, a0 in zip(order, a0s):
        cxa, cya = cs[idx]
        for i in range(n+1):
            a = a0 + (math.pi/2)*i/n
            path.append((cxa+rad*math.cos(a), cya+rad*math.sin(a)))
    return path

def curve_loop(name, path, z, cx, cy, bevel, mat):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'
    sp = cu.splines.new('POLY'); sp.points.add(len(path)-1)
    for pt, (x, y) in zip(sp.points, path):
        pt.co = (x, y, 0, 1)
    sp.use_cyclic_u = True
    cu.bevel_depth = bevel; cu.bevel_resolution = 6
    ob = bpy.data.objects.new(name, cu); ob.location = (cx, cy, z)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(mat)
    return ob

def circle_path(r, n=96):
    return [(r*math.cos(2*math.pi*i/n), r*math.sin(2*math.pi*i/n)) for i in range(n)]

NUM_FONT = None
def numeral_font():
    global NUM_FONT
    if NUM_FONT is None:
        for fp in ('/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf',
                   '/System/Library/Fonts/Supplemental/Arial Black.ttf'):
            if os.path.exists(fp):
                NUM_FONT = bpy.data.fonts.load(fp); break
    return NUM_FONT

IVORY = 'E7DDC3'

def mark(num, band_hex, accent_hex, hard, corner_hex, cx, cy):
    # tile — near-black warm, tinted a breath toward the band color
    bpy.ops.mesh.primitive_cube_add(location=(cx, cy, 0))
    tile = bpy.context.object
    tile.scale = (1.0, 1.0, 0.10)
    bev = tile.modifiers.new('b', 'BEVEL'); bev.width = 0.15; bev.segments = 14
    tm = bpy.data.materials.new('t'+num); p = principled(tm)
    p.inputs['Base Color'].default_value = mixc(hexc('0F0C0A'), hexc(band_hex), 0.03)
    p.inputs['Roughness'].default_value = 0.78
    try: p.inputs['Specular IOR Level'].default_value = 0.15
    except Exception: pass
    nt = tm.node_tree
    noise = nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 520.0
    bump = nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.04
    nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], nt.nodes['Principled BSDF'].inputs['Normal'])
    tc = nt.nodes.new('ShaderNodeTexCoord')
    dot = nt.nodes.new('ShaderNodeVectorMath'); dot.operation = 'DOT_PRODUCT'
    dot.inputs[1].default_value = (0.25, -0.25, 0.0)
    off = nt.nodes.new('ShaderNodeMath'); off.operation = 'ADD'; off.inputs[1].default_value = 0.5
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.interpolation = 'EASE'
    ramp.color_ramp.elements[0].position = 0.76
    ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = 0.99
    ramp.color_ramp.elements[1].color = hexc(corner_hex) if corner_hex else (0, 0, 0, 1)
    nt.links.new(tc.outputs['Object'], dot.inputs[0])
    nt.links.new(dot.outputs['Value'], off.inputs[0])
    nt.links.new(off.outputs['Value'], ramp.inputs['Fac'])
    pb = nt.nodes['Principled BSDF']
    nt.links.new(ramp.outputs['Color'], pb.inputs['Emission Color'])
    pb.inputs['Emission Strength'].default_value = 0.30 if corner_hex else 0.0
    tile.data.materials.append(tm)

    band_mat = brushed_metal('band'+num, band_hex)
    glow_mat = emissive('glow'+num, accent_hex if accent_hex else band_hex, 5.0)

    # one band generator; corner radius IS the rank progression (circle -> square)
    rad_out = 0.78 * hard
    cu = bpy.data.curves.new('band'+num, 'CURVE'); cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'; cu.extrude = 0.055
    cu.bevel_depth = 0.038; cu.bevel_resolution = 6
    for half, rad in ((0.78, rad_out), (0.52, max(rad_out - 0.26, 0.02))):
        path = rounded_rect_path(half, rad)
        sp = cu.splines.new('POLY'); sp.points.add(len(path)-1)
        for pt, (x, y) in zip(sp.points, path):
            pt.co = (x, y, 0, 1)
        sp.use_cyclic_u = True
    band = bpy.data.objects.new('band'+num, cu)
    band.location = (cx, cy, 0.16)
    bpy.context.collection.objects.link(band)
    band.data.materials.append(band_mat)

    # combo line: only when the rank carries a second color (e.g. watermelon)
    if accent_hex:
        acc_mat = polished_metal('acc'+num, accent_hex)
        curve_loop('acA'+num, rounded_rect_path(0.565, max(rad_out - 0.215, 0.035)),
                   0.245, cx, cy, 0.011, acc_mat)
    curve_loop('gl'+num, rounded_rect_path(0.65, max(rad_out - 0.13, 0.035)),
               0.10, cx, cy, 0.05, glow_mat)

    # crown — extruded silhouette replaces the numeral at rank 1
    CP = [(-0.50, 0.00), (0.50, 0.00), (0.50, 0.26), (0.36, 0.72), (0.17, 0.40),
          (0.00, 0.85), (-0.17, 0.40), (-0.36, 0.72), (-0.50, 0.26)]
    S = 1.15
    nm = bpy.data.materials.new('n'+num); p = principled(nm)
    p.inputs['Base Color'].default_value = hexc(IVORY)
    p.inputs['Roughness'].default_value = 0.36
    try:
        p.inputs['Coat Weight'].default_value = 0.15
        p.inputs['Coat Roughness'].default_value = 0.2
    except Exception: pass
    yoff = -0.45
    cuc = bpy.data.curves.new('crown'+num, 'CURVE'); cuc.dimensions = '2D'
    cuc.fill_mode = 'BOTH'; cuc.extrude = 0.05
    cuc.bevel_depth = 0.007; cuc.bevel_resolution = 3
    sp2 = cuc.splines.new('POLY'); sp2.points.add(len(CP)-1)
    for pt, (x, y) in zip(sp2.points, CP):
        pt.co = (x*S, (y+yoff)*S, 0, 1)
    sp2.use_cyclic_u = True
    crown = bpy.data.objects.new('crown'+num, cuc)
    crown.location = (cx, cy+0.04, 0.20)
    bpy.context.collection.objects.link(crown)
    crown.data.materials.append(nm)
    # pearl finials on the three points
    for fx, fy in ((-0.36, 0.735), (0.00, 0.865), (0.36, 0.735)):
        fc = bpy.data.curves.new('fin'+num, 'CURVE'); fc.dimensions = '2D'
        fc.fill_mode = 'BOTH'; fc.extrude = 0.05
        fc.bevel_depth = 0.007; fc.bevel_resolution = 3
        path = circle_path(0.062, 32)
        spf = fc.splines.new('POLY'); spf.points.add(len(path)-1)
        for pt, (x, y) in zip(spf.points, path):
            pt.co = (fx*S + x, (fy+yoff)*S + y, 0, 1)
        spf.use_cyclic_u = True
        fin = bpy.data.objects.new('fin'+num, fc)
        fin.location = (cx, cy+0.04, 0.225)
        bpy.context.collection.objects.link(fin)
        fin.data.materials.append(nm)

# hard: corner-radius factor — 1.0 is a pure circle, small values approach square.
# Square = senior, circle = entry, per Halo. No combo colorways.
MARKS = [
    dict(num='1', band='AC3F3A', accent=None, hard=0.20, corner=None),
]
OLD_MARKS = [
    dict(num='45', band='6E6A63', accent=None, hard=1.00, corner='9C6234'),
    dict(num='37', band='9C6234', accent=None, hard=0.85, corner='447A4E'),
    dict(num='28', band='447A4E', accent=None, hard=0.68, corner='4F8BC9'),
    dict(num='20', band='4F8BC9', accent=None, hard=0.52, corner='7743AB'),
    dict(num='12', band='7743AB', accent=None, hard=0.36, corner='AC3F3A'),
    dict(num='4',  band='AC3F3A', accent=None, hard=0.20, corner='F1EEE8'),
]

def build_sheet():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, -0.02))
    g = bpy.context.object
    gm = bpy.data.materials.new('g'); p = principled(gm)
    p.inputs['Base Color'].default_value = hexc('0B0A09'); p.inputs['Roughness'].default_value = 0.9
    g.data.materials.append(gm)

    xs = (0.0,); ys = (0.0,)
    for i, mk in enumerate(MARKS):
        mark(mk['num'], mk['band'], mk['accent'], mk['hard'], mk['corner'],
             xs[0], ys[0])

    def area(loc, rot, size, energy, color=(1, 1, 1), spread=180):
        bpy.ops.object.light_add(type='AREA', location=loc, rotation=rot)
        L = bpy.context.object
        L.data.size = size; L.data.energy = energy; L.data.color = color
        try: L.data.spread = math.radians(spread)
        except Exception: pass
        return L
    area((-2.4, 1.9, 3.6), (math.radians(-30), math.radians(-30), 0), 2.6, 158, (1.0, 0.96, 0.88), 55)
    area((2.7, -1.2, 2.0), (math.radians(24), math.radians(40), 0), 1.2, 85, (0.82, 0.90, 1.0), 60)
    area((0.4, -2.6, 3.0), (math.radians(35), 0, 0), 4.0, 24)
    sc.world = bpy.data.worlds.new('w'); sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = hexc('1A1A1E'); bg.inputs['Strength'].default_value = 0.55

    bpy.ops.object.camera_add(location=(0, -0.5, 4.2), rotation=(math.radians(6.5), 0, 0))
    cam = bpy.context.object
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.5
    sc.camera = cam

    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 128
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 1024; sc.render.resolution_y = 1024
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
    for n in list(ct.nodes): ct.nodes.remove(n)
    rl = ct.nodes.new('CompositorNodeRLayers')
    glare = ct.nodes.new('CompositorNodeGlare')
    glare.glare_type = 'FOG_GLOW'; glare.quality = 'HIGH'
    glare.threshold = 2.2; glare.size = 6
    try: glare.mix = -0.55
    except Exception: pass
    cc = ct.nodes.new('CompositorNodeColorCorrection')
    cc.master_contrast = 1.07; cc.master_gain = 1.02; cc.master_lift = -0.005
    el = ct.nodes.new('CompositorNodeEllipseMask')
    el.width = 1.25; el.height = 1.25
    blur = ct.nodes.new('CompositorNodeBlur'); blur.size_x = 420; blur.size_y = 420; blur.use_relative = False
    mixv = ct.nodes.new('CompositorNodeMixRGB'); mixv.blend_type = 'MULTIPLY'; mixv.inputs['Fac'].default_value = 0.28
    ramp = ct.nodes.new('CompositorNodeValToRGB')
    ramp.color_ramp.elements[0].color = (0.55, 0.55, 0.58, 1)
    ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    comp = ct.nodes.new('CompositorNodeComposite')
    ct.links.new(rl.outputs['Image'], glare.inputs['Image'])
    ct.links.new(glare.outputs['Image'], cc.inputs['Image'])
    ct.links.new(el.outputs['Mask'], blur.inputs['Image'])
    ct.links.new(blur.outputs['Image'], ramp.inputs['Fac'])
    ct.links.new(cc.outputs['Image'], mixv.inputs[1])
    ct.links.new(ramp.outputs['Image'], mixv.inputs[2])
    ct.links.new(mixv.outputs['Image'], comp.inputs['Image'])

build_sheet()
bpy.context.scene.render.filepath = os.path.join(OUT, 'crown_hero.png')
bpy.ops.render.render(write_still=True)
print('RENDERED sheet')
bpy.context.scene.render.resolution_x = 220
bpy.context.scene.render.resolution_y = 220
bpy.context.scene.render.filepath = os.path.join(OUT, 'crown_small.png')
bpy.ops.render.render(write_still=True)
print('RENDERED apex small')
