"""SatNOGS artifact `.h5` I/O and Doppler-track extraction.

The `.h5` (artifact v2) is self-contained: a (time x frequency) waterfall, timestamps, an Hz
frequency axis, the per-obs TLE used for Doppler correction, and the station location. The signal
in a corrected waterfall is a near-vertical line; `extract_track` pulls it out with a carrier-locked
search window, parabolic sub-bin peak interpolation, and iterative MAD outlier rejection."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np


@dataclass
class Waterfall:
    f0_hz: float
    lat: float
    lon: float
    alt_m: float
    tle: list[str]              # [name, line1, line2] used for the applied Doppler correction
    start: datetime
    relative_time_s: np.ndarray
    freqax_hz: np.ndarray       # offset from f0 (Hz)
    db: np.ndarray              # (T, F) power in dB, per-bin normalised


def load_waterfall(h5path: str | Path) -> Waterfall:
    with h5py.File(h5path, "r") as f:
        m = json.loads(f.attrs["metadata"])
        wf = f["waterfall"]
        st = wf.attrs["start_time"]
        st = st.decode() if isinstance(st, bytes) else st
        data = wf["data"][:].astype(np.float32)
        scale = wf["scale"][:].astype(np.float32)
        offset = wf["offset"][:].astype(np.float32)
        loc = m["location"]
        return Waterfall(
            f0_hz=float(m["frequency"]),
            lat=float(loc["latitude"]), lon=float(loc["longitude"]), alt_m=float(loc["altitude"]),
            tle=m["tle"].strip().splitlines(),
            start=datetime.fromisoformat(st.replace("Z", "+00:00")),
            relative_time_s=wf["relative_time"][:].astype(float),
            freqax_hz=wf["frequency"][:].astype(float),
            db=data * scale[None, :] + offset[None, :],
        )


def extract_track(wf: Waterfall, snr_pct: float = 80.0, win_hz: float = 4000.0,
                  mad_k: float = 4.0, mad_iters: int = 3, min_points: int = 10
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Return (relative_time_s, freq_offset_hz) of the near-vertical signal track, or empty arrays."""
    db = wf.db
    freqax = wf.freqax_hz
    relt = wf.relative_time_s
    T, F = db.shape
    dfbin = float(freqax[1] - freqax[0])

    peak0 = np.argmax(db, axis=1)
    snr = db[np.arange(T), peak0] - np.median(db, axis=1)
    hi = np.where(snr >= np.percentile(snr, snr_pct))[0]
    if len(hi) < min_points:
        return np.array([]), np.array([])

    cbin = int(np.argmax(db[hi].mean(axis=0)))           # carrier from integrated high-SNR spectrum
    win = max(3, int(win_hz / dfbin))
    t_pts: list[float] = []
    f_pts: list[float] = []
    for i in hi:
        lo, hib = max(1, cbin - win), min(F - 1, cbin + win)
        p = lo + int(np.argmax(db[i, lo:hib]))
        y0, y1, y2 = db[i, p - 1], db[i, p], db[i, p + 1]
        den = y0 - 2 * y1 + y2
        delta = float(np.clip(0.5 * (y0 - y2) / den, -1, 1)) if den != 0 else 0.0
        t_pts.append(float(relt[i]))
        f_pts.append(freqax[p] + delta * dfbin)

    t = np.asarray(t_pts)
    fo = np.asarray(f_pts)
    for _ in range(mad_iters):
        med = np.median(fo)
        mad = np.median(np.abs(fo - med)) + 1e-9
        keep = np.abs(fo - med) < mad_k * mad
        t, fo = t[keep], fo[keep]
    return t, fo
