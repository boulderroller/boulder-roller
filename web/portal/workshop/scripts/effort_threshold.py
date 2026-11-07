"""Offline adapter to the repository's actual training Threshold SQL.

No service credentials or external database: a disposable socket-only PostgreSQL
instance receives native power anchors for the one consenting corpus owner.
Illustrative display identities never become fabricated training histories.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import psycopg2
from psycopg2.extras import Json

FUNCTIONS = [
    ('154_derived_threshold_authority.sql', 'derive_reward_threshold_cp'),
    ('165_threshold_fit_plausibility.sql', 'reward_threshold_fit_is_plausible'),
    ('168_training_eligibility_terminal_replay.sql', 'training_counted_statuses'),
    ('168_training_eligibility_terminal_replay.sql', 'current_training_threshold'),
]


def function_sources(root):
    return [re.search(r'CREATE (?:OR REPLACE )?FUNCTION public\.' + name + r'\([\s\S]*?\$\$;',
                      (root / 'backend/sql' / file).read_text())[0] for file, name in FUNCTIONS]


@contextmanager
def threshold_estimator(root, corpus, parse):
    """Read native anchors once, then use production as-of selection and fit."""
    pg_ctl, initdb = shutil.which('pg_ctl'), shutil.which('initdb')
    if not pg_ctl or not initdb:
        raise RuntimeError('Local PostgreSQL is required; no remote database fallback')
    import workout_parse as wp
    evidence, rejected = [], {}
    for date, raw in corpus.execute('SELECT start_date, streams_json FROM rides JOIN activity_streams USING(activity_id) ORDER BY start_date, CAST(activity_id AS INTEGER)'):
        streams = {s['type']: s for s in json.loads(raw)}
        if 'watts' not in streams:
            continue
        try:
            activity = parse(date, streams)
            # Match training_metrics.evidence_for, including v3 power repair.
            training = wp.compute_training_metrics(activity, 0, engine_version=3)
            curve = dict(zip(training.power_curve_s, training.power_curve_w or []))
            anchors = {str(duration): curve.get(duration) for duration in (180, 420, 900)}
        except (wp.ParseError, wp.DurationLimitExceeded) as error:
            key = type(error).__name__
            rejected[key] = rejected.get(key, 0) + 1
            continue
        if any(v is not None for v in anchors.values()):
            # Require the complete source ride to precede the effort's date.
            ended = datetime.fromtimestamp(max(activity.time_ms) / 1000, timezone.utc)
            evidence.append((date, ended.isoformat(), {f'best_{k}s_w': v for k, v in anchors.items()}))
    with tempfile.TemporaryDirectory(prefix='effort-threshold-') as temporary:
        directory = Path(temporary)
        socket = directory / 'socket'
        socket.mkdir()
        subprocess.run([initdb, '-D', str(directory / 'data'), '-A', 'trust', '--no-locale', '-U', 'postgres'], check=True, capture_output=True)
        subprocess.run([pg_ctl, '-D', str(directory / 'data'), '-l', str(directory / 'postgres.log'), '-o', f'-F -k {socket} -c listen_addresses= -p 5432', '-w', 'start'], check=True, capture_output=True)
        try:
            with psycopg2.connect(host=str(socket), port=5432, dbname='postgres', user='postgres') as connection:
                with connection.cursor() as cursor:
                    cursor.execute('''CREATE TABLE reward_ftp_authorities(user_id uuid, ftp_w int, effective_at timestamptz, verified_at timestamptz, id uuid, source text, verified_by text);
                        CREATE TABLE rides(user_id uuid, started_at timestamptz, ended_at timestamptz, processing_status text, training_evidence jsonb);''')
                    for source in function_sources(root):
                        cursor.execute(source)
                    owner = '00000000-0000-4000-8000-000000000001'
                    cursor.executemany("INSERT INTO rides VALUES (%s,%s,%s,'completed',%s)", [(owner, date, end, Json(anchors)) for date, end, anchors in evidence])

                    def estimate(date):
                        before = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
                        # Current SQL admits started_at <= as_of. Exclude the whole
                        # current day and any older ride ending on/after it as well.
                        cursor.execute("UPDATE rides SET processing_status=CASE WHEN ended_at < %s THEN 'completed' ELSE 'failed' END", (before,))
                        cursor.execute('SELECT current_training_threshold(%s,%s)', (owner, before - timedelta(microseconds=1)))
                        threshold = cursor.fetchone()[0]
                        cursor.execute("SELECT count(*), min(started_at), max(started_at), max((training_evidence->>'best_180s_w')::numeric), max((training_evidence->>'best_420s_w')::numeric), max((training_evidence->>'best_900s_w')::numeric) FROM rides WHERE processing_status='completed' AND started_at < %s", (before,))
                        count, first, last, *anchors = cursor.fetchone()
                        return threshold, {'as_of': date, 'cutoff': 'complete rides before this UTC date', 'source_owner': 'consenting corpus owner; display identities are illustrative', 'power_rides': count, 'first_ride_date': first.date().isoformat() if first else None, 'last_ride_date': last.date().isoformat() if last else None, 'anchors_w': [float(v) if v is not None else None for v in anchors], 'value': threshold['value'] if threshold else None, 'basis': threshold['basis'] if threshold else 'insufficient_or_implausible_prior_power_evidence'}

                    yield estimate, {'native_rejected_power_rides': rejected, 'native_anchor_rides': len(evidence)}
        finally:
            subprocess.run([pg_ctl, '-D', str(directory / 'data'), '-m', 'fast', '-w', 'stop'], check=True, capture_output=True)
