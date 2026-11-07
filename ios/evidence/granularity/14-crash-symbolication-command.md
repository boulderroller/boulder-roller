# L3.03 / odmi6.14 symbolication command — local evidence

Date: 2026-08-13. Evidence class: **local archived-build proof**.

The preserved build-2126 dSYM has UUID
`6C9675ED-09FE-3D62-BC64-4DBDDB500007` and `__TEXT` virtual address
`0x100000000`. A known app-symbol offset of `0x4000` was used to check the
runbook command:

```text
atos -arch arm64 -o <BoulderRoller dSYM DWARF> -l 0x0 0x4000
-> 0x4000                              (not symbolicated)

atos -arch arm64 -o <BoulderRoller dSYM DWARF> \
  -l 0x100000000 0x100004000
-> APIError.errorDescription.getter (APIClient.swift:15)
```

`docs/runbooks/IOS_CRASH_SYMBOLICATION.md` now reads the matching dSYM's
`__TEXT` base and adds each MetricKit `offsetIntoBinaryTextSegment` before
calling `atos`. This proves the documented path reaches a named frame; it is
not evidence of a real physical-device MetricKit delivery, which remains
gated on hardware and MetricKit's next-launch delivery window.
