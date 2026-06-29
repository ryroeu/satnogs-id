"""CLI: identify the emitter in a SatNOGS artifact .h5 against a candidate catalog, via the
strf/rffit wrap. Run in the container:
    docker compose run --rm app python scripts/identify_obs.py <obs.h5> <catalog.tle> [--site 9001]
"""
from __future__ import annotations
import argparse
import tempfile
from pathlib import Path

from satnogs_id.shared.waterfall import load_waterfall
from satnogs_id.id.dat import build_dat, site_line
from satnogs_id.id.identify import run_rffit_identify


def main() -> None:
    ap = argparse.ArgumentParser(description="Identify a SatNOGS emitter from its Doppler via rffit.")
    ap.add_argument("h5")
    ap.add_argument("catalog")
    ap.add_argument("--site", type=int, default=9001)
    ap.add_argument("--sites-txt", default="/opt/strf/data/sites.txt")
    args = ap.parse_args()

    wf = load_waterfall(args.h5)
    dat = Path(tempfile.gettempdir()) / "obs.dat"
    n = build_dat(wf, args.site, dat)
    if n == 0:
        print("no signal track extracted"); return
    with open(args.sites_txt, "a") as f:
        f.write(site_line(wf, args.site))
    res = run_rffit_identify(dat, args.catalog, args.site)
    print(f"{n} track points; predicted NORAD: {res.predicted}")
    for rms, norad in res.ranking[:8]:
        print(f"  {norad}: {rms:.3f} kHz")


if __name__ == "__main__":
    main()
