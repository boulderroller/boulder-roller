# iOS crash symbolication — self-hosted, $0

Bead `boulderroller-v2-odmi6.14` (LIST THREE item 3). The app captures its
own MetricKit crash/hang diagnostics and POSTs them to the authenticated
ingest; this runbook turns a stored diagnostic into named frames using the
dSYMs preserved at archive time. No SaaS anywhere in the path.

## Where things live

| Piece | Path |
|---|---|
| Client capture | `ios/BoulderRoller/Diagnostics/CrashDiagnostics.swift` (MetricKit subscriber → bounded queue → authenticated upload) |
| Ingest endpoint | `POST /mobile/diagnostics` (`backend/app/routes/mobile.py`) |
| Stored diagnostics | `ios_diagnostics` table (payload jsonb = Apple's diagnostic JSON) |
| dSYMs per build | `~/BoulderRoller-dSYMs/<version>-<build>-<sha>/` (written by `ios/scripts/archive.sh`; optional droplet mirror `root@$DROPLET_IP:/root/boulderroller-dsyms/`) |

MetricKit delivers diagnostics on the **next launch** after the event, on
real devices only (never the simulator — the DEBUG forced-test path exists
for pipeline verification). Expect up to ~24h delay for some payload types.

## 1. Pull the diagnostic

```bash
bash scripts/hooks/staging-ops.sh db-query \
  "SELECT id, wallet, app_version, build_number, diagnostic_type, received_at
     FROM ios_diagnostics ORDER BY received_at DESC LIMIT 10"

bash scripts/hooks/staging-ops.sh db-query \
  "SELECT payload FROM ios_diagnostics WHERE id = '<ID>'" > /tmp/diag.json
```

## 2. Read the call stack

Apple's crash diagnostic JSON has `callStackTree.callStacks[].callStackRootFrames[]`
with recursive `subFrames`. Each frame carries `binaryName`, `binaryUUID`,
`address`, and `offsetIntoBinaryTextSegment`.

```bash
jq '.callStackTree.callStacks[0]' /tmp/diag.json
```

## 3. Match the dSYM

The envelope's `build_number` names the dSYM folder. Verify UUIDs match:

```bash
ls ~/BoulderRoller-dSYMs/            # pick <version>-<build>-<sha>
dwarfdump --uuid ~/BoulderRoller-dSYMs/<folder>/BoulderRoller.app.dSYM
# must equal the frame's binaryUUID
```

## 4. Symbolicate frames with atos

MetricKit gives `offsetIntoBinaryTextSegment`, not a complete Mach-O virtual
address. Read the dSYM binary's `__TEXT` base, add each offset, and pass the
reconstructed address to `atos`:

```bash
BR_DWARF="$HOME/BoulderRoller-dSYMs/<folder>/BoulderRoller.app.dSYM/Contents/Resources/DWARF/BoulderRoller"
BR_TEXT_BASE="$(otool -l "$BR_DWARF" | awk '/segname __TEXT/{seen=1} seen && /vmaddr/{print $2; exit}')"
BR_OFFSET=<offsetIntoBinaryTextSegment-as-decimal>
BR_ADDRESS="$(printf '0x%x' "$((BR_TEXT_BASE + BR_OFFSET))")"
atos -arch arm64 -o "$BR_DWARF" -l "$BR_TEXT_BASE" "$BR_ADDRESS"
```

One-liner for every BoulderRoller frame in the first call stack:

```bash
BR_DWARF="$HOME/BoulderRoller-dSYMs/<folder>/BoulderRoller.app.dSYM/Contents/Resources/DWARF/BoulderRoller"
BR_TEXT_BASE="$(otool -l "$BR_DWARF" | awk '/segname __TEXT/{seen=1} seen && /vmaddr/{print $2; exit}')"
while read -r BR_OFFSET; do
  BR_ADDRESS="$(printf '0x%x' "$((BR_TEXT_BASE + BR_OFFSET))")"
  atos -arch arm64 -o "$BR_DWARF" -l "$BR_TEXT_BASE" "$BR_ADDRESS"
done < <(jq -r '.callStackTree.callStacks[0] | .. | objects
  | select(.binaryName? == "BoulderRoller")
  | .offsetIntoBinaryTextSegment' /tmp/diag.json)
```

(System-framework frames symbolicate against Apple's symbol caches in
Xcode; rider-relevant truth is almost always in the app frames.)

## Verifying the pipeline without a crash (DEBUG only)

```bash
xcrun simctl launch <sim-udid> com.boulderroller.app -BRDebugForceCrashDiagnostic
```

pushes one clearly-labeled synthetic envelope (`diagnostic_type =
debug_forced_test`, `payload.simulated = true`) through the real queue,
uploader, and deployed ingest after sign-in. It proves transport and
storage; it is never evidence of a real crash.
