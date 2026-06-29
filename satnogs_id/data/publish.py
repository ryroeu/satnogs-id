"""Assemble the satnogs-id Doppler dataset and push it to the Hugging Face Hub -- the project's
distribution artifact, mirroring satnogs-signal's published waterfalls dataset. We publish labeled
Doppler TRACKS (not the heavy `.h5`): per pass, the un-corrected received-frequency curve + station
+ truth NORAD, so the set is a ready supervised benchmark for near-identical cluster identification.
(satnogs-id wraps strf/rffit and trains no model, so the dataset -- not a model -- is the artifact.)"""
from __future__ import annotations

from .dataset import Dataset
from ..id.dat import extract_doppler
from ..shared.geometry import intdes_from_tle1
from ..shared.waterfall import load_waterfall

REPO_ID = "ryroeu/satnogs-id-doppler"


def build_records(ds: Dataset, object_names: dict[int, str] | None = None,
                  min_points: int = 10) -> list[dict]:
    """One row per pass: its un-corrected Doppler track + station + truth label + provenance."""
    object_names = object_names or {}
    records: list[dict] = []
    for r in ds.records:
        wf = load_waterfall(ds.h5_path(r))
        time_mjd, freq_recv_hz = extract_doppler(wf)
        if len(time_mjd) < min_points:
            continue
        records.append({
            "obs_id": r.obs_id,
            "norad": r.norad,
            "object": object_names.get(r.norad, ""),
            "station": r.station,
            "start": r.start,
            "intdes": intdes_from_tle1(wf.tle[1]),
            "frequency_hz": wf.f0_hz,
            "station_lat": wf.lat,
            "station_lon": wf.lon,
            "station_alt_m": wf.alt_m,
            "time_mjd": time_mjd,
            "freq_recv_hz": freq_recv_hz,
            "n_points": len(time_mjd),
        })
    return records


def to_hf_dataset(records: list[dict]):
    from datasets import Dataset as HFDataset, Features, Sequence, Value
    features = Features({
        "obs_id": Value("int64"),
        "norad": Value("int64"),
        "object": Value("string"),
        "station": Value("int64"),
        "start": Value("string"),
        "intdes": Value("string"),
        "frequency_hz": Value("float64"),
        "station_lat": Value("float64"),
        "station_lon": Value("float64"),
        "station_alt_m": Value("float64"),
        "time_mjd": Sequence(Value("float64")),
        "freq_recv_hz": Sequence(Value("float64")),
        "n_points": Value("int64"),
    })
    return HFDataset.from_list(records, features=features)


def push(hf_dataset, repo_id: str = REPO_ID, private: bool = True):  # pragma: no cover
    hf_dataset.push_to_hub(repo_id, private=private)
