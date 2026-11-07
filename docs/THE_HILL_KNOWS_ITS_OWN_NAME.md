# The Hill Knows Its Own Name

*How Boulder Rollers replaced 90 hand-tuned parameters with provable mathematics*

---

## The Problem

Climb detection in cycling apps is built on educated guesses. An engineer sets thresholds — "minimum 50 meters gain," "at least 4% gradient," "duration over 2 minutes" — and tweaks them until the results look reasonable. By the time it works across different terrain types, there are roughly 90 configurable parameters, split across separate profiles for flat, rolling, hilly, and mountainous riding.

These systems are approximately right in the places that got the most attention, and quietly wrong everywhere else. They miss climbs that don't fit the template. They hallucinate climbs that do fit but aren't really there. And the fingerprinting — the way the system recognizes "this is the same hill" across different rides — uses SHA256 hashing, a cryptographic function designed to make similar inputs produce completely different outputs. Two GPS recordings of the same hill routinely produce different fingerprints.

For a social fitness app, that's an annoyance. For a platform where economic value is attached to geographic features — where riders stake tokens on real-world climbs — it's a structural problem.

## What We Built

Four components, each grounded in established mathematics, each replacing a category of hand-tuning.

### 1. Persistent Homology — Finding Every Climb

A branch of topology that extracts ALL elevation features at ALL scales in a single pass. Zero tunable parameters. The algorithm processes the elevation profile once and returns every bump, hill, and mountain pass, with exact start and end boundaries and a mathematical measure of each feature's prominence.

It also builds a merge tree — a hierarchy showing how small features nest inside larger ones. A mountain pass with intermediate valleys is represented exactly: one parent feature containing sub-features, each with precise boundaries. No heuristic trimming.

**What it replaces:** The momentum-based detector, 5 terrain presets, all gradient/duration/vert thresholds.

### 2. Noise Floor — Knowing What's Real

GPS altimeters have ~1 meter of random error per reading. Using extreme value theory (the math behind flood modeling and catastrophe insurance), we derived that any feature smaller than 3.0 meters is indistinguishable from sensor noise at 99.9% confidence. That number comes from the physics of the BMP280 barometric sensor, not from an engineer's judgment.

**What it replaces:** Arbitrary "minimum 50m" thresholds that throw away real climbs to avoid false positives.

### 3. Geographic Significance — Context-Aware Scoring

A 30-meter hill in the Netherlands is remarkable. In the Alps, it's a speed bump. For each ~250 km² hexagonal cell on Earth, we fit a Generalized Pareto Distribution to all terrain features in that area. The shape of the distribution automatically encodes the terrain type — mountainous regions have heavy tails (there's always a bigger climb), flat regions have bounded distributions (there's a physical maximum).

Every climb gets a significance score from 0 to 1 meaning "how rare is this feature for this specific area." The system reports confidence tiers and caps scores when data is sparse — it never claims more certainty than it has.

Three fitted parameters per cell. ~8MB compressed for global coverage. ~$5-10 to compute.

**What it replaces:** Discrete terrain classification (flat/rolling/hilly/mountainous) and the assumption that all climbs are equally significant.

### 4. DCT Signatures — Fingerprints That Preserve Similarity

The Discrete Cosine Transform — the math behind JPEG and MP3 — creates climb fingerprints where similar hills produce similar fingerprints. Two recordings of the same climb with GPS noise produce a distance of ~0.014. Two different climbs produce ~0.092+. A 2.3x separation gap, validated across 500 synthetic profiles.

64 bytes per signature, including a geographic anchor to prevent matching hills on opposite sides of a ridge. Multi-gate matching: version check → geographic proximity → vertical/distance tolerance → shape comparison.

**What it replaces:** SHA256 gradient hashing (where similarity is mathematically destroyed by design).

## The Numbers

| | Before | After |
|---|---|---|
| Tunable parameters | ~90 hand-set | 1 derived + 3 fitted per cell |
| Climb boundaries | Heuristic trim (guessed) | Topological (exact) |
| Noise floor | 15-100m (guessed) | 3.0m (derived, 99.9% confidence) |
| Terrain context | 4 discrete categories | Continuous per 250 km² |
| Signature matching | SHA256 Hamming (broken) | DCT relative Euclidean (2.3x gap) |
| Algorithm complexity | O(n) with large constant | O(n) single pass |

## Why It Matters

**For the product:** Vaults — on-chain representations of real-world climbs — are built on geographic truth, not engineering opinion. Matching is reliable. Significance is fair across all terrain.

**For DePIN:** This is a general-purpose system for turning noisy physical-world sensor data into reliable, matchable digital features. The detection is parameter-free and reproducible. The fingerprints are stable. The scoring is geographically honest. It applies to any sensor network that needs to verify physical-world claims.

**For IP:** Two rounds of expert mathematical review scored the components 7-9/10 and assessed the work as publishable at academic venues (ACM SIGSPATIAL, computational geometry conferences). This is novel intellectual property, not just engineering.

**For open-source:** The core detection and fingerprinting system will be released as an open-source DePIN Telemetry SDK, positioning Boulder Rollers as infrastructure in the broader ecosystem.

---

*Full technical specification: `docs/CLIMB_DETECTION_V2_SPEC.md`*
