# Power Profile Classification in Cycling — Research Report

**Date:** 2026-04-15
**Scope:** Coggan power profiling, academic classification literature, platform rider typing, validation of Boulder Rollers' RIDER_ARCHETYPES RFC thresholds
**For:** Grounding `docs/rfcs/RIDER_ARCHETYPES.md` in established sports science

## Executive Summary

The archetype model is **partially grounded in established science** and **partially freelancing**. The good news: the foundational concept of classifying riders by the shape of their power-duration curve is well-established (Coggan's power profile, WKO phenotyping, Wahoo 4DP, and peer-reviewed literature by Pinot & Grappe and Leo et al. all do this). The 6-class list is close to industry standard. The bad news: (1) the specific numeric thresholds are unvalidated and use a ratio-to-FTP approach that diverges from established practice, (2) the RFC's threshold values in CLAUDE.md and in the RFC body are inconsistent with each other, (3) Coggan/WKO uses 4 phenotypes not 6, (4) the matchup cycle is pure game design with zero sports-science basis, and (5) "day-one" classification from a single ride is unreliable per the literature. Recommendations: adopt the Wahoo/TrainerRoad 6-class taxonomy (which matches ours), switch from ratio-to-FTP thresholds to W/kg percentile-based classification against the Coggan table, add a confidence indicator, and require 4-6 weeks of data before showing a "confirmed" classification.

## 1. Coggan's Power Profile

Dr. Andrew Coggan and Hunter Allen published the Power Profile table in *Training and Racing with a Power Meter* (VeloPress, 1st ed. 2006, 3rd ed. 2019). The table plots W/kg across four durations — 5 seconds (neuromuscular power), 1 minute (anaerobic capacity), 5 minutes (VO2max), and FTP/60 minutes (lactate threshold) — against eight categories from Untrained to World Class for both men and women.

**Key W/kg reference values (men):**

| Category | 5s W/kg | 1min W/kg | 5min W/kg | FTP W/kg |
|---|---|---|---|---|
| Untrained | <11.0 | <6.0 | <3.5 | <2.5 |
| Cat 5 | 11.0-13.0 | 6.0-7.5 | 3.5-4.2 | 2.5-3.2 |
| Cat 4 | 13.0-15.5 | 7.5-8.5 | 4.2-4.7 | 3.2-3.7 |
| Cat 3 | 15.5-18.0 | 8.5-9.5 | 4.7-5.2 | 3.7-4.2 |
| Cat 2 | 18.0-20.0 | 9.5-10.5 | 5.2-5.7 | 4.2-4.7 |
| Cat 1 | 20.0-22.5 | 10.5-11.0 | 5.7-6.1 | 4.7-5.2 |
| Pro | 22.5-24.0 | 11.0-11.5 | 6.1-6.4 | 5.2-5.8 |
| World Class | >24.0 | >11.5 | >6.4 | >5.8 |

(Approximate representative values from the Coggan table; original is in Allen & Coggan book, Table 6.2.)

**How Coggan maps to rider types:** Coggan's original framework does not formally assign "sprinter" or "climber" labels. It describes the *shape* of a rider's profile across the four durations. A down-sloping profile (high 5s, low FTP relative to category) indicates a sprinter type; an up-sloping profile (low 5s, high FTP) indicates a time trialist/climber type. The labeling was formalized later in WKO4/WKO5.

**Critical distinction from our approach:** Coggan uses **absolute W/kg at each duration** compared against population percentiles. He does **not** use ratios of short-duration power to FTP. The ratio approach (r5s = 5s_power / FTP) normalizes out absolute fitness level, isolating only the *shape* of the curve. Both are valid but answer different questions: Coggan asks "how strong are you at each duration?" while our ratio approach asks "what shape is your curve regardless of overall level?"

**Source:** Allen, H. & Coggan, A. (2019). *Training and Racing with a Power Meter*, 3rd Edition. VeloPress. Also: [TrainingPeaks: Creating Your Power Profile](https://www.trainingpeaks.com/blog/power-profiling/).

## 2. Academic Literature

**Key papers:**

1. **Pinot & Grappe (2011).** "The record power profile to assess performance in elite cyclists." *Int J Sports Med*, 32(11), 839-844. Established the Record Power Profile (RPP) concept — the full power-duration curve from race data rather than lab tests. Found that RPP shape differs systematically between sprinters, climbers, and flat specialists among professional cyclists. This is the closest peer-reviewed validation that curve shape predicts rider type.

2. **Leo, Spragg, Podlogar, Lawley & Mujika (2022).** "Power profiling and the power-duration relationship in cycling: a narrative review." *Eur J Appl Physiol*, 122, 301-316. DOI: [10.1007/s00421-021-04833-y](https://doi.org/10.1007/s00421-021-04833-y). Most comprehensive review to date. Key findings: (a) formal test values predict race performance for only ~6 months before retesting is needed, (b) the power-duration curve shifts downward with accumulated fatigue, (c) field data from multiple rides is more ecologically valid than single-test protocols.

3. **Sanders & van Erp (2021).** "The Physical Demands and Power Profile of Different Stage Types Within a Cycling Grand Tour." *Eur J Sport Sci*. Showed that stage type (flat, hilly, mountain, TT) demands different power profile shapes, supporting the concept that rider specialization maps to terrain demands.

**Classification methods in the literature:** No peer-reviewed paper uses threshold-based rule tables like ours. The academic approaches are: (a) visual inspection of curve shape (Coggan original), (b) statistical phenotyping via the power-duration model parameters (WKO/Coggan), (c) cluster analysis on RPP features (Pinot & Grappe). There is **no converged standard**.

**National federations:** British Cycling and Cycling Australia use power profiling for talent identification but their specific thresholds are internal and not published in peer-reviewed literature.

## 3. Existing Apps and Platforms

| Platform | Rider Typing? | Types | Method | Data Required | Published? |
|---|---|---|---|---|---|
| **WKO5** | Yes | 4: Sprinter, Pursuiter, TTer, All-Rounder | Statistical fit of power-duration model; phenotype from curve shape parameters | 90+ days ride data recommended | [wko5.com/phenotypes](https://www.wko5.com/phenotypes) |
| **Wahoo SYSTM (4DP)** | Yes | 6: Sprinter, Attacker, Pursuiter, TT, Climber, Rouleur | Ratios between 4 test efforts (5s, 1min, 5min, 20min) | Single structured test ("Full Frontal") | [Wahoo 4DP Support](https://support.wahoofitness.com/hc/en-us/articles/360021401080-4DP-Rider-Type) |
| **TrainerRoad** | Yes | 6: Sprinter, Puncheur, Attacker, Rouleur, TT, Climber, All-Rounder | Percentile ranking at each duration from ride history | Accumulated ride data with maximal efforts | [TrainerRoad Power Rankings](https://support.trainerroad.com/hc/en-us/articles/33888909138459) |
| **Xert** | Yes | ~20 focus types | Focus Duration from power distribution; maps to athlete types | Continuous ride data | [Xert Athlete Types](https://www.baronbiosys.com/beginners-hub/discover/athlete-types/) |
| **Intervals.icu** | Partial | No explicit type label | Power curve vs Coggan percentile chart; user interprets shape | Any ride data with power | [intervals.icu](https://www.intervals.icu/) |
| **Strava** | No | N/A | Power curve display only, no typing | N/A | N/A |
| **Zwift** | No | Category by W/kg only | W/kg bands (A/B/C/D), no phenotyping | Single FTP test | N/A |
| **GoldenCheetah** | Partial | No explicit type | Power profile chart vs Coggan table | Ride data | Open source |

**The closest analog to our system is Wahoo 4DP**, which uses the same 4 durations, classifies into 6 types, and uses **ratios between efforts** rather than absolute W/kg. Wahoo's 6 types (Sprinter, Attacker, Pursuiter, TT, Climber, Rouleur) map almost exactly to ours (Sprinter, Puncheur, Breakaway, Rouleur, Climber, GC).

**WKO5 uses only 4 phenotypes** (no Climber or Puncheur as separate types) because it classifies purely on curve shape without incorporating weight.

## 4. Validation of Our Thresholds

**1. Are ratio-to-FTP thresholds used in established literature?**
Yes, but only by Wahoo 4DP (industry, not peer-reviewed). WKO uses model-fitted parameters. Coggan's original table uses absolute W/kg. Our ratio approach is **defensible but not the dominant paradigm**.

**2. Is FTP/kg >= 4.8 reasonable for "Climber"?**
On Coggan's table, 4.8 W/kg FTP falls between Cat 1 and Pro. This threshold means **only elite amateurs and professionals can be classified as Climbers**. For serious amateurs, too high. A strong amateur climber might have FTP/kg of 3.8-4.2. **Recommendation: lower to ~4.0 W/kg**, or use a percentile-based approach.

**3. Should we include 20min and 60min durations?**
The RFC already uses 20min as the FTP proxy. The 4-duration standard (5s/1min/5min/20min) is the established norm. Adding 60min adds minimal classification value. **Our 4-duration choice is correct.**

**4. Does the matchup cycle have a sports-science basis?**
**No.** The Sprinter→Breakaway→Climber→Puncheur→Rouleur→GC cycle is **pure game design** with no basis in cycling science or race tactics. In real cycling, matchups are terrain-dependent, not cyclical. **This is fine since it's explicitly cosmetic, but do not cite any sports-science basis for it.**

**5. Normative tables for amateurs?**
Yes. The Coggan table covers Untrained through World Class. Cycling Analytics published a large-n recreational rider analysis ([cyclinganalytics.com/blog](https://www.cyclinganalytics.com/blog/2018/06/how-does-your-cycling-power-output-compare)). **Calibrate against Coggan amateur tiers (Cat 5 through Cat 2), not pro/world-class.**

**RFC internal inconsistency:** The thresholds in CLAUDE.md (r5s >= 3.2, r1m >= 2.8, r5m >= 2.2) differ from the RFC body (r5s > 3.5, r1min > 1.9, r5min > 1.25). The RFC body values are more plausible physiologically. **The RFC body values should be treated as canonical.**

## 5. Cold-Start and Data Requirements

**How much data is needed?** Per Leo et al. (2022), formal test values predict for ~6 months. WKO5 recommends 90+ days. Wahoo 4DP requires a single structured 60-minute test.

**Is "day-one from a single ride" realistic?** Only if the ride includes genuine maximal efforts at all four durations — which normal riding almost never does. **Realistic classification requires 4-8 rides across 2-4 weeks.**

**No power meter?** No platform performs rider-type classification without power data. HR alone cannot distinguish neuromuscular from aerobic phenotypes. **Power meter requirement is standard.**

**Seasonal variance:** Profile shape is relatively stable (a sprinter stays a sprinter), but absolute values shift 5-15% across a season. **Use a 90-day rolling window rather than all-time bests.**

## 6. Recommendations for Boulder Rollers

1. **Keep the 6-class taxonomy.** Aligns with Wahoo 4DP and TrainerRoad.
2. **Fix the threshold inconsistency.** Adopt RFC body values as canonical, delete CLAUDE.md draft values.
3. **Lower the Climber FTP/kg gate.** 4.8 → ~4.0 W/kg for the amateur audience.
4. **Add a confidence indicator.** "Provisional" until 4-6 rides with varied efforts, "Confirmed" after.
5. **Use a 90-day rolling window** for best-effort calculation. Reflects current fitness, not ancient peaks.
6. **Cite these sources in the RFC:** Allen & Coggan (2019) for foundational profiling, Pinot & Grappe (2011) for peer-reviewed RPP validation, Wahoo 4DP as closest industry precedent.
7. **Explicitly label the matchup cycle as game design.** Zero sports-science basis. Fine since it's cosmetic.
8. **Consider a "relative to peers" dimension.** "Sprinter — Cat 3 level" is more informative than "Sprinter" alone.

## Sources

1. Allen, H. & Coggan, A. (2019). *Training and Racing with a Power Meter*, 3rd Edition. VeloPress.
2. Pinot, J. & Grappe, F. (2011). "The record power profile to assess performance in elite cyclists." *Int J Sports Med*, 32(11), 839-844. [PubMed](https://pubmed.ncbi.nlm.nih.gov/22052032/)
3. Leo, P., Spragg, J., Podlogar, T., Lawley, J.S., & Mujika, I. (2022). "Power profiling and the power-duration relationship in cycling." *Eur J Appl Physiol*, 122, 301-316. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8783871/)
4. Sanders, D. & van Erp, T. (2021). "The Physical Demands and Power Profile of Different Stage Types." *Eur J Sport Sci*. [Wiley](https://onlinelibrary.wiley.com/doi/10.1080/17461391.2018.1554706)
5. [TrainingPeaks: Creating Your Power Profile](https://www.trainingpeaks.com/blog/power-profiling/)
6. [WKO5: Phenotypes](https://www.wko5.com/phenotypes)
7. [Wahoo 4DP Rider Type](https://support.wahoofitness.com/hc/en-us/articles/360021401080-4DP-Rider-Type)
8. [TrainerRoad: Power Rankings](https://support.trainerroad.com/hc/en-us/articles/33888909138459)
9. [Xert: Athlete Types](https://www.baronbiosys.com/beginners-hub/discover/athlete-types/)
10. [Cycling Analytics: Power Output Comparison](https://www.cyclinganalytics.com/blog/2018/06/how-does-your-cycling-power-output-compare)
