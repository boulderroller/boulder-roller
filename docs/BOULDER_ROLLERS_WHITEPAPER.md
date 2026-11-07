# Boulder Rollers

*A pattern-based ride-to-earn protocol using emergent geography*

**Version:** 1.0
**Date:** December 2025

> ⚠️ **PARTIALLY OUTDATED**: This whitepaper describes an earlier CAL model where
> users received a "daily CAL budget" and manually "scored" patterns. The current
> model is: **CAL is earned from TSS on rides (1 CAL per TSS)**, automatically
> tributed to vaults crossed, with no manual scoring. See `docs/TOKENOMICS_V2.md`
> and `docs/gitbook/` for the authoritative current design.

---

## 0. Introduction

Boulder Rollers is a protocol for turning recorded endurance activities into verifiable proofs of effort, and, when desired, into on-chain rewards and identity.

The core ideas are:

* The protocol **does not record activities itself**. It ingests completed files or API payloads from existing devices and services (e.g. Garmin, Strava, Whoop, manual upload).
* Each activity is mapped onto a coarse global grid of **tiles**, and analyzed to detect a small set of **Patterns** that describe meaningful efforts (e.g. climbs, steady work, exploration).
* Riders receive a daily, non-transferable **CAL** allowance that limits how many of those Patterns may be elevated into protocol-level **claims** on a given day.
* When a rider chooses to "score" a Pattern using CAL, the protocol mints a reward token (**DUNG**) and updates on-chain identity objects called **Beetle Cards**, with optional small shares to regional and route-like objects (Arenas and Flows).

The aim is to provide:

* A useful and unobtrusive way to log and understand rides, even without tokens.
* A clear, narrow path from real-world effort → formal Pattern → on-chain attestation and rewards.
* An emergent geographic structure that avoids copying segment-based systems or relying on user-drawn polylines.

The design focuses on a small number of primitives and rules, keeping the protocol understandable and evolvable.

---

## 1. Motivation and Philosophy

### 1.1 Context

Most existing social fitness systems are built around:

* **Segments**: user-defined polylines representing specific routes or portions of routes.
* **Map-matching**: complex algorithms that determine whether an activity "matches" each segment, often under proprietary rules and patents.
* **Centralized curation**: a single platform controls which segments exist, how they are scored, and how they are presented.

This model has several consequences:

* Implementation complexity (segment proliferation, ambiguous matches, edge cases).
* Intellectual property and legal constraints around polyline definitions and matching algorithms.
* A sense of "always-on surveillance", where all movement is constantly compared to a global database.

Boulder Rollers takes a different approach.

### 1.2 Design Principles

The protocol is guided by the following principles:

1. **Post-hoc, not live**
   The system ingests completed activity files. It does not track riders in real time, nor does it require them to plan routes within the protocol.

2. **Patterns, not segments**
   The protocol is interested in recurring *shapes of effort*—such as sustained climbs, steady endurance blocks, or exploration of new areas—rather than predefined polylines.

3. **Emergent geography**
   Instead of user-drawn segments, the protocol uses a global grid of tiles. From activity patterns over time, it derives **Arenas** (regions of interest) and, optionally, **Flows** (frequent uphill lines) as emergent structures.

4. **Simple, explicit rules**
   A small number of clearly defined rules govern:
   * How activities become Patterns,
   * How Patterns become Scored,
   * How rewards are calculated and distributed.

5. **Separation of concerns**
   The heavy data (GPS, streams, tiles) lives off-chain. On-chain, the protocol maintains only:
   * A fungible reward token (DUNG),
   * A set of identity and region objects (Beetle Cards, Arenas, optionally Flows),
   * A single scoring interface that mints and distributes tokens.

6. **Optional participation**
   A rider may treat the system purely as a ride and history viewer. Scoring Patterns, consuming CAL, and minting DUNG are optional layers on top.

The goal is not to replicate existing social fitness platforms on-chain, but to provide a modest, precise set of tools for recognizing and rewarding effort.

---

## 2. System Overview

### 2.1 High-Level Flow

1. A rider completes a ride using an existing device or service.
2. The resulting file or payload is uploaded to Boulder Rollers.
3. The protocol constructs an internal **Activity**:
   * Normalizes the raw telemetry,
   * Projects positions into **tiles**.
4. A **Pattern Engine** analyzes the Activity and detects zero or more Patterns, such as:
   * A climb in a particular Arena,
   * A steady endurance block,
   * A significant amount of new terrain explored.
