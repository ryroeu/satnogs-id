"""Build rffit inputs from a SatNOGS waterfall: the Doppler `.dat` (extract track -> un-correct ->
MJD/received-freq/site rows), the candidate catalog (3LE), and the strf `sites.txt` site line."""
from __future__ import annotations
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Sequence

from ..shared import geometry
from ..shared.waterfall import Waterfall, extract_track


def build_dat(wf: Waterfall, site_id: int, dat_path: str | Path, **extract_kwargs) -> int:
    """Extract the near-vertical track, un-correct with the obs TLE, write an rffit `.dat`.
    Returns the number of points written."""
    t, foff = extract_track(wf, **extract_kwargs)
    if len(t) == 0:
        Path(dat_path).write_text("")
        return 0
    times = [wf.start + timedelta(seconds=float(s)) for s in t]
    rr = geometry.range_rate_km_s(wf.tle[1], wf.tle[2], wf.lat, wf.lon, wf.alt_m, times)
    recv = geometry.uncorrect(wf.f0_hz, foff, rr)
    rows = sorted((geometry.mjd(times[i]), float(recv[i])) for i in range(len(t)))
    with open(dat_path, "w") as g:
        for mj, fr in rows:
            g.write(f"{mj:.6f}\t{fr:.2f}\t1.0\t{site_id}\n")
    return len(rows)


def site_line(wf: Waterfall, site_id: int) -> str:
    """A strf `sites.txt` line. Use a free 4-digit `site_id` (strf only parses 4-digit ids, so the
    `7{station}` convention breaks for SatNOGS stations > 999)."""
    return f"{site_id} GS {wf.lat:.4f} {wf.lon:.4f} {int(wf.alt_m)} obs\n"


def write_catalog(tles: Iterable[Sequence[str]], path: str | Path) -> int:
    n = 0
    with open(path, "w") as g:
        for name, l1, l2 in tles:
            g.write(f"{name}\n{l1}\n{l2}\n")
            n += 1
    return n
