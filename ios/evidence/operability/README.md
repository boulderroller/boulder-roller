# Operability batch evidence (batch D)

Beads: `boulderroller-v2-odmi6.8` (push), `boulderroller-v2-odmi6.14`
(crash + TestFlight lane), `boulderroller-v2-f4acp.2.9` (session ops, root
tracker), backend halves `boulderroller-v2-k7387` (root tracker).

Evidence classes are labeled per AGENTS.md: **local** (this machine),
**deployed** (production droplet), **physical** (real device — none here;
MetricKit delivery and real APNs delivery are physical-device outcomes).

| File | Class | What it shows |
|---|---|---|
| `reconciled-local-proof-2026-08-13.txt` | local | Fresh `origin/main` reconciliation, 292/292 simulator suite, 16-state production-path fixture walkthrough, and unsigned Release archive checks at merge commit `8a9abe43` |
| `suite-292-corrective-green.txt` | local | Full iOS suite after the cold-start session correction: 292/292 (the prior 290 plus the keychain persistence and overlapping/sequential resume regressions) |
| `suite-290-green.txt` | local | Full iOS suite after the batch: 290/290 (baseline 255; +16 session ops, +6 crash diagnostics, +13 push) |
| `archive-unsigned-run.txt` | local | `ios/scripts/archive.sh` producing a device `.xcarchive` with the git-derived build number (2126) and dSYMs preserved to `~/BoulderRoller-dSYMs/0.1.0-2126-415f4f8d/` — everything up to the signing boundary |
| `upload-lane-key-boundary.txt` | local | `ios/scripts/upload_testflight.sh` failing truthfully (exit 2) with the exact founder-account items missing |
| `crash-e2e-deployed.txt` | deployed | DEBUG forced test diagnostic (honestly labeled `debug_forced_test`, `simulated: true`) from the simulator app through the real queue → uploader → deployed `/mobile/diagnostics` → row verified in the production DB |
| `push-worker-dryrun-deployed.txt` | deployed | Send worker on the droplet: enabled in dry-run, scan cycle logs, flags-off default documented |

Gated honestly (needs the founder's Apple account / physical device):
- Real MetricKit crash delivery (device-only; simulator never delivers).
- Signed archive, TestFlight upload, internal-tester install.
- Real APNs delivery (p8 + team signing) — worker stays OFF/dry-run;
  notification copy stays `[COPY: Tim]` placeholders behind the
  `COPY_RATIFIED` latch.
