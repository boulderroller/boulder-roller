"""Rebuild selected B from bundled native source. Run explicitly in Blender4.3.2."""
import argparse, gzip, hashlib, json, math, random, sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',required=True)
argv=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
args=parser.parse_args(argv)
if bpy.app.version[:3] != (4,3,2):
    raise RuntimeError('Pinned source requires Blender4.3.2; do not silently weaken the scene guards.')
PACKAGE=Path(__file__).resolve().parent
OUTPUT=Path(args.output_dir).expanduser().resolve()
source_provenance=json.loads((PACKAGE/'source-provenance.json').read_text())
for filename,metadata in source_provenance['source_assets'].items():
    content=(PACKAGE/filename).read_bytes()
    assert hashlib.sha256(content).hexdigest()==metadata['sha256'],filename
    if filename.endswith('.gz'):
        assert hashlib.sha256(gzip.decompress(content)).hexdigest()==metadata['uncompressed_sha256'],filename
source_paths=json.loads(gzip.decompress((PACKAGE/'wises-contours-and-road.json.gz').read_bytes()))
gps=json.loads((PACKAGE/'wises-recorded-gps.json').read_text())['samples']
assert len(gps)==236 and gps[0]['t']==6686 and gps[-1]['t']==6921
lon0,lat0=-75.2248,40.0560
mx,my=111320*np.cos(np.deg2rad(lat0)),111132
projected=np.array([[(p['lon']-lon0)*mx,(p['lat']-lat0)*my] for p in gps])
assert np.allclose(projected,np.array(source_paths['road'])[:,:2],rtol=0,atol=1e-9)
SEED=10052026
candidate='B'

# Blender-only curve tessellation and image output settings.
BLENDER_CURVE_SETTINGS={'resolution_u':1,'bevel_resolution':1}
BLENDER_BASE_IMAGE_SETTINGS={'resolution_x':2200,'resolution_y':1550,'resolution_percentage':100}
BLENDER_FINAL_IMAGE_SETTINGS={'resolution_x':3080,'resolution_y':2170}

def apply_blender_settings(target,settings):
    for property_name,value in settings.items():
        setattr(target,property_name,value)

def material(name,color,roughness=1):
    mat=bpy.data.materials.new(name);mat.diffuse_color=(*color,1);mat.use_nodes=True
    p=mat.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=roughness
    return mat


def curve(name,points,mat,radius):
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.bevel_depth=radius
    apply_blender_settings(data,BLENDER_CURVE_SETTINGS)
    spline=data.splines.new('POLY');spline.points.add(len(points)-1)
    for p,co in zip(spline.points,points):p.co=(*co,1)
    ob=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(ob);data.materials.append(mat);return ob


def area(name,location,power,size):
    light=bpy.data.lights.new(name,'AREA');light.energy=power;light.shape='DISK';light.size=size
    ob=bpy.data.objects.new(name,light);bpy.context.collection.objects.link(ob);ob.location=location
    ob.rotation_euler=(Vector((0,0,250))-ob.location).to_track_quat('-Z','Y').to_euler()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def plain(value):
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    try:
        return [plain(v) for v in value]
    except TypeError:
        return str(value)


def nodes_fingerprint(tree):
    if not tree:
        return None
    nodes = []
    for node in sorted(tree.nodes, key=lambda n: n.name):
        data = {'name': node.name, 'type': node.bl_idname, 'inputs': [(s.name, plain(s.default_value)) for s in node.inputs if hasattr(s, 'default_value')]}
        for key in ('operation', 'blend_type', 'noise_dimensions', 'normalize'):
            if hasattr(node, key):
                data[key] = plain(getattr(node, key))
        if hasattr(node, 'color_ramp'):
            data['ramp'] = [(e.position, plain(e.color)) for e in node.color_ramp.elements]
        nodes.append(data)
    links = sorted(((a.from_node.name, a.from_socket.name, a.to_node.name, a.to_socket.name) for a in tree.links))
    return digest({'nodes': nodes, 'links': links})


