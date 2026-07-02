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

from .geometry import Station


@dataclass
class Waterfall:
    """A parsed SatNOGS `.h5`: corrected waterfall, axes, correction TLE, and station."""

    f0_hz: float
    station: Station
    tle: list[str]  # [name, line1, line2] used for the applied Doppler correction
    start: datetime
    relative_time_s: np.ndarray
    freqax_hz: np.ndarray  # offset from f0 (Hz)
    db: np.ndarray  # (n_time, n_freq) power in dB, per-bin normalised


@dataclass
class TrackParams:
    """`extract_track` knobs: SNR gate, carrier search window, MAD outlier rejection."""

    snr_pct: float = 80.0
    win_hz: float = 4000.0
    mad_k: float = 4.0
    mad_iters: int = 3
    min_points: int = 10


def _str_attr(obj: h5py.Group, key: str) -> str:
    """Read an HDF5 string attribute (h5py returns it as str or bytes) as a str."""
    v = obj.attrs[key]
    if isinstance(v, bytes):
        return v.decode()
    assert isinstance(v, str), f"attribute {key!r} is not a string"
    return v


def _array(group: h5py.Group, key: str) -> np.ndarray:
    """Read an HDF5 dataset under `group` as a numpy array (h5py's __getitem__ is loosely typed)."""
    ds = group[key]
    assert isinstance(ds, h5py.Dataset), f"{key!r} is not an HDF5 dataset"
    return ds[:]


def load_waterfall(h5path: str | Path) -> Waterfall:
    """Parse a SatNOGS `.h5` artifact into a Waterfall."""
    with h5py.File(h5path, "r") as f:
        m = json.loads(_str_attr(f, "metadata"))
        wf = f["waterfall"]
        assert isinstance(wf, h5py.Group), "waterfall group missing from .h5"
        st = _str_attr(wf, "start_time")
        data = _array(wf, "data").astype(np.float32)
        scale = _array(wf, "scale").astype(np.float32)
        offset = _array(wf, "offset").astype(np.float32)
        loc = m["location"]
        return Waterfall(
            f0_hz=float(m["frequency"]),
            station=Station(
                lat=float(loc["latitude"]),
                lon=float(loc["longitude"]),
                alt_m=float(loc["altitude"]),
            ),
            tle=m["tle"].strip().splitlines(),
            start=datetime.fromisoformat(st.replace("Z", "+00:00")),
            relative_time_s=_array(wf, "relative_time").astype(float),
            freqax_hz=_array(wf, "frequency").astype(float),
            db=data * scale[None, :] + offset[None, :],
        )


def _parabolic_delta(y0: float, y1: float, y2: float) -> float:
    """Sub-bin peak offset (bins, clipped to +/-1) from a 3-point parabolic fit."""
    den = y0 - 2 * y1 + y2
    return float(np.clip(0.5 * (y0 - y2) / den, -1, 1)) if den != 0 else 0.0


def _refine_peaks(
    wf: Waterfall, hi: np.ndarray, cbin: int, win: int
) -> tuple[np.ndarray, np.ndarray]:
    """Sub-bin carrier peak within +/-win of cbin for each high-SNR waterfall row."""
    db, freqax, relt = wf.db, wf.freqax_hz, wf.relative_time_s
    dfbin = float(freqax[1] - freqax[0])
    lo, hib = max(1, cbin - win), min(db.shape[1] - 1, cbin + win)
    t_pts: list[float] = []
    f_pts: list[float] = []
    for i in hi:
        p = lo + int(np.argmax(db[i, lo:hib]))
        delta = _parabolic_delta(db[i, p - 1], db[i, p], db[i, p + 1])
        t_pts.append(float(relt[i]))
        f_pts.append(freqax[p] + delta * dfbin)
    return np.asarray(t_pts), np.asarray(f_pts)


def _mad_reject(
    times: np.ndarray, freqs: np.ndarray, mad_k: float, mad_iters: int
) -> tuple[np.ndarray, np.ndarray]:
    """Iteratively drop points whose frequency lies beyond mad_k median-absolute-deviations."""
    for _ in range(mad_iters):
        med = np.median(freqs)
        mad = np.median(np.abs(freqs - med)) + 1e-9
        keep = np.abs(freqs - med) < mad_k * mad
        times, freqs = times[keep], freqs[keep]
    return times, freqs


def extract_track(
    wf: Waterfall, params: TrackParams | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Return (relative_time_s, freq_offset_hz) of the signal track, or empty arrays."""
    p = params or TrackParams()
    db = wf.db
    n_time = db.shape[0]
    peak0 = np.argmax(db, axis=1)
    snr = db[np.arange(n_time), peak0] - np.median(db, axis=1)
    hi = np.where(snr >= np.percentile(snr, p.snr_pct))[0]
    if len(hi) < p.min_points:
        return np.array([]), np.array([])

    cbin = int(
        np.argmax(db[hi].mean(axis=0))
    )  # carrier from integrated high-SNR spectrum
    win = max(3, int(p.win_hz / (wf.freqax_hz[1] - wf.freqax_hz[0])))
    times, freqs = _refine_peaks(wf, hi, cbin, win)
    return _mad_reject(times, freqs, p.mad_k, p.mad_iters)
