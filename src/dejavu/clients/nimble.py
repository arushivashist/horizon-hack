import json
import os
import urllib.error
import urllib.request


class NimbleClient:
    """Minimal Nimble client for live web extraction."""

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or os.getenv("NIMBLE_API_KEY")
        configured = base_url or os.getenv("NIMBLE_BASE_URL")
        # Extract uses Nimble's SDK API. Keep old api.webit.live env values
        # from accidentally routing Extract to the legacy realtime surface.
        if not configured or "api.webit.live" in configured:
            configured = "https://sdk.nimbleway.com/v1"
        self.base_url = configured.rstrip("/")

    def _post(self, path, payload):
        if not self.api_key:
            return {"mode": "no-key", "results": []}
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Nimble HTTP {exc.code} calling {self.base_url + path}: {body[:1000]}"
            ) from exc

    def extract(self, url):
        return self._post("/extract", {"url": url})
