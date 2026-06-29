"""Harvest an id eval dataset for a cluster of near-identical objects: for each truth object, pull
its strong (with-signal, .h5) passes via the polite client, download each artifact, and attach an
epoch-matched candidate catalog (the whole launch's soup). Pagination reaches historical passes, so
N grows well beyond the 25-per-page recent window once the API cooldown clears.

Run in-container: docker compose run --rm app python -m satnogs_id.data.build geoscan _eval/geoscan
"""
from __future__ import annotations
import argparse
from pathlib import Path

from ..shared.api import SatnogsClient, nearest_tle
from .dataset import Dataset, PassRecord

# Known IDENTIFIED clusters used as an answer key. soup = the full launch's NORAD range; truth =
# the SatNOGS-assigned object per member. Geoscan: intl 2025-155, launched 2025-07-25.
CLUSTERS: dict[str, dict] = {
    "geoscan": {
        "soup": list(range(64876, 64896)),
        "truth": {64879: "Geoscan-6", 64880: "Geoscan-1", 64890: "Geoscan-2",
                  64891: "Geoscan-5", 64892: "Geoscan-4", 64893: "Geoscan-3"},
    },
}


def harvest(cluster: str, out_dir: str, k: int = 12, min_alt: float = 25.0,
            max_pages: int = 3, client: SatnogsClient | None = None) -> Dataset:
    cfg = CLUSTERS[cluster]
    client = client if client is not None else SatnogsClient()
    ds = Dataset(root=Path(out_dir), records=[])
    (ds.root / "h5").mkdir(parents=True, exist_ok=True)
    (ds.root / "catalogs").mkdir(parents=True, exist_ok=True)

    # One paginated fetch per candidate; the polite client caches each, so re-runs cost no requests.
    cand_obs = {n: client.observations(norad=n, max_pages=max_pages) for n in cfg["soup"]}

    for norad, name in cfg["truth"].items():
        strong = sorted(
            (o for o in cand_obs[norad]
             if o.get("waterfall_status") == "with-signal" and (o.get("max_altitude") or 0) >= min_alt),
            key=lambda o: -(o.get("max_altitude") or 0))
        got = 0
        for o in strong:
            if got >= k:
                break
            oid, station, tdate = o["id"], o.get("ground_station"), o["start"][:10]
            url = client.h5_url(oid)
            if not url:
                continue
            h5rel = f"h5/obs{oid}_n{norad}_st{station}.h5"
            client.download(url, ds.root / h5rel)
            catrel = f"catalogs/soup_{oid}.tle"
            with open(ds.root / catrel, "w") as g:
                for n in cfg["soup"]:
                    t = nearest_tle(cand_obs[n], tdate)
                    if t:
                        g.write(f"{t[0]}\n{t[1]}\n{t[2]}\n")
            ds.records.append(PassRecord(oid, norad, int(station), h5rel, catrel, tdate))
            got += 1
        print(f"{name} ({norad}): {got} passes")

    ds.save()
    print(f"dataset: {len(ds.records)} passes -> {ds.root}/manifest.json")
    return ds


def _main() -> None:
    ap = argparse.ArgumentParser(description="Harvest an id eval dataset for a known cluster.")
    ap.add_argument("cluster", choices=sorted(CLUSTERS))
    ap.add_argument("out_dir")
    ap.add_argument("-k", type=int, default=12, help="max passes per object")
    ap.add_argument("--min-alt", type=float, default=25.0, help="min max-altitude (deg) for a strong pass")
    ap.add_argument("--max-pages", type=int, default=3, help="observation pages to paginate per object")
    args = ap.parse_args()
    harvest(args.cluster, args.out_dir, k=args.k, min_alt=args.min_alt, max_pages=args.max_pages)


if __name__ == "__main__":
    _main()
