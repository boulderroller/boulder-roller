# Portal Standards Amendment and Numerical Display Contract

**Status:** ACTIVE — adopted by Tim 2026-09-07
**Date:** 2026-09-07
**Source:** external review of the live portal against its own standards
(`history/portal-audit-2026-09-07/`; drafted by a GPT-6 Pro research thread,
adopted as written). Findings and implementation lanes live beside it in
`history/portal-audit-2026-09-07/LANES.md`; they are work, not standard.
**Audience:** Product, design, frontend, QA, coding agents

This document resolves the named conflicts between
`docs/design/PORTAL_DESIGN_SYSTEM_2026.md`, `docs/design/LANGUAGE_SPEC.md` and
`docs/PORTAL_TRUTHS.md`. It controls only its explicit conflicts; otherwise the
existing semantic and language hierarchy stands. `docs/PROTOCOL_TRUTHS.md`
remains superior.

Where this amendment names a number-slot rule, the Numerical Display Contract
in Part II is the operative text.

---

# Part I — Portal standards amendment

I have not inspected the mounted stylesheet or router. Accordingly, the amendment preserves the actual Night Ledger token values and requires explicit mappings of existing routes; it does not pretend screenshot samples are CSS hex values or invent an analysis URL.

:chatgpt-content-reference{index="5"}

## Portal standards amendment — adoption text

**Prepared:** 2026-09-07. **Effect:** Active on Tim’s adoption. This amendment resolves the named conflicts in the supplied Portal Design-System Contract, Language & Visibility Spec and Portal Truths; it does not certify implementation compliance.

### 1. Palette: Night Ledger

The portal, its entry/public previews/share assets, and BoulderScan’s shared visual language use one dark theme: warm-charcoal page and panel grounds, warm off-white reading text, readable neutral secondary text, restrained seams, and cobalt for deliberate action, selection, focus or result emphasis. Asset identity does not assign a second accent: CAL and DUNG values are not inherently blue and gold. Basemap geography may retain its muted contextual colours.

The currently mounted Night Ledger CSS tokens supply the concrete colour values. Record those values once in the canonical token table before colour edits; do not sample JPEGs or invent replacement hex values. Page, panel, reading-text, secondary-text, seam and accent roles are the sole colour authority; compatibility aliases must resolve to those roles. Reading text must not use decorative/faint-line tokens. Normal reading text must meet a 4.5:1 internal contrast floor; colour alone must not carry a state.

Within these surfaces, this supersedes the light palette, black-on-light reading direction and separate terrain-green/CAL-blue/DUNG-gold instructions, including gold/olive visual directions in the Language Spec. It does not change their semantic layer order, CAL/tribute meaning, typography roles, radius rules or motion policy. Marketing, documentation-site and native-app redesigns are outside this amendment.

### 2. Numerical absence

Adopt the accompanying Numerical display contract. A supported zero remains zero; an unknown, unavailable, withheld or unestablished number has no numerical content. Replace the Design-System Contract’s empty-cell substitution rule and Portal Truths’ unavailable-chain-read dash with abstention. Language examples that place a placeholder in a numerical slot are superseded to that extent only.

A named state or founder-approved factual explanation may appear beside the object or action, never as a substitute number. Preserve account-setup, privacy-blocking and operation-state behavior. Abstention does not authorize hiding a real zero, inventing finality or collapsing distinct custody amounts.

### 3. Route ownership

`/climbs` owns discovery; `/climbs/:climbId` owns Climb detail. `/rides/:rideId` is the canonical Ride object URL for public and authorized owner projections. New object links, canonical metadata and return destinations use those owners. `/activities/:rideId` becomes a compatibility alias resolving the same Ride identity, not a second page/data owner.

Preserve valid query/fragment state, authorization and privacy checks. Existing analysis, share and other supported child destinations remain supported through explicit mappings of the actual router; do not invent or blindly rewrite suffixes. Retain the documented `/map`, `/segments/:climbId` and `/vaults` compatibility behavior, including Vault-to-Climb resolution. Profile, rider, Notifications, Settings and Guide ownership is unchanged. Unauthenticated entry remains full-page; a redirect does not grant access.

