# Mobile credential lifecycle

Bead `boulderroller-v2-f4acp.2.14`. The release-protecting inventory for
every credential the native iOS lane depends on. No raw secret, key, or
token ever appears in Git, Beads, logs, or this runbook — only where each
lives, who owns it, and how it rotates.

General credential rotation policy (Supabase, Strava, edge) is the closed
bead `boulderroller-v2-2f9w`; this file covers only the mobile/Apple set.

## Inventory

| Credential | Owner | Source of truth | Environments | Consumers | Expiry | Rotation |
|---|---|---|---|---|---|---|
| Apple Developer team id | Tim | Apple Developer account | prod | `ios/.release-config.env` (`DEVELOPMENT_TEAM`), archive signing | none (membership renews yearly — see below) | n/a; membership renewal is the event |
| Apple Developer membership | Tim | Apple Developer account | prod | signing, TestFlight, APNs | **1 year, hard lapse** | renew before expiry; lapse revokes certificates and pulls the app from TestFlight |
| ASC API key (`.p8`) | Tim | `~/.appstoreconnect/private_keys/` on the release Mac | prod | `upload_testflight.sh`, cloud signing | none | revoke in ASC → generate replacement → update `ASC_KEY_ID`/`ASC_ISSUER_ID`/`ASC_KEY_PATH` in `ios/.release-config.env` |
| APNs auth key (`.p8`) | Tim (issued); droplet env (runtime) | Apple Developer → Keys; deployed to the droplet send worker only | prod | backend `mobile_push` send worker (`docs/runbooks/MOBILE_PUSH_OPERATIONS.md`) | none | issue replacement key → deploy to droplet env → verify sandbox delivery → revoke old key in the Apple portal |
| Distribution certificate + provisioning profile | Apple (cloud-managed) | App Store Connect, via `-allowProvisioningUpdates` | prod | archive/export | **1 year** (auto-managed) | cloud signing regenerates; a revoked/expired cert fails the archive step loudly — nothing to store locally |
| Privy app id + mobile client id | mobile lane | `ios/BoulderRoller/App/AppConfig.swift` (public client config, committed by design) | prod | native auth | none | rotate in the Privy dashboard, then update AppConfig in the same change; old id keeps working until removed server-side |
| API TLS (`api.boulderroller.xyz`) | backend lane | Caddy on the droplet (ACME auto-renew) | prod | every client | ~90 days, **auto-renewed** | none routine; an expired cert means Caddy renewal broke — droplet incident, not a mobile rotation |
| Backend signing / protocol authority keys | math lane | droplet + `~/.config/solana` | devnet | settlement | n/a | out of scope here — owned by `ttkx` (managed secret workflows) |

## Release checks

`ios/scripts/archive.sh` and `upload_testflight.sh` already fail truthfully
when `ios/.release-config.env` entries are missing. Lead-time warnings:

- **Membership**: put the Apple Developer renewal date in
  `ios/.release-config.env` as `APPLE_MEMBERSHIP_RENEWAL=YYYY-MM-DD` when
  the account exists; the release checklist (ios/RELEASE.md) reads it and
  blocks a release inside 30 days of lapse without an explicit note.
- **Certificates/profiles**: cloud-managed; the archive step is the check.
- **APNs**: the send worker logs delivery failures per
  `MOBILE_PUSH_OPERATIONS.md`; an auth failure (403 `InvalidProviderToken`)
  is the revoked/expired-key signature.

## Rotation drill (pending — needs the Apple account)

A non-production drill must prove, once the founder steps in
`ios/RELEASE.md` are done: replacement APNs key delivers to a sandbox
device while the old key is revoked; a regenerated ASC key uploads a
build; archive signing survives certificate regeneration; auth recovery
(Privy id rotation) leaves a signed-in device able to refresh. Record the
drill's evidence on the bead when it runs.
