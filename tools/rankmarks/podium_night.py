import bpy, math, os, random

OUT = os.path.dirname(os.path.abspath(__file__))
PBR = os.path.join(OUT, 'pbr', 'rock035')

def hexc(h, alpha=1.0):
    h = h.lstrip('#')
    r, g, b = (int(h[i:i+2], 16)/255.0 for i in (0, 2, 4))
    def lin(c): return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
    return (lin(r), lin(g), lin(b), alpha)

def principled(mat):
    mat.use_nodes = True
    return mat.node_tree.nodes.get('Principled BSDF')

def ceramic(name, hexcol):
    m = bpy.data.materials.new(name); p = principled(m)
    p.inputs['Base Color'].default_value = hexc(hexcol)
    p.inputs['Roughness'].default_value = 0.36
    try:
        p.inputs['Coat Weight'].default_value = 0.15
        p.inputs['Coat Roughness'].default_value = 0.2
    except Exception: pass
    return m

def granite(name):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree
    pb = nt.nodes['Principled BSDF']
    tc = nt.nodes.new('ShaderNodeTexCoord')
    def img(fname, noncolor=False):
        node = nt.nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(os.path.join(PBR, fname))
        node.projection = 'BOX'; node.projection_blend = 0.3
        nt.links.new(tc.outputs['Object'], node.inputs['Vector'])
        if noncolor:
            node.image.colorspace_settings.name = 'Non-Color'
        return node
    col = img('Rock035_1K-JPG_Color.jpg')
    # dry summer dust settles on upward faces: pale warm layer by world normal
    geo = nt.nodes.new('ShaderNodeNewGeometry')
    dotz = nt.nodes.new('ShaderNodeVectorMath'); dotz.operation = 'DOT_PRODUCT'
    dotz.inputs[1].default_value = (0.0, 0.0, 1.0)
    dramp = nt.nodes.new('ShaderNodeValToRGB')
    dramp.color_ramp.elements[0].position = 0.55
    dramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    dramp.color_ramp.elements[1].position = 1.0
    dramp.color_ramp.elements[1].color = (0.22, 0.22, 0.22, 1)
    dmix = nt.nodes.new('ShaderNodeMix'); dmix.data_type = 'RGBA'
    dmix.inputs['B'].default_value = hexc('A89D89')
    nt.links.new(geo.outputs['Normal'], dotz.inputs[0])
    nt.links.new(dotz.outputs['Value'], dramp.inputs['Fac'])
    nt.links.new(dramp.outputs['Color'], dmix.inputs['Factor'])
    nt.links.new(col.outputs['Color'], dmix.inputs['A'])
    nt.links.new(dmix.outputs['Result'], pb.inputs['Base Color'])
    rough = img('Rock035_1K-JPG_Roughness.jpg', noncolor=True)
    nt.links.new(rough.outputs['Color'], pb.inputs['Roughness'])
    nrm = img('Rock035_1K-JPG_NormalGL.jpg', noncolor=True)
    nmap = nt.nodes.new('ShaderNodeNormalMap')
    nt.links.new(nrm.outputs['Color'], nmap.inputs['Color'])
    nt.links.new(nmap.outputs['Normal'], pb.inputs['Normal'])
    return m


MARBLE = os.path.join(OUT, 'pbr', 'marble')