def fingerprints():
    (geometry, cameras, lights, road) = ([], [], [], [])
    for ob in sorted(scene.objects, key=lambda a: a.name):
        header = {'name': ob.name, 'type': ob.type, 'matrix': [list(v) for v in ob.matrix_world], 'hide_render': ob.hide_render, 'modifiers': [(m.name, m.type) for m in ob.modifiers]}
        if ob.type == 'MESH':
            data = ob.data
            record = {**header, 'vertices': [list(v.co) for v in data.vertices], 'edges': [list(e.vertices) for e in data.edges], 'polygons': [(list(p.vertices), p.use_smooth, p.material_index) for p in data.polygons]}
            geometry.append(record)
            if ob.name != 'Actual Wises 3DEP surface':
                road.append({**record, 'materials': [(m.name, nodes_fingerprint(m.node_tree)) for m in data.materials]})
        elif ob.type == 'CURVE':
            data = ob.data
            record = {**header, 'dimensions': data.dimensions, 'resolution_u': data.resolution_u, 'bevel_resolution': data.bevel_resolution, 'fill_mode': data.fill_mode, 'splines': [{'type': s.type, 'cyclic': s.use_cyclic_u, 'points': [(list(p.co), p.radius, p.tilt, p.weight_softbody) for p in s.points], 'bezier': [(list(p.co), list(p.handle_left), list(p.handle_right)) for p in s.bezier_points]} for s in data.splines]}
            if not ob.name.startswith('actual contour '):
                record['bevel_depth'] = data.bevel_depth
                road.append({**record, 'materials': [(m.name, nodes_fingerprint(m.node_tree)) for m in data.materials]})
            geometry.append(record)
        elif ob.type == 'CAMERA':
            d = ob.data
            cameras.append({**header, 'type': d.type, 'lens': d.lens, 'ortho_scale': d.ortho_scale, 'shift': [d.shift_x, d.shift_y], 'clip': [d.clip_start, d.clip_end], 'dof': [d.dof.use_dof, d.dof.focus_distance, d.dof.aperture_fstop]})
        elif ob.type == 'LIGHT':
            d = ob.data
            lights.append({**header, 'type': d.type, 'energy': d.energy, 'color': list(d.color), 'size': getattr(d, 'size', None), 'shape': getattr(d, 'shape', None), 'angle': getattr(d, 'angle', None), 'nodes': nodes_fingerprint(d.node_tree)})
    settings = {'resolution': [scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage], 'engine': scene.render.engine, 'samples': scene.cycles.samples, 'seed': scene.cycles.seed, 'denoise': scene.cycles.use_denoising, 'transparent': scene.render.film_transparent, 'color_mode': scene.render.image_settings.color_mode, 'view': [scene.view_settings.view_transform, scene.view_settings.look, scene.view_settings.exposure, scene.view_settings.gamma], 'camera': scene.camera.name}
    return {'geometry_and_control_points': digest(geometry), 'camera': digest(cameras), 'lights': digest(lights), 'world': nodes_fingerprint(scene.world.node_tree), 'road_and_endpoints_including_materials_and_widths': digest(road), 'render_and_color_settings': digest(settings)}


