"""Attach verified native map captures and make a compact normalized delivery model."""
import argparse,hashlib,json,math
from pathlib import Path
from PIL import Image

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--projection-dir',type=Path,required=True)
parser.add_argument('--route',type=Path,required=True)
parser.add_argument('--map-desktop',type=Path,required=True)
parser.add_argument('--map-mobile',type=Path,required=True)
parser.add_argument('--terrain-image',type=Path,required=True)
parser.add_argument('--profile-desktop',type=Path,required=True)
parser.add_argument('--profile-mobile',type=Path,required=True)
args=parser.parse_args()
out=args.projection_dir

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

precise=json.loads((out/'wises-interaction.json').read_text())
route=json.loads(args.route.read_text())
assert len(precise['samples'])==len(route['coordinates'])==236
assert route['coordinates']==[[p['lon'],p['lat']] for p in precise['samples']]
maps={'sourceGpsSha256':precise['sourceHashes']['gps']}
checks={}

def mercator(lon,lat):
    return ((lon+180)/360,(180-180/math.pi*math.log(math.tan(math.pi/4+lat*math.pi/360)))/360)

for name,image_path,size in (('mapDesktop',args.map_desktop,(608,161)),
                              ('mapMobile',args.map_mobile,(680,276))):
    metadata_path=out/(name+'.json')
    frame=json.loads(metadata_path.read_text())
    assert frame['ready'] and frame['frameName']==name
    assert frame['sourceGpsSha256']==precise['sourceHashes']['gps']
    assert frame['routeSha256']==sha(args.route)
    assert Image.open(image_path).size==(frame['width'],frame['height'])==size
    assert len(frame['nativePixelPositions'])==236
    camera=frame['camera']
    assert camera['bearing']==camera['pitch']==0
    assert all(v==0 for v in camera['padding'].values())
    assert size==(frame['logicalWidth']*frame['pixelRatio'],frame['logicalHeight']*frame['pixelRatio'])
    world_size=512*2**camera['zoom']
    center=mercator(*camera['center'])
    maximum_error=0
    for i,(pixel_x,pixel_y) in enumerate(frame['nativePixelPositions']):
        point=mercator(*route['coordinates'][i])
        independently_projected=[((point[0]-center[0])*world_size+frame['logicalWidth']/2)*frame['pixelRatio'],
                                 ((point[1]-center[1])*world_size+frame['logicalHeight']/2)*frame['pixelRatio']]
        maximum_error=max(maximum_error,abs(independently_projected[0]-pixel_x),abs(independently_projected[1]-pixel_y))
        precise['samples'][i][name]=[pixel_x/frame['width'],pixel_y/frame['height']]
    assert maximum_error<0.000001,maximum_error
    frame['captureSha256']=sha(image_path)
    frame['captureFile']=image_path.name
    frame['metadataSha256']=sha(metadata_path)
    frame['projectionReference']='Exact MapLibre map.project() at recorded zero-pitch/bearing Mercator capture camera.'
    maps[name]=frame
    precise['frames'][name]={k:v for k,v in frame.items() if k!='nativePixelPositions'}
    checks[name]={'independentMercatorMaxPixelError':maximum_error,
                  'sourceImageSha256':frame['captureSha256']}

(out/'map-capture-frames.json').write_text(json.dumps(maps,separators=(',',':'))+'\n')
precise['sourceHashes']['mapProjectionMetadata']=sha(out/'map-capture-frames.json')
precise['sourceHashes']['deliveryGenerator']=sha(Path(__file__))
precise['mapProjectionStatus']='Exact verified native MapLibre captures and camera projections; no manual fitting.'
image_paths={'terrain':args.terrain_image,'profileDesktop':args.profile_desktop,
             'profileMobile':args.profile_mobile,'mapDesktop':args.map_desktop,'mapMobile':args.map_mobile}
for name,path in image_paths.items():
    frame=precise['frames'][name]
    assert Image.open(path).size==(frame['width'],frame['height'])
    frame['sourceImageSha256']=sha(path)
    frame['sourceImageFile']=path.name
    if 'projectionReference' not in frame:
        frame['projectionReference']=frame.get('projection','Exact export_profiles.py raster axes/data transform.')
precise['coordinateFrame']='Normalized source raster: x right, y down, origin top left. Preserve source aspect; account for CSS object-fit/object-position when overlaying.'
(out/'source-projections.json').write_text(json.dumps(precise,separators=(',',':'))+'\n')

frame_names=('terrain','mapDesktop','mapMobile','profileDesktop','profileMobile')
delivery={'frames':{name:{'width':precise['frames'][name]['width'],
                            'height':precise['frames'][name]['height'],
                            'sourceImageSha256':precise['frames'][name]['sourceImageSha256'],
                            'projectionReference':precise['frames'][name]['projectionReference']}
                    for name in frame_names},'samples':[]}
rounding_error={name:0 for name in frame_names}
for sample in precise['samples']:
    row={'t':int(sample['t']),'d':sample['d_m'],'elevation':sample['elevation_m']}
    for name in frame_names:
        coords=sample[name]
        assert all(0<=value<=1 for value in coords)
        rounded=[round(value,8) for value in coords]
        dimensions=[precise['frames'][name][key] for key in ('width','height')]
        rounding_error[name]=max(rounding_error[name],*(abs(a-b)*size for a,b,size in zip(coords,rounded,dimensions)))
        row[name]=rounded
    delivery['samples'].append(row)
assert all(value<0.001 for value in rounding_error.values())
(out/'interaction.json').write_text(json.dumps(delivery,separators=(',',':'))+'\n')
checks.update({'sampleCount':236,'fixedSceneFingerprintsPreserved':precise['fixedSceneFingerprints'],
               'profileSampleCount':precise['profile']['sampleCount'],
               'profileGapCount':len(precise['profile']['gaps']),
               'normalizedDecimalPlaces':8,'maxRoundingErrorPixelsByFrame':rounding_error,
               'sourceProjectionSha256':sha(out/'source-projections.json'),
               'deliverySha256':sha(out/'interaction.json'),
               'nativeEndpoints':{name:[[row[name][0]*precise['frames'][name]['width'],row[name][1]*precise['frames'][name]['height']]
                                         for row in (precise['samples'][0],precise['samples'][-1])]
                                  for name in frame_names}})
(out/'projection-validation.json').write_text(json.dumps(checks,indent=2)+'\n')
print(json.dumps({'delivery':str(out/'interaction.json'),'bytes':(out/'interaction.json').stat().st_size,
                  'samples':len(delivery['samples']),'maxRoundingErrorPixelsByFrame':rounding_error,
                  'mapChecks':{name:checks[name] for name in ('mapDesktop','mapMobile')}}))
