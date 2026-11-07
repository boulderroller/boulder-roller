"""Swap the production Postgres password on the droplet (run by rotate-db-password.sh).

Runs on the droplet as root, with the new password in NEW_DB_PASSWORD, never in
argv, output or logs. Modes:
  dry-run   edit temporary copies, check them, and run read-only health checks
  apply     back up the env files, swap the password, recreate, verify
  rollback  restore the backups, recreate, put Grafana's old password back, verify
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

MODE, SUFFIX = sys.argv[1], sys.argv[2]
REPO = '/root/boulder-repo'
MONITORING = f'{REPO}/infrastructure/monitoring'  # where grafana and postgres-exporter run from
APP_ENV = f'{REPO}/.env'
MON_ENV = f'{MONITORING}/.env'
OLD_MON_ENV = '/root/monitoring/.env'  # an older copy of the stack; kept consistent, not running
BACKUP = {
    APP_ENV: f'/root/.secrets/boulder-repo.env.{SUFFIX}',
    MON_ENV: f'/root/.secrets/monitoring.env.{SUFFIX}',
    OLD_MON_ENV: f'/root/.secrets/root-monitoring.env.{SUFFIX}',
}
URL_KEYS = {APP_ENV: ['DATABASE_URL', 'INDEXER_DATABASE_URL'],
            MON_ENV: ['POSTGRES_EXPORTER_DSN'], OLD_MON_ENV: ['POSTGRES_EXPORTER_DSN']}
PLAIN_KEYS = {MON_ENV: ['SUPABASE_DB_PASSWORD'], OLD_MON_ENV: ['SUPABASE_DB_PASSWORD']}
AUTH_ERROR = re.compile(r'password authentication failed|InvalidPasswordError|28P01|SASL auth|'
                        r'authentication failed', re.I)
failures = []


def say(message):
    print(f'[{MODE}] {message}', flush=True)


def check(ok, message):
    say(('ok   ' if ok else 'FAIL ') + message)
    if not ok:
        failures.append(message)


def run(*args, cwd=None, env=None, quiet=True):
    result = subprocess.run(args, cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE if quiet else None, stderr=subprocess.STDOUT)
    return result.returncode, (result.stdout or '')


def read_lines(path):
    with open(path) as handle:
        return handle.read().splitlines(keepends=True)


def split(line):
    """(key, raw value, quote) for KEY=VALUE lines, else None."""
    if '=' not in line or line.lstrip().startswith('#'):
        return None
    key, value = line.rstrip('\n').split('=', 1)
    quote = value[:1] if value[:1] in '"\'' and value[-1:] == value[:1] and len(value) >= 2 else ''
    return key.strip(), (value[1:-1] if quote else value), quote


def with_password(url, password):
    parts = urllib.parse.urlsplit(url)
    userinfo, _, hostport = parts.netloc.rpartition('@')
    user = userinfo.split(':', 1)[0]
    return urllib.parse.urlunsplit(parts._replace(netloc=f'{user}:{password}@{hostport}'))


def password_of(url):
    return urllib.parse.unquote(urllib.parse.urlsplit(url).password or '')


def edited(path, password):
    """The file's lines with only the password parts replaced."""
    lines, values = read_lines(path), {}
    for line in lines:
        parsed = split(line)
        if parsed:
            values[parsed[0]] = parsed[1]
    out = []
    for line in lines:
        parsed = split(line)
        if not parsed:
            out.append(line)
            continue
        key, value, quote = parsed
        new = None
        if key in URL_KEYS.get(path, []):
            if value:
                new = with_password(value, password)
            elif key == 'POSTGRES_EXPORTER_DSN':  # empty since 14 Oct: build a working one
                host = values.get('SUPABASE_DB_HOST') or 'db.qzkqjevawthyboymqrle.supabase.co'
                user = values.get('SUPABASE_DB_USER') or 'postgres'
                new = f'postgresql://{user}:{password}@{host}:5432/postgres?sslmode=require'
        elif key in PLAIN_KEYS.get(path, []):
            new = password
        out.append(line if new is None else f'{key}={quote}{new}{quote}\n')
    return lines, out


