# Climb V12 — terrain statistics

Local workshop correction, 14 September 2026. V11 and all earlier candidate files remain unchanged.

The retained Strava reference (`../references/strava-climb.png`, Manayunk Wall, 9 September) shows six measures in order: Distance, Elevation Gain, Avg Grade, Lowest Elev, Highest Elev, Elev Difference. V12 keeps that order on one desktop baseline and a three-column/two-row phone plate, using the accepted V11 palette and type. Values retain useful tenths; whole numbers do not acquire `.0`.

## Measurement definitions and source boundary

All page measurements use the supplied terrain length and profile at source precision. Gain sums positive adjacent elevation changes; average grade is signed endpoint rise divided by distance; lowest/highest use the profile extrema; elevation difference is highest minus lowest. This fixes V11’s use of endpoint rise for the difference slot, which was masked by all six built-ins starting at their low point and ending at their high point.

Wises: 1157.05 m distance, 62.2 m cumulative gain, 60 m net rise, 47/107 m low/high. Sprague: 55.2/122.6 m low/high and 67.4 m difference. Whole-meter rounding previously made that relationship appear to be 123−55=67.

Do not use the legacy `terrain.gain` field indiscriminately: retained ride data supplies cumulative gain, but public canonical `elevGainM` maps from `vert_m`, explicitly NET RISE under PROTOCOL_TRUTHS §14.6. The public fixture has 117.11 m cumulative profile gain and 87.36 m net rise. Neither figure is an arithmetic error. These are separate concepts. An initial test expecting the source gain field to be universal was discarded after this source trace disproved its premise. Canonical fields, source fixtures, economic vertical, qualification and payout behavior remain unchanged.

These are profile-derived workshop figures, not independent terrain validation. No smoothing or corrected survey accuracy is claimed. Strava also documents source variability and smoothing; its proprietary processing has not been reproduced: https://support.strava.com/en-us/articles/15401909-elevation

Production handoff: preserve a distinct cumulative-ascent measure versus canonical net vertical. Do not silently map the legacy net-rise API field to the page’s cumulative gain slot.

## Local verification

- Focused regression: undulating terrain incorrectly returned a 20 m endpoint difference where its highest−lowest difference is 65 m; corrected test passes. Additional ascending/descending, cumulative ascent, flat-zero, useful-decimal and V12 return-context cases pass.
- 111 workshop tests, typecheck and workshop build pass. Existing large-bundle advisory remains in this all-generations harness.
- Browser: all six scenario headers; rider, visitor and signed-out states; personal-best → scoped ride analysis → Back to climb returns to V12; V11 retains its old header; no browser warnings/errors observed.
- Exact CSS viewports 1440×1000 and 390×844 inspected. No mobile horizontal overflow. Saved viewport exports are cropped by the browser screenshot tool to 1430×993 and 380×822; they are not full-size pixel exports.
- `references/v12/overview-1440.jpg`, `overview-390.jpg`, `sprague-390.jpg` show loaded local maps and final statistics.
