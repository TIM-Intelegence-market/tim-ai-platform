# TIM P0-001 — Continuous Coverage Gap Register

## Register rules

Times are UTC. End timestamps are exclusive. Each row represents a distinct
missing BTCUSDT 1m candle range inside
`[2026-07-22T20:14:00Z, 2026-07-23T14:27:00Z)`.

All rows have:

- zero persisted AggTrades during every missing minute;
- at least one corresponding persisted DATA_GAP event;
- event cause `UNKNOWN_SOURCE_OR_PERSISTENCE_GAP`;
- no reconstructed data.

`MISSING_INPUT` means nearby persisted health evidence shows the stream
inactive or writes stale. `UNKNOWN` means available health evidence is
insufficient or contradictory. Event line numbers refer to
`data/operational/events.jsonl`.

| ID | Start | End | Min | Cause | AggTrades | DATA_GAP lines |
|---|---|---|---:|---|---:|---|
| CG-001 | 2026-07-23 04:09 | 04:14 | 5 | MISSING_INPUT | 0 | 3674 |
| CG-002 | 2026-07-23 04:16 | 04:31 | 15 | MISSING_INPUT | 0 | 3687, 3689 |
| CG-003 | 2026-07-23 04:35 | 04:51 | 16 | MISSING_INPUT | 0 | 3688, 3697 |
| CG-004 | 2026-07-23 04:53 | 05:07 | 14 | MISSING_INPUT | 0 | 3695, 3698 |
| CG-005 | 2026-07-23 05:09 | 05:15 | 6 | MISSING_INPUT | 0 | 3696, 3699 |
| CG-006 | 2026-07-23 05:17 | 05:33 | 16 | MISSING_INPUT | 0 | 3702, 3705 |
| CG-007 | 2026-07-23 05:35 | 05:50 | 15 | MISSING_INPUT | 0 | 3709, 3710 |
| CG-008 | 2026-07-23 05:52 | 06:07 | 15 | MISSING_INPUT | 0 | 3716, 3719 |
| CG-009 | 2026-07-23 06:09 | 06:16 | 7 | MISSING_INPUT | 0 | 3717, 3720 |
| CG-010 | 2026-07-23 06:18 | 06:32 | 14 | MISSING_INPUT | 0 | 3718, 3724 |
| CG-011 | 2026-07-23 06:34 | 06:49 | 15 | MISSING_INPUT | 0 | 3727, 3728 |
| CG-012 | 2026-07-23 06:50 | 07:03 | 13 | MISSING_INPUT | 0 | 3733, 3734 |
| CG-013 | 2026-07-23 07:04 | 07:18 | 14 | MISSING_INPUT | 0 | 3738, 3740 |
| CG-014 | 2026-07-23 07:19 | 07:34 | 15 | MISSING_INPUT | 0 | 3739, 3741 |
| CG-015 | 2026-07-23 07:35 | 07:51 | 16 | MISSING_INPUT | 0 | 3747, 3758 |
| CG-016 | 2026-07-23 07:58 | 08:13 | 15 | MISSING_INPUT | 0 | 3763, 3765 |
| CG-017 | 2026-07-23 08:14 | 08:18 | 4 | MISSING_INPUT | 0 | 3764 |
| CG-018 | 2026-07-23 08:20 | 08:34 | 14 | MISSING_INPUT | 0 | 3769, 3770 |
| CG-019 | 2026-07-23 08:36 | 08:53 | 17 | MISSING_INPUT | 0 | 3774, 3775 |
| CG-020 | 2026-07-23 08:54 | 09:10 | 16 | MISSING_INPUT | 0 | 3782, 3785 |
| CG-021 | 2026-07-23 09:12 | 09:19 | 7 | MISSING_INPUT | 0 | 3783 |
| CG-022 | 2026-07-23 09:21 | 09:35 | 14 | MISSING_INPUT | 0 | 3784, 3790 |
| CG-023 | 2026-07-23 09:37 | 09:52 | 15 | UNKNOWN | 0 | 3789, 3792 |
| CG-024 | 2026-07-23 09:54 | 10:10 | 16 | MISSING_INPUT | 0 | 3799, 3801 |
| CG-025 | 2026-07-23 10:11 | 10:20 | 9 | MISSING_INPUT | 0 | 3800, 3802 |
| CG-026 | 2026-07-23 10:22 | 10:37 | 15 | MISSING_INPUT | 0 | 3806, 3807 |
| CG-027 | 2026-07-23 10:38 | 10:55 | 17 | MISSING_INPUT | 0 | 3811, 3812 |
| CG-028 | 2026-07-23 10:56 | 11:11 | 15 | MISSING_INPUT | 0 | 3819, 3822 |
| CG-029 | 2026-07-23 11:13 | 11:21 | 8 | MISSING_INPUT | 0 | 3820, 3823 |
| CG-030 | 2026-07-23 11:23 | 11:39 | 16 | MISSING_INPUT | 0 | 3821, 3824 |
| CG-031 | 2026-07-23 11:41 | 11:56 | 15 | MISSING_INPUT | 0 | 3842, 3843 |
| CG-032 | 2026-07-23 12:04 | 12:19 | 15 | MISSING_INPUT | 0 | 3864, 3866 |
| CG-033 | 2026-07-23 12:20 | 12:26 | 6 | MISSING_INPUT | 0 | 3865, 3867 |

## Totals

| Category | Ranges | Minutes | Share of missing minutes |
|---|---:|---:|---:|
| MISSING_INPUT | 32 | 415 | 96.512 % |
| UNKNOWN | 1 | 15 | 3.488 % |
| PROCESS_STOP | 0 proven | 0 proven | 0 % |
| VALIDATOR_FAILURE | 0 proven | 0 proven | 0 % |
| PIPELINE_FAILURE | 0 proven | 0 proven | 0 % |
| MANUAL_STOP | 0 proven | 0 proven | 0 % |
| **Total** | **33** | **430** | **100.000 %** |

## Special evidence for CG-023

Health records around CG-023 report:

- event line 3786: stream active, validator running, fresh write;
- event line 3791: stream active, validator running, fresh write.

Nevertheless, no AggTrade or closed 1m candle is persisted during the
15-minute range. This contradiction prevents a more specific classification.
The range remains `UNKNOWN`.

## Register status

All 33 ranges are historical, preserved, and unresolved at the physical-cause
level. They must not be reconstructed or marked closed by this investigation.
