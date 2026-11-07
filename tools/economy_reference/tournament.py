"""Reproducible full-factorial tournament; writes the data used by RESULTS.md."""
import argparse
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from itertools import product
import json
from pathlib import Path

from .config import DEFAULT_PATH, load_config
from .experiments import controls
from .simulation import STRATEGIES, run


def normalize(value, digits):
    if isinstance(value, float):
        return round(value, digits)
    if isinstance(value, dict):
        return {k: normalize(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v, digits) for v in value]
    return value


def grid_jobs(p):
    grid = p['model']['grid']
    keys = list(grid)
    return [(p, strategy, dict(zip(keys, values)))
            for values in product(*(grid[key] for key in keys)) for strategy in STRATEGIES]


def compact(run_result):
    # Full phase actor accounts retained. Repeated weekly paths/calendars only in defaults/controls.
    return {k: v for k, v in run_result.items() if k not in ('price_path', 'unlock_calendar', 'amm_inventory_origin_usd_not_direct_payments')}


def execute(job):
    p, strategy, overrides = job
    return compact(run(p, strategy, overrides))


def summary(rows):
    result = {}
    for strategy in STRATEGIES:
        matches = [r for r in rows if r['strategy'] == strategy]
        if not matches:
            continue
        best = max(matches, key=lambda r: r['totals']['whale']['economic_cash_usd'])
        worst = min(matches, key=lambda r: r['totals']['whale']['economic_cash_usd'])
        result[strategy] = {
            'runs': len(matches), 'profitable_cash_runs': sum(r['totals']['whale']['economic_cash_usd'] > 0 for r in matches),
            'P1_failures': sum(not r['P1'] for r in matches),
            'P2_cash_failures': sum(not r['P2_cash'] for r in matches),
            'P2_marked_failures': sum(not r['P2_marked'] for r in matches),
            'P3_cash_failures': sum(not r['P3_cash'] for r in matches),
            'best_cash_usd': best['totals']['whale']['economic_cash_usd'], 'best_scenario': best['scenario'],
            'worst_cash_usd': worst['totals']['whale']['economic_cash_usd'], 'worst_scenario': worst['scenario'],
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_PATH)
    parser.add_argument('--output', type=Path, default=DEFAULT_PATH.parents[1] / 'economy-tournament-2026-10-08/results.json')
    parser.add_argument('--refresh-controls', action='store_true', help='Preserve the completed grid; require identical config and default outcomes, then rerun controls')
    parser.add_argument('--quick', action='store_true', help='Defaults and controls only; explicitly not the full grid')
    args = parser.parse_args()
    p = load_config(args.config)
    defaults = {s: run(p, s) for s in STRATEGIES}
    comparison = controls(p)
    if args.refresh_controls:
        saved = json.loads(args.output.read_text())
        assert saved['full_grid'], 'Cannot preserve an incomplete grid'
        assert saved['config_sha256'] == sha256(args.config.read_bytes()).hexdigest(), 'Config changed: rerun full grid'
        assert saved['defaults'] == normalize(defaults, p['model']['output_digits']), 'Default outcomes changed: rerun full grid'
        saved['controls'] = normalize(comparison, p['model']['output_digits'])
        args.output.write_text(json.dumps(saved, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
        print('Controls refreshed; exact config and all eight default outcomes unchanged.')
        return
    rows = []
    if not args.quick:
        jobs = grid_jobs(p)
        with ProcessPoolExecutor(max_workers=p['model']['tournament_workers']) as workers:
            for i, result in enumerate(workers.map(execute, jobs), 1):
                rows.append(result)
                if i % p['model']['progress_every'] == 0:
                    print(f'{i}/{len(jobs)} grid runs complete', flush=True)
    scale = [run(p, s, {'hills': h, 'weeks': weeks}) for h, weeks in zip(p['model']['scale_checks']['hills'], p['model']['scale_checks']['weeks']) for s in STRATEGIES]
    data = {'schema_version': p['model']['schema_version'], 'evidence_class': 'offline deterministic simulation; not a forecast',
            'config_sha256': sha256(args.config.read_bytes()).hexdigest(), 'parameters': p,
            'strategy_phases': STRATEGIES, 'defaults': defaults, 'controls': comparison,
            'grid_summary': summary(rows), 'grid_runs': rows, 'scale_runs': scale,
            'full_grid': not args.quick, 'grid_count': len(rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(normalize(data, p['model']['output_digits']), sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
    print(json.dumps({'output': str(args.output), 'grid_runs': len(rows), 'defaults': len(defaults), 'scale_runs': len(scale), 'bytes': args.output.stat().st_size}))


if __name__ == '__main__':
    main()