def verify_edit(path, before, after, password):
    changed = [split(b)[0] for b, a in zip(before, after) if b != a]
    check(len(before) == len(after), f'{path}: same {len(before)} lines')
    for key in changed:
        old = next(split(l)[1] for l in before if split(l) and split(l)[0] == key)
        new = next(split(l)[1] for l in after if split(l) and split(l)[0] == key)
        if key in URL_KEYS.get(path, []) and old:
            o, n = urllib.parse.urlsplit(old), urllib.parse.urlsplit(new)
            same = (o.scheme, o.username, o.hostname, o.port, o.path, o.query) == \
                   (n.scheme, n.username, n.hostname, n.port, n.path, n.query)
            check(same and password_of(new) == password, f'{path}: {key} changes only its password')
        elif key in URL_KEYS.get(path, []):
            check(password_of(new) == password, f'{path}: {key} built from SUPABASE_DB_HOST/USER')
        else:
            check(new == password, f'{path}: {key} replaced')
    wanted = set(URL_KEYS.get(path, []) + PLAIN_KEYS.get(path, []))
    present = {split(l)[0] for l in before if split(l)}
    missed = sorted((wanted & present) - set(changed))
    check(not missed, f'{path}: every password key handled ({", ".join(sorted(wanted & present))})'
          + (f'; missed {", ".join(missed)}' if missed else ''))