def stone_material(name, tint_hex=None, tint_amount=0.0, scale=1.6):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree
    pb = nt.nodes['Principled BSDF']
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mapn = nt.nodes.new('ShaderNodeMapping')
    mapn.inputs['Scale'].default_value = (scale, scale, scale)
    nt.links.new(tc.outputs['Object'], mapn.inputs['Vector'])
    def img(fname, noncolor=False):
        node = nt.nodes.new('ShaderNodeTexImage')
        node.image = bpy.data.images.load(os.path.join(MARBLE, fname))
        node.projection = 'BOX'; node.projection_blend = 0.3
        nt.links.new(mapn.outputs['Vector'], node.inputs['Vector'])
        if noncolor:
            node.image.colorspace_settings.name = 'Non-Color'
        return node
    col = img('Marble012_1K-JPG_Color.jpg')
    if tint_hex:
        tmix = nt.nodes.new('ShaderNodeMixRGB')
        tmix.blend_type = 'MULTIPLY'
        tmix.inputs['Fac'].default_value = tint_amount
        tmix.inputs['Color2'].default_value = hexc(tint_hex)
        nt.links.new(col.outputs['Color'], tmix.inputs['Color1'])
        nt.links.new(tmix.outputs['Color'], pb.inputs['Base Color'])
    else:
        nt.links.new(col.outputs['Color'], pb.inputs['Base Color'])
    rough = img('Marble012_1K-JPG_Roughness.jpg', noncolor=True)
    radd = nt.nodes.new('ShaderNodeMath'); radd.operation = 'ADD'
    radd.inputs[1].default_value = 0.18
    nt.links.new(rough.outputs['Color'], radd.inputs[0])
    nt.links.new(radd.outputs['Value'], pb.inputs['Roughness'])
    nrm = img('Marble012_1K-JPG_NormalGL.jpg', noncolor=True)
    nmap = nt.nodes.new('ShaderNodeNormalMap')
    nmap.inputs['Strength'].default_value = 0.5
    nt.links.new(nrm.outputs['Color'], nmap.inputs['Color'])
    nt.links.new(nmap.outputs['Normal'], pb.inputs['Normal'])
    return m

def tile(name, tile_hex):
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
    t = bpy.context.object
    t.scale = (1.0, 1.0, 0.10)
    bev = t.modifiers.new('b', 'BEVEL'); bev.width = 0.15; bev.segments = 14
    tm = bpy.data.materials.new('t'+name); p = principled(tm)
    p.inputs['Base Color'].default_value = hexc(tile_hex)
    p.inputs['Roughness'].default_value = 0.82
    try: p.inputs['Specular IOR Level'].default_value = 0.1
    except Exception: pass
    nt = tm.node_tree
    noise = nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 520.0
    bump = nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.03
    nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], nt.nodes['Principled BSDF'].inputs['Normal'])
    t.data.materials.append(tm)

def qbez(p0, p1, p2, n=12):
    return [((1-t)**2*p0[0] + 2*(1-t)*t*p1[0] + t*t*p2[0],
             (1-t)**2*p0[1] + 2*(1-t)*t*p1[1] + t*t*p2[1])
            for t in [i/n for i in range(1, n+1)]]

