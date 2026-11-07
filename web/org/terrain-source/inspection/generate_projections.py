"""Project recorded Wises samples from the guarded Blender source and profile exporter.

Run in Blender4.3.2 with --factory-startup. This builds the guarded scene in
memory, without rendering or saving it. Optional map JSON must contain native
MapLibre project() results from the exact static-image capture camera.
"""
import argparse, ast, hashlib, json, sys
from pathlib import Path
import bpy
from bpy_extras.object_utils import world_to_camera_view

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--terrain-source',type=Path,required=True)
parser.add_argument('--ride',type=Path,required=True)
parser.add_argument('--profile-exporter',type=Path,required=True)
parser.add_argument('--map-projections',type=Path)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
assert bpy.app.version[:3]==(4,3,2)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Keep every source assertion and exact selected-B scene operation. Exclude only
# the first output-directory creation and subsequent save/render operations.
renderer=args.terrain_source/'render_wises.py'
tree=ast.parse(renderer.read_text())
cut=next(i for i,node in enumerate(tree.body) if isinstance(node,ast.Expr)
         and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute)
         and isinstance(node.value.func.value,ast.Name)
         and node.value.func.value.id=='OUTPUT' and node.value.func.attr=='mkdir')
source_namespace={'__file__':str(renderer),'__name__':'__projection_source__'}
saved_argv=sys.argv
sys.argv=['render_wises.py','--','--output-dir',str(args.output.parent)]
try:
    exec(compile(ast.Module(body=tree.body[:cut],type_ignores=[]),str(renderer),'exec'),source_namespace)
finally:
    sys.argv=saved_argv
scene=source_namespace['scene']
assert source_namespace['actual']==source_namespace['expected']
assert (scene.render.resolution_x,scene.render.resolution_y)==(3080,2170)

gps=source_namespace['gps']
ride=json.loads(args.ride.read_text())
all_points=[p for p in ride['ride']['samples'] if p['elevation'] is not None]
climb=next(c for c in ride['climbs'] if c['id']=='43f15658')
selected=[p for p in all_points if climb['start']<=p['t']<=climb['end']]
assert selected==gps and len(gps)==236
assert all_points[-1]['d']==128721.17
gaps=[{'after_t':a['t'],'before_t':b['t'],'seconds':b['t']-a['t']}
      for a,b in zip(all_points,all_points[1:]) if b['t']-a['t']>30]
assert len(all_points)==16082 and len(gaps)==8

road=scene.objects['canonical road blue']
spline=road.data.splines[0]
assert spline.type=='POLY' and len(spline.points)==len(gps)
terrain=[]
for p in spline.points:
    point=world_to_camera_view(scene,scene.camera,road.matrix_world@p.co.xyz)
    assert point.z>0 and 0<=point.x<=1 and 0<=point.y<=1
    terrain.append([float(point.x),float(1-point.y)])

# Read the fixed raster frame from the actual exporter AST; font/tick rendering
# cannot change a manually adjusted axes rectangle or its data transform.
profile_tree=ast.parse(args.profile_exporter.read_text())
calls=[node for node in ast.walk(profile_tree) if isinstance(node,ast.Call)]
subplots=next(c for c in calls if isinstance(c.func,ast.Attribute) and c.func.attr=='subplots')
adjust=next(c for c in calls if isinstance(c.func,ast.Attribute) and c.func.attr=='subplots_adjust')
ylim=next(c for c in calls if isinstance(c.func,ast.Attribute) and c.func.attr=='set_ylim')
xlim=next(c for c in calls if isinstance(c.func,ast.Attribute) and c.func.attr=='set_xlim')
assert ast.unparse(xlim.args[0])=='0' and ast.unparse(xlim.args[1])=='x[-1]'
ymin,ymax=[ast.literal_eval(v) for v in ylim.args]
assert (ymin,ymax)==(0,175)

def evaluate(node,mobile):
    if isinstance(node,ast.IfExp):
        assert isinstance(node.test,ast.Name) and node.test.id=='mobile'
        return evaluate(node.body if mobile else node.orelse,mobile)
    return ast.literal_eval(node)

