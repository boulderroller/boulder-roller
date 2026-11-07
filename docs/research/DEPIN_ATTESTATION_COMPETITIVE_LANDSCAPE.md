# DePIN Attestation + Competitive Landscape -- Research Report

**Date:** 2026-04-15
**Author:** Research agent (opus)
**Purpose:** Inform grant applications, investor conversations, and architectural decisions for Boulder Rollers

---

## Executive Summary

Boulder Rollers occupies a unique position in both the DePIN attestation landscape and the fitness-crypto market. Among DePIN protocols, its canonical-hash attestation architecture -- deterministic ride hashing with on-chain commitment and structural replay protection -- is more rigorous than any fitness-crypto competitor and comparable in design intent to serious DePIN projects like Helium and DIMO, albeit without trusted hardware. Among fitness-crypto projects, Boulder Rollers is the only protocol focused specifically on cycling geography with permanent on-chain economic objects (Climbs, Vaults, Record Boards). The move-to-earn sector (STEPN, Sweatcoin, Genopets) has matured but remains dominated by walking/running with thin attestation -- GPS plus accelerometer heuristics, no user-verifiable hashes, no on-chain ride commitments. No competitor combines cycling-specific climb detection, geographic financialization, canonical ride hashing, and dual-token staking economics. The biggest gap is the absence of trusted hardware; the biggest differentiator is the permanent geographic asset model that makes staking economically meaningful beyond simple move-to-earn tokenomics.

---

## 1. DePIN Sensor Attestation Patterns

### Summary Table

| Protocol | Sensor Type | Attestation Method | User-Verifiable? | Chain | Trust Boundary |
|----------|------------|-------------------|-------------------|-------|----------------|
| Helium | RF coverage | Hardware ECC keys + oracle PoC + witness consensus | Partial (witness receipts public) | Solana | Oracle verification of RF signals |
| DIMO | Vehicle OBD-II telemetry | Secure element (hardware) + ECDSA signing + on-chain vehicle NFTs | Partial (signed data, no recomputation) | Polygon | Device firmware integrity |
| Hivemapper | Dashcam imagery | Vision-based consensus across devices + AI Map validation | No (AI-internal) | Solana | Centralized AI map processing |
| WeatherXM | Weather sensors (temp, humidity, irradiance) | Solar Obstacle Detection + QoD scoring + Proof of Location | Partial (QoD scores visible) | Wormhole/custom | Backend QoD algorithm |
| IoTeX W3bstream | General (any sensor) | Multi-prover: ZK circuits, TEE, MPC | Yes (ZK proofs verifiable on-chain) | IoTeX (EVM) | Circuit correctness + prover integrity |
| Geodnet | GNSS corrections | Proof of Location + Proof of Accuracy + BLS consensus | Partial (accuracy scores visible) | Custom + Solana bridge | Validator cross-reference |
| Silencio | Phone microphone (noise dB) | DID per device + on-chain noise records + photo verification | No (backend scoring) | Peaq | Phone sensor trust + backend |
| Natix | Phone/Tesla cameras | Edge AI processing + privacy anonymization + community validation | No (AI-internal) | Peaq | Edge compute integrity |

### Protocol Details

**Helium** is the gold standard for DePIN attestation. Hotspots embed ECC/RSA cryptographic keys at the factory. Proof of Coverage requires each hotspot to beacon every 6 hours; approximately 12 nearby witnesses must cryptographically confirm they received the RF signal. Off-chain Oracles verify signal-to-noise ratios and geometric consistency, then submit signed reports to Solana for reward settlement. The trust boundary starts at the Oracle layer -- the physical RF verification happens off-chain, and users must trust that Oracle operators are honest. However, the multi-witness requirement makes single-actor spoofing extremely difficult. Helium uses H3 hexagons (like Boulder Rollers) for density scaling. [1][2]

