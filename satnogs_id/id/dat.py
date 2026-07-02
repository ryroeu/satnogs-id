"""Build rffit inputs from a SatNOGS waterfall: the Doppler `.dat` (extract track -> un-correct ->
MJD/received-freq/site rows), the candidate catalog (3LE), and the strf `sites.txt` site line."""

from __future__ import annotations
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Sequence

from ..shared import geometry
from ..shared.waterfall import TrackParams, Waterfall, extract_track


def extract_doppler(
    wf: Waterfall, params: TrackParams | None = None
) -> tuple[list[float], list[float]]:
    """Extract the near-vertical track and un-correct it -> (time_mjd, freq_recv_hz), sorted in
    time. This is the physical received Doppler curve -- what rffit fits and what the published
    dataset stores. Returns empty lists if no track is found."""
    t, foff = extract_track(wf, params)
    if len(t) == 0:
        return [], []
    times = [wf.start + timedelta(seconds=float(s)) for s in t]
    rr = geometry.range_rate_km_s(wf.tle[1], wf.tle[2], wf.station, times)
    recv = geometry.uncorrect(wf.f0_hz, foff, rr)
    rows = sorted((geometry.mjd(times[i]), float(recv[i])) for i in range(len(t)))
    return [r[0] for r in rows], [r[1] for r in rows]


def build_dat(
    wf: Waterfall, site_id: int, dat_path: str | Path, params: TrackParams | None = None
) -> int:
    """Extract + un-correct the track and write an rffit `.dat`. Returns the number of points."""
    mjd, recv = extract_doppler(wf, params)
    if not mjd:
        Path(dat_path).write_text("", encoding="utf-8")
        return 0
    with open(dat_path, "w", encoding="utf-8") as g:
        for m, fr in zip(mjd, recv):
            g.write(f"{m:.6f}\t{fr:.2f}\t1.0\t{site_id}\n")
    return len(mjd)


def site_line(wf: Waterfall, site_id: int) -> str:
    """A strf `sites.txt` line. Use a free 4-digit `site_id` (strf only parses 4-digit ids, so the
    `7{station}` convention breaks for SatNOGS stations > 999)."""
    s = wf.station
    return f"{site_id} GS {s.lat:.4f} {s.lon:.4f} {int(s.alt_m)} obs\n"


def write_catalog(tles: Iterable[Sequence[str]], path: str | Path) -> int:
    """Write candidate 3LEs to a strf catalog file. Returns the number written."""
    n = 0
    with open(path, "w", encoding="utf-8") as g:
        for name, l1, l2 in tles:
            g.write(f"{name}\n{l1}\n{l2}\n")
            n += 1
    return n
