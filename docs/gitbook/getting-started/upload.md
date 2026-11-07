# Upload a ride

1. On the web, choose **Upload ride** in the page header.
2. Choose **Choose file** and select a FIT, GPX, or TCX file up to 50 MB.
   Check **Who can see this ride?** and **Map visibility**, which start at
   your defaults, then choose **Upload ride**.
3. The ride appears in your feed when processing completes, normally within a
   minute.

FIT files carry the full sensor record; use them when you have them.

| Output | Requirement |
|--------|-------------|
| Climb results | GPS points with timestamps; a leaderboard place also needs elevation across the climb |
| CAL | A power meter with enough power data, and an established Threshold ([Threshold](../rides/cal.md#threshold)) |
| Training metrics | Power, once your Threshold is established |

A ride without power gets climb times, no training stress, and no CAL. If it
carries heart rate but no power, it goes under review and takes no leaderboard
place. A ride completed more than 30 days before upload counts no CAL and
takes no leaderboard place ([Review](../rides/processing.md#review)).

Rides can also be [recorded on iOS](ios.md).
