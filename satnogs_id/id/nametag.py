"""Decoded name-tag confidence: read a satellite's self-reported AX.25 callsign from an observation's
decoded frames and score it against the Doppler ID as a supplemental second opinion (never truth).
See docs/superpowers/specs/2026-06-30-decoded-name-confidence-design.md."""
from __future__ import annotations


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
