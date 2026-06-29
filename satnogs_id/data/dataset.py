"""The id eval dataset contract: a directory with a `manifest.json` listing pass records, each
pinning one observation to its truth NORAD, ground station, artifact `.h5`, and the epoch-matched
candidate catalog. The harvester (data.build) writes it; the eval harness (id.eval) reads it."""
from __future__ import annotations
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

_NAME_RE = re.compile(r"obs(\d+)_n(\d+)_st(\d+)")


@dataclass
class PassRecord:
    obs_id: int
    norad: int        # truth: the SatNOGS-assigned catalog object for this observation
    station: int
    h5: str           # path relative to the dataset root
    catalog: str      # path relative to the dataset root (3LE candidate soup)
    start: str = ""   # YYYY-MM-DD (used for epoch matching at harvest time; unused at eval time)


@dataclass
class Dataset:
    root: Path
    records: list[PassRecord]

    def save(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps([asdict(r) for r in self.records], indent=2))
        return manifest

    @classmethod
    def load(cls, root: str | Path) -> "Dataset":
        root = Path(root)
        recs = [PassRecord(**d) for d in json.loads((root / "manifest.json").read_text())]
        return cls(root, recs)

    def h5_path(self, r: PassRecord) -> Path:
        return self.root / r.h5

    def catalog_path(self, r: PassRecord) -> Path:
        return self.root / r.catalog


def manifest_from_dir(root: str | Path) -> Dataset:
    """Reconstruct a Dataset from loose `obs{id}_n{norad}_st{station}.h5` + `soup_{id}.tle` files
    (the M0 probe layout), so the existing downloads become a testable fixture with no API calls."""
    root = Path(root)
    records: list[PassRecord] = []
    for h5 in sorted(root.rglob("*.h5")):
        m = _NAME_RE.search(h5.name)
        if not m:
            continue
        oid, norad, station = (int(g) for g in m.groups())
        cats = list(root.rglob(f"soup_{oid}.tle"))
        if not cats:
            continue
        records.append(PassRecord(
            obs_id=oid, norad=norad, station=station,
            h5=str(h5.relative_to(root)), catalog=str(cats[0].relative_to(root)),
        ))
    return Dataset(root, records)
