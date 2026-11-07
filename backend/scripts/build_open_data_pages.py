#!/usr/bin/env python3
"""Build docs pages and exact API metadata index from verified local releases."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
PACK=ROOT/'history/pro-research-2026-09-07/files/odbl-round3'
ORIGIN='https://docs.boulderroller.xyz'


def render_copy(manifest, delivery):
    # The first ten lines are the adopted page; remaining lines are authoring rules.
    template='\n\n'.join((PACK/'export-page.txt').read_text().splitlines()[:10])
    values={**manifest,**delivery}
    missing=set(re.findall(r'\{([^}]+)\}',template))-values.keys()
    if missing: raise ValueError('Unresolved page values: '+','.join(sorted(missing)))
    result=template.format_map(values)
    if re.search(r'\{[^}]*\}',result): raise ValueError('Unresolved placeholder')
    base='/open-data/releases/'+manifest['release_id']+'/'
    links={'Download complete release':base+'release.zip','individual files':'#individual-files','region extracts':'#region-extracts','schema and verification instructions':'#schema-and-verification-instructions','source notices':base+'NOTICES.txt','previous releases':'/open-data#previous-releases','© OpenStreetMap contributors':'https://www.openstreetmap.org/copyright','ODbL 1.0':'https://opendatacommons.org/licenses/odbl/1-0/','SOURCES.jsonl':base+'SOURCES.jsonl','NOTICES.txt':base+'NOTICES.txt'}
    result=re.sub('|'.join(re.escape(k) for k in sorted(links,key=len,reverse=True)),lambda m: f'<a href="{links[m[0]]}">{m[0]}</a>',result)
    return '# '+result+'\n'


def human_bytes(n):
    """1488231 -> '1.5 MB (1,488,231 bytes)'."""
    for unit,size in (('GB',10**9),('MB',10**6),('kB',10**3)):
        if n>=size: return f'{n/size:.1f} {unit} ({n:,} bytes)'
    return f'{n:,} bytes'


def render_landing(manifest,delivery,entries):
    """The /open-data landing page. Per-release pages stay frozen; only this page is readable-formatted.
    Counsel's adopted wording is unchanged; only numbers, headings, and the file list differ."""
    shown=dict(delivery)
    for key,value in delivery.items():
        if isinstance(value,int) and key.endswith('bytes'): shown[key]=human_bytes(value)
    page=render_copy(manifest,shown)
    page=re.sub(r'\b1 regions\b','1 region',page)
    base='/open-data/releases/'+manifest['release_id']+'/'
    page+='\n## Individual files\n\nEvery file in this release is listed on the [release page]('+base+'); <a download href="'+base+'SHA256SUMS">SHA256SUMS</a> gives each file\'s SHA-256 checksum, and manifest.json its size.\n'
    page+='\n## Region extracts\n\n'+'\n'.join(f'- <a download href="{base}regions/{region}.jsonl">{region.replace("-"," ").title()}</a>' for region in manifest['regions'])+'\n'
    page+='\n## Schema and verification instructions\n\n'+f'<a download href="{base}SHA256SUMS">SHA256SUMS</a> · <a href="{base}manifest.json">manifest.json</a> · <a download href="{base}release.zip.sha256">release.zip.sha256</a>\n\n```sh\nsha256sum -c release.zip.sha256\nunzip release.zip\nsha256sum -c SHA256SUMS\n```\n\nOn macOS, use `shasum -a 256 -c` in place of `sha256sum -c`.\n'
    page+='\n## All releases {#previous-releases}\n\n'+'\n'.join(f'- [{m["release_id"]}](/open-data/releases/{m["release_id"]}/)'+(' (current)' if m['release_id']==manifest['release_id'] else '') for m,_,_,_ in reversed(entries))+'\n'
    return page


