# Read-only corpus replay

Local/offline evidence from the repo's unchanged CanonTraversalEngine. The same retained September PostGIS corridors are used before and after; only the admitted 15 finishes, spans and profiles change.

Scanned **1,416 rides**, evaluating **5,229** ride/climb pairs after a conservative bounding-box and buffered unchanged-start intersection prefilter (Claude's review method).

| Metric | Before | After |
|---|---:|---:|
| Accepted traversals | 425 | 470 |
| Frozen segment-template reference recall | 94/98 (95.92%) | 94/98 (95.92%) |
| Corrected D13 pooled boundary p95 | 0.027 m | 0.027 m |
| Full-population pooled timing p95 | 2.007 s | 1.883 s |
| Legacy D13 pooled repeat-boundary p95 | 11.714 m | 11.459 m |
| Legacy D13 moved-set pooled p95 | 6.114 m | 5.550 m |
| Moved-climb last-100 m stopped efforts | 16/93 (17.20%) | 2/138 (1.45%) |

**Corrected boundary and timing metrics are measured locally using the pinned gate-consistency definitions. Current full-corpus pooled boundary: passes; pooled timing: passes. Other publication gates still apply.** The historical overall 10 m check fails; it is retained as a legacy diagnostic, not the current publication bar. See [fix round 2 authority](../../codex-briefs-2026-10-20/gate-rule-fix-2.md).

Baseline traversal retention: **100.00%**. **0 lost**, **45 newly accepted**. Every paired effort's fractional and whole-second change, each lost/new effort, and every frozen-reference miss is retained in [REPLAY.json](REPLAY.json). Ride ordinals replace source activity identifiers; no raw rider coordinates are emitted.

## Method

Reference templates are mapped once on the before geometry with the existing `map_reference_templates` and `load_expected_passes` helpers. Their denominator is frozen before scoring the after geometry. Matching is one-to-one using the existing `reference_contains_observed` predicate. This measures agreement with independently mappable recorded segment efforts; it is separate from retention of baseline canon traversals.

The legacy D13 diagnostic uses `boundary_repeat_metrics`, preserving every accepted observation. A climb/gate group is eligible only with at least two distinct rides. Error is bracket-interpolated canonical progress relative to the group median, pooled at p95, with its former 10 m comparison retained. It interpolates clipped bracketing-sample centreline projections; corrected scoring projects the intersection itself. Neither measures physical surveyed accuracy.

Stop classification reuses the research's unmodified `corpus_stops.analyse_stops`: speed below 1 m/s for at least 3 seconds within the timed interval, located in that phase's last 100 m. No stop time is subtracted. The brief's approximate 17% came from a different research traversal set; use the measured before denominator above for this comparison.

## Admitted climbs

| Climb | Accepted before → after | Last-100 m stopped before → after | Paired efforts | Median elapsed reduction |
|---|---:|---:|---:|---:|
| Port Royal Avenue | 3 → 3 | 0 → 0 | 3 | 4.41 s |
| Youngs Ford Road | 3 → 5 | 0 → 0 | 3 | 5.12 s |
| Conshohocken State Road | 5 → 13 | 1 → 1 | 5 | 10.32 s |
| Leverington Avenue | 1 → 2 | 1 → 0 | 1 | 21.48 s |
| Centennial Road | 1 → 27 | 0 → 1 | 1 | 7.25 s |
| Wises Mill Road | 18 → 18 | 10 → 0 | 18 | 20.92 s |
| Shurs Lane | 0 → 4 | 0 → 0 | 0 | no paired efforts |
| Falls Road / Conshohocken Avenue | 15 → 15 | 0 → 0 | 15 | 3.71 s |
| Ellis Road | 0 → 0 | 0 → 0 | 0 | no paired efforts |
| West School House Lane | 0 → 1 | 0 → 0 | 0 | no paired efforts |
| Calumet Street / West Coulter Street | 1 → 1 | 0 → 0 | 1 | 4.02 s |
| Midvale Avenue | 3 → 5 | 0 → 0 | 3 | 6.08 s |
| Black Rock Road | 42 → 42 | 4 → 0 | 42 | 7.02 s |
| Wynnefield Avenue | 1 → 1 | 0 → 0 | 1 | 5.87 s |
| Gay Street | 0 → 1 | 0 → 0 | 0 | no paired efforts |

## Legacy D13 per climb

No eligible repeats means absent p95, not zero. Duplicate road names remain separate registry identities.

| Climb (registry prefix) | p95 before m | p95 after m | Eligible endpoints before / after |
|---|---:|---:|---:|
| Mary Waters Ford Road (00af30ab) | 3.447 | 3.447 | 16 / 16 |
| Rose Glen Road (04cd0ed7) | 3.015 | 3.015 | 18 / 18 |
| Flat Rock Road (05c90c28) | 3.119 | 3.119 | 42 / 42 |
| Mill Creek Road (125085d8) | 6.453 | 6.453 | 8 / 8 |
| Calumet Street / West Coulter Street (13ab82c7) | no eligible repeats | no eligible repeats | 0 / 0 |
| Falls Road / Neill Drive (182a6026) | 6.522 | 6.522 | 172 / 172 |
| Parker Avenue (2068fd1f) | no eligible repeats | no eligible repeats | 0 / 0 |
| Falls Road / Conshohocken Avenue (27137dbc) | 4.638 | 4.638 | 30 / 30 |
| Shawmont Avenue (281af3df) | 1.025 | 1.025 | 20 / 20 |
| Cynwyd Heritage Trail (293e7b48) | no eligible repeats | no eligible repeats | 0 / 0 |
| Old Gulph Road (31cee316) | 0.947 | 0.947 | 8 / 8 |
| Youngs Ford Road (3312d952) | 0.888 | 7.926 | 6 / 10 |
| Stony Lane (358be76b) | no eligible repeats | no eligible repeats | 0 / 0 |
| Leverington Avenue (35fc7a81) | no eligible repeats | 0.239 | 0 / 4 |
| Midvale Avenue (372f52a5) | 5.263 | 6.810 | 6 / 10 |
| Andorra Road (38a0f999) | 5.271 | 5.271 | 14 / 14 |
| Bryn Tyddyn Drive (390dfafb) | no eligible repeats | no eligible repeats | 0 / 0 |
| Rockland Avenue (3e619621) | no eligible repeats | no eligible repeats | 0 / 0 |
| Wises Mill Road (43f15658) | 10.947 | 8.697 | 36 / 36 |
| Domino Lane (4baf34ad) | no eligible repeats | no eligible repeats | 0 / 0 |
| Cheltenham Avenue (4d743e20) | no eligible repeats | no eligible repeats | 0 / 0 |
| Sprague Road (4fd1981e) | 1.159 | 1.159 | 10 / 10 |
| Hagys Mill Road (545c9819) | 0.872 | 0.872 | 4 / 4 |
| Waverly Road (554c4d95) | 2.246 | 2.246 | 40 / 40 |
| McClenaghan Mill Road (63630665) | no eligible repeats | no eligible repeats | 0 / 0 |
| Old Gulph Road / Williamson Road / Youngs Ford Road (682ce122) | 5.839 | 5.839 | 4 / 4 |
| Paoli Avenue (6c6ae57a) | no eligible repeats | no eligible repeats | 0 / 0 |
| Merion Square Road (6d622c61) | 11.922 | 11.922 | 8 / 8 |
| Stanton Street (723e3169) | no eligible repeats | no eligible repeats | 0 / 0 |
| Grays Lane (7a04d7b3) | no eligible repeats | no eligible repeats | 0 / 0 |
| Righters Mill Road (82182865) | 6.347 | 6.347 | 8 / 8 |
| Ellis Road (8254f8ea) | no eligible repeats | no eligible repeats | 0 / 0 |
| Valley Green Road (8582724d) | no eligible repeats | no eligible repeats | 0 / 0 |
| Conshohocken State Road (8d732652) | no eligible repeats | no eligible repeats | 0 / 0 |
| Gypsy Lane (9259f572) | no eligible repeats | no eligible repeats | 0 / 0 |
| Conshohocken State Road (9358a8db) | 13.530 | 13.530 | 18 / 18 |
| Manor Road (9592cc22) | 0.673 | 0.673 | 4 / 4 |
| Schuylkill River Trail (964488ee) | 13.923 | 13.923 | 166 / 166 |
| Gay Street (98cf1c5e) | no eligible repeats | no eligible repeats | 0 / 0 |
| Conshohocken State Road (9a9b1cb6) | 14.940 | 13.514 | 10 / 26 |
| Green Lane (a253c363) | 7.753 | 7.753 | 10 / 10 |
| Fairview Avenue (a82b0077) | no eligible repeats | no eligible repeats | 0 / 0 |
| Morris Avenue (a8693ac1) | no eligible repeats | no eligible repeats | 0 / 0 |
| Jefferson Street / North Woodbine Avenue (aec5dcc5) | 4.246 | 4.246 | 18 / 18 |
| Dehaven Avenue (b24159c1) | no eligible repeats | no eligible repeats | 0 / 0 |
| Levering Street / Lyceum Avenue (b3c31818) | 5.980 | 5.980 | 26 / 26 |
| Black Rock Road (b51920f8) | 3.813 | 3.835 | 84 / 84 |
| Port Royal Avenue (b6029653) | 0.461 | 0.452 | 6 / 6 |
| West Bells Mill Road (b7d82a29) | 0.656 | 0.656 | 8 / 8 |
| Wynnefield Avenue (beb71d2e) | no eligible repeats | no eligible repeats | 0 / 0 |
| Centennial Road (c73804d9) | no eligible repeats | 2.089 | 0 / 54 |
| Church Street (c8b70854) | no eligible repeats | no eligible repeats | 0 / 0 |
| West School House Lane (cfaea96b) | no eligible repeats | no eligible repeats | 0 / 0 |
| Shurs Lane (cfd560e9) | no eligible repeats | 1.477 | 0 / 8 |
| Lafayette Road (d4716fc9) | 14.891 | 14.891 | 14 / 14 |
| Barren Hill Road (deabc865) | 6.404 | 6.404 | 8 / 8 |
| Hagys Ford Road North / Hagys Ford Road (ef9aa753) | no eligible repeats | no eligible repeats | 0 / 0 |

## Black Rock start revision

The unchanged 30 m start half-extent is active and re-evidenced under Claude's D10 call in fix round 2. The finish remains 25 m. Accepted starts outside the default 25 m extent:

- Ride ordinal 160, start 2683.902 s: 29.265 m from the start-gate centre.

## Compared with the previous proposal

Commit `b93e09ea4` had 471 accepted traversals; the current proposal has 470. 1 prior-proposal effort(s) no longer qualify. This comparison is separate from retention of the 425 registry-baseline traversals.

- Black Rock Road, ride ordinal 200: prior start 2764.667 s, finish 2865.212 s. The prior finish crossing is 26.012 m from the gate centre. Current attempt: partial_traversal; no finish crossing.

Each loss was re-evaluated using both exact proposal geometries. Sanitized crossing times, bracket indices, gate positions/lengths and rejection reasons are in REPLAY.json.


The original corpus passed SQLite integrity checking and its SHA-256 remained `64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee`. No database/provider/chain writes occurred.


## Round 3: Wises Mill and Centennial

Fresh replay compares the two amended finishes with their exact round-2 predecessors. The registry baseline is also retained in REPLAY.json. The corrected boundary metric projects each actual intersection onto the centreline and uses every crossing in groups with at least two distinct rides. Timing thins 1 s brackets to every eighth sample across all eight offsets; recording pauses and edges are counted but unscored, and lost/ambiguous crossings remain in p95 as infinity. The full-population timing p95 is used, never the measured-only diagnostic.

Definitions: gate-consistency `8993e19996ce5c8c2bb050845e03bf5b13d9fa22`; SHA-256 `ffb7e47bed3f8f779e50dad911c8555d6dc815a4245345669dd58dbf1016fad1`. Neither lane nor the traversal engine was edited. Thresholds: corrected boundary p95 ≤10 m; timing p95 ≤2 s. These local metrics do not replace field checks or other cutover gates.

| Climb | Accepted round 2 → 3 | Last-100 m stopped efforts | Extra shift m | Native / serialized UTM stop clearance m |
|---|---:|---:|---:|---:|
| Wises Mill Road | 18 → 18 | 0 → 0 | 3.000 | 15.042 / 15.059 |
| Centennial Road | 27 → 27 | 1 → 1 | 1.429 | 15.000 / 15.014 |

| Climb, both gates pooled | Corrected boundary p95 m, round 2 → 3 | Timing p95 s, round 2 → 3 |
|---|---:|---:|
| Wises Mill Road | 0.018 → 0.018 | 1.705 → 1.661 |
| Centennial Road | 0.030 → 0.030 | 2.253 → 2.562 |

| Climb / gate | Corrected boundary p95 m, round 2 → 3 | Timing p95 s, round 2 → 3 | Round 3 measured / failed / pause offsets |
|---|---:|---:|---:|
| Wises Mill Road / start | 0.018 → 0.018 | 1.595 → 1.595 | 86 / 2 / 0 |
| Wises Mill Road / finish | 0.037 → 0.035 | 1.899 → 1.666 | 84 / 0 / 4 |
| Centennial Road / start | 0.035 → 0.035 | 1.518 → 1.518 | 128 / 2 / 14 |
| Centennial Road / finish | 0.010 → 0.015 | 9.634 → 3.287 | 119 / 5 / 20 |

### Wises Mill Road: every paired effort

0 losses; 0 newly accepted. Negative deltas mean shorter elapsed time. Ordinals refer only to this frozen corpus.

| Ride ordinal | Start s | Round 2 elapsed s | Round 3 elapsed s | Delta s | Whole seconds round 2 → 3 |
|---:|---:|---:|---:|---:|---:|
| 167 | 2188.198 | 168.851601 | 168.231353 | -0.620248 | 169 → 168 |
| 240 | 2090.099 | 191.911472 | 191.144873 | -0.766599 | 192 → 191 |
| 297 | 2591.088 | 213.117638 | 212.308749 | -0.808888 | 213 → 212 |
| 337 | 2391.148 | 186.015201 | 185.433335 | -0.581866 | 186 → 185 |
| 433 | 3921.378 | 225.432874 | 224.360120 | -1.072754 | 225 → 224 |
| 457 | 2486.933 | 143.350508 | 142.750314 | -0.600194 | 143 → 143 |
| 593 | 7128.405 | 228.810190 | 227.906914 | -0.903276 | 229 → 228 |
| 604 | 6727.076 | 195.452399 | 194.382818 | -1.069581 | 195 → 194 |
| 610 | 12360.851 | 179.725467 | 179.069314 | -0.656153 | 180 → 179 |
| 651 | 4066.512 | 260.689911 | 259.531226 | -1.158685 | 261 → 260 |
| 774 | 210327.961 | 276.774885 | 275.462377 | -1.312508 | 277 → 275 |
| 817 | 5199.926 | 185.115870 | 184.292046 | -0.823824 | 185 → 184 |
| 820 | 2489.030 | 210.277294 | 209.350373 | -0.926921 | 210 → 209 |
| 914 | 3625.390 | 330.206880 | 329.111119 | -1.095761 | 330 → 329 |
| 991 | 2262.589 | 208.356491 | 207.363029 | -0.993463 | 208 → 207 |
| 1099 | 5608.772 | 246.405165 | 245.562778 | -0.842387 | 246 → 246 |
| 1192 | 3571.269 | 304.252545 | 303.096116 | -1.156429 | 304 → 303 |
| 1237 | 5367.852 | 176.614335 | 175.741358 | -0.872977 | 177 → 176 |

### Centennial Road: every paired effort

0 losses; 0 newly accepted. Negative deltas mean shorter elapsed time. Ordinals refer only to this frozen corpus.

| Ride ordinal | Start s | Round 2 elapsed s | Round 3 elapsed s | Delta s | Whole seconds round 2 → 3 |
|---:|---:|---:|---:|---:|---:|
| 45 | 3722.327 | 271.875248 | 271.290917 | -0.584331 | 272 → 271 |
| 56 | 4957.460 | 252.494803 | 252.291309 | -0.203495 | 252 → 252 |
| 71 | 4855.835 | 246.074204 | 245.901060 | -0.173144 | 246 → 246 |
| 73 | 6262.185 | 259.480651 | 259.206533 | -0.274118 | 259 → 259 |
| 256 | 5384.930 | 278.603334 | 278.177454 | -0.425879 | 279 → 278 |
| 281 | 3904.311 | 232.423874 | 232.014306 | -0.409567 | 232 → 232 |
| 283 | 4091.013 | 231.743187 | 230.839693 | -0.903494 | 232 → 231 |
| 311 | 3623.959 | 225.566120 | 225.121625 | -0.444496 | 226 → 225 |
| 425 | 4507.562 | 659.420476 | 654.407799 | -5.012677 | 659 → 654 |
| 434 | 5168.703 | 239.517773 | 235.734696 | -3.783077 | 240 → 236 |
| 435 | 2692.538 | 198.621941 | 198.382061 | -0.239881 | 199 → 198 |
| 440 | 3239.986 | 218.937058 | 218.586531 | -0.350527 | 219 → 219 |
| 542 | 4302.157 | 203.780591 | 202.957959 | -0.822631 | 204 → 203 |
| 563 | 152786.320 | 258.847977 | 258.478640 | -0.369337 | 259 → 258 |
| 592 | 4324.805 | 208.009573 | 205.333154 | -2.676419 | 208 → 205 |
| 614 | 5901.491 | 212.878856 | 212.312860 | -0.565995 | 213 → 212 |
| 642 | 4214.848 | 261.701333 | 261.257940 | -0.443393 | 262 → 261 |
| 665 | 4662.222 | 202.044576 | 201.705112 | -0.339464 | 202 → 202 |
| 678 | 4899.309 | 220.273167 | 219.963118 | -0.310048 | 220 → 220 |
| 686 | 3081.344 | 212.598664 | 211.703990 | -0.894674 | 213 → 212 |
| 742 | 8926.776 | 289.317417 | 288.932940 | -0.384477 | 289 → 289 |
| 760 | 41111.662 | 232.360009 | 231.553848 | -0.806161 | 232 → 232 |
| 785 | 3901.711 | 212.422530 | 211.721257 | -0.701272 | 212 → 212 |
| 848 | 3710.026 | 202.052012 | 201.784921 | -0.267091 | 202 → 202 |
| 856 | 4073.635 | 211.945449 | 211.677813 | -0.267636 | 212 → 212 |
| 886 | 4628.852 | 282.533607 | 282.053401 | -0.480206 | 283 → 282 |
| 912 | 3885.993 | 229.750967 | 229.172973 | -0.577993 | 230 → 229 |
