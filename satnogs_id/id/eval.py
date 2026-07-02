"""Honest identification metrics over a Dataset: top-1 accuracy with a Wilson 95% CI, the
true-object rank distribution, the margin-over-best-confuser distribution, and a per-object
breakdown.

Run in-container: docker compose run --rm app python -m satnogs_id.id.eval <dataset_dir>."""

from __future__ import annotations
import argparse
import math
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..data.dataset import Dataset
from ..shared.waterfall import load_waterfall
from .dat import build_dat, site_line
from .identify import IdentifyResult, run_rffit_identify


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion -- well-behaved at small n and p near 0/1,
    unlike the normal approximation (which would give [100%, 100%] for 8/8 and hide all
    uncertainty)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class EvalResult:
    """Accumulated id metrics: counts, true-object ranks, margins, per-object tallies."""

    n_scored: int = 0
    n_correct: int = 0
    unusable: int = 0
    ranks: list[int] = field(default_factory=list)
    margins_khz: list[float] = field(default_factory=list)
    per_object: dict[int, tuple[int, int]] = field(
        default_factory=dict
    )  # norad -> (correct, total)

    @property
    def top1(self) -> float:
        """Top-1 accuracy (fraction of scored passes whose true object ranked first)."""
        return self.n_correct / self.n_scored if self.n_scored else 0.0

    @property
    def ci(self) -> tuple[float, float]:
        """Wilson 95% confidence interval for the top-1 accuracy."""
        return wilson_ci(self.n_correct, self.n_scored)

    def report(self, names: dict[int, str] | None = None) -> str:
        """Render the accumulated metrics as a human-readable multi-line report."""
        names = names or {}
        lo, hi = self.ci
        lines = [
            f"=== id eval: {self.n_scored + self.unusable} passes "
            f"({self.n_scored} scored, {self.unusable} unusable) ===",
            f"TOP-1 ACCURACY: {self.n_correct}/{self.n_scored} = {100 * self.top1:.1f}%  "
            f"(95% Wilson CI {100 * lo:.0f}-{100 * hi:.0f}%)",
            "rank of true object: "
            + (
                ", ".join(
                    f"rank{r}:{self.ranks.count(r)}" for r in sorted(set(self.ranks))
                )
                or "n/a"
            ),
        ]
        if self.margins_khz:
            a = sorted(self.margins_khz)
            lines.append(
                f"margin over best confuser (correct): median {a[len(a) // 2]:.2f} kHz, "
                f"min {a[0]:.2f}, max {a[-1]:.2f}"
            )
        lines.append("per-object top-1:")
        for n in sorted(self.per_object):
            c, t = self.per_object[n]
            lines.append(f"  {names.get(n, n)} ({n}): {c}/{t}")
        return "\n".join(lines)


def _run_pass(
    ds: Dataset, record, site: int, sites_txt: str, min_points: int
) -> IdentifyResult | None:
    """Build a pass's `.dat`, register the site, run identify; None if too few points."""
    wf = load_waterfall(ds.h5_path(record))
    dat = Path(tempfile.gettempdir()) / f"{record.obs_id}.dat"
    if build_dat(wf, site, dat) < min_points:
        return None
    with open(sites_txt, "a", encoding="utf-8") as f:
        f.write(site_line(wf, site))
    return run_rffit_identify(dat, ds.catalog_path(record), site)


def _record_result(res: EvalResult, out: IdentifyResult, norad: int) -> None:
    """Fold one scored pass's ranking into the running EvalResult."""
    correct = out.predicted == norad
    res.n_scored += 1
    res.n_correct += int(correct)
    c, t = res.per_object.get(norad, (0, 0))
    res.per_object[norad] = (c + int(correct), t + 1)
    rk = out.rank_of(norad)
    if rk:
        res.ranks.append(rk)
    margin = out.margin_khz(norad)
    if correct and margin is not None:
        res.margins_khz.append(margin)


def evaluate(
    ds: Dataset,
    base_site: int = 9001,
    sites_txt: str = "/opt/strf/data/sites.txt",
    min_points: int = 10,
) -> EvalResult:
    """Score every pass in the dataset and accumulate top-1 accuracy, ranks, and margins."""
    res = EvalResult()
    for k, r in enumerate(ds.records):
        site = base_site + (k % 900)
        out = _run_pass(ds, r, site, sites_txt, min_points)
        if out is None or out.predicted is None:
            res.unusable += 1
            continue
        _record_result(res, out, r.norad)
    return res


def _main() -> None:
    ap = argparse.ArgumentParser(
        description="Evaluate identification accuracy over a dataset."
    )
    ap.add_argument("dataset")
    args = ap.parse_args()
    ds = Dataset.load(args.dataset)
    print(evaluate(ds).report())


if __name__ == "__main__":
    _main()
