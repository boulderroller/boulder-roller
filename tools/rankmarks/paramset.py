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

# Archivo Black (OFL, fonts/) — ratified 2026-08-27 after the small-proof duel
NUM_FONT = None
def numeral_font():
    global NUM_FONT
    if NUM_FONT is not None:
        try:
            if bpy.data.fonts.get(NUM_FONT.name) == NUM_FONT:
                return NUM_FONT
        except ReferenceError:
            pass
    fp = os.path.join(OUT, 'fonts', 'archivo-black.ttf')
    if os.path.exists(fp):
        NUM_FONT = bpy.data.fonts.load(fp)
    return NUM_FONT

IVORY = 'E7DDC3'
CORNER_EMISSION_MAX = 1.6
DEFAULT_CORNER_PROGRESS = 0.1875  # Preserves the accepted 0.30 sheet strength.

def mark(num, band_hex, accent_hex, hard, corner_hex, cx, cy,
         corner_progress=DEFAULT_CORNER_PROGRESS, tabs=None):
    if not 0.0 <= corner_progress <= 1.0:
        raise ValueError('corner_progress must be between 0.0 and 1.0')

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
    pb = nt.nodes['Principled BSDF']
    if corner_hex and tabs:
        # Halo tab codex: soft radial washes emanating from the given
        # corners ('TL','TR','BR','BL'), or 'FULL' for a whole-tile wash.
        # Tab count carries the coarse read; positions carry the fine one.
        CORNERS = {'TL': (-1.0, 1.0), 'TR': (1.0, 1.0),
                   'BR': (1.0, -1.0), 'BL': (-1.0, -1.0)}
        tc = nt.nodes.new('ShaderNodeTexCoord')
        if True:
            # 'FULL' floods from all four corners: same radial grammar as the
            # tab tiers, driven past total coverage — hottest at the corners,
            # calmest behind the numeral.
            if tabs == 'FULL':
                tab_list, reach = ['TL', 'TR', 'BR', 'BL'], 2.1
            else:
                # the field grows with tier: singles stay compact corner
                # glows clear of the numeral; the wash reaches deeper as
                # more corners light.
                tab_list = tabs
                reach = {1: 0.92, 2: 1.10, 3: 1.30, 4: 1.30}[len(tab_list)]
            fac_out = None
            flat = nt.nodes.new('ShaderNodeVectorMath')
            flat.operation = 'MULTIPLY'
            flat.inputs[1].default_value = (1.0, 1.0, 0.0)
            nt.links.new(tc.outputs['Object'], flat.inputs[0])
            import math as _math
            for tab in tab_list:
                cxv, cyv = CORNERS[tab]
                # Radial falloff from the corner: quarter-disc iso-lines
                # hug the corner, tapering symmetrically along both edges —
                # the tab stays a countable corner object at any tier.
                dist = nt.nodes.new('ShaderNodeVectorMath')
                dist.operation = 'DISTANCE'
                dist.inputs[1].default_value = (cxv, cyv, 0.0)
                nt.links.new(flat.outputs['Vector'], dist.inputs[0])
                fall = nt.nodes.new('ShaderNodeMapRange')
                fall.inputs['From Min'].default_value = 0.12
                fall.inputs['From Max'].default_value = reach
                fall.inputs['To Min'].default_value = 1.0
                fall.inputs['To Max'].default_value = 0.0
                nt.links.new(dist.outputs['Value'], fall.inputs['Value'])
                if fac_out is None:
                    fac_out = fall.outputs['Result']
                else:
                    mx = nt.nodes.new('ShaderNodeMath'); mx.operation = 'MAXIMUM'
                    nt.links.new(fac_out, mx.inputs[0])
                    nt.links.new(fall.outputs['Result'], mx.inputs[1])
                    fac_out = mx.outputs['Value']
        ramp = nt.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.interpolation = 'EASE'
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
        ramp.color_ramp.elements[1].position = 0.66
        ramp.color_ramp.elements[1].color = hexc(corner_hex)
        # hot tip: the tab is lit from its corner, fading inward
        base = hexc(corner_hex)
        tip = tuple(min(1.0, c + (1.0 - c) * 0.25) for c in base[:3]) + (1.0,)
        e2 = ramp.color_ramp.elements.new(0.97)
        e2.color = tip
        # confine the wash to the top face: side faces stay dark so the
        # tile silhouette stays crisp (bevels get a partial wrap).
        geo = nt.nodes.new('ShaderNodeNewGeometry')
        nsep = nt.nodes.new('ShaderNodeSeparateXYZ')
        nt.links.new(geo.outputs['Normal'], nsep.inputs[0])
        nmask = nt.nodes.new('ShaderNodeMapRange')
        nmask.inputs['From Min'].default_value = 0.35
        nmask.inputs['From Max'].default_value = 0.9
        nmask.inputs['To Min'].default_value = 0.0
        nmask.inputs['To Max'].default_value = 1.0
        nt.links.new(nsep.outputs['Z'], nmask.inputs['Value'])
        gate = nt.nodes.new('ShaderNodeMath')
        gate.operation = 'MULTIPLY'
        nt.links.new(fac_out, gate.inputs[0])
        nt.links.new(nmask.outputs['Result'], gate.inputs[1])
        nt.links.new(gate.outputs['Value'], ramp.inputs['Fac'])
        nt.links.new(ramp.outputs['Color'], pb.inputs['Emission Color'])
        # camera-ray-only emission: the wash reads hot to the eye but throws
        # no light, so it can't bounce off the ring onto phantom corners.
        lp = nt.nodes.new('ShaderNodeLightPath')
        est = nt.nodes.new('ShaderNodeMath')
        est.operation = 'MULTIPLY'
        est.inputs[1].default_value = 1.05
        nt.links.new(lp.outputs['Is Camera Ray'], est.inputs[0])
        nt.links.new(est.outputs['Value'], pb.inputs['Emission Strength'])
    else:
        pb.inputs['Emission Strength'].default_value = 0.0
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

    # numeral — proud of the band so it casts its own keyline shadow
    bpy.ops.object.text_add(location=(cx, cy+0.02, 0.20))
    txt = bpy.context.object
    txt.data.body = num
    f = numeral_font()
    if f: txt.data.font = f
    txt.data.size = 1.76 if len(num) == 1 else 1.34
    txt.data.space_character = 0.96
    txt.data.extrude = 0.10
    txt.data.bevel_depth = 0.016
    txt.data.bevel_resolution = 6
    txt.data.align_x = 'CENTER'; txt.data.align_y = 'CENTER'
    nm = bpy.data.materials.new('n'+num); p = principled(nm)
    p.inputs['Base Color'].default_value = hexc(IVORY)
    p.inputs['Roughness'].default_value = 0.36
    try:
        p.inputs['Coat Weight'].default_value = 0.15
        p.inputs['Coat Roughness'].default_value = 0.2
    except Exception: pass
    txt.data.materials.append(nm)
    return tm

