# Physics Residual Noise Budget — Empirical Study on the Golden Corpus

**Bead:** `boulderroller-v2-wm0w` · **Date:** 2026-07-16 · **Status:** Research findings (no production code touched)

**Question:** Can a physics residual engine — reported power-meter watts vs physics-implied watts over known climb geometry — serve as a fraud detector (fabricated FIT files, BLE power inflation, e-bikes)? The physics is settled; the unknown was the **false-positive rate on honest riders**. All corpus rides are honest, so the measured residual distribution *is* the honest-rider noise floor.

---

## TL;DR — Go, narrowly scoped

**GO as a gated evidence tier; NO-GO as a general-purpose lie detector.** The residual is tight exactly where the physics says it should be — steep, sustained climbs — and useless on shallow grades where aero and drafting dominate.

Headline numbers (545 gated traversals: stream grade ≥ 4 %, duration ≥ 120 s, global fitted mass):

1. **Honest noise floor on gated climbs:** median +0.1 %, IQR [−4.7, +4.1] %, p5/p95 [−12.8, +11.5] %. On 6–8 % grades the IQR narrows to [−2.7, +4.9] % (MAD 5.8 %). On 2–4 % grades it blows out to IQR ≈ 20 % wide — that regime is unusable.
2. **E-bike-style fraud (same watts, +8 km/h) is caught essentially for free:** 99.5–100 % catch at ride level at a −20 % threshold whose honest negative-side FPR is ≈ 4 %. Even +5 km/h assist is caught at 93–99 %.
3. **Gross power inflation (+25 %) is catchable:** 84 % ride-level catch at a one-sided +15 % threshold with **1.5 % honest FPR** (0.5 % FPR / 71 % catch at +20 %).
4. **Subtle inflation (+10 %) is below the noise floor:** only 22–50 % catch at any acceptable FPR. Do not claim detection below ~15 % inflation.
5. **Weather verdict: DROP.** Open-Meteo 10 m wind applied at full strength makes residuals *worse* (IQR 14.1 → 20.7 %); the best sheltering scale (k ≈ 0.3) buys only ~3–4 % IQR/MAD reduction. Model wind decorrelates from road-level wind on sheltered SEPA roads — the decorrelation is the finding.
6. **Derived weigh-in is feasible:** total system mass fits at 81.4 kg with ±3 kg IQR across steep traversals and 1.4–4.6 kg IQR on repeated segments, stable 2013–2016. The 2017 collapse (to a fitted 63.8 kg) is drafting/equipment contamination, not weight loss — which is itself the design lesson: **calibration must be per-athlete, per-equipment-era, and rolling.**

The single largest un-modeled noise term on this corpus is **drafting, not wind**: 2017 fast group rides (28–39 km/h on ~2 % grades) produce −50 to −70 % residuals. Positive-side (inflation) detection is inherently robust to drafting (drafting only pushes residuals negative); negative-side (e-bike) detection needs either a deeper threshold or a solo-effort gate.

---

## 1. Census

Everything below is bounded by this table.

| Population | Count |
|---|---|
| Rides in corpus (`activity_streams`) | 1,416 |
| Rides with time+latlng+altitude+distance | 1,416 (100 %) |
| Rides with a `watts` stream | **480** (34 %) — every one has 100 % watts sample coverage |
| Years covered by watts rides | 2012–2018 |
| Geography of watts rides | SEPA 308, LA/Malibu 83, Other 40, Tucson 19, Vermont/NH 12, rest ≤ 10 each |
| `velocity_smooth` present | 0 rides (velocity derived from distance stream) |
| Raw climb-segment efforts in watts rides (Strava efforts, elev ≥ 25 m AND grade ≥ 2 %) | 4,525 across 1,148 segments |
| **Deduplicated, quality-gated traversals** | **1,534** across **333 rides**, 508 unique segments |
| Favorable regime (stream grade ≥ 4 %, T ≥ 120 s) | **545 traversals**, 202 rides, 217 segments (36 % of traversals) |
| Steep calibration set (grade ≥ 6 %, T ≥ 120 s) | 178 traversals |