**DIMO** takes a trusted-hardware approach. Their Macaron dongle and LTE R1 device contain secure elements that sign vehicle telemetry data with ECDSA (secp256k1). Vehicles are minted as on-chain NFTs on Polygon with paired device identity. Data authenticity is bound to the hardware key -- a compromised device can produce fake data, but the cryptographic chain from device to chain is intact for legitimate hardware. Users cannot independently recompute attestations without access to the signing key. DIMO's trust boundary is device firmware integrity. [3][4]

**Hivemapper** uses a vision-based consensus mechanism where multiple Bee dashcams independently capture imagery of the same area. The network cross-references observations at the hex level -- if multiple devices report similar objects at similar locations and times, data is treated as valid. Map AI processes raw footage into structured map data. This is strong against single-actor fraud but the AI processing is centralized and not independently auditable by contributors. Built on Solana with state compression for efficient rewards. [5][6]

**WeatherXM** developed Solar Obstacle Detection (SOD), which compares theoretical solar irradiance curves against actual station measurements to verify proper installation and detect manipulation. A Quality of Data (QoD) score drives token rewards. They also use Proof of Location and require users to submit installation photos ("Know Your Station"). The trust boundary is the backend QoD algorithm -- users see their scores but cannot audit the algorithm. [7][8]

**IoTeX W3bstream** is the most architecturally ambitious framework. It is a generalized off-chain compute layer supporting ZK proofs (via Risc0, SP1, Circom, Halo2), TEE execution (Intel SGX/TDX, AMD SEV, AWS Nitro), and MPC. Prover nodes process sensor data and generate validity proofs that are verifiable on-chain. For location specifically, they have demonstrated ZK proofs of liveness, location, and movement with GEODNET hardware. This is the closest thing to a trustless DePIN attestation framework, though practical deployment remains limited to a handful of partner projects. [9][10]

**Geodnet** operates a network of GNSS base stations providing centimeter-accuracy correction data. Proof of Location and Proof of Accuracy protocols verify geographic authenticity. Validator nodes cross-reference data quality against nearby stations and use BLS signature consensus. This detects spoofing at the network level. Trust boundary: validator honesty and station hardware integrity. [11]

**Silencio** and **Natix** both rely primarily on smartphone sensors (microphone and camera respectively) with backend validation. Silencio uses decentralized device identity (DID) on Peaq and processes 30K+ daily transactions on-chain, but the noise measurement validation is server-side. Natix uses edge AI for privacy-preserving image processing but data validation is similarly centralized. Neither offers user-verifiable attestation of individual contributions. [12][13]

---

## 2. ZK Proofs for Physical Sensor Data

### Current State

Zero-knowledge proofs for physical sensor data are technically feasible but not yet production-ready for real-time fitness applications.

**Published work exists** for ZK Proof-of-Location (zk-PoL). Academic papers demonstrate systems where a vehicle can prove territorial compliance without revealing exact GPS coordinates. The zkMaps project on GitHub proves a user is within a geographic area without exposing precise location. IoTeX W3bstream has demonstrated ZK proofs of movement using GEODNET hardware with Risc0's zkVM. [14][15]

**zkML is maturing rapidly.** EZKL can convert ONNX ML models to ZK-SNARK circuits. zkPyTorch (March 2025) proved VGG-16 inference in 2.2 seconds. Modulus Labs benchmarked on-chain inference up to 18M parameters. Giza is using zkML for DeFi yield strategy verification. By 2026, experts predict production-grade zkML in finance and healthcare. [16][17]

**For GPS traces specifically:** ZK-PoL protocols achieve acceptable security against main attacks but with ~2-minute average execution times -- suitable for delay-tolerant applications (post-ride attestation) but not real-time. Proving "I was at location X" without revealing the full trace is demonstrated in research; proving "I completed this specific climb route" with sensor fusion (GPS + power + HR + elevation) at ZK-grade rigor is not yet demonstrated by anyone. [14]

### Feasibility Assessment for Boulder Rollers

A ZK proof that a rider completed a specific climb (matching elevation profile, within GPS bounds, with plausible power/HR data) is **2-3 years from practical deployment** for the following reasons:

