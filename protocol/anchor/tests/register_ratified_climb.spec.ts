import { expect } from 'chai';
import { spawnSync } from 'child_process';
import { createHash } from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import {
  CHAIN_METRIC_PROJECTION_ALGORITHM,
  quantizedScaledInteger,
} from '../scripts/register_ratified_climb.js';

const workspace = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const script = path.join(workspace, 'scripts', 'register_ratified_climb.ts');
const fixture = path.join(workspace, 'tests', 'fixtures', 'ratified-canon-row-v1.json');
const metricProjectionFixture = path.join(
  workspace,
  'tests',
  'fixtures',
  'canon_metric_projection_v1.json',
);
const launchMetricManifest = path.resolve(
  workspace,
  '..',
  '..',
  'history',
  'canon-runtime-cutover-2026-07-21',
  'chain-metric-projection-launch-manifest.json',
);

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`;
  }
  if (value !== null && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

function run(args: string[]) {
  return spawnSync(process.execPath, [script, ...args], {
    cwd: workspace,
    encoding: 'utf8',
    env: {
      ...process.env,
      NODE_OPTIONS: '--loader ts-node/esm --no-warnings',
    },
  });
}

describe('ratified canon registration artifact', () => {
  it('recomputes the cross-language profile hash, D12 bytes, and deterministic PDAs', () => {
    const result = run(['--row', fixture, '--dry-run']);

    expect(result.status, result.stderr).to.equal(0);
    const report = JSON.parse(result.stdout);
    expect(report.registry_row_uuid).to.equal('11111111-2222-4333-8444-555555555555');
    expect(report.canonical_profile_hash).to.equal(
      'aedd59564db63ada0c6c64eeb1c9de65c3f1f51c6c0dfe22d8ded0d6c2ba208c',
    );
    expect(report.canon_commitment_hex).to.equal(
      '01123e4567e89b42d3a456426614174000000100000000000000000000000000'
      + 'aedd59564db63ada0c6c64eeb1c9de65c3f1f51c6c0dfe22d8ded0d6c2ba208c',
    );
    expect(report.commitment_hash).to.equal(
      '092d18c3ab6e194442b49c1a513b5610d04bae741351a17a63f109d9b7804974',
    );
    expect(report.climb_pda).to.equal('EoitxZP23XYVS7Q4nbZKw2mwsFuGaXjNkMtDqCZyVK8q');
    expect(report.climb_version_index_pda).to.equal(
      '3cvBtEnufvZG9KhP1WSL3V5nB1L2q5N4BwqD8wgdBYjB',
    );
    expect(report.onchain_metrics).to.deep.equal({
      vert_decimeters: 1005,
      distance_meters: 2000,
      avg_gradient_basis_points: 525,
    });
    expect(report.chain_metric_projection_algorithm).to.equal(
      'boulderroller_chain_metric_projection_v1',
    );
  });

  it('matches every shared cross-language chain metric projection vector', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ratified-climb-metrics-'));
    try {
      const vectors = JSON.parse(fs.readFileSync(metricProjectionFixture, 'utf8'));
      for (const vector of vectors.valid) {
        const artifact = JSON.parse(fs.readFileSync(fixture, 'utf8'));
        Object.assign(artifact.registry_row, vector.registry_metrics);
        artifact.chain_metric_projection = {
          algorithm: vectors.algorithm,
          ...vector.projection,
        };
        const metricPath = path.join(directory, `${vector.name}.json`);
        fs.writeFileSync(metricPath, JSON.stringify(artifact));

        const result = run(['--row', metricPath, '--dry-run']);
        expect(result.status, `${vector.name}: ${result.stderr}`).to.equal(0);
        const report = JSON.parse(result.stdout);
        expect(report.onchain_metrics, vector.name).to.deep.equal(vector.projection);
        expect(report.canon_commitment_hex).to.equal(artifact.commitment.bytes_hex);
        expect(report.commitment_hash).to.equal(artifact.commitment.sha256_hex);
      }
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('matches the pinned Python and PostgreSQL projections for all 57 launch candidates', () => {
    const manifest = JSON.parse(fs.readFileSync(launchMetricManifest, 'utf8'));
    expect(manifest.schema).to.equal('boulderroller.chain-metric-launch-manifest');
    expect(manifest.projection_algorithm).to.equal(CHAIN_METRIC_PROJECTION_ALGORITHM);
    expect(manifest.candidates).to.have.length(57);

    const digest = createHash('sha256')
      .update(canonicalJson(manifest.candidates))
      .digest('hex');
    expect(digest).to.equal(manifest.candidate_manifest_sha256);
    expect(digest).to.equal('da93ce9735a7e609248b67d8f7c6d1d4ea53d8f017e8710e1e76aec20cdc9adb');

    for (const candidate of manifest.candidates) {
      const metrics = candidate.registry_metrics;
      expect(
        {
          algorithm: CHAIN_METRIC_PROJECTION_ALGORITHM,
          vert_decimeters: quantizedScaledInteger(metrics.vert_m, 10, 0xffff_ffff, 'vert_m'),
          distance_meters: quantizedScaledInteger(metrics.length_m, 1, 0xffff_ffff, 'length_m'),
          avg_gradient_basis_points: quantizedScaledInteger(
            metrics.avg_gradient_pct,
            100,
            0xffff,
            'avg_gradient_pct',
          ),
        },
        candidate.display_name,
      ).to.deep.equal(candidate.chain_metric_projection);
    }
  });

  it('rejects every invalid shared metric vector before registration', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ratified-climb-invalid-metrics-'));
    try {
      const vectors = JSON.parse(fs.readFileSync(metricProjectionFixture, 'utf8'));
      for (const vector of vectors.invalid) {
        const artifact = JSON.parse(fs.readFileSync(fixture, 'utf8'));
        Object.assign(artifact.registry_row, vector.registry_metrics);
        const metricPath = path.join(directory, `${vector.name}.json`);
        fs.writeFileSync(metricPath, JSON.stringify(artifact));

        const result = run(['--row', metricPath, '--dry-run']);
        expect(result.status, vector.name).to.not.equal(0);
      }
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('rejects a projection that differs by one encoded unit', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ratified-climb-projection-drift-'));
    try {
      const artifact = JSON.parse(fs.readFileSync(fixture, 'utf8'));
      artifact.chain_metric_projection.distance_meters += 1;
      const driftedPath = path.join(directory, 'drifted-projection.json');
      fs.writeFileSync(driftedPath, JSON.stringify(artifact));

      const result = run(['--row', driftedPath, '--dry-run']);
      expect(result.status).to.not.equal(0);
      expect(result.stderr).to.contain(
        'exported chain metric projection does not match the recomputed registry metrics',
      );
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('rejects altered evidence and unavailable carry semantics before any transaction', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ratified-climb-'));
    try {
      const row = JSON.parse(fs.readFileSync(fixture, 'utf8'));
      row.registry_row.canonical_profile[1].elev_m += 1;
      const alteredPath = path.join(directory, 'altered.json');
      fs.writeFileSync(alteredPath, JSON.stringify(row));
      const altered = run(['--row', alteredPath]);
      expect(altered.status).to.not.equal(0);
      expect(altered.stderr).to.contain('canonical profile hash mismatch');

      row.registry_row.canonical_profile[1].elev_m -= 1;
      row.registry_row.record_continuity_policy = 'carry_records_forward';
      const carryPath = path.join(directory, 'carry.json');
      fs.writeFileSync(carryPath, JSON.stringify(row));
      const carry = run(['--row', carryPath]);
      expect(carry.status).to.not.equal(0);
      expect(carry.stderr).to.contain('only new_record_board is operational');
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('rejects pre-publish rows and drifted exported D12 evidence', () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ratified-climb-boundary-'));
    try {
      const artifact = JSON.parse(fs.readFileSync(fixture, 'utf8'));
      const rawRowPath = path.join(directory, 'raw-row.json');
      fs.writeFileSync(rawRowPath, JSON.stringify(artifact.registry_row));
      const rawRow = run(['--row', rawRowPath]);
      expect(rawRow.status).to.not.equal(0);
      expect(rawRow.stderr).to.contain('boulderroller.canon-registration schema version 1');

      artifact.commitment.sha256_hex = '11'.repeat(32);
      const driftedPath = path.join(directory, 'drifted-commitment.json');
      fs.writeFileSync(driftedPath, JSON.stringify(artifact));
      const drifted = run(['--row', driftedPath]);
      expect(drifted.status).to.not.equal(0);
      expect(drifted.stderr).to.contain('exported commitment evidence does not match');
    } finally {
      fs.rmSync(directory, { recursive: true, force: true });
    }
  });

  it('rejects raw identity flags on the send path', () => {
    const result = run(['--row', fixture, '--send', '--canon-id', 'raw-identity']);

    expect(result.status).to.not.equal(0);
    expect(result.stderr).to.contain('unknown or incomplete argument: --canon-id');
  });

  it('requires an explicit fresh-program id on every send', () => {
    const result = run([
      '--row', fixture,
      '--rpc', 'http://127.0.0.1:8899',
      '--admin-keypair', '/not/read/admin.json',
      '--fee-payer', '/not/read/payer.json',
      '--send',
    ]);

    expect(result.status).to.not.equal(0);
    expect(result.stderr).to.contain('--send requires an explicit --program-id');
  });
});
