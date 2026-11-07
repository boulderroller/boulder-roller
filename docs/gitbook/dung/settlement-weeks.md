# Settlement weeks

| Parameter | Value |
|-----------|-------|
| Week boundary | Monday 12:00 UTC |
| Finalization | From 24 hours after the boundary (Tuesday 12:00 UTC) |
| Receipts | From Tuesday 12:00 UTC |

A settlement week runs Monday 12:00 UTC to Monday 12:00 UTC. At the boundary
each vault fixes its backers' shares for the week. After a 24-hour grace
period Boulder Roller finalizes the week, in this order:

1. The week's DUNG is computed from the vault's tribute
   ([Distribution](distribution.md)).
2. Leaderboard seats and the Local Legend are paid directly to their wallets.
3. Backers' DUNG is credited to their positions as **DUNG ready**.
4. Payouts appear under **Settlements** on iOS and under **History** in
   Portfolio on the web.

## Rules

- A deposit's or withdrawal's share of DUNG changes at a boundary, never
  mid-week; the CAL itself moves right away.
- If a week is not finalized on time, Boulder Roller finalizes it at the next
  attempt. Tribute that arrived in the meantime is not lost; it is paid with
  the late week.
- Settled weeks never reopen.

## Timeline

A deposit made on a Wednesday counts from the next Monday 12:00 UTC. That week
settles the Monday after, and its DUNG is ready from Tuesday 12:00 UTC, about
13 days after you deposited. Monday 12:00 UTC is 8:00 in Philadelphia during
daylight time and 7:00 in winter.