### 4. Status and precedence

On adoption, Portal Truths, updated 2026-08-02, becomes **ACTIVE AS AMENDED**. Replace its Candidate header and Section 14 accordingly. Protocol Truths remains superior; the portal remains a reading surface, not an authority over protocol state. This amendment controls only its explicit conflicts; otherwise the existing semantic and language hierarchy stands. It ratifies no unsupplied document or unresolved product trigger.

The existing two-live-lanes cap remains in force. Record implementation gaps separately from the standard; accepted requirements are not claims of shipped behavior.

---

# Part II — Numerical display contract

## Numerical display contract — ratification text

**Effect:** Normative on Tim’s adoption. Applies to app-authored quantities, counts, chart observations and their accessible/share renditions. Defined axis ticks describe a scale; they are not claimed observations.

### Required fields and visibility

| Field | Required internal fact | Must be visible when |
|---|---|---|
| **Metric and value** | Metric identity, unit, precision policy; a valid exact value tagged known, or explicit absence with a reason only when known. | Metric and unit are always identifiable, directly or through an unambiguous row, axis or group heading. |
| **Object** | Stable object identity, applicable revision and authorized viewer projection. | The named ride, climb, rider, account or event is not already unmistakable from context. Raw IDs need not appear. |
| **Population and basis** | Included set or measured span, filters, custody, sample/aggregation rule, denominator, coverage/completeness and comparison basis where relevant. | Omission could confuse two measures, hide a partial total, blur custody, or misstate the meaning of a comparison or count. |
| **Effective time** | Observation/event/model as-of time or interval, relevant revision, and timezone for calendar boundaries. Fetch time is separate. | A value is historical, stale, scheduled or compared across dates; a period is non-obvious; or a current claim would otherwise be unsupported. |
| **Authority and state** | Permitted source, evidence/reference and revision, freshness, and subject-specific availability/finality. Local form state can authorize a form counter, not an economic claim. | Pending, projected, held, delayed or unavailable state changes interpretation or action. Normal sporting success is implicit; technical source detail stays optional. |

### Rendering rules

**Known is not synonymous with final.** A known projected amount may appear only with its explicit subject-specific qualification. Show zero only when the permitted source establishes exactly zero for the displayed state and population. An absent account, incomplete response, missing measurement or failed read never supplies zero. Do not use truthiness to hide valid zero or negative values. Do not round a positive amount into an apparent zero; retain sufficient precision or an approved numerical bound.

**Absence has no numerical glyph.** Render no dash, placeholder zero, word or sentence in a missing number’s slot. Omit an absent standalone metric and a wholly empty comparison row/column; preserve useful object rows and table structure. Put any authorized explanation in a separate, associated status area, including its accessible description. Missing chart samples are gaps, not invented zero samples. Declared aggregation/model curves must identify that basis when material.

**Scope may be inherited, not guessed.** A shared header may qualify several values only when it accurately describes all of them. Same-object, same-basis, same-revision claims use the same authorized value and formatter across room, feed, analysis and share. Comparisons and totals require compatible populations, units, times and completeness; never sum a paginated subset as the total or derive protocol eligibility in the browser.

**Old is not current; hidden is not missing evidence to recover.** Show a supported stale value only where privacy rules permit, with its effective time and state. Never reuse a previous viewer’s value or disclose withheld values through hidden DOM, tooltips, accessibility text or share output. Founder-approved explanations may clarify a supported distinction; they may not excuse contradictory data.

**Typography:** Use the existing numerical and label roles, including the expressly bounded Ride-summary exception. Do not invent a second number style or migrate every component as a prerequisite to this contract.

---

## Impact inventory

The render-by-render inventory of where this contract changes what is shown is
recorded in `history/portal-audit-2026-09-07/NUMERICAL_DISPLAY_CONTRACT.md`
(section "Where it changes the 34 renders"). It is an inventory, not a scope
expansion; implementation proceeds through the lanes in
`history/portal-audit-2026-09-07/LANES.md`.
