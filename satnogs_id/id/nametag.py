"""Decoded name-tag confidence: read a satellite's self-reported AX.25 callsign from an
observation's decoded frames and score it against the Doppler ID as a supplemental second opinion
(never truth). See docs/superpowers/specs/2026-06-30-decoded-name-confidence-design.md."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


def parse_callsign(frame_hex: str) -> str | None:
    """The AX.25 source callsign (frame bytes 7-12, each ASCII shifted left one bit). None if the
    frame is too short, not hex, or the address isn't printable."""
    try:
        b = bytes.fromhex(frame_hex)
    except ValueError:
        return None
    if len(b) < 14:
        return None
    src = "".join(chr(c >> 1) for c in b[7:13]).strip()
    if src and all(32 <= ord(ch) < 127 for ch in src):
        return src
    return None


@dataclass
class NameTag:
    """A scored name-tag opinion: the dominant satellite, its tier, agreement, and a reason."""

    norad: int | None  # dominant resolved satellite (None when tier == "NONE")
    tier: str  # HIGH | MEDIUM | LOW | DISAGREES | NONE
    agrees: bool | None  # vs the Doppler ID; None when tier == "NONE"
    reason: str  # one-line human explanation


def assess(messages: list[tuple[int, bool]], predicted_norad: int) -> NameTag:
    """Tier per the spec's evaluation order. `messages` = (resolved_norad, flagged_shared) each."""
    if not messages:
        return NameTag(None, "NONE", None, "no messages decoded for this observation")
    norads = [n for n, _ in messages]
    flagged = any(f for _, f in messages)
    total = len(norads)
    counts = Counter(norads)
    dominant, dom_count = counts.most_common(1)[0]
    share = dom_count / total
    agrees = dominant == predicted_norad
    if total == 1:
        return NameTag(dominant, "LOW", agrees, "a single decoded message")
    if share <= 0.5:
        return NameTag(
            dominant,
            "LOW",
            agrees,
            f"no majority (messages split across {len(counts)} satellites)",
        )
    if not agrees:
        return NameTag(
            dominant,
            "DISAGREES",
            False,
            f"majority disagrees with Doppler ({dom_count} of {total} messages)",
        )
    if total >= 3 and share >= 0.8 and not flagged:
        return NameTag(
            dominant, "HIGH", True, f"heard in {dom_count} of {total} decoded messages"
        )
    why = (
        "flagged shared by SatNOGS"
        if flagged
        else f"only {total} messages"
        if total < 3
        else f"{dom_count} of {total} messages agree"
    )
    return NameTag(dominant, "MEDIUM", True, why)


def resolve_messages(
    frames: list[dict], callsign_map: dict[str, int]
) -> list[tuple[int, bool]]:
    """Turn raw telemetry frames into (resolved_norad, flagged_shared). Frames whose callsign
    does not parse or is not in the cluster's callsign map are dropped."""
    out: list[tuple[int, bool]] = []
    for fr in frames:
        callsign = parse_callsign(fr.get("frame") or "")
        norad = callsign_map.get(callsign) if callsign else None
        if norad is None:
            continue
        out.append((norad, bool(fr.get("associated_satellites"))))
    return out


def format_name_tag(
    nt: "NameTag | None", names: dict[int, str], predicted: int | None = None
) -> str:
    """One-line badge for a NameTag. `names` maps NORAD -> display name; `predicted` is the Doppler
    NORAD, used to name it when the tag disagrees. '' when there's no tag."""
    if nt is None:
        return ""
    if nt.tier == "NONE":
        return "Name tag:  —  ·  none  — " + nt.reason
    assert nt.norad is not None  # non-NONE tiers always carry a resolved NORAD
    label = names.get(nt.norad, str(nt.norad))
    if nt.tier == "DISAGREES":
        doppler = (
            names.get(predicted, str(predicted))
            if predicted is not None
            else "the Doppler ID"
        )
        return (
            f"Name tag:  {label}  ·  ⚠ disagrees  — "
            f"Doppler says {doppler} (possibly a co-audible neighbour)"
        )
    mark = "  ✓ agrees" if nt.agrees else ""
    return f"Name tag:  {label}  ·  {nt.tier}{mark}  — {nt.reason}"