1. **Circuit complexity:** Boulder Rollers' canonical ride hash involves thousands of 1Hz sensor samples with multi-field aggregation. Converting this to a ZK circuit is possible but expensive to prove.
2. **No cycling-specific ZK work exists.** All published zk-PoL work focuses on point-in-region or trajectory compliance, not multi-sensor fitness attestation.
3. **The ROI is unclear today.** Our canonical-hash approach already provides replay protection and user-verifiability of the commitment. ZK would add privacy (hiding the trace while proving the ride) and trustlessness (removing backend authority from the attestation). Privacy is a future benefit; trustlessness matters more at scale but is premature for devnet/alpha.

### Trust Spectrum Comparison

```
Most Trusted (least verification)
  |  Honor system (most M2E apps)
  |  GPS + accelerometer heuristics (STEPN SMAC)
  |  Backend-attested canonical hash (Boulder Rollers) <-- WE ARE HERE
  |  Trusted hardware signing (DIMO, Helium)
  |  Multi-device consensus (Hivemapper, Helium PoC)
  |  ZK proof of computation (IoTeX W3bstream)
  |  ZK proof of sensor data + location (research stage)
Most Trustless (full verification)
```

Boulder Rollers sits at a meaningful point on this spectrum: the canonical hash binds the backend's attestation to the rider's source file, so a dishonest backend produces a hash the rider can detect. This is stronger than any M2E competitor and comparable to DIMO's device-signing model (without requiring custom hardware).

---

## 3. Fitness/Cycling Crypto Competitive Landscape

### Summary Table

| Project | Status | Chain | Token Model | Activity Verification | User-Verifiable? |
|---------|--------|-------|-------------|----------------------|-------------------|
| STEPN | Active | Solana/BSC/own | Dual (GMT/GST) | SMAC ML anti-cheat (GPS+accel) | No |
| Sweatcoin | Active | NEAR/multi | Single (SWEAT) | Movement Validator algorithm | No |
| Genopets | Active (low activity) | Solana | Dual (GENE/KI) | Step counting via phone | No |
| Wirtual | Active | BSC | Single (WIRTUAL) | Strava/Fitbit/Garmin API | No |
| MapMetrics | Active | Peaq (ex-Solana) | Single (MMAP) | Drive GPS tracking | No |
| Dotmoovs | Low activity | Polygon | Single (MOOV) | AI video analysis of sports moves | No |
| FitBurn | Low activity | Custom | Single (CAL) | Calorie tracking | No |
| BikeRush | Effectively dead | BSC | Dual (BRT/BST) | GPS cycling tracking | No |
| RunBlox | Dead/pivoted | Avalanche | Dual (RUX/OBX) | GPS run tracking | No |
| PUML | Low activity | Solana | Single (PUMLx) | Steps + corporate wellness | No |

### Project Details

**STEPN** remains the dominant move-to-earn platform by brand recognition and market cap. Their SMAC (STEPN Model for Anti-Cheating) system uses machine learning trained on GPS, accelerometer, and health data with autoencoder-based anomaly detection. Users who trigger anti-cheat lose their "Turing Score" and face marketplace restrictions. GMT governance token has a 6B fixed supply; GST utility token is inflationary. STEPN GO (2024) expanded the platform. The token is down 80%+ from highs but the platform remains active. Key weakness: walking/running only, no geographic financialization, no on-chain activity commitments, NFT sneaker model creates high entry barrier. [18][19]

**Sweatcoin/Sweat Economy** is the largest by user count (200M+ registered users, 21M+ active). Their "Movement Validator" algorithm has been developed over 9+ years to verify steps from true physical activity. The November 2025 "1-1-1" update added multichain support (Ethereum, Base, BNB, Arbitrum, NEAR) and SWEAT as a universal gas token. The Sweat Foundation burned 600M tokens and committed to buyback-funded sustainability. Key weakness: step-counting only, no cycling support, no geographic economics, OKX delisted SWEAT in Dec 2025. [20][21]

