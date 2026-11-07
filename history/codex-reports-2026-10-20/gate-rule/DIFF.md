# Finish-gate diff — 20 October 2026

Offline comparison against the sealed 10 September registry: 57 climbs, 16 admitted finish changes, 41 unchanged, every start unchanged. Falls Road / Neill Drive stays unchanged: a same-name road split is not a junction. The 15 traffic-control moves cite Tim's 20 October “yes all 15” approval; Wises Mill and Centennial also cite his later “yes shift both back” amendment. No registry or chain writes.

| Climb | Tim named | Control | Moved m | Length m old → new | Rise m old → new | Grade % old → new | New centre lat, lon |
|---|---|---|---:|---|---|---|---|
| Port Royal Avenue | yes | all_way_stop | 27.00 | 1530.43 → 1503.43 | 93.07 → 92.98 | 6.081 → 6.185 | 40.0573386, -75.2417052 |
| Youngs Ford Road | yes | stop_ratified_direction_unknown | 27.00 | 2037.01 → 2010.01 | 84.52 → 82.80 | 4.149 → 4.119 | 40.0445808, -75.2795791 |
| Conshohocken State Road | yes | traffic_signals | 27.00 | 1240.97 → 1213.97 | 78.94 → 76.37 | 6.361 → 6.291 | 40.0583757, -75.3012815 |
| Leverington Avenue | no | crossing=traffic_signals, traffic_signals | 27.00 | 1206.32 → 1179.32 | 70.24 → 69.73 | 5.823 → 5.912 | 40.0354788, -75.2176522 |
| Centennial Road | no | stop | 29.06 | 1639.79 → 1610.73 | 67.99 → 66.50 | 4.146 → 4.129 | 40.0234531, -75.2551219 |
| Wises Mill Road | yes | traffic_signals | 30.00 | 1087.96 → 1057.96 | 68.13 → 66.01 | 6.263 → 6.239 | 40.0539076, -75.2308452 |
| Shurs Lane | no | traffic_signals | 27.00 | 890.45 → 863.45 | 67.87 → 67.09 | 7.622 → 7.770 | 40.0268250, -75.2096955 |
| Falls Road / Conshohocken Avenue | yes | traffic_signals | 27.00 | 1686.52 → 1659.52 | 55.93 → 55.71 | 3.316 → 3.357 | 40.0021888, -75.2108336 |
| Ellis Road | no | stop | 27.00 | 1644.02 → 1617.02 | 49.72 → 47.76 | 3.025 → 2.953 | 39.9918170, -75.3272453 |
| West School House Lane | yes | crossing=traffic_signals, traffic_signals | 33.79 | 1212.05 → 1178.26 | 56.42 → 56.06 | 4.655 → 4.758 | 40.0202570, -75.1926567 |
| Calumet Street / West Coulter Street | yes | traffic_signals | 27.00 | 722.59 → 695.59 | 31.01 → 32.03 | 4.292 → 4.605 | 40.0143745, -75.1920768 |
| Midvale Avenue | yes | traffic_signals | 27.00 | 1062.07 → 1035.07 | 50.68 → 49.77 | 4.772 → 4.809 | 40.0168318, -75.1886080 |
| Black Rock Road | no | all_way_stop | 32.14 | 576.69 → 544.55 | 30.86 → 29.14 | 5.351 → 5.351 | 40.0301786, -75.2983313 |
| Wynnefield Avenue | no | traffic_signals | 27.00 | 386.33 → 359.33 | 23.79 → 22.20 | 6.159 → 6.177 | 39.9898633, -75.2190674 |
| Gay Street | no | all_way_stop | 27.00 | 220.39 → 193.39 | 23.24 → 20.75 | 10.544 → 10.729 | 40.0278079, -75.2226174 |

Metres moved uses the unrounded centreline calculation; old/new length fields are independently rounded, so their subtraction can differ by a centimetre.

Claude's fix-round-1 call under D7.5 gives every control at least 15 m clearance, including when this extends the default setback band. Black Rock retains 32.14 m; West School House's 32.89 m clearance cut snaps a further 0.90 m upstream under M1 to avoid a sub-metre final segment: total 33.79 m, with 15.90 m signal clearance. Black Rock's end half-width is reset to 25 m under D10; its 35 m override is superseded and its 30 m start half-width is unchanged. Youngs Ford's directionless stop is authorized only for its exact predecessor/node by the brief's “yes all 15”; the OSM direction remains unknown.

## Lafayette crest amendment

Lafayette's founder-approved natural top is a separate crest decision, not a D7.5 junction setback. Length **1528.87 → 2244.40 m**, rise **74.28 → 101.30 m**, average grade **4.858 → 4.513%**; start unchanged, finish extended **715.53 m** with the standard 25 m half-width. All 15 traffic-control successors above are unchanged. See [the Lafayette section](REPORT.md#lafayette-crest) for the decision, exact geometry, replay and the two Stony Lane turns that do not complete this extension.

## Ten unmapped terminating/turning finishes for field check

These are the research's terminates/turns subset, not ten independently surveyed T junctions.