def write_atomic(path, lines):
    status = os.stat(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.env.')
    with os.fdopen(fd, 'w') as handle:
        handle.writelines(lines)
    os.chmod(tmp, status.st_mode & 0o777)
    os.chown(tmp, status.st_uid, status.st_gid)
    os.replace(tmp, path)


def compose_env():
    image = run('docker', 'inspect', '-f', '{{.Config.Image}}', 'boulder-repo-api-1')[1].strip()
    sha = image.rsplit(':', 1)[-1]
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        sys.exit(f'cannot tell the running API release from image {image!r}')
    # The deploy exports these; without APP_VERSION compose would use a :dev image.
    return dict(os.environ, APP_VERSION=sha, ENVIRONMENT='production', APP_ENV='production'), sha


def recreate():
    env, sha = compose_env()
    say(f'recreating api, indexer, keeper at {sha[:9]}; grafana and postgres-exporter')
    code, out = run('docker', 'compose', 'up', '-d', '--no-build', '--no-deps', 'api', 'indexer', 'keeper',
                    cwd=REPO, env=env)
    check(code == 0, 'docker compose up api indexer keeper' + ('' if code == 0 else f': {out[-400:]}'))
    code, out = run('docker', 'compose', '-f', 'docker-compose.monitoring.yml', 'up', '-d', '--no-deps',
                    'grafana', 'postgres-exporter', cwd=MONITORING)
    check(code == 0, 'docker compose up grafana postgres-exporter' + ('' if code == 0 else f': {out[-400:]}'))


def http(url, method='GET', body=None, auth=None, timeout=10):
    headers = {'Content-Type': 'application/json'} if body is not None else {}
    if auth:
        headers['Authorization'] = 'Basic ' + base64.b64encode(auth.encode()).decode()
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()
    except Exception as error:  # connection refused while a container restarts
        return 0, str(error)


def wait_for(probe, seconds):
    deadline = time.time() + seconds
    while True:
        if probe():
            return True
        if time.time() > deadline:
            return False
        time.sleep(3)


def grafana_auth():
    env = json.loads(run('docker', 'inspect', '-f', '{{json .Config.Env}}', 'grafana')[1] or '[]')
    values = dict(item.split('=', 1) for item in env if '=' in item)
    return f'{values.get("GF_SECURITY_ADMIN_USER", "admin")}:{values.get("GF_SECURITY_ADMIN_PASSWORD", "")}'


def set_grafana_password(password):
    auth = grafana_auth()
    wait_for(lambda: http('http://127.0.0.1:3001/api/health')[0] == 200, 90)
    code, body = http('http://127.0.0.1:3001/api/datasources/uid/supabase', auth=auth)
    if code != 200:
        check(False, f'read the Grafana "supabase" datasource (HTTP {code})')
        return
    source = json.loads(body)
    source['secureJsonData'] = {'password': password}
    code, _ = http('http://127.0.0.1:3001/api/datasources/uid/supabase', 'PUT', source, auth)
    check(code == 200, f'Grafana "supabase" datasource password updated (HTTP {code})')


def started_at(name):
    return run('docker', 'inspect', '-f', '{{.State.StartedAt}}', name)[1].strip()


def verify(after_change):
    ok = wait_for(lambda: http('http://127.0.0.1:8080/health/db')[0] == 200, 120)
    check(ok, 'API /health/db answers 200')
    ok = wait_for(lambda: http('http://127.0.0.1:8080/health/chain', timeout=15)[0] == 200, 90)
    check(ok, 'API /health/chain answers 200')
    ok = wait_for(lambda: run('docker', 'inspect', '-f', '{{.State.Health.Status}}',
                              'boulder-repo-indexer-1')[1].strip() == 'healthy', 150)
    check(ok, 'indexer container healthy')
    if after_change:
        time.sleep(20)  # let the keeper and indexer open their first connections
    for name in ('boulder-repo-api-1', 'boulder-repo-indexer-1', 'boulder-repo-keeper-1'):
        state = run('docker', 'inspect', '-f', '{{.State.Status}} {{.RestartCount}}', name)[1].split()
        logs = run('docker', 'logs', '--since', started_at(name), name)[1]
        hits = len(AUTH_ERROR.findall(logs))
        check(state[:1] == ['running'] and hits == 0,
              f'{name} running ({" ".join(state)}), {hits} auth errors in its log since start')
    auth = grafana_auth()
    ok = wait_for(lambda: http('http://127.0.0.1:3001/api/datasources/uid/supabase/health',
                               auth=auth, timeout=30)[0] == 200, 90)
    check(ok, 'Grafana "supabase" datasource health OK')
    ok = wait_for(lambda: re.search(r'^pg_up 1(\.0)?$', http('http://127.0.0.1:9187/metrics')[1], re.M), 90)
    check(ok, 'postgres-exporter reports pg_up 1')


def main():
    password = os.environ.pop('NEW_DB_PASSWORD', '').strip()
    files = [path for path in (APP_ENV, MON_ENV, OLD_MON_ENV) if os.path.isfile(path)]
    if MODE == 'rollback':
        for path in files:
            if os.path.isfile(BACKUP[path]):
                write_atomic(path, read_lines(BACKUP[path]))
                say(f'restored {path} from {BACKUP[path]}')
        recreate()
        old = next((split(l)[1] for l in read_lines(MON_ENV) if split(l) and split(l)[0] == 'SUPABASE_DB_PASSWORD'), '')
        if old:
            set_grafana_password(old)
        verify(after_change=True)
    else:
        if not (password.isalnum() and password.isascii() and len(password) >= 32):
            sys.exit('the new password must be 32+ letters and digits')
        current = password_of(next(split(l)[1] for l in read_lines(APP_ENV)
                                   if split(l) and split(l)[0] == 'DATABASE_URL'))
        if password == current:
            sys.exit('the new password equals the current one; nothing to swap')
        workdir = tempfile.mkdtemp(prefix='dbreset-dry-') if MODE == 'dry-run' else None
        plans = []
        for path in files:
            before, after = edited(path, password)
            verify_edit(path, before, after, password)
            plans.append((path, after))
        if failures:
            sys.exit('edit checks failed; nothing was changed')
        if MODE == 'dry-run':
            for path, after in plans:
                copy = os.path.join(workdir, path.strip('/').replace('/', '_'))
                shutil.copy2(path, copy)
                write_atomic(copy, after)
                check(read_lines(copy) == after, f'temporary copy of {path} written and read back')
            shutil.rmtree(workdir)
            say('live files untouched; read-only checks of the running services follow')
            verify(after_change=False)
        else:
            for path, after in plans:
                if not os.path.exists(BACKUP[path]):
                    shutil.copy2(path, BACKUP[path])
                    os.chmod(BACKUP[path], 0o600)
                say(f'backup {BACKUP[path]} (mode 600)')
                write_atomic(path, after)
            recreate()
            set_grafana_password(password)
            verify(after_change=True)
    if failures and MODE == 'dry-run':
        say(f'{len(failures)} read-only check(s) failed on the running services; nothing was changed '
            '(pg_up stays 0 until the swap gives postgres-exporter a DSN)')
        sys.exit(1)
    if failures:
        say(f'{len(failures)} check(s) failed. Roll back with: scripts/rotate-db-password.sh --rollback')
        sys.exit(1)
    say('all checks passed')


main()
