# Open climb data

Download the complete published climb geography used by Boulder Roller. No account, wallet, token ownership, or payment is required. Commercial reuse is permitted under the licences below.

Release: 9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c. Published: 2026-09-09T01:53:33Z. Schema: br-geography-export-1. Includes 57 climb identities and 57 geographic revisions across 1 region.

<a href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/release.zip">Download complete release</a> — ZIP, 1.5 MB (1,488,231 bytes). Uncompressed size: 4.2 MB (4,227,140 bytes). SHA-256: c379351bf44a6dc3bce16c52cc7a7372c573304c0af90e01fa68afa8dd52d667.

Contents: climb centerlines, start and finish lines, authoritative corridors, H3 coverage, elevation samples, geographic revision history, and source/licence notices. The release includes all active and historical published revisions in its manifest, not only the map’s current selection.

Also available: <a href="#individual-files">individual files</a>; <a href="#region-extracts">region extracts</a> (subsets, not the complete release); <a href="#schema-and-verification-instructions">schema and verification instructions</a>; <a href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/NOTICES.txt">source notices</a>; <a href="/open-data#previous-releases">previous releases</a>.

Licence: the published climb database is available under <a href="https://opendatacommons.org/licenses/odbl/1-0/">ODbL 1.0</a>. It contains data derived from <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>. Third-party elevation-content terms and notices are identified in <a href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/SOURCES.jsonl">SOURCES.jsonl</a> and <a href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/NOTICES.txt">NOTICES.txt</a>. Those notices apply where the corresponding source contributes.

Boulder Roller grants ODbL rights in its contributions to this database to the extent it holds those rights. Source providers retain the rights and notices identified in this release; no exclusive right is claimed over public-domain source material.

This release does not contain private candidate hypotheses, raw ride recordings, rider identities, or economic account records. It does not include CARTO basemap tiles or AWS Terrain Tiles merely because those layers appear on the website.

Geometry and elevation processing are described in the release's `climbs.jsonl`. Source providers do not endorse Boulder Roller. An export release is not a change to a climb’s sporting rules or its on-chain commitment.

## Individual files

Every file in this release is listed on the [release page](/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/); <a download href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/SHA256SUMS">SHA256SUMS</a> gives each file's SHA-256 checksum, and manifest.json its size.

## Region extracts

- <a download href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/regions/philadelphia.jsonl">Philadelphia</a>

## Schema and verification instructions

<a download href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/SHA256SUMS">SHA256SUMS</a> · <a href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/manifest.json">manifest.json</a> · <a download href="/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/release.zip.sha256">release.zip.sha256</a>

```sh
sha256sum -c release.zip.sha256
unzip release.zip
sha256sum -c SHA256SUMS
```

On macOS, use `shasum -a 256 -c` in place of `sha256sum -c`.

## All releases {#previous-releases}

- [9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c](/open-data/releases/9f89ef25e834f114a36a2811413363adef9497991f7a984c6a7a9d6378d5999c/) (current)