**Genopets** combines move-to-earn with virtual pet nurturing on Solana. Steps convert to in-game Energy for pet evolution and PvP battles. Technically active but engagement appears low in 2025-2026. Dual token (GENE governance + KI utility). Verification is basic phone step counting. No cycling or geographic component. [22]

**Wirtual** is the closest to a multi-sport platform, supporting running, walking, swimming, cycling, dancing, and working out. It connects to Strava, Fitbit, Garmin, and Apple Health APIs. BSC-based with tier-based earning (more tokens held = more earned). Active but small user base. Key distinction: supports cycling activities via Strava integration, but no climb detection, no geographic assets, no on-chain ride commitments. [23]

**MapMetrics** is a drive-to-earn DePIN that rewards navigation data contribution. Migrated from Solana to Peaq in 2024-2025. Microsoft mapping data partner. Building B2B data sales to sustain tokenomics. Active development with AI search features planned. Not fitness-focused but relevant as a geographic DePIN on the earn-while-moving spectrum. [24]

**BikeRush** was the most direct cycling competitor -- a ride-to-earn dApp with NFT bicycles on BSC, clearly modeled on STEPN's mechanics. All available information dates to 2022. The website (bikerush.io) exists but there are no 2024-2026 updates. **Effectively dead.** [25]

**Dotmoovs, FitBurn, RunBlox, PUML** are all in various states of minimal activity or effective death. Dotmoovs claims 200K users for AI-judged sports challenges on Polygon. FitBurn's CAL token (confusing name overlap with Boulder Rollers' CAL) trades near zero. RunBlox appears to have pivoted or shut down. PUML focuses on corporate wellness with minimal crypto integration. None have meaningful cycling features or attestation rigor. [26][27]

---

## 4. Boulder Rollers Competitive Position

### 1. Where does Boulder Rollers sit on the attestation-rigor spectrum?

Boulder Rollers has the **strongest attestation of any fitness-crypto project** and is **mid-tier among serious DePIN protocols**. The canonical ride hash (deterministic 1Hz sample quantization, sorted-key JSON serialization, SHA-256, on-chain RideAttestation PDA with parser versioning) is categorically more rigorous than STEPN's SMAC, Sweatcoin's Movement Validator, or any other M2E platform's approach. No fitness-crypto competitor commits a user-recomputable hash to chain. Among broader DePIN, Boulder Rollers lacks trusted hardware (Helium, DIMO) and multi-device consensus (Hivemapper), but its hash-binding architecture means a compromised backend produces detectable evidence -- a property most DePIN protocols lack.

### 2. What does Boulder Rollers do that NO competitor does?

- **Geographic financialization of cycling climbs.** No one else turns real hills into permanent on-chain economic objects with staking, Record Royalty, and stewardship roles.
- **Canonical ride hashing with user-verifiability.** The rider holding the source FIT/GPX file can independently recompute the hash and compare it against the on-chain RideAttestation. Zero M2E competitors offer this.
- **Permanent Record Board economics.** All-time top 10 riders earn ongoing Record Royalty from vault activity -- permanent excellence rewarded in perpetuity. This has no analog in any competitor.
- **Structural replay protection via child receipt PDAs.** CalMintReceipt and ClimbCompletionReceipt keyed by ride attestation prevent economic duplication at the Anchor constraint level.
- **Dual-token model with real geographic yield.** CAL (effort) and DUNG (value) separated by function, with yield derived from geographic traffic, not inflationary emission alone.

### 3. What do competitors do that Boulder Rollers should consider?