def complete_fixed_fingerprints():
    result = fingerprints()
    result.pop('render_and_color_settings')
    result['all_curve_widths_and_annotation_shadow_visibility'] = digest([{'name': ob.name, 'bevel_depth': ob.data.bevel_depth, 'bevel_resolution': ob.data.bevel_resolution, 'visible_shadow': ob.visible_shadow} for ob in sorted(scene.objects, key=lambda ob: ob.name) if ob.type == 'CURVE'])
    result['all_object_ray_visibility'] = digest([{'name': ob.name, 'values': {k: getattr(ob, k) for k in ('visible_camera', 'visible_diffuse', 'visible_glossy', 'visible_transmission', 'visible_volume_scatter', 'visible_shadow') if hasattr(ob, k)}} for ob in sorted(scene.objects, key=lambda ob: ob.name)])
    result['all_materials'] = digest([{'name': mat.name, 'use_nodes': mat.use_nodes, 'diffuse_color': list(mat.diffuse_color), 'roughness': mat.roughness, 'metallic': mat.metallic, 'nodes': nodes_fingerprint(mat.node_tree)} for mat in sorted(bpy.data.materials, key=lambda mat: mat.name)])
    result['fixed_color_and_render_treatment'] = digest({'engine': scene.render.engine, 'transparent': scene.render.film_transparent, 'mode': scene.render.image_settings.color_mode, 'format': scene.render.image_settings.file_format, 'resolution_percentage': scene.render.resolution_percentage, 'view': [scene.view_settings.view_transform, scene.view_settings.look, scene.view_settings.exposure, scene.view_settings.gamma], 'cycles_seed': scene.cycles.seed, 'denoise': scene.cycles.use_denoising, 'adaptive_sampling': scene.cycles.use_adaptive_sampling, 'noise_threshold': scene.cycles.adaptive_threshold})
    return result



import bpy, math, json
import numpy as np
from pathlib import Path
from mathutils import Vector

OUT=OUTPUT
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
scene.render.engine='CYCLES'
scene.cycles.samples=32
scene.cycles.use_denoising=True
apply_blender_settings(scene.render,BLENDER_BASE_IMAGE_SETTINGS)
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.film_transparent=True
scene.render.filepath=str(OUT/'wises-ridge-blender.png')
scene.world.use_nodes=True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.94,.945,.90,1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.34
scene.view_settings.view_transform='AgX'
scene.view_settings.look='AgX - Medium High Contrast'
scene.view_settings.exposure=-.25
scene.view_settings.gamma=1


terrain_mat=material('paper olive terrain',(.68,.72,.59))
nodes=terrain_mat.node_tree.nodes;links=terrain_mat.node_tree.links
geometry=nodes.new('ShaderNodeNewGeometry'); separate=nodes.new('ShaderNodeSeparateXYZ')
links.new(geometry.outputs['Position'],separate.inputs[0])
ramp=nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].position=0;ramp.color_ramp.elements[0].color=(.88,.90,.84,1)
ramp.color_ramp.elements[1].position=1;ramp.color_ramp.elements[1].color=(.84,.88,.76,1)
middle=ramp.color_ramp.elements.new(.58);middle.color=(.72,.79,.63,1)
divide=nodes.new('ShaderNodeMath');divide.operation='DIVIDE';divide.inputs[1].default_value=120
links.new(separate.outputs['Z'],divide.inputs[0]);links.new(divide.outputs[0],ramp.inputs[0]);links.new(ramp.outputs[0],nodes.get('Principled BSDF').inputs['Base Color'])

d=np.load(PACKAGE/'wises-native-window.npz');x,y,z=d['x'],d['y'],d['z']
ny,nx=z.shape
verts=[(float(x[j]),float(y[i]),float(z[i,j])*1) for i in range(ny) for j in range(nx)]
faces=[(i*nx+j,(i+1)*nx+j,(i+1)*nx+j+1,i*nx+j+1) for i in range(ny-1) for j in range(nx-1)]
mesh=bpy.data.meshes.new('native terrain surface');mesh.from_pydata(verts,[],faces);mesh.update()
obj=bpy.data.objects.new('Actual Wises 3DEP surface',mesh);bpy.context.collection.objects.link(obj);obj.data.materials.append(terrain_mat)
for face in mesh.polygons: face.use_smooth=True

contour_mat=material('minor topographic ink',(.36,.41,.32))
major_mat=material('major topographic ink',(.29,.35,.27))
blue=material('canonical road blue',(.10,.26,.44),.6)
paper=material('road paper halo',(.96,.96,.90),1)