Dedup + quality gates removed 66 % of raw efforts, consistent with the corpus lesson that ~53 % of segments are stacked duplicates of the same hill. Per-ride interval clustering (overlap > 20 % of the shorter effort → same hill; keep the largest-elevation version) plus gates: duration ≥ 60 s, distance ≥ 200 m, no recording gap > 10 s inside the effort (103 dropped), ≥ 95 % valid watts, mean power ≥ 80 W (20 dropped), smoothed stream Δh ≥ 15 m (129 dropped — mostly lumpy segments where Strava's high−low `elevation_diff` overstates net gain).

## 2. Method and assumptions

Segment-level **energy balance** (not instantaneous comparison — integrating over the traversal kills sample-level noise):

```
W_wheel = η · P̄_reported · T
W_wheel = m·(g·Δh + Crr·g·D + ΔKE/kg) + ½·ρ·CdA·∫v_air²·v dt
residual% = (P̄_reported − P_implied) / P_implied,  P_implied = W_physics / (η·T)
```

| Parameter | Value | Basis |
|---|---|---|
| Drivetrain efficiency η | 0.975 | power meters read at crank/pedal; wheel sees ~97.5 % |
| Crr | 0.005 | road tires, dry pavement (prior range 0.004–0.008) |
| CdA | 0.32 m² | climbing position (prior range 0.25–0.40) |
| Air density ρ | 1.225·exp(−alt/8435) | altitude-scaled ISA; Open-Meteo T/P refinement tested, negligible (§6) |
| System mass m | **fitted** — 81.4 kg global; per-year variant | closed-form per traversal (§5) |
| Altitude smoothing | 15 s centered moving average; Δh from mean of first/last 10 s | Strava-corrected altitude is still noisy |
| Velocity | derivative of 5 s-smoothed distance stream | no `velocity_smooth` in corpus |
| KE term | ½(v₁²−v₀²) from endpoint speeds (5 s means) | matters on short efforts entered at speed |
| Rolling term | Crr·m·g·D (cos θ ≈ 1 up to 15 % grades) | <1.1 % error at max grades seen |

**Why steep grades are the favorable regime** — median share of total work done against gravity, by grade band: 2–4 %: 59 % · 4–6 %: 76 % · 6–8 %: 87 % · ≥8 %: 92 %.

**Assumption sensitivity** (median residual shift if the assumption is wrong):

| Perturbation | 2–4 % | 4–6 % | 6–8 % | ≥8 % |
|---|---|---|---|---|
| mass +5 kg | +4.3 % | +5.2 % | +5.7 % | +5.9 % |
| Crr +0.002 | +4.2 % | +3.2 % | +2.6 % | +2.1 % |
| CdA +0.07 | +6.7 % | +3.5 % | +1.6 % | +0.9 % |

On steep grades the only assumption that materially matters is mass — which is why mass is fitted, and why aero/rolling priors can stay fixed.

## 3. Honest residual distributions

All 1,534 traversals, global mass (residual %, reported − implied):

| Slice | n | median | IQR | p5 | p95 |
|---|---|---|---|---|---|
| **All** | 1,534 | −0.4 | [−8.1, +5.7] | −31.2 | +17.4 |
| Grade 2–4 % | 866 | −1.9 | [−13.5, +6.4] | −35.1 | +18.4 |
| Grade 4–6 % | 459 | +0.5 | [−5.2, +4.8] | −21.0 | +15.3 |
| Grade 6–8 % | 162 | +0.1 | [−2.7, +4.9] | −11.8 | +13.1 |
| Grade ≥8 % | 47 | +1.5 | [−4.0, +6.4] | −20.4 | +13.7 |
| Duration 1–3 min | 615 | −0.0 | [−12.1, +7.5] | −35.4 | +20.4 |
| Duration 3–6 min | 587 | 0.0 | [−7.2, +5.5] | −28.2 | +15.3 |
| Duration ≥6 min | 332 | −1.4 | [−6.4, +3.5] | −17.5 | +11.7 |
| Speed <12 km/h | 25 | +4.2 | [−1.7, +10.2] | −22.5 | +20.1 |
| Speed 12–18 km/h | 291 | +1.3 | [−3.1, +6.0] | −15.0 | +15.1 |
| Speed ≥18 km/h | 1,218 | −1.3 | [−10.0, +5.4] | −32.7 | +17.6 |

**Gated regime (grade ≥ 4 %, T ≥ 120 s), the deployable slice:** median +0.1 %, IQR [−4.7, +4.1] %, p5 −12.8 %, p95 +11.5 %. Restricted to the clean solo era (2013–2016): p5 −9.2 %, p95 +11.7 %.

**Tail anatomy (this is the important part):**
- The **negative tail is drafting.** The twelve worst traversals (−50 to −70 %) are all May 2017 group rides at 28–39 km/h on 1.7–2.9 % false flats: solo aero physics implies 300–670 W while the rider reported 106–254 W sitting in a paceline. 2017's gated-median residual is −12.3 % vs +0.6 % for 2013–2016.
- The **positive tail lives at low grade / moderate speed** (repeated intervals on exposed 1–3 % segments, e.g. four traversals of one segment on 2016-05-01 all at +33 to +37 % — consistent with an un-modeled headwind day, see §6). Above 4 % grade the worst honest positives shrink dramatically.
- Per-ride aggregation (duration-weighted mean over a ride's traversals) tightens everything: all-rides IQR [−5.0, +5.0] %, p5/p95 [−25.5, +13.5].

## 4. Threshold table — honest FPR vs synthetic-fraud catch rate

Synthetic frauds built by perturbing real traversals: uniform watts inflation (+10 %, +25 %) and e-bike simulation (identical reported watts, every speed sample +8 or +5 km/h over the same geometry, time axis recompressed). Power inflation shows up as a **positive** residual, e-bike as a **negative** one, so thresholds are one-sided per fraud class.

**Gated regime (grade ≥ 4 %, T ≥ 120 s), ride level** (duration-weighted, 202 rides):

| Threshold | Honest FPR (pos side) | Honest FPR (two-sided) | Catch +25 % watts | Catch +10 % watts | Catch e-bike +8 km/h | Catch e-bike +5 km/h |
|---|---|---|---|---|---|---|
| ±8 % | 9.4 % | 25.2 % | 94 % | 59 % | 100 % | 99.5 % |
| ±10 % | 4.5 % | 15.3 % | 93 % | 50 % | 100 % | 99.5 % |
| ±12 % | 3.0 % | 10.4 % | 90 % | 37 % | 100 % | 99.5 % |
| **±15 %** | **1.5 %** | 6.9 % | **84 %** | 22 % | **100 %** | **98.5 %** |
| ±20 % | 0.5 % | 4.5 % | 71 % | 7 % | 99.5 % | 93 % |

Traversal-level, same gate (545 traversals): +15 % one-sided → 2.8 % FPR / 86 % catch of +25 % inflation; −25 % one-sided → 2.4 % FPR / 98 % catch of e-bike +8 km/h and 70 % of +5 km/h.

Tightening the gate to grade ≥ 5 % improves further (ride level: +15 % → 2.1 % FPR, 87 % catch; −20 % → 100 % e-bike catch at ~4.8 % two-sided FPR). Ungated (all 1,534 traversals) the same thresholds give 7–23 % FPR — the gate is not optional.

**Recommended asymmetric design point** (gate: grade ≥ 4 %, T ≥ 120 s, ≥ 1 gated climb):
- **+15 % positive threshold** → flags watts inflation ≥ ~20 % at ≈ 1.5 % honest ride FPR. Robust to drafting (drafting cannot push residuals positive).
- **−25 % negative threshold** → flags e-bike/speed fabrication at ≈ 2 % honest FPR, ~98 % catch for meaningful assist. Deeper than the positive side because drafting pollutes the honest negative tail.
- Everything between the thresholds, and everything on <4 % grades: **abstain** — the residual is a weak prior there, not evidence.

## 5. Mass as fitted parameter — "derived weigh-in"

Each traversal yields a closed-form mass estimate: m̂ = (η·P̄·T − aero) / (g·Δh + Crr·g·D + ΔKE/kg). On the steep calibration set (grade ≥ 6 %, T ≥ 120 s, n = 178):

- **Global fit: 81.4 kg** total system (rider + bike + kit). IQR **[79.0, 85.3] kg**.
- **Repeated segments** (same climb across rides): the ten best-sampled climbs have per-segment IQRs of **1.4–4.6 kg** around medians 78.6–88.3 kg.
- **Within a single ride** (≥ 3 steep traversals): median IQR **3.1 kg**.
- **Longitudinal:** 2013: 83.9 · 2014: 81.6 · 2015: 81.2 · 2016: 85.4 — stable to ±2 kg over four years. Then 2017: 63.8 (wide IQR [44, 73]) and 2018: 76.3.

The 2017 "weight loss" is spurious — the same drafting-contaminated group rides drag the mass fit down (a drafting rider needs less power, which the solver can only explain as less mass). With per-year mass calibration, 2017–18 gated residuals recenter from median −12.3 % to −1.4 %.

**Ground truth postscript (2026-07-16, from the athlete):** rider body weight in this era was **65 kg**. Two consequences:

1. The fitted 81.4 kg implies 16.4 kg of bike + kit + bottles. A realistic loadout is ~11–14 kg, so the fit likely carries a **+3–5 kg (+4–7 %) positive bias** — the mass parameter absorbing under-modeled resistive losses (Crr prior on the low side, altitude smoothing shaving Δh, drivetrain). Per the §2 sensitivity table this bias would shift residual medians +4–6 % if mass were held at truth; because mass is fitted, residuals recenter and the bias hides in the mass estimate instead. This confirms the standing caveat with a number: **fitted mass is a consistency instrument, not a scale.** Its *spread* (±3 kg) and *stability* are the honest readouts; its center is model-bias-loaded. Anchoring to a one-time measured or attested rider weight converts it into an absolute check.
2. The 2017 fit of 63.8 kg total system is now provably impossible, not just suspicious — it sits *below the rider's body weight alone*, implying a negative-mass bicycle. Drafting contamination is confirmed as the mechanism. Design rule this hands us for free: **fitted system mass < attested rider weight is a hard abstention signal** (either heavy drafting or data manipulation; both mean the traversal is not usable evidence).

**Verdict on derived weigh-in: feasible to ±3 kg** from a handful of steep solo traversals, which is tight enough to (a) bootstrap the residual engine with no declared weight, and (b) cross-check a declared weight. But it must be estimated on steep solo efforts only and re-fit per equipment era; a CUSUM-style drift monitor on the residual median would catch both equipment changes and systematic spoofing of the calibration itself.

## 6. Weather term — verdict: drop it

Hourly wind (speed + direction), temperature, and pressure fetched from Open-Meteo's historical archive for all 473 unique ride-day/location cells (100 % coverage, zero failures, responses cached). Headwind = wind projected onto each traversal's distance-weighted mean heading; aero recomputed with signed relative-air velocity at rider-height scale factors k ∈ {0, 0.3, 0.5, 0.7, 1.0}.

| Wind scale k | Residual IQR (all) | MAD |
|---|---|---|
| 0.0 (no wind) | 14.1 % | 10.2 % |
| **0.3** | **13.7 %** | **9.8 %** |
| 0.5 | 14.5 % | 10.7 % |
| 0.7 | 17.1 % | 12.6 % |
| 1.0 (full 10 m wind) | 20.7 % | 15.3 % |

- **Full-strength model wind actively hurts** (+47 % IQR). The optimum is k ≈ 0.3 — tree-lined SEPA river-valley roads see roughly 30 % of open 10 m wind — and even at the optimum the gain is **~3 % IQR / ~4 % MAD**. In the gated bands the effect is inconsistent (4–6 %: −7 % MAD; 6–8 %: *worse*; ≥8 %: −17 % on n = 47).
- The wind signal is real but weak: correlation between the no-wind residual and the predicted headwind power delta is Spearman 0.23 overall, rising to only 0.35 in the best case (straight-line, low-grade traversals) where wind should dominate.
- The smoking gun: at k = 1, the model predicts a median |9.3 %| power shift from wind (83 % of traversals shifted > 3 %). If station/model wind reflected road-level wind, adding it would collapse the variance. It doesn't — **10 m gridded wind largely decorrelates from sheltered road-level wind**, which was the hypothesized failure mode and is now measured.
- Density refinement from Open-Meteo temperature/pressure: no measurable change (IQR 13.8 vs 14.1 — noise).

**"Weather co-signs the ride" should be dropped as an evidence tier.** At most, log wind for forensic review of flagged rides (a +30 % residual on a 60 km/h-gust day deserves human eyes before action), and note that the gated regime barely feels wind anyway (gravity ≥ 76 % of work).

## 7. Limitations

- **Single-athlete corpus** (one primary rider, one PM lineage). The noise floor measured here excludes athlete-to-athlete PM variance (calibration offsets, left-only doubling, temperature drift across brands). Multi-athlete validation is required before hard enforcement; treat these FPRs as best-case.
- **Mass fitted on the same corpus** used to measure residuals → the *center* of the distribution is optimistic by construction; the *spread* is the honest readout. A deployed system with declared weight would add the declared-weight error (±5 kg ≈ ±5 % on steep grades).
- **Strava-corrected altitude, no raw barometer.** Δh comes from Strava's DEM-corrected stream. In production, canon geometry (D9: canon-compiled climbs from OSM+DEM) replaces this with a *fixed, versioned* Δh per climb — strictly better than this study's per-ride altitude, so gated-regime spread should tighten, not widen.
- **`watts` streams assumed to be device watts** (Strava's API returns watts streams for power-meter rides). If any rides carry estimated power, they inflate the measured noise floor — again making these numbers conservative.
- **Synthetic frauds are simplistic** (uniform inflation, constant assist). A sophisticated adversary shaping fraud to stay inside ±15 % on climbs is not addressed — but such an adversary has capped their gain at ~15 % of honest effort, which bounds the economic damage per ride.
- **Drafting is unmodeled and real.** Group-ride negative residuals are indistinguishable from "reported watts too low" cases. The corpus has no solo/group labels; the 2017 cluster was identified by speed/grade forensics.
- Open-Meteo archive reanalysis (~9–25 km grid) is not station truth; the wind verdict is about *this* data source at *this* terrain, which is the deployment-relevant question for Philadelphia.

## 8. Implications for detector design

1. **The residual engine earns a place as a gated, asymmetric evidence tier — not a universal lie detector.**
   - Gate: canon climbs with grade ≥ 4 % (better ≥ 5 %) and effort duration ≥ 120 s. That covered 36 % of traversals and 61 % of rides-with-climbs in this corpus — Philadelphia terrain generates enough gated evidence for weekly settlement relevance.
   - Positive side (+15 %): flag suspected power inflation. Drafting-proof by construction.
   - Negative side (−25 %): flag suspected e-bike/speed fabrication. ~98–100 % catch of ≥ +5 km/h assist at ≈ 2 % FPR.
   - Between thresholds, or off-gate: **abstain**. Publish the abstention honestly — "physics could not check this ride" is a valid state.
2. **Evidence tier:** the residual can support **corroboration and flag-for-review**, not sole-source slashing. At 1.5–2 % FPR, a hard auto-reject would wrongly hit an honest rider roughly every ~60 gated rides — unacceptable for permanent DUNG records. Right shape: residual flag → hold CAL credit for the affected climbs pending a second signal (repeat traversal, trusted-sensor lane, steward review). The mobile trusted-sensor lane (BLE power + attestation) remains the escalation path the flag feeds into.
3. **Calibration is per-athlete, per-equipment-era, rolling.** Fit mass from the rider's own steep solo history (±3 kg achievable within a few rides); monitor residual median with a drift detector; re-fit on equipment change. Never use a global constant across years — the 2017 era shift (−12 %) shows what that costs.
4. **A "solo effort" heuristic materially helps the negative side.** Even a crude one (speed vs implied-solo-power plausibility on <4 % grades, or pack-detection from timing overlap with other riders once multi-rider data exists) would reclaim much of the drafting-polluted negative tail.
5. **Drop the weather co-sign; keep the weather log.** No variance payoff at decision time; cheap forensic context for flagged rides.
6. **Detectability floor to communicate honestly:** ≥ ~20 % watts inflation and ≥ ~5 km/h motor assist on gated climbs are detectable; ≤ 10 % inflation is not. This caps, not eliminates, the cheating surface — an adversary constrained to +15 % on every gated climb is an adversary whose fraud yield is bounded and whose consistency across repeated canon traversals becomes its own statistical tell (repeated-segment residual history, per §5, is tight at ±2–5 kg equivalent).
7. **Canon synergy:** everything above gets *better* under canon-first identity (epic `4crx`) — fixed Δh/D per canon climb removes per-ride altitude smoothing error, the largest controllable term in the gated noise budget.

---

### Reproducibility limitation

Verified during recovery on 2026-07-30: the original private session scratch
directory no longer exists and was not captured in the repository preservation
archive. The analysis scripts (`01_census.py` through `06_gated_analysis.py`),
473 cached Open-Meteo responses, extracted stream caches, intermediate JSON,
and the executable environment are unavailable.

This document preserves the original method, parameters, cohort counts, and
reported findings, but its numerical results cannot currently be independently
rerun from tracked repository artifacts. Treat them as historical research
evidence—not a reproducible benchmark or production enforcement gate—until a
fresh current-corpus reproduction package is created. The original study
reported opening the corpus database read-only; recovery did not independently
reverify that execution claim.
