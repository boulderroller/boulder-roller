#!/usr/bin/env python3
"""Read credentials for the R2 backups without ever printing them to a terminal.

    envfile.py export FILE KEY...   print `export KEY=...` lines for eval
    envfile.py pg                   turn $DATABASE_URL into libpq PG* exports
    envfile.py r2 SOURCE            normalise Tim's R2 file (or folder) into r2.env

Output is meant for `eval "$(...)"` or a pipe, never for a terminal. Errors name
missing keys only, never values.
"""
import os
import shlex
import sys
import urllib.parse
from pathlib import Path

R2_KEYS = {
    'R2_ACCESS_KEY_ID': ['R2_ACCESS_KEY_ID', 'AWS_ACCESS_KEY_ID', 'ACCESS_KEY_ID', 'R2_ACCESS_KEY'],
    'R2_SECRET_ACCESS_KEY': ['R2_SECRET_ACCESS_KEY', 'AWS_SECRET_ACCESS_KEY', 'SECRET_ACCESS_KEY', 'R2_SECRET_KEY'],
    'R2_BUCKET': ['R2_BUCKET', 'R2_BUCKET_NAME', 'BUCKET', 'BUCKET_NAME'],
}
ENDPOINT_KEYS = ['R2_ENDPOINT', 'R2_S3_ENDPOINT', 'S3_ENDPOINT', 'AWS_ENDPOINT_URL', 'AWS_ENDPOINT_URL_S3', 'ENDPOINT']
ACCOUNT_KEYS = ['R2_ACCOUNT_ID', 'CF_ACCOUNT_ID', 'CLOUDFLARE_ACCOUNT_ID', 'ACCOUNT_ID']


def parse(path):
    values = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].lstrip()
        key, sep, value = line.partition('=')
        if not sep:
            key, sep, value = line.partition(':')
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
            value = value[1:-1]
        values[key] = value
    return values


def fail(message):
    print(f'envfile.py: {message}', file=sys.stderr)
    sys.exit(3)


def export(path, keys):
    values = parse(path)
    missing = [key for key in keys if not values.get(key)]
    if missing:
        fail(f'{path} has no value for: {", ".join(missing)}')
    for key in keys:
        print(f'export {key}={shlex.quote(values[key])}')


def pg():
    url = urllib.parse.urlsplit(os.environ.get('DATABASE_URL', ''))
    if url.scheme not in ('postgres', 'postgresql') or not url.hostname:
        fail('DATABASE_URL is not a postgres:// URL')
    query = urllib.parse.parse_qs(url.query)
    values = {
        'PGHOST': url.hostname,
        'PGPORT': str(url.port or 5432),
        'PGUSER': urllib.parse.unquote(url.username or ''),
        'PGPASSWORD': urllib.parse.unquote(url.password or ''),
        'PGDATABASE': urllib.parse.unquote(url.path.lstrip('/')) or 'postgres',
        'PGSSLMODE': query.get('sslmode', ['require'])[0],
    }
    for key, value in values.items():
        print(f'export {key}={shlex.quote(value)}')


def r2(source):
    source = Path(source).expanduser()
    if source.is_dir():
        files = [source / name for name in ('env', '.env', 'r2.env', 'credentials', 'config')]
        files = [file for file in files if file.is_file()] or sorted(p for p in source.iterdir() if p.is_file())
    else:
        files = [source]
    values = {}
    for file in files:
        values.update(parse(file))
    out, missing = {}, []
    for canonical, aliases in R2_KEYS.items():
        found = next((values[a] for a in aliases if values.get(a)), '')
        out[canonical] = found
    endpoint = next((values[a] for a in ENDPOINT_KEYS if values.get(a)), '')
    if endpoint:
        parts = urllib.parse.urlsplit(endpoint if '://' in endpoint else 'https://' + endpoint)
        bucket_in_path = parts.path.strip('/').split('/')[0]
        if bucket_in_path and not out['R2_BUCKET']:
            out['R2_BUCKET'] = bucket_in_path
        endpoint = f'{parts.scheme}://{parts.netloc}'
    else:
        account = next((values[a] for a in ACCOUNT_KEYS if values.get(a)), '')
        endpoint = f'https://{account}.r2.cloudflarestorage.com' if account else ''
    out['R2_ENDPOINT'] = endpoint
    missing = [key for key, value in out.items() if not value]
    if missing:
        names = ', '.join(sorted(values)) or 'nothing'
        fail(f'{source} lacks {", ".join(missing)} (it defines: {names}); '
             'R2 needs an S3 access key ID and secret, the account ID or S3 endpoint, and the bucket')
    for key in ('R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_ENDPOINT', 'R2_BUCKET'):
        print(f'{key}={shlex.quote(out[key])}')


def main(argv):
    if len(argv) >= 3 and argv[0] == 'export':
        export(argv[1], argv[2:])
    elif argv == ['pg']:
        pg()
    elif len(argv) == 2 and argv[0] == 'r2':
        r2(argv[1])
    else:
        fail('usage: envfile.py export FILE KEY... | pg | r2 SOURCE')


if __name__ == '__main__':
    main(sys.argv[1:])