paths=source_paths
for i,c in enumerate(paths['contours']):
    major=abs(c['elevation']%10)<.01
    pts=[(p[0],p[1],c['elevation']*1+.7) for p in c['points']]
    curve('actual contour '+str(i),pts,major_mat if major else contour_mat,.36 if major else .20)
road=paths['road']
curve('canonical road paper halo',[(p[0],p[1],p[2]*1+2.1) for p in road],paper,4)
curve('canonical road blue',[(p[0],p[1],p[2]*1+6.4) for p in road],blue,2.1)
# Explicit glyph topology preserves selected vertex/edge/face order across source rebuilds.
endpoint_specs=json.loads(gzip.decompress((PACKAGE/'wises-endpoint-meshes.json.gz').read_bytes()))
assert len(endpoint_specs)==4
for spec in endpoint_specs:
    mesh=bpy.data.meshes.new(spec['name'])
    mesh.from_pydata(spec['vertices'],spec['edges'],[p['vertices'] for p in spec['polygons']])
    mesh.update()
    ob=bpy.data.objects.new(spec['name'],mesh)
    bpy.context.collection.objects.link(ob)
    ob.location=spec['location'];ob.rotation_euler=spec['rotation_euler'];ob.scale=spec['scale']
    mesh.materials.append(bpy.data.materials[spec['material']])
    for face,original in zip(mesh.polygons,spec['polygons']):
        face.use_smooth=original['smooth'];face.material_index=original['material_index']
    # from_pydata normalizes each undirected edge's pair order; restore selected serialization.
    mesh.edges.foreach_set('vertices',np.asarray(spec['edges'],dtype=np.int32).ravel())

area('large soft northwest daylight',(-1600,700,2400),2500000,1700)
area('soft lowland bounce',(-700,-1600,1900),500000,1800)
sun=bpy.data.lights.new('soft relief daylight','SUN');sun.energy=2.0;sun.angle=math.radians(12)
sun_ob=bpy.data.objects.new('soft relief daylight',sun);bpy.context.collection.objects.link(sun_ob)
sun_ob.rotation_euler=Vector((.65,-.15,-.7)).to_track_quat('-Z','Y').to_euler()

cam_data=bpy.data.cameras.new('ridge portrait camera');cam=bpy.data.objects.new('ridge portrait camera',cam_data);bpy.context.collection.objects.link(cam);scene.camera=cam
bearing=math.radians(273); elevation=math.radians(18);target=Vector((0,0,75))
cam.location=target+Vector((-math.sin(bearing)*3000,-math.cos(bearing)*3000,math.tan(elevation)*3000))
cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
cam_data.type='ORTHO';cam_data.ortho_scale=1500;cam_data.lens=60;cam_data.clip_end=20000

rng = random.Random(SEED)
variants, changes = {}, []
contours = sorted((ob for ob in scene.objects if ob.name.startswith('actual contour ')),
                  key=lambda ob: int(ob.name.rsplit(' ', 1)[1]))
assert len(contours) == 1123
for ob in contours:
    old_width = ob.data.bevel_depth
    weight_factor = rng.uniform(.96, 1.04)
    # Thirty-one shared, tightly spaced ink values keep the variation quiet and bounded.
    ink_bin = rng.randrange(31)
    ink_factor = .97 + ink_bin * .002
    old_mat = ob.data.materials[0]
    key = (old_mat.name, ink_bin)
    if key not in variants:
        mat = old_mat.copy()
        mat.name = old_mat.name + ' texture-v2 ink ' + str(ink_bin)
        rgba = tuple(old_mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value)
        varied = (*[c * ink_factor for c in rgba[:3]], rgba[3])
        mat.diffuse_color = varied
        mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = varied
        variants[key] = mat
    ob.data.materials[0] = variants[key]
    ob.data.bevel_depth = old_width * weight_factor
    changes.append({'contour': ob.name, 'width_before': old_width, 'width_after': ob.data.bevel_depth,
                    'weight_factor': weight_factor, 'ink_factor': ink_factor})