# hard: corner-radius factor — 1.0 is a pure circle, small values approach square.
# Square = senior, circle = entry, per Halo. No combo colorways.
MARKS = [
    dict(num='50', band='6E6A63', accent=None, hard=1.00, corner='9C6234', prog=0.75),
    dict(num='37', band='9C6234', accent=None, hard=0.85, corner='447A4E', prog=0.5),
    dict(num='28', band='447A4E', accent=None, hard=0.68, corner='4F8BC9', prog=0.25),
    dict(num='20', band='4F8BC9', accent=None, hard=0.52, corner='7743AB', prog=1.0),
    dict(num='12', band='7743AB', accent=None, hard=0.36, corner='AC3F3A', prog=0.5),
    dict(num='4',  band='AC3F3A', accent=None, hard=0.20, corner=None),
]

def build_sheet():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, -0.02))
    g = bpy.context.object
    gm = bpy.data.materials.new('g'); p = principled(gm)
    p.inputs['Base Color'].default_value = hexc('0B0A09'); p.inputs['Roughness'].default_value = 0.9
    g.data.materials.append(gm)

    xs = (-2.7, 0.0, 2.7); ys = (1.4, -1.4)
    for i, mk in enumerate(MARKS):
        mark(mk['num'], mk['band'], mk['accent'], mk['hard'], mk['corner'],
             xs[i % 3], ys[i // 3],
             corner_progress=mk.get('prog', DEFAULT_CORNER_PROGRESS))

    def area(loc, rot, size, energy, color=(1, 1, 1), spread=180):
        bpy.ops.object.light_add(type='AREA', location=loc, rotation=rot)
        L = bpy.context.object
        L.data.size = size; L.data.energy = energy; L.data.color = color
        try: L.data.spread = math.radians(spread)
        except Exception: pass
        return L
    area((-8.0, 6.5, 12.0), (math.radians(-30), math.radians(-30), 0), 8.0, 1250, (1.0, 0.96, 0.88), 55)
    area((9.0, -4.0, 7.0), (math.radians(24), math.radians(40), 0), 4.0, 600, (0.82, 0.90, 1.0), 60)
    area((1.2, -9.0, 10.0), (math.radians(35), 0, 0), 12.0, 140)
    sc.world = bpy.data.worlds.new('w'); sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = hexc('1A1A1E'); bg.inputs['Strength'].default_value = 0.55

    bpy.ops.object.camera_add(location=(0, -1.0, 16.0), rotation=(math.radians(4), 0, 0))
    cam = bpy.context.object
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = 8.2
    sc.camera = cam

    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 128
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 1620; sc.render.resolution_y = 1120
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
    el.width = 1.7; el.height = 1.55
    blur = ct.nodes.new('CompositorNodeBlur'); blur.size_x = 500; blur.size_y = 500; blur.use_relative = False
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

if __name__ == '__main__':
    build_sheet()
    bpy.context.scene.render.filepath = os.path.join(OUT, 'set_sheet.png')
    bpy.ops.render.render(write_still=True)
    print('RENDERED sheet')