- Andorra Road — Church Road.
- Dehaven Avenue — New Dehaven Street.
- Hagys Mill Road — Spring Lane.
- Mary Waters Ford Road — Jefferson Street, North Woodbine Avenue.
- McClenaghan Mill Road — Hansell Road.
- Merion Square Road — Youngs Ford Road.
- Morris Avenue — Ridgewood Road, Roscommon Road.
- Rockland Avenue — Highland Avenue.
- Rose Glen Road — Youngs Ford Road.
- Valley Green Road — West Springfield Avenue.

## Near-start controls retained

- Conshohocken State Road: 43.6 m:  (signal)
- Green Lane: 94.9 m: Smick Street (ped_crossing, stop_climb, stop_cross_traffic)
- Shurs Lane: 51.0 m: Cresson Street (all_way_stop, ped_crossing)

## Research interior-control census

Interior timing remains elapsed time. These are the research labels with the reviewed Black Rock correction: Black Rock's research label at 547.1 m is an unnamed connector road, not a control. Its climber-facing stop sign is at 559.55 m; the new finish is 15 m before it. No stopped time is subtracted.

- Barren Hill Road: 2125.40 m: Harts Lane (all_way_stop)
- Black Rock Road: 547.10 m: unnamed connector road (not a control); 559.55 m: climber-facing stop sign (stop)
- Calumet Street / West Coulter Street: 283.60 m: Stanton Street (all_way_stop, ped_crossing); 310.20 m: Cresson Street (all_way_stop, ped_crossing); 403.00 m: Dobson Street (all_way_stop, ped_crossing); 636.70 m: West Coulter Street (all_way_stop, ped_crossing)
- Centennial Road: standalone: stop_climb
- Conshohocken State Road: 621.70 m: Hollow Road (signal)
- Conshohocken State Road: 43.60 m:  (signal); 243.40 m: Merion Hill Lane (signal)
- Cynwyd Heritage Trail: standalone: ped_crossing, rail
- Falls Road / Conshohocken Avenue: 996.10 m: East Country Club Road (ped_crossing, signal); 1386.70 m: West Country Club Road (ped_crossing, signal)
- Grays Lane: 574.30 m: Laurel Lane (all_way_stop); standalone: barrier
- Green Lane: 94.90 m: Smick Street (ped_crossing, stop_climb, stop_cross_traffic); 113.30 m: Saint Davids Street (ped_crossing, stop_climb, stop_cross_traffic, stop_opposite); 121.80 m: Saint Davids Street (ped_crossing, stop_climb, stop_cross_traffic, stop_opposite); 345.80 m: Silverwood Street (all_way_stop, ped_crossing); 687.00 m: Manayunk Avenue (all_way_stop, ped_crossing)
- Hagys Ford Road North / Hagys Ford Road: 930.50 m: Hollow Road (signal)
- Jefferson Street / North Woodbine Avenue: 1819.20 m: Hillcrest Road (stop_climb, stop_cross_traffic)
- Levering Street / Lyceum Avenue: 194.40 m: Silverwood Street (all_way_stop, ped_crossing)
- Leverington Avenue: 462.50 m: Silverwood Street (all_way_stop, ped_crossing); 491.40 m: Boone Street (all_way_stop, ped_crossing); 849.30 m: Jacob Street, Pechin Street (all_way_stop, ped_crossing); 1010.00 m: Mitchell Street (all_way_stop, ped_crossing)
- Midvale Avenue: 627.30 m: Conrad Street, Warden Drive (ped_crossing, signal); standalone: ped_crossing, signal
- Mill Creek Road: 654.90 m: Cherry Lane, Glenn Road (all_way_stop); standalone: barrier
- Morris Avenue: 343.80 m: Williamson Road (all_way_stop); 1264.50 m: Lafayette Road, North Ithan Avenue (all_way_stop)
- Old Gulph Road / Williamson Road / Youngs Ford Road: 478.90 m: Mill Creek Road (signal); standalone: barrier, stop_cross_traffic
- Port Royal Avenue: standalone: barrier
- Schuylkill River Trail: 150.90 m: Lee Street (ped_crossing, rail); 1118.20 m: Cherry Street (ped_crossing, rail); 1378.10 m: Poplar Street (ped_crossing, rail, stop_cross_traffic); 1614.60 m: Ash Street (ped_crossing, rail, stop_cross_traffic); 1812.80 m: Harry Street (ped_crossing, rail, stop_cross_traffic); 2090.50 m: Oak Street (rail); standalone: rail; 1 interior rail crossing(s)
- Shawmont Avenue: 102.90 m: Green Tree Run (all_way_stop)
- Shurs Lane: 51.00 m: Cresson Street (all_way_stop, ped_crossing); 281.20 m: Terrace Street (all_way_stop, ped_crossing); 554.00 m: Pechin Street (all_way_stop, ped_crossing); 721.40 m: Mitchell Street (all_way_stop, ped_crossing)
- Waverly Road: 886.10 m: Sweet Briar Road (all_way_stop)
- West School House Lane: 440.00 m: Gypsy Lane (all_way_stop, ped_crossing); standalone: ped_crossing_signal, rail; 2 interior rail crossing(s)
- Wises Mill Road: standalone: ped_crossing
- Wynnefield Avenue: standalone: ped_crossing

All 57 old/new rows, precise gate endpoints and control-node tags are in DIFF.json. The September registration manifest has only Shawmont Avenue registered; its candidate is byte-equivalent and unaffected. This is retained indexed evidence, not a current chain check.
