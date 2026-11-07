# Climb V7 — local design QA

Date: 13 September 2026. Bead: `boulderroller-v2-it5gh`.

## Outcome and boundary

Candidate V7 is an additive local workshop generation. V1–V6 source, assets, layouts and CSS are preserved. Ride and Feed candidate components are unchanged. The shared harness gains the V7 button, return-path recognition, validated V7 imports, and deduplicated ride choices. No production, chain, wallet or real-rider outcome is asserted.

The user approved simpler measurements, a denser readable leaderboard, consistent history inspection and economics using established trust patterns. V7 keeps the dark navbar and existing typefaces/rank assets. Measurements form one plate; standings precede history; public Vault activity and the viewer's position have separate areas. The trophies live in the standings rather than a duplicate leading-times panel.

## Visual comparison

Source: preserved V6, Wises Mill Road, returning rider, ready state. Target: V7 with that same scenario/viewer/state. Both were reviewed together at CSS viewports 1440×1000 and 390×844. Same in-app browser, no browser zoom changes; map-ready state awaited.

Evidence is in `../../history/climb-v7-workshop-2026-09-13/`:

| Evidence | Artifact dimensions |
| --- | --- |
| `source-v6-desktop-1440.jpg` and `climb-v7-top-1440.jpg` | 1430×993 each |
| `source-v6-phone-390.jpg` and `climb-v7-top-390.jpg` | 380×822 each |
| `climb-v7-desktop-1440.jpg` | Full page, 1430×2540 |
| `climb-v7-phone-390.jpg` | Full page, 380×3611 |
| `deposit-review-390.jpg` | 390×844 |

The browser capture API exports JPEG and normalizes the viewport image to the document width excluding its 10px scrollbar. DOM checks confirmed innerWidth 1440/390 and no horizontal document overflow. The matched source and target images use the same normalization. No image editing was applied.

Reviewed the complete page and focused on the measurement plate, leaderboard, history readout, Vault allocation/position and action dialog. Corrected excessive Rider column width, weak supporting labels, Local Legend placement and a phone map endpoint hidden beneath controls. The final map fit leaves clear space for its finish marker. No unresolved blocking visual or interaction defect was found; subjective taste remains for the user's review.

## Interaction evidence

- All six built-in scenarios render V7: Wises (10 rows), Black Rock (4), Sprague (1), first visit (10, Deposit available), Vault example (10, position), public geography (no invented board or Vault).
- Rider, visitor and signed-out previews retain public Vault data; personal history/amounts are not rendered for other viewers. Loading, empty, error and Try again exercised. Strava toggle reports pressed and adds exactly one reference panel. V6 remains selectable.
- Board inspection opens one row at a time. Bound Example Rider row exposes its actual recording; authored Casey row says recording unavailable. No fabricated analysis destination.
- History single clicks replace selection; Compare explicitly permits A/B; Escape clears. Aug 7 versus Aug 28 reads 4:14 versus 3:55 and −19s. All four historical links use their own explicit timing fixtures and return to V7. Fresh navigation to Aug 21 shows Aug 21, 4:03, and no invented sensor channels.
- A valid imported study with duplicate history points and no funding account keeps six selectable efforts. Identical points are separated by 24px in the inspected desktop plot. Withdraw opens from the position; Deposit is absent without an account. Export/import preserves history bindings.
- Settlement week changes update 1080 → 960 → 840 DUNG. History-row selection updates the same readings. Allocation selection opens details; percentages derive from supplied amounts, including totals below one DUNG.
- Deposit input rejects fractional CAL, 99 and over-balance 487; accepts 100. Max gives 486, review shows 1686 principal after. Review receives keyboard focus. Withdraw labels 1200 as deposited CAL and requires a quote. Collect shows exact 7.776 DUNG and wallet destination. Escape restores focus to the opener. No transaction is submitted.
- Final climb → historical analysis → climb pass produced no browser errors or warnings. Ride choices have unique identifiers and one copy of each V7 history study.

## Data and economics truth

V7 metadata explicitly identifies authored standings/economics and synthetic historical timing. Terrain is retained; extra history recordings rescale time over the existing climb and omit power, cadence and heart rate. They are not additional real recordings. Provenance is available in the Data panel and exported scenario.

The economic fixture keeps lifetime CAL tribute separate from deposited principal. Three authored settled weeks apply one eligible position's 1% unlock of the 27% position bucket: 81.73% leaderboard, 0.27% positions, 3% Local Legend, 5% liquidity, 10% treasury. Ready DUNG 7.776 equals the three supplied position allocations. Current principal is not represented as a withdrawal quote. No APY, live price, transaction hash or eligibility is fabricated.

Authority reviewed: PORTAL_TRUTHS, PROTOCOL_TRUTHS, LANGUAGE_SPEC and PROOF_ECONOMY_PRIMITIVES. Established interaction references: [Morpho Vault overview/activity](https://app.morpho.org/base/vault/0xbeef0e0834849aCC03f0089F01f4F1Eeb06873C9/steakhouse-prime-usdc#overview), [Uniswap position details](https://support.uniswap.org/hc/en-us/articles/40420536034061-The-Liquidity-Position-Details-Screen), [Lido withdrawal states](https://help.lido.fi/en/articles/7858341-how-do-lido-on-ethereum-withdrawals-work). The borrowed patterns are inspectable history, clear state, principal/collectible separation and review before signing; their protocol mechanics are not copied.

Production integration still needs truthful backend bindings for lifetime tribute, the returned settlement window, the viewer's position/collectible amount, and actual quote/signing flows. This candidate demonstrates UI behavior only.

## Verification

97 workshop tests pass; workshop typecheck and build pass. Focused regressions were observed failing before fixes: V7 return routing, imported ownership escalation, and fractional history gaps. Build reports the existing large all-candidates workshop bundle warning; this is not a portal release/performance claim. Independent read-only review covered economic authority and React/accessibility/import edge cases. Exact diff check passes.