5. By default, all Patterns remain **unscored**. They inform:
   * Personal history and visualizations,
   * Aggregate maps and difficulty fields,
   * Emergent Arenas and Flows.
6. The rider may optionally choose one or more Patterns from that Activity to **Score**, if they have sufficient **CAL** remaining for the day.
7. The Scoring process:
   * Consumes CAL,
   * Computes a DUNG reward based on the Pattern,
   * Calls an on-chain **Scoring Contract** with a summary attestation.
8. The Scoring Contract:
   * Mints DUNG and distributes it between the rider, Arena/Flow owners (if applicable), and the protocol treasury,
   * Updates relevant **Beetle Cards** (on-chain identity objects),
   * Emits a ScoredPattern event for indexing.

### 2.2 Core Components

**Off-chain (core logic and data):**
* Activity ingestion and canonicalization,
* Tile projection,
* Arena and (optional) Flow discovery,
* Pattern detection (Climb, Steady, Exploration),
* Reward calculation and CAL accounting.

**On-chain (minimal, auditable layer):**
* DUNG token,
* Beetle Cards (soulbound NFTs),
* Arena NFTs (regional objects),
* Optional Flow/ClimbLine NFTs,
* Scoring Contract that mints DUNG and updates Beetle Cards according to a fixed revenue split.

The boundary between off-chain and on-chain is intentionally narrow: on-chain components do not see raw GPS or polyline geometry, only IDs, metrics, and reward amounts.

---

## 3. Data Model

### 3.1 Activities

An **Activity** is the canonical representation of one completed workout file.

For each uploaded file or API payload, the system constructs:

* `activityId` - unique identifier
* `wallet` - user/wallet identifier
* `source` - "garmin" | "strava" | "whoop" | "manual"
* `startTime`, `endTime` - timestamps
* `rawMetrics` - basic aggregates (distance, duration, total ascent)
* `canonicalStream` - optional time series (t, lat, lon, elevation, power?, heartRate?, speed?)
* `tiles[]` - sequence of tile samples (t, tileId, elevation, power?, heartRate?, speed?)
* `patterns[]` - zero or more detected Patterns

### 3.2 Tiles and Arenas

A **Tile** is a cell in a discrete global grid (H3 or S2 at a chosen resolution). Tiles are referenced by IDs.

* Each tile has an ID: `tileId` - integer or fixed-length code
* A deterministic function `index(lat, lon)` maps each coordinate pair to exactly one `tileId`
* Resolution target: ~50–100m cell size for road cycling (H3 res 10/11)

An **Arena** is a named region defined as a set of tiles and summary statistics.

* `arenaId` - unique identifier
* `name` - human-readable label
* `tiles` - set of tileIds at game resolution
* `stats` - optional aggregate statistics

### 3.3 Patterns

A **Pattern** is a recognizable effort shape identified inside one Activity.

**ClimbPattern** - continuous uphill efforts in a climb-oriented Arena
**SteadyPattern** - sustained, steady aerobic work
**ExplorationPattern** - activity involving new or unusual tiles or times

---

## 4. CAL and DUNG

### 4.1 CAL: Daily Claim Budget

CAL represents a rider's daily capacity to turn Patterns into protocol-level claims.

* Baseline daily target: ~2200 units (loosely corresponding to basal metabolic rate)
* Non-transferable, resets daily
* Consumed when scoring Patterns

### 4.2 DUNG: Reward Token

DUNG is a fungible token representing protocol rewards.

* Minted only by the Scoring Contract in response to valid Scored Patterns
* Distribution: α (rider) + β (Arena) + γ (Flow) + τ (treasury) = 1

Initial configuration:
* α = 0.9 (90% to rider)
* β = 0, γ = 0 (no region/flow shares initially)
* τ = 0.1 (10% to treasury)

---

## 5. On-Chain Objects

### 5.1 DUNG Token

Standard fungible asset (SPL). Minting restricted to Scoring Contract.

### 5.2 Beetle Cards (Soulbound NFTs)

Non-transferable NFTs representing a rider's accumulated effort in a given scope.

* `ClimbBeetle(wallet, arenaId)` - climb-specific identity for a particular Arena
* `SteadyBeetle(wallet, "GLOBAL")` - steady-effort history
* `ExplorerBeetle(wallet, "GLOBAL")` - exploration history

