---
license: cc-by-sa-4.0
pretty_name: SatNOGS Doppler — near-identical cluster ID
tags:
- satellite
- doppler
- orbit-determination
- satnogs
- radio
task_categories:
- tabular-classification
size_categories:
- n<1K
configs:
- config_name: default
  data_files:
  - split: train
    path: data/train-*
---

# SatNOGS Doppler — near-identical cluster identification

Labeled **Doppler tracks** extracted from [SatNOGS](https://satnogs.org) waterfall observations, for
the task of identifying *which* member of a near-identical rideshare cluster produced a given pass.
Built by [satnogs-id](https://github.com/RYASTRA/satnogs-id), which wraps Cees Bassa's
[strf](https://github.com/cbassa/strf) (`rffit`) — no trained model; the labels come from physics.

## What's in it

One row per observation pass. The SatNOGS waterfall is Doppler-*corrected*, so each track is
**un-corrected** back to the physical received frequency — `freq_recv = f0 + offset − f0·range_rate/c`
— the curve `rffit` actually fits. This is non-circular: it does not depend on which TLE was applied.

| column | meaning |
|---|---|
| `obs_id` | SatNOGS Network observation id |
| `norad` | **truth label** — SatNOGS-assigned catalog object |
| `object` | human name (e.g. `Geoscan-4`) |
| `station` | SatNOGS ground-station id |
| `start` | observation date |
| `intdes` | launch international designator |
| `frequency_hz` | nominal transmit frequency |
| `station_lat`, `station_lon`, `station_alt_m` | receiver location |
| `time_mjd` | per-point time (MJD) — variable length |
| `freq_recv_hz` | per-point un-corrected received frequency (Hz) — variable length |
| `n_points` | track length |

## Current contents

**51 passes across two identified near-identical clusters** (distinguish them by the `intdes` column),
the second held out as a generalisation test. Identification is `rffit`'s own
`identify_satellite_from_doppler`.

- **Geoscan** (`2025-155`) — 6 identical cubesats, **28 passes**, **28/28 top-1** (all rank-1, CI 88–100%).
- **Tevel-2** (`2025-052`, held-out) — 9 identical cubesats, **23 passes**, **20/23 top-1** (87%, CI 68–95%;
  all 3 misses are rank-2 near-ties). A different bus / band / geometry the method never saw — it
  generalises, but isn't a suspiciously-perfect 100%.

## Usage

```python
from datasets import load_dataset
ds = load_dataset("ryroeu/satnogs-id-doppler", split="train")
row = ds[0]
# row["time_mjd"], row["freq_recv_hz"] -> the Doppler track; row["norad"] -> truth label
```

To refit with strf, write each row as an `rffit` `.dat` (`MJD  freq_hz  1.0  site`) plus a `sites.txt`
line from `station_lat/lon/alt_m`.

## Limitations

- Two clusters so far; both amateur UHF cubesat rideshares. Wider orbit/band coverage is future work.
- Truth is the **SatNOGS-assigned identity**, not independently decoded telemetry.
- Tracks are auto-extracted (parabolic sub-bin peak + carrier window + MAD rejection); weak /
  low-elevation passes carry less Doppler curvature, so their margins are thinner.

## Credit & license

Data from the [SatNOGS](https://satnogs.org) network + DB (CC BY-SA 4.0). Identification engine:
[strf](https://github.com/cbassa/strf) (Cees Bassa). Pipeline: [satnogs-id](https://github.com/RYASTRA/satnogs-id).