def build_pages(docs):
    docs=Path(docs);releases=docs/'public/open-data/releases'
    entries=[]
    for path in sorted(releases.glob('*/manifest.json')):
        manifest=json.loads(path.read_text());delivery=json.loads((path.parent/'delivery.json').read_text())
        if manifest['release_id']!=path.parent.name: raise ValueError('Release path mismatch')
        for name,record in manifest['files'].items():
            if Path(name).is_absolute() or '..' in Path(name).parts: raise ValueError('Unsafe member')
            data=(path.parent/name).read_bytes()
            if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']: raise ValueError('Corrupt release member')
        if hashlib.sha256((path.parent/'release.zip').read_bytes()).hexdigest()!=delivery['archive_sha256']: raise ValueError('Corrupt ZIP')
        base='/open-data/releases/'+manifest['release_id']+'/'
        page=render_copy(manifest,delivery)
        page+='\n## individual files\n\n'+ '\n'.join(f'- <a download href="{base}{name}">{name}</a>' for name in sorted(manifest['files']))+'\n'
        page+='\n## region extracts\n\n'+ '\n'.join(f'- <a download href="{base}regions/{region}.jsonl">{region}</a>' for region in manifest['regions'])+'\n'
        page+='\n## schema and verification instructions\n\n'+f'<a download href="{base}SHA256SUMS">SHA256SUMS</a> · <a href="{base}manifest.json">manifest.json</a> · <a download href="{base}release.zip.sha256">release.zip.sha256</a>\n\n```sh\nsha256sum -c release.zip.sha256\nunzip release.zip\nsha256sum -c SHA256SUMS\n```\n'
        target=docs/'open-data/releases'/manifest['release_id']/'index.md'
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.read_text()!=page: raise ValueError('Immutable release page changed')
        if not target.exists(): target.write_text(page)
        entries.append((manifest,delivery,page,path.parent))
    if not entries: raise ValueError('No complete release')
    entries.sort(key=lambda x:(x[0]['published_at_utc'],x[0]['release_id']))
    manifest,delivery,page,directory=entries[-1]
    (docs/'open-data.md').write_text(render_landing(manifest,delivery,entries))
    (docs/'public/open-data/latest.json').write_text(json.dumps({'release_id':manifest['release_id'],'manifest_url':ORIGIN+'/open-data/releases/'+manifest['release_id']+'/manifest.json'},sort_keys=True)+'\n')
    sources={r['asset_id']:r for r in map(json.loads,(directory/'SOURCES.jsonl').read_text().splitlines())}
    profiles={r['geographic_revision_id']:r for r in map(json.loads,(directory/'profiles.jsonl').read_text().splitlines())}
    index={}
    for row in map(json.loads,(directory/'climbs.jsonl').read_text().splitlines()):
        revision=row['geographic_revision_id'];base=ORIGIN+'/open-data/releases/'+manifest['release_id']+'/'
        metadata={'scope':'Only the geographic components identified by this metadata; independent rider observations and economic records are outside this declaration.','release_id':manifest['release_id'],'canon_id':row['canon_id'],'canon_version':row['canon_version'],'geographic_revision_id':revision,'license':{'id':'ODbL-1.0','url':'https://opendatacommons.org/licenses/odbl/1-0/'},'attribution':{'text':'© OpenStreetMap contributors','url':'https://www.openstreetmap.org/copyright'},'source_offer':base+'release.zip','manifest_url':base+'manifest.json','notices_url':base+'NOTICES.txt','sources':[{k:sources[asset][k] for k in ('asset_id','license_id','license_url','source_updated_at','notices')} for asset in row['source_ids']]}
        exported={**row,'version':row['canon_version'],'id':row['registry_id'],'canonical_profile':[{k:p[k] for k in ('dist_m','elev_m')} for p in profiles[revision]['samples']]}
        index.setdefault(row['registry_id'],[]).append({'exported':exported,'geographic_data':metadata})
    target=ROOT/'backend/app/data/open_data_index.json';target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(index,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n')
    scan=ROOT/'web/scan/src/data/open-data.json';scan.parent.mkdir(exist_ok=True)
    scan.write_text(json.dumps({key:[{'canon_id':v['exported']['canon_id'],'version':v['exported']['version'],'profile':v['exported']['canonical_profile'],'metadata':v['geographic_data']} for v in values] for key,values in index.items()},sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n')
    print(json.dumps({'release_id':manifest['release_id'],'climbs':manifest['climb_identity_count'],**delivery}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--docs',type=Path,default=ROOT/'docs/gitbook');build_pages(parser.parse_args().docs)