def build_crown():
    iv = stone_material('marble_iv')
    tips = [(-0.58, 0.60), (-0.30, 0.80), (0.0, 0.94), (0.30, 0.80), (0.58, 0.60)]
    blunt = [(x, y - 0.055) for x, y in tips]
    valleys = [(-0.44, 0.30), (-0.15, 0.33), (0.15, 0.33), (0.44, 0.30)]
    def flank(a, b):
        going_up = b[1] > a[1]
        low, high = (a, b) if going_up else (b, a)
        ctrl = (high[0] + (low[0]-high[0])*0.22, low[1] + (high[1]-low[1])*0.22)
        return qbez(a, ctrl, b)
    cap = 0.03
    path = [(-0.68, 0.0), (0.68, 0.0), (0.72, 0.26)]
    cur = (0.72, 0.26)
    tipset = set(blunt)
    order = [blunt[4], valleys[3], blunt[3], valleys[2], blunt[2],
             valleys[1], blunt[1], valleys[0], blunt[0]]
    for node in order:
        if node in tipset:
            path += flank(cur, (node[0]+cap, node[1]))
            path.append((node[0]-cap, node[1]))
            cur = (node[0]-cap, node[1])
        else:
            path += flank(cur, node)
            cur = node
    path += flank(cur, (-0.72, 0.26))
    S = 1.26; yoff = -0.47
    cu = bpy.data.curves.new('crown', 'CURVE'); cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'; cu.extrude = 0.05
    cu.bevel_depth = 0.02; cu.bevel_resolution = 6
    sp = cu.splines.new('POLY'); sp.points.add(len(path)-1)
    for pt, (x, y) in zip(sp.points, path):
        pt.co = (x*S, (y+yoff)*S, 0, 1)
    sp.use_cyclic_u = True
    crown = bpy.data.objects.new('crown', cu)
    crown.location = (0, -0.14, 0.16)
    bpy.context.collection.objects.link(crown)
    crown.data.materials.append(iv)
    bpy.ops.object.select_all(action='DESELECT')
    crown.select_set(True); bpy.context.view_layer.objects.active = crown
    bpy.ops.object.convert(target='MESH')
    crown = bpy.context.object
    sub = crown.modifiers.new('s', 'SUBSURF'); sub.subdivision_type = 'SIMPLE'
    sub.levels = 2; sub.render_levels = 3
    ctex = bpy.data.textures.new('carve', 'CLOUDS'); ctex.noise_scale = 0.65
    cdp = crown.modifiers.new('carve', 'DISPLACE'); cdp.texture = ctex
    cdp.strength = 0.02
    try: bpy.ops.object.shade_smooth_by_angle(angle=math.radians(40))
    except Exception: bpy.ops.object.shade_smooth()
    bpy.ops.mesh.primitive_cube_add(location=(0, (0.13+yoff)*S - 0.14, 0.235))
    mold = bpy.context.object
    mold.scale = (0.66*S, 0.03, 0.022)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mv = mold.modifiers.new('b', 'BEVEL'); mv.width = 0.014; mv.segments = 4
    mold.data.materials.append(iv)
    radii = [0.062, 0.072, 0.085, 0.072, 0.062]
    for (tx, ty), r in zip(tips, radii):
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=3, radius=r,
            location=(tx*S, (ty-0.055+yoff)*S + r*0.45 - 0.14, 0.225))
        bpy.ops.object.shade_smooth()
        bpy.context.object.data.materials.append(iv)

def build_laurel():
    lm = stone_material('jade', tint_hex='5F8256', tint_amount=0.95, scale=2.2)
    iv = stone_material('marble_knot')
    R = 0.74
    rng = random.Random(7)
    leaves = []
    for side in (1, -1):
        for i in range(10):
            th = math.radians(8 + i*13.5 + rng.uniform(-1.3, 1.3))
            r_i = R + rng.uniform(-0.018, 0.018)
            px = side*r_i*math.sin(th)
            py = -r_i*math.cos(th)
            bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=1.0, depth=1.0,
                                            location=(px, py, 0.155 + rng.uniform(-0.008, 0.012)))
            leaf = bpy.context.object
            ang = side*(th - math.pi/2) + side*math.radians(-24 + rng.uniform(-5, 5))
            roll = math.radians(rng.uniform(-14, 14))
            leaf.rotation_euler = (roll, 0, ang)
            sc = rng.uniform(0.88, 1.14)
            leaf.scale = (0.052*sc, 0.135*sc*rng.uniform(0.92, 1.08), 0.034*sc)
            leaves.append(leaf)
    bpy.ops.object.select_all(action='DESELECT')
    for l in leaves: l.select_set(True)
    bpy.context.view_layer.objects.active = leaves[0]
    bpy.ops.object.join()
    wreath = bpy.context.object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    sub = wreath.modifiers.new('s', 'SUBSURF'); sub.subdivision_type = 'SIMPLE'
    sub.levels = 2; sub.render_levels = 2
    wtex = bpy.data.textures.new('wcarve', 'CLOUDS'); wtex.noise_scale = 0.35
    wdp = wreath.modifiers.new('carve', 'DISPLACE'); wdp.texture = wtex
    wdp.strength = 0.012
    wreath.data.materials.append(lm)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.09, location=(0, -R, 0.17))
    bpy.ops.object.shade_smooth()
    bpy.context.object.data.materials.append(iv)

