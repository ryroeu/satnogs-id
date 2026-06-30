# satnogs-id

**Which bird is it?** — post-launch object identification from multi-station SatNOGS Doppler.

After a rideshare drops dozens of near-identical cubesats in one orbit, deciding *which catalog
object is which* is genuinely hard and time-sensitive: the bus is the same, the TLEs overlap, and
the only thing that separates two siblings is the precise shape of their Doppler curve. This tool
takes a SatNOGS observation and ranks which cataloged object best matches its Doppler — and it does
so by **wrapping the authoritative tool for the job, Cees Bassa's [strf](https://github.com/cbassa/strf)
(`rffit`)**, rather than reinventing orbit determination.

## How it works

The SatNOGS waterfall is **Doppler-corrected** (verified from the `gr-satnogs` flowgraph), so a real
signal sits as a near-vertical line. The pipeline:

1. Pull the observation's artifact `.h5` (self-contained: waterfall + timestamps + Hz axis + the
   per-obs TLE + station location).
2. **Extract** the near-vertical track (parabolic sub-bin peak, carrier-locked window, MAD outlier
   rejection).
3. **Un-correct** it — `freq_recv = f0 + offset − f0·range_rate/c` — recovering the *physical* received
   Doppler curve. This is non-circular: it doesn't depend on which TLE was applied.
4. Run **`rffit`'s own** `identify_satellite_from_doppler()` against a candidate catalog. Lowest
   Doppler-RMS = the identification.

## Does it work? (honest eval)

Benchmarked on **two** identified near-identical clusters (SatNOGS-assigned identity as the answer
key), the second held out as a generalisation test:

| cluster | objects | passes | top-1 | 95% Wilson CI |
|---|---|---|---|---|
| **Geoscan** (2025-155, primary) | 6 identical | 28 | **28/28** (all rank-1) | 88–100% |
| **Tevel-2** (2025-052, **held-out**) | 9 identical | 23 | **20/23** | 68–95% |

The held-out cluster — a different bus, band, and pass geometry the method had never seen —
generalises at **87%**, and every one of the 3 misses is the *second*-best fit (a near-tie with a
sibling), not a wild error. That's the honest signature of a physical method near its resolution
limit on a harder cluster, not an overfit 100%.

**Limitations, stated plainly:** truth is SatNOGS-assigned identity, not independently decoded
telemetry; thin / low-elevation passes carry less Doppler curvature, so a few siblings sit within
~0.1 kHz; and *forward* mode needs a **recent** observation — candidate elements must be near the
observation epoch (current CelesTrak elements identify a ~6-week-old pass cleanly but fail at
~6 months, which the tool flags as ambiguous).

## Artifact on the Hugging Face Hub

This project wraps `strf`/`rffit` and trains **no model**, so — unlike the sibling
[satnogs-signal](https://github.com/RYASTRA/satnogs-signal) (which publishes a model *and* a dataset) — the **dataset is
the artifact**: the harvested, labeled Doppler tracks, a ready supervised benchmark for
near-identical cluster identification.

- 📊 **Dataset** — [`ryroeu/satnogs-id-doppler`](https://huggingface.co/datasets/ryroeu/satnogs-id-doppler)
  — one row per pass: the un-corrected received-Doppler track (`time_mjd`, `freq_recv_hz`) + station
  location + truth `norad` + provenance (`obs_id`, `intdes`, `start`).

```bash
docker compose run --rm app python scripts/build_and_push.py --dataset _eval/geoscan    # build locally
docker compose run --rm app python scripts/build_and_push.py --cluster geoscan --push   # publish (needs HF token)
```

## Name-tag confidence (Identify view)

Some clusters (currently **Tevel-2**) broadcast a per-unit callsign in their telemetry. When present,
the Identify view shows that **self-reported name tag** next to the Doppler answer as an independent
second opinion — never as ground truth (the birds fly close enough that one pass can hear several).
The tier is computed transparently:

| tier | rule |
|---|---|
| **HIGH** | ≥3 decoded messages · ≥80% name the same satellite · matches the Doppler ID · not flagged shared by SatNOGS |
| **MEDIUM** | a majority that matches Doppler, but weaker: 2 messages, or 50–80% agreement, or flagged shared |
| **LOW** | 1 message, or no majority (roughly split) |
| **⚠ disagrees** | a clear majority that contradicts the Doppler ID (possibly a co-audible neighbour) |
| **none** | no messages decoded (e.g. all of Geoscan) |

## Quickstart

The container *is* the environment (it bundles `strf`/`rffit`); there is no host virtualenv. Put your
SatNOGS DB token in a gitignored `.env` (`satnogs_db_api_key=…`) — artifacts are authenticated.

```bash
docker compose build
docker compose run --rm app pytest -q                                   # unit tests

# Build an eval dataset for a known cluster, then score it
docker compose run --rm app python -m satnogs_id.data.build geoscan _eval/geoscan
docker compose run --rm app python -m satnogs_id.id.eval _eval/geoscan

# Forward / live: identify one observation against live CelesTrak candidates (no answer key)
docker compose run --rm app python -m satnogs_id.service.forward 14075713

# The Gradio 'Identify' view on http://localhost:7860
docker compose run --rm --service-ports app python app.py
```

## Layout

```
satnogs_id/
  shared/   API client (polite: cache, backoff, pagination) · Doppler geometry · waterfall I/O
  data/     dataset contract + cluster harvester
  id/       rffit wrap (.dat/catalog build · identify) + the eval harness
  service/  forward (live) identification + the Gradio Identify view
docs/       prior-art survey · MVP design spec · Milestone-0 feasibility + result
```

## Deploying the Identify view

The image defaults to serving the Gradio app on port 7860, so it runs as a **Hugging Face Docker
Space** as-is (set the SatNOGS/HF tokens as Space secrets). Read-only — nothing is written back to
SatNOGS.

## Credit

Identification and orbit fitting are done by **[strf](https://github.com/cbassa/strf)** (Cees Bassa).
Data comes from the **[SatNOGS](https://satnogs.org)** network and DB. This project is the automation,
dataset, blind-association, and honest-eval layer around them.