- **Trusted hardware (DIMO model):** A dedicated cycling computer or sensor with a secure element could sign ride data at the device level, moving the trust boundary from "backend-attested" to "hardware-attested." This would be a significant upgrade but requires hardware partnerships.
- **ML anti-cheat (STEPN SMAC):** STEPN's autoencoder-based anomaly detection on motion patterns is worth studying. Boulder Rollers' climb detection engine already analyzes power/HR/elevation consistency, but a dedicated adversarial-input detection model would strengthen fraud resistance.
- **Multi-device consensus (Hivemapper model):** If multiple riders complete the same climb, cross-referencing their attestations (elevation profiles, timing, GPS traces) could create a consensus layer without trusted hardware.
- **Multichain presence (Sweatcoin "1-1-1"):** Sweatcoin's expansion to 5+ chains broadened their reach. Boulder Rollers' Solana-native approach is correct for now but worth watching.

### 4. Is there a cycling-specific gap in the market?

**Yes -- a massive one.** BikeRush (the only cycling-specific M2E project) is effectively dead. Wirtual supports cycling via Strava integration but treats it identically to walking/swimming with no cycling-specific intelligence. No active project does cycling-specific climb detection, geographic vault economics, or power-meter-aware attestation. The intersection of "cycling + DePIN + geographic financialization" is entirely unoccupied. Strava dominates cycling data but has no token economics and no on-chain presence. The gap is clear and wide.

### 5. What is the strongest "why us, not them" argument?

For a grant committee or investor: **Boulder Rollers is the only protocol that creates permanent, stakeable geographic assets from real cycling data with cryptographically committed ride attestation on Solana.** Every M2E competitor rewards movement generically -- walk here or there, it does not matter. Boulder Rollers rewards specific geographic achievement: that hill, that climb, that record. The attestation architecture (canonical hashing + on-chain commitment + structural replay protection) is more rigorous than any fitness-crypto competitor and designed for progressive decentralization toward ZK or hardware attestation. The dual-token model creates real geographic yield (stakers earn from climb traffic), not just inflationary emissions. And the cycling-specific gap in the market is completely uncontested.

---

## 5. Recommendations

1. **Publish the attestation architecture.** The canonical ride hashing spec is a competitive moat. Write a public technical blog post explaining the trust model for grant reviewers and investors who will compare against STEPN/Sweatcoin's vague "anti-cheat" claims.

2. **Explore multi-rider consensus as a near-term trust upgrade.** When multiple riders complete the same climb, cross-referencing their elevation profiles and GPS traces provides a consensus signal without requiring hardware. This is achievable with current architecture and strengthens the "progressive decentralization" narrative.

3. **Monitor IoTeX W3bstream for ZK integration.** W3bstream's multi-prover framework (ZK circuits via Risc0/SP1) is the most production-ready path to proving ride attestations in ZK. When their tooling matures, Boulder Rollers' canonical serialization format is already ZK-circuit-friendly (integer quantization, deterministic ordering, fixed schema).

4. **Do NOT pursue trusted hardware in the near term.** Hardware partnerships are capital-intensive and premature for alpha. The canonical-hash approach with backend authority is the right trade-off for 2026. Plan the migration path (device-signed attestations) but do not execute until post-TGE with meaningful user base.

5. **Emphasize the cycling gap in grant applications.** BikeRush is dead. Wirtual treats cycling as an afterthought. Strava has no tokens. The Solana ecosystem has zero cycling-specific DePIN projects. This is the clearest market gap argument available.

6. **Build an anomaly detection model for GPS spoofing.** STEPN's SMAC approach (autoencoder on motion data) is applicable. Power-meter correlation with elevation gain is a strong signal unique to cycling -- a rider claiming a 1000m climb with 50W average power is implausible. This is achievable with existing data.

7. **Position as "DePIN for cycling geography" not "move-to-earn."** The M2E label carries baggage from STEPN/Sweatcoin's speculative cycles. Boulder Rollers' geographic financialization model is structurally different and should be framed as DePIN (geographic infrastructure) rather than M2E (token emission for movement).

---

## Sources

