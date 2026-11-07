import bpy, math, os

OUT = os.path.dirname(os.path.abspath(__file__))

def hexc(h, alpha=1.0):
    h = h.lstrip('#')
    r, g, b = (int(h[i:i+2], 16)/255.0 for i in (0, 2, 4))
    def lin(c): return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
    return (lin(r), lin(g), lin(b), alpha)

def principled(mat):
    mat.use_nodes = True
    return mat.node_tree.nodes.get('Principled BSDF')

IVORY = 'E7DDC3'

def ivory_mat(name):
    m = bpy.data.materials.new(name); p = principled(m)
    p.inputs['Base Color'].default_value = hexc(IVORY)
    p.inputs['Roughness'].default_value = 0.36
    try:
        p.inputs['Coat Weight'].default_value = 0.15
        p.inputs['Coat Roughness'].default_value = 0.2
    except Exception: pass
    return m

def filled_curve(name, pts, z, cx, cy, mat, extrude=0.05, bevel=0.007):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'; cu.extrude = extrude
    cu.bevel_depth = bevel; cu.bevel_resolution = 3
    sp = cu.splines.new('POLY'); sp.points.add(len(pts)-1)
    for pt, (x, y) in zip(sp.points, pts):
        pt.co = (x, y, 0, 1)
    sp.use_cyclic_u = True
    ob = bpy.data.objects.new(name, cu); ob.location = (cx, cy, z)
    bpy.context.collection.objects.link(ob)
    ob.data.materials.append(mat)
    return ob

def circle_path(r, n=48):
    return [(r*math.cos(2*math.pi*i/n), r*math.sin(2*math.pi*i/n)) for i in range(n)]

def rounded_rect_path(half, rad, n=14):
    rad = min(rad, half)
    cs = [(half-rad, half-rad), (-(half-rad), half-rad),
          (-(half-rad), -(half-rad)), (half-rad, -(half-rad))]
    a0s = [0, math.pi/2, math.pi, 3*math.pi/2]
    path = []
    for idx, a0 in zip([0, 1, 2, 3], a0s):
        cxa, cya = cs[idx]
        for i in range(n+1):
            a = a0 + (math.pi/2)*i/n
            path.append((cxa+rad*math.cos(a), cya+rad*math.sin(a)))
    return path

def tile(num, tile_hex, cx, cy):
    bpy.ops.mesh.primitive_cube_add(location=(cx, cy, 0))
    t = bpy.context.object
    t.scale = (1.0, 1.0, 0.10)
    bev = t.modifiers.new('b', 'BEVEL'); bev.width = 0.15; bev.segments = 14
    tm = bpy.data.materials.new('t'+num); p = principled(tm)
    p.inputs['Base Color'].default_value = hexc(tile_hex)
    p.inputs['Roughness'].default_value = 0.78
    try: p.inputs['Specular IOR Level'].default_value = 0.15
    except Exception: pass
    nt = tm.node_tree
    noise = nt.nodes.new('ShaderNodeTexNoise'); noise.inputs['Scale'].default_value = 520.0
    bump = nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = 0.04
    nt.links.new(noise.outputs['Fac'], bump.inputs['Height'])
    nt.links.new(bump.outputs['Normal'], nt.nodes['Principled BSDF'].inputs['Normal'])
    t.data.materials.append(tm)

def build_crown(cx, cy, mat):
    CP = [(-0.50, 0.00), (0.50, 0.00), (0.50, 0.26), (0.36, 0.72), (0.17, 0.40),
          (0.00, 0.85), (-0.17, 0.40), (-0.36, 0.72), (-0.50, 0.26)]
    S = 1.45; yoff = -0.42
    pts = [(x*S, (y+yoff)*S) for x, y in CP]
    filled_curve('crown', pts, 0.20, cx, cy+0.02, mat)
    for fx, fy in ((-0.36, 0.735), (0.00, 0.865), (0.36, 0.735)):
        c = [(fx*S + x, (fy+yoff)*S + y) for x, y in circle_path(0.062, 32)]
        filled_curve('fin', c, 0.225, cx, cy+0.02, mat)

def build_laurel(cx, cy, mat):
    R = 0.50; S = 1.30
    LEAF = [(0, 0.115), (0.034, 0.05), (0.045, 0.0), (0.034, -0.05),
            (0, -0.115), (-0.034, -0.05), (-0.045, 0.0), (-0.034, 0.05)]
    for side in (1, -1):
        for i in range(8):
            th = math.radians(12 + i*17)
            px = side*R*math.sin(th)*S
            py = -R*math.cos(th)*S
            a = side*(th - math.pi/2) + side*math.radians(-20)
            pts = []
            for lx, ly in LEAF:
                rx = lx*math.cos(a) - ly*math.sin(a)
                ry = lx*math.sin(a) + ly*math.cos(a)
                pts.append((px+rx*S, py+ry*S))
            filled_curve('leaf%d_%d' % (side, i), pts, 0.20, cx, cy+0.06, mat)
    knot = [(x, y - R*S) for x, y in circle_path(0.07, 24)]
    filled_curve('knot', knot, 0.225, cx, cy+0.06, mat)

def build_cobble(cx, cy, mat):
    # angular faceted boulder — straight facet edges are what read as stone
    S = 1.08
    stone = [(-0.50, -0.34), (-0.56, -0.02), (-0.40, 0.26), (-0.10, 0.40),
             (0.24, 0.36), (0.50, 0.16), (0.56, -0.12), (0.36, -0.34)]
    pts = [(x*S, (y+0.10)*S) for x, y in stone]
    filled_curve('stone', pts, 0.225, cx, cy, mat)
    # raised facet planes cast chisel shadow lines on the face
    fA = [(-0.32, 0.06), (-0.08, 0.28), (0.14, 0.22), (-0.12, -0.02)]
    fB = [(0.10, -0.20), (0.34, -0.06), (0.42, -0.20), (0.20, -0.30)]
    for i, f in enumerate((fA, fB)):
        fp = [(x*S, (y+0.10)*S) for x, y in f]
        filled_curve('facet%d' % i, fp, 0.25, cx, cy, mat, extrude=0.02, bevel=0.005)
    bar = [(x, y*0.16 - 0.34) for x, y in rounded_rect_path(0.62, 0.14)]
    filled_curve('plinth', bar, 0.20, cx, cy, mat)

MARKS = [
    dict(name='cobble', tile='232120', builder=build_cobble),
    dict(name='laurel', tile='141B12', builder=build_laurel),
    dict(name='crown',  tile='0F0E0C', builder=build_crown),
]

def build_sheet():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 0, -0.02))
    g = bpy.context.object
    gm = bpy.data.materials.new('g'); p = principled(gm)
    p.inputs['Base Color'].default_value = hexc('0B0A09'); p.inputs['Roughness'].default_value = 0.9
    g.data.materials.append(gm)

    xs = (-2.7, 0.0, 2.7)
    for i, mk in enumerate(MARKS):
        tile(mk['name'], mk['tile'], xs[i], 0.0)
        mk['builder'](xs[i], 0.0, ivory_mat('iv_'+mk['name']))

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
    sc.render.resolution_x = 1620; sc.render.resolution_y = 760
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
    el.width = 1.7; el.height = 2.0
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

build_sheet()
bpy.context.scene.render.filepath = os.path.join(OUT, 'podium_sheet.png')
bpy.ops.render.render(write_still=True)
print('RENDERED podium')
