#!/usr/bin/env python3
"""Copy every Supabase Storage object (ride files, media) into a local folder.

    storage_snapshot.py OUT_DIR          download all buckets into OUT_DIR/<bucket>/<path>
    storage_snapshot.py --list-only      count objects and bytes; download nothing

Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from the environment and writes
OUT_DIR/manifest.json. Each file's size is checked against Storage's metadata.
Standard library only, so the droplet's own python3 runs it.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PAGE = 1000


def api(method, path, body=None, timeout=60):
    base = os.environ['SUPABASE_URL'].rstrip('/') + '/storage/v1'
    key = os.environ['SUPABASE_SERVICE_KEY']
    headers = {'Authorization': f'Bearer {key}', 'apikey': key}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout)


def objects(bucket, folder=''):
    """Yield (path, item) for every file under folder, walking subfolders."""
    offset = 0
    while True:
        with api('POST', f'/object/list/{urllib.parse.quote(bucket)}', {
            'prefix': folder, 'limit': PAGE, 'offset': offset,
            'sortBy': {'column': 'name', 'order': 'asc'},
        }) as response:
            items = json.load(response)
        for item in items:
            path = f'{folder}/{item["name"]}' if folder else item['name']
            if item.get('id') is None:  # a folder placeholder
                yield from objects(bucket, path)
            else:
                yield path, item
        if len(items) < PAGE:
            return
        offset += PAGE


def size_of(item):
    return int((item.get('metadata') or {}).get('size') or 0)


def main(argv):
    list_only = argv == ['--list-only']
    if not list_only and len(argv) != 1:
        sys.exit(__doc__)
    out = None if list_only else Path(argv[0])
    with api('GET', '/bucket') as response:
        buckets = sorted(bucket['id'] for bucket in json.load(response))
    manifest = {'buckets': {}, 'objects': 0, 'bytes': 0}
    for bucket in buckets:
        count = total = 0
        for path, item in objects(bucket):
            expected = size_of(item)
            if out is not None:
                target = out / bucket / path
                target.parent.mkdir(parents=True, exist_ok=True)
                quoted = urllib.parse.quote(f'{bucket}/{path}')
                with api('GET', f'/object/authenticated/{quoted}', timeout=300) as response, \
                        open(target, 'wb') as handle:
                    while chunk := response.read(1 << 20):
                        handle.write(chunk)
                actual = target.stat().st_size
                if expected and actual != expected:
                    sys.exit(f'{bucket}/{path}: downloaded {actual} bytes, Storage says {expected}')
                expected = actual
            count += 1
            total += expected
        manifest['buckets'][bucket] = {'objects': count, 'bytes': total}
        manifest['objects'] += count
        manifest['bytes'] += total
    if out is not None:
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    print(json.dumps(manifest, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1:])
