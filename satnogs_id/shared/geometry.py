"""Doppler geometry via skyfield, and the Doppler-correction inverse.

The SatNOGS waterfall is Doppler-CORRECTED (verified from the gr-satnogs flowgraph source:
soapy_source -> doppler_compensation -> waterfall_sink). The station tunes to track the
satellite's assigned-TLE Doppler, so a signal sits at a near-vertical residual offset. To recover
the physical received frequency for rffit we add the correction back:

    freq_recv = f0 + offset - f0 * range_rate / c

(exactly as strf's satnogs_waterfall_tabulation_helper.py does). This is independent of which TLE
was used to correct, so it is non-circular -- it recovers the actual received Doppler curve."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from skyfield.api import EarthSatellite, load, wgs84

C_KM_S = 299792.458
MJD_EPOCH = datetime(1858, 11, 17, tzinfo=timezone.utc)
_TS = load.timescale(builtin=True)


@dataclass
class Station:
    """Ground-station location (WGS84) used for topocentric Doppler geometry."""

    lat: float
    lon: float
    alt_m: float


def tle_epoch(line1: str) -> datetime:
    """Parse the epoch (columns 19-32, `YYDDD.dddddddd`) of TLE line 1 into a UTC datetime. Used to
    measure how far a candidate's elements must be propagated to the observation -- the thing that
    governs whether current (CelesTrak) elements are still valid for a given observation."""
    field = line1[18:32]
    yy = int(field[:2])
    doy = float(field[2:])
    year = 2000 + yy if yy < 57 else 1900 + yy
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=doy - 1.0)


def intdes_from_tle1(line1: str) -> str:
    """Launch international designator (e.g. '2025-155') from TLE line 1 cols 10-17 ('25155Q'). Lets
    forward mode derive the candidate launch straight from the observation's own elements."""
    field = line1[9:17].strip()
    yy = int(field[:2])
    num = int(field[2:5])
    year = 2000 + yy if yy < 57 else 1900 + yy
    return f"{year}-{num:03d}"


def range_rate_km_s(
    tle1: str, tle2: str, station: Station, times: list[datetime]
) -> np.ndarray:
    """Topocentric range rate (km/s; positive = receding) of a satellite from a ground station."""
    sat = EarthSatellite(tle1, tle2, "sat", _TS)
    ground = wgs84.latlon(station.lat, station.lon, elevation_m=station.alt_m)
    pos = (sat - ground).at(_TS.from_datetimes(times))
    r = pos.position.km
    v = pos.velocity.km_per_s
    assert isinstance(r, np.ndarray) and isinstance(v, np.ndarray)
    return np.sum(r * v, axis=0) / np.linalg.norm(r, axis=0)


def doppler_offset_hz(f0_hz: float, range_rate: np.ndarray) -> np.ndarray:
    """Predicted Doppler offset (Hz) for a transmit frequency f0 and range rate (km/s)."""
    return -f0_hz * range_rate / C_KM_S


def uncorrect(
    f0_hz: float, offset_hz: np.ndarray, range_rate: np.ndarray
) -> np.ndarray:
    """Recover physical received frequency from a Doppler-corrected waterfall offset."""
    return f0_hz + offset_hz - f0_hz * range_rate / C_KM_S


def mjd(dt: datetime) -> float:
    """Modified Julian Date of a datetime (naive datetimes are treated as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - MJD_EPOCH).total_seconds() / 86400.0
