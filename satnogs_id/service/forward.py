"""Forward (live) identification -- the product flow, with NO answer key.

Given a SatNOGS observation of an object whose identity is in question, rank candidate catalog
objects by Doppler RMS via the strf/rffit pipeline and report the most likely identity plus a
confidence margin. Candidates come from an INDEPENDENT live source -- CelesTrak's current GP catalog
by launch international designator -- or an explicit catalog file. (The un-correction still uses the
observation's own TLE only to recover the physical Doppler curve; identification is against the
external catalog, so the answer is not tautological.)

Run in-container:
    docker compose run --rm app python -m satnogs_id.service.forward <obs_id> --intdes 2025-155
"""

from __future__ import annotations
import argparse
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..data.build import CLUSTERS
from ..id.dat import build_dat, site_line, write_catalog
from ..id.identify import IdentifyResult, run_rffit_identify
from ..id.nametag import assess, format_name_tag, resolve_messages
from ..shared.api import RateLimited, SatnogsClient
from ..shared.geometry import intdes_from_tle1, tle_epoch
from ..shared.waterfall import load_waterfall

if TYPE_CHECKING:
    from ..id.nametag import NameTag


@dataclass
class ForwardID:
    """Result of a forward identification: the ranking plus confidence, staleness, and name-tag."""

    obs_id: int
    n_points: int
    result: IdentifyResult
    ambiguous_khz: float
    epoch_gap_days: float | None = None
    name_tag: "NameTag | None" = None

    @property
    def best(self) -> int | None:
        """Most-likely NORAD id (lowest Doppler RMS), or None when there was no identification."""
        return self.result.predicted

    @property
    def margin_khz(self) -> float | None:
        """RMS gap between the top candidate and the runner-up (the confidence)."""
        r = self.result.ranking
        return (r[1][0] - r[0][0]) if len(r) >= 2 else None

    @property
    def ambiguous(self) -> bool:
        """True when the runner-up margin is below the ambiguity threshold (needs another pass)."""
        m = self.margin_khz
        return m is not None and m < self.ambiguous_khz

    def summary(self) -> str:
        """Human-readable identification summary, including the name-tag badge when present."""
        if self.best is None:
            return f"obs {self.obs_id}: no identification (no usable track or empty catalog)"
        m = self.margin_khz
        flag = (
            "  [AMBIGUOUS -- margin below threshold; needs another pass]"
            if self.ambiguous
            else ""
        )
        lines = [
            f"obs {self.obs_id}: most likely NORAD {self.best}"
            f"  (best RMS {self.result.ranking[0][0]:.3f} kHz"
            + (f", margin {m:.3f} kHz over runner-up" if m is not None else "")
            + ")"
            + flag,
            f"  {self.n_points} Doppler points; top candidates:",
        ]
        for rms, norad in self.result.ranking[:5]:
            lines.append(f"    {norad}: {rms:.3f} kHz")
        if (
            self.ambiguous
            and self.epoch_gap_days is not None
            and self.epoch_gap_days > 60
        ):
            lines.append(
                f"  note: candidate elements sit ~{self.epoch_gap_days:.0f} d from the "
                "observation epoch -- likely too stale; current TLEs suit recent passes."
            )
        if self.name_tag is not None:
            names = next(
                (c["truth"] for c in CLUSTERS.values() if self.best in c["truth"]), {}
            )
            badge = format_name_tag(self.name_tag, names, predicted=self.best)
            if badge:
                lines.append("  " + badge)
        return "\n".join(lines)


@dataclass
class IdentifyConfig:
    """Optional knobs for identify_observation: site id, ambiguity threshold, paths, and client."""

    site_id: int = 9001
    ambiguous_khz: float = 0.5
    sites_txt: str = "/opt/strf/data/sites.txt"
    work_dir: str | Path | None = None
    client: SatnogsClient | None = None


def _assess_name_tag(
    client: SatnogsClient, obs_id: int, predicted: int | None
) -> "NameTag | None":
    """Decoded-callsign name-tag for the predicted object, or None (supplemental; never fatal)."""
    if predicted is None:
        return None
    cmap = next(
        (
            c["callsigns"]
            for c in CLUSTERS.values()
            if "callsigns" in c and predicted in c["truth"]
        ),
        None,
    )
    if not cmap:
        return None
    try:
        return assess(resolve_messages(client.telemetry(obs_id), cmap), predicted)
    except (RateLimited, OSError, ValueError, KeyError):
        return None  # supplemental: a telemetry hiccup must not break Doppler


def identify_observation(
    obs_id: int,
    *,
    intdes: str | None = None,
    catalog: str | Path | None = None,
    config: IdentifyConfig | None = None,
) -> ForwardID:
    """Identify obs_id against a candidate catalog. Candidates come from an explicit `catalog` file,
    or live CelesTrak GP for `intdes`, or -- if neither is given -- the launch derived from the
    observation's own elements (auto)."""
    cfg = config or IdentifyConfig()
    client = cfg.client if cfg.client is not None else SatnogsClient()
    work = Path(cfg.work_dir) if cfg.work_dir else Path(tempfile.mkdtemp())
    work.mkdir(parents=True, exist_ok=True)

    url = client.h5_url(obs_id)
    if not url:
        raise RuntimeError(f"observation {obs_id} has no .h5 artifact")
    wf = load_waterfall(client.download(url, work / f"obs{obs_id}.h5"))

    dat = work / f"obs{obs_id}.dat"
    n = build_dat(wf, cfg.site_id, dat)
    if n == 0:
        return ForwardID(obs_id, 0, IdentifyResult(predicted=None), cfg.ambiguous_khz)
    with open(cfg.sites_txt, "a", encoding="utf-8") as f:
        f.write(site_line(wf, cfg.site_id))

    if catalog is None:
        intdes = intdes or intdes_from_tle1(wf.tle[1])
        catalog = work / "candidates.tle"
        write_catalog(client.celestrak_gp_tle(intdes), catalog)
    result = run_rffit_identify(dat, catalog, cfg.site_id)
    gap = _median_epoch_gap_days(catalog, wf.start)
    name_tag = _assess_name_tag(client, obs_id, result.predicted)
    return ForwardID(obs_id, n, result, cfg.ambiguous_khz, gap, name_tag=name_tag)


def _median_epoch_gap_days(catalog: str | Path, obs_start) -> float | None:
    line1s = [
        ln
        for ln in Path(catalog).read_text(encoding="utf-8").splitlines()
        if ln.startswith("1 ")
    ]
    if not line1s:
        return None
    gaps = sorted(
        abs((tle_epoch(ln) - obs_start).total_seconds()) / 86400.0 for ln in line1s
    )
    return gaps[len(gaps) // 2]


def _main() -> None:
    ap = argparse.ArgumentParser(
        description="Forward identification of a SatNOGS observation."
    )
    ap.add_argument("obs_id", type=int)
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument(
        "--intdes",
        help="launch designator for live CelesTrak candidates (default: auto from the obs)",
    )
    src.add_argument("--catalog", help="explicit candidate catalog .tle file")
    ap.add_argument("--site", type=int, default=9001)
    ap.add_argument("--ambiguous-khz", type=float, default=0.5)
    args = ap.parse_args()
    out = identify_observation(
        args.obs_id,
        intdes=args.intdes,
        catalog=args.catalog,
        config=IdentifyConfig(site_id=args.site, ambiguous_khz=args.ambiguous_khz),
    )
    print(out.summary())


if __name__ == "__main__":
    _main()
