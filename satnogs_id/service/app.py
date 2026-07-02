"""Gradio 'Identify' view: paste a SatNOGS observation id, get the most-likely catalog object from
its Doppler -- read-only, no account needed. A thin shell over forward.identify_observation, wrapped
in a gr.Interface (obs id + launch designator -> Doppler verdict + ranked candidate table)."""

from __future__ import annotations

import gradio as gr

from ..data.build import CLUSTERS
from ..id.nametag import format_name_tag
from ..shared.api import RateLimited
from .forward import ForwardID, identify_observation

INTRO = """# satnogs-id — Identify

Enter a **SatNOGS observation id** that has a waterfall artifact. This ranks which cataloged object
best matches the observation's Doppler, via Cees Bassa's **strf / rffit**. Candidates default to the
object's own launch (live CelesTrak elements); override with a launch designator if you like.
Read-only — nothing is written back to SatNOGS.
"""


def format_result(
    obs_id: int, intdes: str | None, out: ForwardID
) -> tuple[str, list[list]]:
    """Render a ForwardID as (markdown verdict, candidate rows). Pure -- no network, no gradio."""
    if out.best is None:
        return f"**obs {obs_id}:** no usable Doppler track or no candidates.", []
    rms0 = out.result.ranking[0][0]
    md = [
        f"### obs {obs_id} → most likely **NORAD {out.best}**",
        f"- best Doppler RMS **{rms0:.3f} kHz**"
        + (
            f", margin **{out.margin_khz:.3f} kHz** over the runner-up"
            if out.margin_khz is not None
            else ""
        ),
        f"- {out.n_points} Doppler points; candidates from launch **{intdes or 'auto'}**",
    ]
    if out.ambiguous:
        md.append(
            "- ⚠️ **Ambiguous** — the margin is thin; confirm with another pass "
            "(ideally from a different station)."
        )
        if out.epoch_gap_days is not None and out.epoch_gap_days > 60:
            md.append(
                f"- candidate elements are ~{out.epoch_gap_days:.0f} d from the observation — "
                "likely too stale; current TLEs suit recent passes."
            )
    rows = [[norad, f"{rms:.3f}"] for rms, norad in out.result.ranking[:10]]
    _names = next((c["truth"] for c in CLUSTERS.values() if out.best in c["truth"]), {})
    _badge = format_name_tag(out.name_tag, _names, predicted=out.best)
    if _badge:
        md.append("- " + _badge)
    return "\n".join(md), rows


def _run(obs_id, intdes):
    try:
        oid = int(str(obs_id).strip())
    except (TypeError, ValueError):
        return "Enter a numeric observation id.", []
    intdes = (str(intdes).strip() or None) if intdes else None
    try:
        out = identify_observation(oid, intdes=intdes)
    except (RateLimited, RuntimeError, OSError, ValueError, KeyError) as e:
        return f"Could not identify obs {oid}: {e}", []
    return format_result(oid, intdes, out)


def build_identify_app() -> gr.Interface:
    """Build the Gradio 'Identify' interface: obs id + launch -> verdict + table."""
    return gr.Interface(
        fn=_run,
        inputs=[
            gr.Textbox(label="Observation id", placeholder="e.g. 14075713"),
            gr.Textbox(
                label="Launch designator (optional)", placeholder="auto — e.g. 2025-155"
            ),
        ],
        outputs=[
            gr.Markdown(label="Verdict"),
            gr.Dataframe(
                headers=["NORAD", "Doppler RMS (kHz)"],
                label="Ranked candidates",
                interactive=False,
                wrap=True,
            ),
        ],
        title="satnogs-id — Identify",
        description=INTRO,
        examples=[["14075713", ""]],
        flagging_mode="never",
    )
