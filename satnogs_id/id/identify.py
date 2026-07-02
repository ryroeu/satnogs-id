"""Run rffit's headless identify (`-I`, our minimal patch) and parse the ranking. We do NOT
reimplement any estimation -- rffit's own identify_satellite_from_doppler does the matching."""

from __future__ import annotations
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IdentifyResult:
    """rffit's ranking of candidates by Doppler RMS, plus helpers to query it."""

    predicted: int | None  # best-fitting NORAD (lowest Doppler RMS), or None
    ranking: list[tuple[float, int]] = field(
        default_factory=list
    )  # (rms_kHz, norad), ascending

    def rank_of(self, norad: int) -> int | None:
        """1-based rank of ``norad`` in the ranking, or None if absent."""
        for i, (_rms, n) in enumerate(self.ranking):
            if n == norad:
                return i + 1
        return None

    def rms_of(self, norad: int) -> float | None:
        """Doppler RMS (kHz) for ``norad``, or None if absent."""
        return next((rms for rms, n in self.ranking if n == norad), None)

    def margin_khz(self, true_norad: int) -> float | None:
        """RMS gap from the true object to the best *other* candidate (best confuser)."""
        trms = self.rms_of(true_norad)
        conf = next((rms for rms, n in self.ranking if n != true_norad), None)
        return None if (trms is None or conf is None) else conf - trms


def run_rffit_identify(
    dat_path: str | Path,
    catalog_path: str | Path,
    site_id: int,
    rffit_bin: str = "/opt/strf/rffit",
    st_datadir: str = "/opt/strf",
) -> IdentifyResult:
    """Run rffit's headless ``-I`` identify and parse its ranked output into an IdentifyResult."""
    out = subprocess.run(
        [
            rffit_bin,
            "-d",
            str(dat_path),
            "-c",
            str(catalog_path),
            "-s",
            str(site_id),
            "-I",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ST_DATADIR": st_datadir},
    )
    ranking: list[tuple[float, int]] = []
    for line in out.stdout.splitlines():
        head = line.split(":")[0].strip()
        if "kHz" in line and ":" in line and head.isdigit():
            try:
                ranking.append((float(line.split(":")[1].split("kHz")[0]), int(head)))
            except ValueError:
                pass
    ranking.sort()
    return IdentifyResult(predicted=ranking[0][1] if ranking else None, ranking=ranking)
