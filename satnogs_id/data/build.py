"""Harvest an id eval dataset for a cluster of near-identical objects: for each truth object, pull
its strong (with-signal, .h5) passes via the polite client, download each artifact, and attach an
epoch-matched candidate catalog (the whole launch's soup). Pagination reaches historical passes, so
N grows well beyond the 25-per-page recent window once the API cooldown clears.

Run in-container: docker compose run --rm app python -m satnogs_id.data.build geoscan _eval/geoscan
"""

from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path

from ..shared.api import SatnogsClient, nearest_tle
from .dataset import Dataset, PassRecord

# Known IDENTIFIED clusters used as an answer key. soup = the full launch's NORAD range; truth =
# the SatNOGS-assigned object per member. Geoscan: intl 2025-155, launched 2025-07-25.
CLUSTERS: dict[str, dict] = {
    "geoscan": {
        "soup": list(range(64876, 64896)),
        "truth": {
            64879: "Geoscan-6",
            64880: "Geoscan-1",
            64890: "Geoscan-2",
            64891: "Geoscan-5",
            64892: "Geoscan-4",
            64893: "Geoscan-3",
        },
    },
    # Tevel-2: 9 near-identical Israeli cubesats, intl 2025-052, launched 2025-03-15.
    # Held-out generalisation cluster (different bus / band / geometry from Geoscan).
    "tevel2": {
        "soup": [63213, 63214, 63215, 63217, 63218, 63219, 63237, 63238, 63239],
        "truth": {
            63217: "TEVEL2-1",
            63219: "TEVEL2-2",
            63218: "TEVEL2-3",
            63213: "TEVEL2-4",
            63214: "TEVEL2-5",
            63215: "TEVEL2-6",
            63238: "TEVEL2-7",
            63239: "TEVEL2-8",
            63237: "TEVEL2-9",
        },
        # Per-unit AX.25 source callsigns, verified from decoded frames (Task 3). Unit 1 (63217)
        # actually transmits "TLV2-1" (note the letter order vs the others); "TVL2-1" kept as a
        # harmless alias. The other units transmit "TVL2-<n>".
        "callsigns": {
            "TLV2-1": 63217,
            "TVL2-1": 63217,
            "TVL2-2": 63219,
            "TVL2-3": 63218,
            "TVL2-4": 63213,
            "TVL2-5": 63214,
            "TVL2-6": 63215,
            "TVL2-7": 63238,
            "TVL2-8": 63239,
            "TVL2-9": 63237,
        },
    },
}


@dataclass
class HarvestParams:
    """Tuning knobs for `harvest`: passes per object, min elevation, and pages to paginate."""

    k: int = 12
    min_alt: float = 25.0
    max_pages: int = 3


@dataclass
class _HarvestRun:
    """Shared state threaded through the per-pass harvest helpers."""

    client: SatnogsClient
    ds: Dataset
    cand_obs: dict[int, list[dict]]
    soup: list[int]


def _strong_passes(observations: list[dict], min_alt: float) -> list[dict]:
    """Strong (with-signal, high-elevation) passes for one object, best elevation first."""
    return sorted(
        (
            o
            for o in observations
            if o.get("waterfall_status") == "with-signal"
            and (o.get("max_altitude") or 0) >= min_alt
        ),
        key=lambda o: -(o.get("max_altitude") or 0),
    )


def _write_soup_catalog(
    path: Path, soup: list[int], cand_obs: dict[int, list[dict]], tdate: str
) -> None:
    """Write an epoch-matched candidate catalog (the whole launch's soup) for one pass date."""
    with open(path, "w", encoding="utf-8") as g:
        for n in soup:
            t = nearest_tle(cand_obs[n], tdate)
            if t:
                g.write(f"{t[0]}\n{t[1]}\n{t[2]}\n")


def _try_pass(run: _HarvestRun, o: dict, norad: int) -> PassRecord | None:
    """Download one pass's `.h5` + soup catalog and return its PassRecord, or None if unusable."""
    oid, station, tdate = o["id"], o.get("ground_station"), o["start"][:10]
    url = run.client.h5_url(oid)
    if not url or station is None:
        return None
    h5rel = f"h5/obs{oid}_n{norad}_st{station}.h5"
    run.client.download(url, run.ds.root / h5rel)
    catrel = f"catalogs/soup_{oid}.tle"
    _write_soup_catalog(run.ds.root / catrel, run.soup, run.cand_obs, tdate)
    return PassRecord(oid, norad, int(station), h5rel, catrel, tdate)


def harvest(
    cluster: str,
    out_dir: str,
    params: HarvestParams | None = None,
    client: SatnogsClient | None = None,
) -> Dataset:
    """Harvest up to ``params.k`` strong passes per truth object into ``out_dir``."""
    p = params or HarvestParams()
    cfg = CLUSTERS[cluster]
    client = client if client is not None else SatnogsClient()
    ds = Dataset(root=Path(out_dir), records=[])
    (ds.root / "h5").mkdir(parents=True, exist_ok=True)
    (ds.root / "catalogs").mkdir(parents=True, exist_ok=True)

    # One paginated fetch per candidate; the polite client caches each, so re-runs cost no requests.
    cand_obs = {
        n: client.observations(norad=n, max_pages=p.max_pages) for n in cfg["soup"]
    }
    run = _HarvestRun(client, ds, cand_obs, cfg["soup"])

    for norad, name in cfg["truth"].items():
        got = 0
        for o in _strong_passes(cand_obs[norad], p.min_alt):
            if got >= p.k:
                break
            rec = _try_pass(run, o, norad)
            if rec is not None:
                ds.records.append(rec)
                got += 1
        print(f"{name} ({norad}): {got} passes")

    ds.save()
    print(f"dataset: {len(ds.records)} passes -> {ds.root}/manifest.json")
    return ds


def _main() -> None:
    ap = argparse.ArgumentParser(
        description="Harvest an id eval dataset for a known cluster."
    )
    ap.add_argument("cluster", choices=sorted(CLUSTERS))
    ap.add_argument("out_dir")
    ap.add_argument("-k", type=int, default=12, help="max passes per object")
    ap.add_argument(
        "--min-alt",
        type=float,
        default=25.0,
        help="min max-altitude (deg) for a strong pass",
    )
    ap.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="observation pages to paginate per object",
    )
    args = ap.parse_args()
    harvest(
        args.cluster,
        args.out_dir,
        params=HarvestParams(k=args.k, min_alt=args.min_alt, max_pages=args.max_pages),
    )


if __name__ == "__main__":
    _main()