terrain = bpy.data.materials['paper olive terrain']
tree = terrain.node_tree
base_input = tree.nodes.get('Principled BSDF').inputs['Base Color']
original_link = next(link for link in tree.links if link.to_socket == base_input)
original_color = original_link.from_socket
tree.links.remove(original_link)
position = tree.nodes.new('ShaderNodeNewGeometry')
position.name = 'Texture v2 measured surface position'
noise = tree.nodes.new('ShaderNodeTexNoise')
noise.name = 'Texture v2 seeded color grain only'
noise.noise_dimensions = '4D'
noise.inputs['Scale'].default_value = 1.6
noise.inputs['Detail'].default_value = 2
noise.inputs['Roughness'].default_value = .5
noise.inputs['Distortion'].default_value = 0
noise.inputs['W'].default_value = float(SEED % 100000) / 100
tree.links.new(position.outputs['Position'], noise.inputs['Vector'])
remap = tree.nodes.new('ShaderNodeMapRange')
remap.name = 'Texture v2 color multiplier plus minus 0.6 percent'
remap.inputs['From Min'].default_value = 0
remap.inputs['From Max'].default_value = 1
remap.inputs['To Min'].default_value = .994
remap.inputs['To Max'].default_value = 1.006
tree.links.new(noise.outputs['Fac'], remap.inputs['Value'])
multiply = tree.nodes.new('ShaderNodeMixRGB')
multiply.name = 'Texture v2 multiply original height colors'
multiply.blend_type = 'MULTIPLY'
multiply.inputs[0].default_value = 1
tree.links.new(original_color, multiply.inputs[1])
tree.links.new(remap.outputs[0], multiply.inputs[2])
tree.links.new(multiply.outputs[0], base_input)


# A: retain the quiet fill, introduce a softer low-angle key, and neutralize only high terrain color.
area = scene.objects['large soft northwest daylight']
old_area = {'location': list(area.location), 'energy': area.data.energy, 'size': area.data.size}
area.location = (-1600, 700, 1550)
area.rotation_euler = (Vector((0, 0, 80)) - area.location).to_track_quat('-Z', 'Y').to_euler()
area.data.energy = 2500000
area.data.size = 1700
sun = scene.objects['soft relief daylight']
old_sun = {'rotation': list(sun.rotation_euler), 'energy': sun.data.energy, 'angle': sun.data.angle}
sun.rotation_euler = Vector((.65, -.60, -.45)).to_track_quat('-Z', 'Y').to_euler()
sun.data.energy = 1.95
sun.data.angle = math.radians(10)
terrain = bpy.data.materials['paper olive terrain']
ramp = next(n for n in terrain.node_tree.nodes if n.bl_idname == 'ShaderNodeValToRGB')
old_ramp = [(e.position, list(e.color)) for e in ramp.color_ramp.elements]
for e in ramp.color_ramp.elements:
    if abs(e.position - 1) < .001:
        e.color = (.86, .875, .845, 1)
    elif abs(e.position - .58) < .001:
        e.color = (.75, .79, .70, 1)

changes = {'directional_soft_area': {'before': old_area, 'after': {'location': list(area.location),
            'energy': area.data.energy, 'size': area.data.size, 'aim': [0, 0, 80]}},
           'grazing_soft_sun': {'before': old_sun, 'after': {'incoming_direction': [.65, -.60, -.45],
            'energy': sun.data.energy, 'angular_size_deg': 10}},
           'terrain_height_color_ramp': {'before': old_ramp,
            'after': [(e.position, list(e.color)) for e in ramp.color_ramp.elements]},
           'unchanged': ['world fill', 'lowland bounce', 'source 1x terrain and contours',
                         '236-point recorded GPS', 'blue route and both endpoints', 'seeded texture-v2 grain']}