1. [Helium Technical Deep Dive -- Solana](https://solana.com/news/case-study-helium-technical-guide)
2. [Helium Post-Solana Architecture Audit -- Medium](https://medium.com/@teplov.a.g.186/helium-network-a-technical-audit-of-post-solana-depin-architecture-9d43f5e55c39)
3. [DIMO -- CoinMarketCap Overview](https://coinmarketcap.com/cmc-ai/dimo/what-is/)
4. [DIMO Macaron -- Support Documentation](https://support.dimo.co/en-US/dimo-macaron-tech-specs-299449)
5. [Hivemapper Map Data Verification -- Docs](https://docs.hivemapper.com/honey-token/map-data-structure-and-verification)
6. [Hivemapper Case Study -- Solana](https://solana.com/news/case-study-hivemapper)
7. [WeatherXM Know Your Station -- DePIN Scan](https://depinscan.io/news/2025-02-12/weatherxm-introduces-know-your-station-feature-for-enhanced-weather-data-quality)
8. [WeatherXM Network -- Official](https://weatherxm.com/the-network/)
9. [W3bstream GitHub -- IoTeX](https://github.com/iotexproject/w3bstream)
10. [W3bstream Multi-Prover Architecture -- IoTeX Docs](https://docs.iotex.io/depin-infra-modules-dim/w3bstream-depin-verification/multi-prover-architecture)
11. [GEODNET Research Report -- Medium](https://medium.com/@done_71651/geodnet-geod-in-depth-research-report-the-real-yield-king-of-the-depin-sector-35d3e4a6733f)
12. [Silencio on Peaq -- Medium](https://silencionetwork.medium.com/silencio-network-pioneering-depin-on-peaq-with-on-chain-excellence-5c922b45bad7)
13. [Natix Network -- Official](https://www.natix.network/)
14. [ZK Proof of Location in IoT -- IEEE](https://ieeexplore.ieee.org/document/9149366/)
15. [zkMaps -- GitHub](https://github.com/zkMaps/zkMaps)
16. [Definitive Guide to ZKML 2025 -- ICME](https://blog.icme.io/the-definitive-guide-to-zkml-2025/)
17. [State of EZKL 2025 -- EZKL Blog](https://blog.ezkl.xyz/post/state_of_ezkl/)
18. [STEPN SMAC Anti-Cheating -- Whitepaper](https://go-whitepaper.stepn.com/infrastructure-module/smac-cheating-detection)
19. [STEPN Anti-Cheating System -- Whitepaper](https://whitepaper.stepn.com/game-fi-systems/anti-cheating-system)
20. [Sweatcoin Legitimacy Review 2026 -- Bitget](https://www.bitget.com/academy/sweatcoin-legit)
21. [SWEAT Multichain Update -- Medium](https://medium.com/sweat-economy/final-week-to-claim-your-sweat-allocation-e77503f6eb1a)
22. [Genopets -- Solana Compass](https://solanacompass.com/projects/genopets)
23. [Wirtual Whitepaper -- Gitbook](https://wirtual.gitbook.io/wirtual-whitepaper-eng/wpp-for-wirtual-3.0/sweat-mining)
24. [MapMetrics DePIN Podcast -- CryptoSlate](https://cryptoslate.com/podcasts/mapping-the-future-brent-van-der-heiden-on-mapmetrics-drive-to-earn-and-the-power-of-depin/)
25. [BikeRush -- Official](https://bikerush.io/)
26. [FitBurn -- CoinMarketCap](https://coinmarketcap.com/currencies/fitburn/)
27. [Move-to-Earn Overview 2026 -- CryptoNews](https://cryptonews.com/cryptocurrency/best-move-to-earn-crypto/)
28. [DePIN Tokenomics -- Frontiers in Blockchain](https://www.frontiersin.org/journals/blockchain/articles/10.3389/fbloc.2025.1644115/full)
29. [IoT Device Attestation -- Chainscore Labs](https://chainscorelabs.com/glossary/depin-decentralized-physical-infrastructure/depin-resource-markets/iot-device-attestation)
30. [IoTeX + GEODNET Collaboration](https://iotex.io/blog/iotex-and-geodnet-announce-pioneering-collaboration-for-depin-verifiability/)