frames={}
profiles={}
for mobile in (False,True):
    frame_name='profileMobile' if mobile else 'profileDesktop'
    options={k.arg:evaluate(k.value,mobile) for k in subplots.keywords}
    width,height=[v*options['dpi'] for v in options['figsize']]
    assert int(width)==width and int(height)==height
    margins={k.arg:evaluate(k.value,mobile) for k in adjust.keywords}
    left,right,top,bottom=[margins[k] for k in ('left','right','top','bottom')]
    profiles[frame_name]=[[left+(right-left)*p['d']/all_points[-1]['d'],
                          1-bottom-(top-bottom)*(p['elevation']-ymin)/(ymax-ymin)] for p in gps]
    frames[frame_name]={'width':int(width),'height':int(height),'axesFraction':margins,
                        'distanceRangeMeters':[0,all_points[-1]['d']],
                        'elevationRangeMeters':[ymin,ymax]}

rows=[{'t':p['t'],'d_m':p['d'],'elevation_m':p['elevation'],'lon':p['lon'],'lat':p['lat'],
       'terrain':terrain[i],**{name:points[i] for name,points in profiles.items()}}
      for i,p in enumerate(gps)]
map_status='Missing exact native capture camera/projection metadata; no map fitting performed.'
map_hash=None
if args.map_projections:
    maps=json.loads(args.map_projections.read_text())
    assert maps['sourceGpsSha256']==sha(args.terrain_source/'wises-recorded-gps.json')
    for name in ('mapDesktop','mapMobile'):
        frame=maps[name]
        assert len(frame['nativePixelPositions'])==236
        assert frame['camera'] and frame['captureSha256']
        for i,(x,y) in enumerate(frame['nativePixelPositions']):
            rows[i][name]=[x/frame['width'],y/frame['height']]
        frames[name]={key:value for key,value in frame.items() if key!='nativePixelPositions'}
    map_status='Exact MapLibre native capture projection supplied; no geographic fitting.'
    map_hash=sha(args.map_projections)

frames['terrain']={'width':3080,'height':2170,'projection':'Blender world_to_camera_view',
                   'lineObject':'canonical road blue','lineCenterOffsetAboveDemMeters':6.4,
                   'cameraType':scene.camera.data.type,
                   'cameraMatrixWorld':[[float(v) for v in row] for row in scene.camera.matrix_world],
                   'orthographicScaleMeters':scene.camera.data.ortho_scale}
marker_centers=[]
for name in ('Sphere.001','Sphere.003'):
    point=world_to_camera_view(scene,scene.camera,scene.objects[name].matrix_world.translation)
    marker_centers.append([float(point.x),float(1-point.y)])
frames['terrain']['endpointMarkerCenters']=marker_centers
output={'coordinateFrame':'Normalized source raster: x right, y down, origin top left. Multiply by frame width/height for native pixels.',
        'sampleCount':236,'timeBoundsSeconds':[gps[0]['t'],gps[-1]['t']],
        'distanceBoundsMeters':[gps[0]['d'],gps[-1]['d']],
        'sourceHashes':{'generator':sha(Path(__file__)),'renderer':sha(renderer),
                        'terrainManifest':sha(args.terrain_source/'source-provenance.json'),
                        'gps':sha(args.terrain_source/'wises-recorded-gps.json'),
                        'ride':sha(args.ride),'profileExporter':sha(args.profile_exporter),
                        'mapProjectionMetadata':map_hash},
        'fixedSceneFingerprints':source_namespace['actual'],
        'mapProjectionStatus':map_status,'frames':frames,
        'profile':{'sampleCount':len(all_points),'gaps':gaps,'gapThresholdSeconds':30,
                   'elevationSource':'Actual recorded ride elevation, not DEM'},
        'samples':rows}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(output,separators=(',',':'))+'\n')
print(json.dumps({'output':str(args.output),'samples':len(rows),'frames':list(frames),
                  'first':rows[0],'last':rows[-1],'mapStatus':map_status,
                  'frozenSceneExact':source_namespace['actual']==source_namespace['expected']}))
