"""Polite SatNOGS + CelesTrak API client: on-disk response caching, a minimum inter-request
interval, exponential backoff on HTTP 429, and Link-header pagination for the Network observations
endpoint. This is what lets us harvest a real eval set without tripping the rate limiter."""

from __future__ import annotations
import json
import time
import hashlib
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from .config import settings


class RateLimited(Exception):
    """Raised when the SatNOGS/CelesTrak rate limiter is not cleared within max_retries."""


class SatnogsClient:
    """Polite SatNOGS/CelesTrak client: on-disk cache, request throttling, 429 backoff."""

    NETWORK = "https://network.satnogs.org/api"
    DB = "https://db.satnogs.org/api"
    CELESTRAK_GP = "https://celestrak.org/NORAD/elements/gp.php"

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        min_interval: float = 0.4,
        max_retries: int = 6,
        backoff: float = 8.0,
    ) -> None:
        self.cache = Path(cache_dir or settings.cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff = backoff
        self._last = 0.0

    # ---- low-level GET with cache + rate-limit handling ----
    def _raw(
        self, url: str, auth: bool, accept: str = "application/json"
    ) -> tuple[bytes, Any]:
        headers = {"Accept": accept}
        if auth:
            headers["Authorization"] = f"Token {settings.db_key}"
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, headers=headers), timeout=30
                ) as resp:
                    self._last = time.monotonic()
                    return resp.read(), resp.headers
            except urllib.error.HTTPError as e:
                self._last = time.monotonic()
                if e.code == 429 and attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                raise
        raise RateLimited(url)

    def get_json(self, url: str, auth: bool = False, use_cache: bool = True) -> Any:
        """GET a URL and parse JSON, using the on-disk cache when enabled."""
        key = self.cache / (hashlib.sha1(url.encode()).hexdigest() + ".json")
        if use_cache and key.exists():
            return json.loads(key.read_text())
        body, _ = self._raw(url, auth)
        data = json.loads(body)
        if use_cache:
            key.write_text(json.dumps(data))
        return data

    @staticmethod
    def _next_link(headers: Any) -> str | None:
        link = headers.get("Link") if headers else None
        if not link:
            return None
        for part in link.split(","):
            if 'rel="next"' in part:
                return part.split(";")[0].strip().strip("<>")
        return None

    # ---- SatNOGS Network (public reads) ----
    def observations(
        self,
        *,
        norad: int | None = None,
        sat_id: str | None = None,
        max_pages: int = 1,
        **filters: Any,
    ) -> list[dict]:
        """Observations for a satellite, following Link-header pagination up to max_pages.
        Note: the working filter is `norad_cat_id` (not `satellite__norad_cat_id`)."""
        params = {"format": "json"}
        if norad is not None:
            params["norad_cat_id"] = str(norad)
        if sat_id is not None:
            params["sat_id"] = sat_id
        params.update({k: str(v) for k, v in filters.items()})
        url = f"{self.NETWORK}/observations/?" + "&".join(
            f"{k}={v}" for k, v in params.items()
        )
        out: list[dict] = []
        for _ in range(max_pages):
            key = self.cache / (hashlib.sha1(url.encode()).hexdigest() + ".page.json")
            if key.exists():
                page, nxt = json.loads(key.read_text())
            else:
                body, headers = self._raw(url, auth=False)
                page = json.loads(body)
                nxt = self._next_link(headers)
                key.write_text(json.dumps([page, nxt]))
            out.extend(page)
            if not nxt:
                break
            url = nxt
        return out

    def observation(self, obs_id: int | str) -> dict:
        """Fetch a single Network observation record by its id."""
        return self.get_json(f"{self.NETWORK}/observations/?id={obs_id}&format=json")[0]

    # ---- SatNOGS DB (artifacts are authenticated) ----
    def artifacts(self, network_obs_id: int | str) -> list[dict]:
        """Artifact records (the `.h5` waterfalls) for a Network observation, from the DB API."""
        r = self.get_json(
            f"{self.DB}/artifacts/?network_obs_id={network_obs_id}&format=json",
            auth=True,
        )
        return r if isinstance(r, list) else r.get("results", [])

    def telemetry(self, observation_id: int | str) -> list[dict]:
        """Decoded telemetry frames for one observation (cursor-paginated; cached + 429-backed-off
        like every other call here).

        The DB API does not support ?observation_id= as a standalone filter (returns HTTP 400).
        Instead we look up the observation to get its NORAD ID and time window, then query
        ?satellite=<norad>&start=<obs_start>&end=<obs_end>&format=json with auth.
        All returned frames fall within the observation window and typically carry the
        matching observation_id; a client-side guard filters any stragglers."""
        # Resolve NORAD + time bounds from the Network observation record (cached).
        obs = self.observation(observation_id)
        norad = obs.get("norad_cat_id")
        start = obs.get("start")
        end = obs.get("end")
        if not (norad and start and end):
            return []
        out: list[dict] = []
        url = (
            f"{self.DB}/telemetry/"
            f"?satellite={norad}&start={start}&end={end}&format=json"
        )
        seen = 0
        while url and seen < 20:  # cap pages; one observation never needs many
            r = self.get_json(url, auth=True)
            if isinstance(r, dict) and "results" in r:
                out.extend(r["results"])
                url = r.get("next")
            else:
                out.extend(r if isinstance(r, list) else [])
                url = None
            seen += 1
        # Guard: keep only frames whose observation_id matches (or is unset/null).
        str_id = str(observation_id)
        return [
            f
            for f in out
            if f.get("observation_id") is None or str(f.get("observation_id")) == str_id
        ]

    def h5_url(self, network_obs_id: int | str) -> str | None:
        """URL of the first artifact `.h5` for an observation, or None when there is none."""
        for a in self.artifacts(network_obs_id):
            if a.get("artifact_file"):
                return a["artifact_file"]
        return None

    def download(self, url: str, dest: str | Path) -> Path:
        """Download an artifact file (Fastly CDN; falls back to authenticated fetch)."""
        dest = Path(dest)
        try:
            urllib.request.urlretrieve(url, dest)
        except urllib.error.HTTPError:
            req = urllib.request.Request(
                url, headers={"Authorization": f"Token {settings.db_key}"}
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                dest.write_bytes(resp.read())
        return dest

    # ---- CelesTrak GP (public) ----
    def celestrak_gp_tle(self, intdes: str) -> list[tuple[str, str, str]]:
        """3LE rows for a launch's international designator (e.g. '2025-155'), from CelesTrak GP."""
        body, _ = self._raw(
            f"{self.CELESTRAK_GP}?INTDES={intdes}&FORMAT=tle",
            auth=False,
            accept="text/plain",
        )
        lines = [ln.rstrip() for ln in body.decode().splitlines() if ln.strip()]
        return [
            (lines[i], lines[i + 1], lines[i + 2]) for i in range(0, len(lines) - 2, 3)
        ]


def nearest_tle(
    observations: Iterable[dict], target_date: str
) -> tuple[str, str, str] | None:
    """Pick the per-obs TLE (tle0/1/2) whose date is nearest target_date (YYYY-MM-DD)."""
    td = date.fromisoformat(target_date[:10])
    best, best_dd = None, 10**9
    for o in observations:
        if not o.get("tle1"):
            continue
        dd = abs((date.fromisoformat(o["start"][:10]) - td).days)
        if dd < best_dd:
            best_dd, best = dd, o
    if best is None:
        return None
    return ((best.get("tle0") or "0 OBJECT").strip(), best["tle1"], best["tle2"])