Fields: `tokenId`, `owner`, `cardType`, `scopeId`, `score`, `level`, `lastUpdated`

### 5.3 Arena NFTs

Transferable NFTs representing regions. Enable revenue sharing when Arena shares (β > 0) are activated.

### 5.4 Scoring Contract

Receives summary of Scored Pattern from off-chain scoring engine:
* Mints DUNG and distributes according to splits
* Updates or mints relevant Beetle Cards
* Emits `ScoredPattern` event

---

## 6. Emergent Geography and IP Distinction

### 6.1 Emergent Arenas and Flows

The global tile grid allows the protocol to derive geographic structure from usage rather than hand-authored routes.

Over time, as Activities accumulate:
* Tiles with high ride density and significant efforts cluster into **Arenas**
* Within Arenas, frequent uphill sequences become **Flows**

### 6.2 No Segment Database, No Map-Matching Engine

The protocol deliberately avoids:
* Storing a global database of user-defined segments as polylines
* Running a classical map-matching engine to match each Activity to stored polylines

Instead:
* A single projection from `(lat, lon)` to `tileId` anchors all spatial logic
* Patterns are windows over time series within tile sets, not matches against polylines
* "Climbs" are defined by constraints on vertical gain, continuity, and duration in an Arena

This creates clear distance from prior segment-based IP while retaining ability to express "hard efforts in meaningful places".

### 6.3 Privacy Considerations

Tile-based approach offers natural aggregation:
* Public views operate at tile or Arena resolution, not exact coordinates
* Raw GPS streams remain off-chain under user control
* Simple obfuscation schemes (omit home tiles) don't require on-chain changes

---

## 7. Competition Model

### 7.1 Effort-Based (Novel)

Primary competition metric: **relative effort**, not absolute speed.

* W/kg (power-to-weight ratio)
* Effort score (normalized work output)
* Vert/time ratio

Benefits:
* A 60kg rider doing 5.0 W/kg beats an 80kg rider doing 4.0 W/kg
* Rewards training adaptation and fitness
* Route-agnostic within Arena

### 7.2 Time-Based Flows (Future)

Once Flows emerge from rider data:
* "Fastest on Flagstaff Flow" leaderboards
* Classic KOM competition feel
* Tile sequence matching (not polyline matching)

---

## 8. Extensions and Future Work

### 8.1 Epistemic Layer

Trust and disputes:
* Credibility scores for wallets and devices
* Challenges with staking for suspicious attestations
* Slashing for fraudulent patterns

### 8.2 Additional Pattern Families

* Short maximal efforts (sprints)
* High-intensity intervals
* Multi-rider group patterns

### 8.3 Governance

* Approve/deprecate Arenas
* Adjust reward splits
* Set scoring function bounds

### 8.4 External Composability

Because DUNG is standard fungible token and Beetle Cards are on-chain:
* Other systems can use Beetle Cards for eligibility
* Additional reward layers on ScoredPattern events
* Third-party analytics around Arenas and Flows

---

## 9. Conclusion

Boulder Rollers presents a narrow, pattern-based view of ride-to-earn:

* It accepts completed activities from existing recording systems.
* It maps them into a tiled representation of the world and detects a small set of Patterns.
* It introduces CAL as a daily claim budget and DUNG as a reward token.
* It uses a minimal set of on-chain objects—DUNG, Beetle Cards, Arenas, optional Flows—to anchor identity and regional structure.

The emphasis is on clarity, modesty of scope, and separation of concerns. The protocol does not attempt to recreate the entire social experience of existing platforms, nor to encode every possible aspect of training. Instead, it focuses on a small, well-defined bridge between real-world effort and verifiable on-chain records, leaving room for emergent geography and future extensions.

---

## Appendix: Glossary

| Term | Definition |
|------|------------|
| **Activity** | A single uploaded workout/ride |
| **Arena** | Named region defined as set of tiles |
| **Attestation** | Signed proof of effort (internal) |
| **Beetle Card** | Soulbound NFT tracking effort history |
| **CAL** | Daily claim budget (non-transferable) |
| **DUNG** | Fungible reward token |
| **Flow** | Emergent route from tile sequences |
| **Pattern** | Recognized effort shape (Climb/Steady/Exploration) |
| **Scoring** | Process of claiming Pattern for DUNG reward |
| **Tile** | H3 hexagonal cell in global grid |
