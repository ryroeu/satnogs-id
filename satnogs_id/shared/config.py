"""Configuration + credentials. Reads the repo `.env` (gitignored) then the process environment.
Never logs or commits secrets."""

from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: str | Path) -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


@dataclass(frozen=True)
class Settings:
    """Resolved credentials + cache location for the SatNOGS / Hugging Face clients."""

    db_key: str = ""  # SatNOGS DB API token (artifacts are auth-walled)
    network_key: str = (
        ""  # SatNOGS Network API token (reads are public; kept for completeness)
    )
    hf_token: str = ""  # Hugging Face Hub token
    cache_dir: str = ".cache/satnogs_api"

    @property
    def have_db_key(self) -> bool:
        """True when a SatNOGS DB token is configured."""
        return bool(self.db_key)


def load_settings(env_path: str | Path = ".env") -> Settings:
    """Build Settings from the ``.env`` file overlaid by the process environment."""
    e = {**_load_env_file(env_path), **os.environ}
    return Settings(
        db_key=e.get("satnogs_db_api_key", ""),
        network_key=e.get("satnogs_network_api_key", ""),
        hf_token=e.get("HUGGING_FACE_HUB_TOKEN", ""),
        cache_dir=e.get("SATNOGS_ID_CACHE", ".cache/satnogs_api"),
    )


settings = load_settings()