def build_cobble():
    gr = granite('gr')
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0.62))
    rock = bpy.context.object
    rock.scale = (0.56, 0.47, 0.42)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bv0 = rock.modifiers.new('b0', 'BEVEL'); bv0.width = 0.09; bv0.segments = 4
    bpy.ops.object.select_all(action='DESELECT')
    rock.select_set(True); bpy.context.view_layer.objects.active = rock
    bpy.ops.object.modifier_apply(modifier=bv0.name)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.cube_project(cube_size=1.2)
    bpy.ops.object.mode_set(mode='OBJECT')
    sub = rock.modifiers.new('s', 'SUBSURF'); sub.levels = 3; sub.render_levels = 3
    tex = bpy.data.textures.new('cl', 'CLOUDS')
    tex.noise_scale = 0.5
    dp = rock.modifiers.new('d', 'DISPLACE'); dp.texture = tex; dp.strength = 0.09
    dtex = bpy.data.textures.new('relief', 'IMAGE')
    dtex.image = bpy.data.images.load(os.path.join(PBR, 'Rock035_1K-JPG_Displacement.jpg'))
    dp2 = rock.modifiers.new('d2', 'DISPLACE'); dp2.texture = dtex
    dp2.strength = 0.06; dp2.texture_coords = 'UV'
    bpy.ops.object.shade_smooth()
    rock.rotation_euler = (math.radians(24), math.radians(-14), math.radians(20))
    rock.data.materials.append(gr)

SCENES = [
    ('cobble', '121110', build_cobble),
    ('laurel', '0E120E', build_laurel),
    ('crown',  '0B0A0C', build_crown),
]

def build(name, tile_hex, builder):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, -0.02))
    g = bpy.context.object
    gm = bpy.data.materials.new('g'); p = principled(gm)
    p.inputs['Base Color'].default_value = hexc('070606'); p.inputs['Roughness'].default_value = 0.9
    g.data.materials.append(gm)

    tile(name, tile_hex)
    builder()

    # moon lighting: one strong key, deep shadow side, cool rim to carve the edge
    def area(loc, rot, size, energy, color=(1, 1, 1), spread=180):
        bpy.ops.object.light_add(type='AREA', location=loc, rotation=rot)
        L = bpy.context.object
        L.data.size = size; L.data.energy = energy; L.data.color = color
        try: L.data.spread = math.radians(spread)
        except Exception: pass
    area((-2.4, 1.9, 3.6), (math.radians(-30), math.radians(-30), 0), 1.8, 165, (1.0, 0.96, 0.88), 38)
    area((2.7, -1.2, 2.0), (math.radians(24), math.radians(40), 0), 1.2, 62, (0.82, 0.90, 1.0), 60)
    area((0.4, -2.6, 3.0), (math.radians(35), 0, 0), 4.0, 40)
    sc.world = bpy.data.worlds.new('w'); sc.world.use_nodes = True
    wnt = sc.world.node_tree
    bg = wnt.nodes['Background']
    env = wnt.nodes.new('ShaderNodeTexEnvironment')
    env.image = bpy.data.images.load(os.path.join(OUT, 'pbr', 'studio.hdr'))
    wnt.links.new(env.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.22

    bpy.ops.object.camera_add(location=(0, -0.5, 4.2),
                              rotation=(math.radians(6.5), 0, 0))
    cam = bpy.context.object
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = 2.5
    sc.camera = cam

    sc.render.engine = 'CYCLES'
    sc.cycles.samples = 160
    sc.cycles.use_denoising = True
    sc.render.resolution_x = 900; sc.render.resolution_y = 900
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'METAL'
        prefs.get_devices()
        for dd in prefs.devices: dd.use = True
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
    el.width = 1.3; el.height = 1.3
    blur = ct.nodes.new('CompositorNodeBlur'); blur.size_x = 300; blur.size_y = 300; blur.use_relative = False
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

import sys
ONLY = None
for a in sys.argv:
    if a.startswith('--only='): ONLY = a.split('=')[1]
for name, thex, fn in SCENES:
    if ONLY and name != ONLY: continue
    build(name, thex, fn)
    bpy.context.scene.render.filepath = os.path.join(OUT, 'nt_%s.png' % name)
    bpy.ops.render.render(write_still=True)
    bpy.context.scene.render.resolution_x = 110
    bpy.context.scene.render.resolution_y = 110
    bpy.context.scene.render.filepath = os.path.join(OUT, 'nt_%s_110.png' % name)
    bpy.ops.render.render(write_still=True)
    print('RENDERED', name)
