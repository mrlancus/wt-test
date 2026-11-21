"""The website's API, as the helper uses it (bearer key)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from wt_analytics.common.config import Config


class Api:
    def __init__(self, cfg: Config) -> None:
        self.http = httpx.Client(
            base_url=f"{cfg.api_url}/api",
            headers={"authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(30, read=120),
        )

    def put_match(self, session: str, row: dict[str, Any]) -> None:
        self.http.put(f"/matches/{session}", json=row).raise_for_status()

    def inbox(self) -> list[dict[str, Any]]:
        response = self.http.get("/inbox")
        response.raise_for_status()
        return response.json()["files"]

    def download_inbox(self, name: str, to: Path) -> Path:
        tmp = to.with_suffix(".part")
        with self.http.stream("GET", f"/inbox/{name}") as response:
            response.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
        tmp.replace(to)
        return to

    def delete_inbox(self, name: str) -> None:
        self.http.delete(f"/inbox/{name}").raise_for_status()
