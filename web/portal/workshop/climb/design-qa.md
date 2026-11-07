# Climb V3 — local workshop check

Direct user scope: remove the climb rail; compose name, dimensions and terrain as one reading path; keep personal best/history together; make scoped recording links escapable. V1 live capture and V2 remain separate candidates.

- Desktop 1440 × 1000 and phone 390 × 844 inspected in the browser; captures in `evidence/climb-v3-{1440,390}.jpg`. Existing typography, map ground and rank assets retained. No horizontal content overflow at phone width.
- Six bundled scenarios verified in V3; visitor/signed-out hide personal history and supplied private Vault position. Loading is inert with hidden result values; empty omits results; error recovers through Try again.
- Profile drag gives one continuous soft selection and signed average grade (0.47 km / +5.7% in the Wises probe). Map click and Escape clear it. Keyboard selection and map expansion verified.
- Before fix: active Overview left the expanded climb selected. After fix: V3-origin Overview clears scope; Whole ride clears climb/range/power-effort scope. Back to climb stays visible, including legacy Vault mode.
- Personal best and supplied leaderboard recordings open scoped analysis. Second-hop visitor links remain visitor and retain the originating candidate. Native climb-name hrefs match their destinations. Browser Back verified.
- Local scenario upload, scoped recording, imported sibling climb, legacy return, and return to the original imported study verified. Missing recordings stay unlinked; imported sibling data never substitutes built-in data.
- V1 capture and V2 sidebar checked through their buttons; original V2 component, profile, model and CSS remain untouched.
- `workshop:typecheck`, 86 workshop tests, and `workshop:build` pass. Build retains the workshop's large-bundle advisory. Browser warning/error logs empty in the final interaction checks.

Evidence is local/fixture UI proof. No production integration, auth implementation, segment ownership inference, financial action or deployment. The generic owner menu remains absent because this data contains no climb ownership. Explore links the three available local climb studies; provenance belongs in the workshop's Data control.