# B/C: quieter minor ink; contour width and major ink remain exact.
if candidate in ('B', 'C'):
    minor_materials = {ob.data.materials[0].name: ob.data.materials[0] for ob in scene.objects
                       if ob.name.startswith('actual contour ') and
                       ob.data.materials[0].name.startswith('minor topographic ink')}
    ink_changes = []
    for name, mat in sorted(minor_materials.items()):
        p = mat.node_tree.nodes.get('Principled BSDF')
        old = tuple(p.inputs['Base Color'].default_value)
        quiet = (*[a * .80 + b * .20 for a, b in zip(old[:3], (.82, .85, .78))], old[3])
        p.inputs['Base Color'].default_value = quiet
        mat.diffuse_color = quiet
        ink_changes.append({'material': name, 'before': old, 'after': quiet})
    changes['minor_contour_ink'] = {'mix': '20 percent toward light paper gray-green',
                                     'major_ink_and_all_widths_unchanged': True, 'materials': ink_changes}
    annotations = [ob for ob in scene.objects if ob.type == 'CURVE' or
                   (ob.type == 'MESH' and ob.name != 'Actual Wises 3DEP surface')]
    annotation_before = [(ob.name, ob.visible_shadow) for ob in sorted(annotations, key=lambda ob: ob.name)]
    for ob in annotations:
        ob.visible_shadow = False
    changes['annotation_shadow_treatment'] = {'shadow_casting': False, 'object_count': len(annotations),
        'baseline_visibility_sha256': digest(annotation_before),
        'variant_visibility_sha256': digest([(ob.name, ob.visible_shadow) for ob in sorted(annotations, key=lambda ob: ob.name)]),
        'reason': 'Avoid grazing shadows making the raised cartographic route/contours look like physical ridges or channels.',
        'coordinates_widths_and_blue_material_unchanged': True}







# Zero-user startup/base materials are absent from the accepted serialized scene.
startup_mesh=bpy.data.meshes.get('Cube')
if startup_mesh is not None:
    assert startup_mesh.users==0
    bpy.data.meshes.remove(startup_mesh)
for name in ('Material','Dots Stroke','minor topographic ink','major topographic ink'):
    material=bpy.data.materials.get(name)
    if material is not None:
        assert material.users==0,name
        bpy.data.materials.remove(material)

apply_blender_settings(scene.render,BLENDER_FINAL_IMAGE_SETTINGS)
scene.cycles.samples=64
scene.render.filepath=str(OUTPUT/'hc-final.png')
bpy.context.view_layer.update()
actual=complete_fixed_fingerprints()
expected=source_provenance['expected_final_fixed_fingerprints']
mismatches={k:{'expected':expected[k],'actual':actual.get(k)} for k in expected if actual.get(k)!=expected[k]}
assert not mismatches,json.dumps(mismatches,indent=2)
OUTPUT.mkdir(parents=True,exist_ok=True)
output_provenance={'source_manifest_sha256':hashlib.sha256((PACKAGE/'source-provenance.json').read_bytes()).hexdigest(),
 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'source_assets':source_provenance['source_assets'],
 'blender_version':bpy.app.version_string,'resolution':[3080,2170],'cycles_samples':64,'vertical_exaggeration':1,
 'fixed_scene_fingerprints':actual,'selected_final_fingerprints_exact_match':True,
 'rebuild_from_source':True,'saved_scene_dependency':False,'render_completed':False}
(OUTPUT/'hc-final-output-provenance.json').write_text(json.dumps(output_provenance,indent=2)+'\n')
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT/'hc-final.blend'))
bpy.ops.render.render(write_still=True)
assert complete_fixed_fingerprints()==actual
output_provenance['render_completed']=True
output_provenance['output_image_sha256']=hashlib.sha256((OUTPUT/'hc-final.png').read_bytes()).hexdigest()
(OUTPUT/'hc-final-output-provenance.json').write_text(json.dumps(output_provenance,indent=2)+'\n')
print('SOURCE_REBUILD_READY',scene.render.filepath,'ALL_FIXED_FINGERPRINTS_MATCH',True)
