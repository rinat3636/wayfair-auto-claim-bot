"""
wayfair_config.py — Configuration for the Wayfair Service Pro auto-claim bot.

All tunables are driven by environment variables with sensible defaults.
GraphQL operation hashes are loaded from gql_hashes.json (auto-updated).
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("wayfair.config")

# ── Authentication ────────────────────────────────────────────────────────────
WAYFAIR_EMAIL: str = os.getenv("WAYFAIR_EMAIL", "")
WAYFAIR_PASSWORD: str = os.getenv("WAYFAIR_PASSWORD", "")

# ── API Endpoints ─────────────────────────────────────────────────────────────
WAYFAIR_BASE_URL: str = os.getenv("WAYFAIR_BASE_URL", "https://www.wayfair.com")
WAYFAIR_GRAPHQL_PATH: str = "/wayhome/graphql"
WAYFAIR_AUTH_PATH: str = "/v/wayhome/wayhome_authentication/authenticate"
WAYFAIR_AUTH_TOKEN_PATH: str = "/v/wayhome/wayhome_authentication/authenticate_with_token"

# ── Hashes file ───────────────────────────────────────────────────────────────
_HASHES_DIR = Path(__file__).parent
HASHES_FILE: Path = _HASHES_DIR / "gql_hashes.json"

_DEFAULT_HASHES: dict[str, str] = {
    "GetAvailableJobsQueryV2": "9552adecb96184eb14097417bfddb695",
    "GetJobDetailsQueryV2": "22498828b7bb4e9366eddee089696eb1",
    "JobClaimMutationV2": "351542590863fe8489c5ca20c0095b8f",
    "GetScheduledJobsQueryV2": "c67ba4587c04389d9b736952fec2f120",
    "JobStatusQueryV2": "43f50e8ef5a894e697feb58ca39a5c62",
    "GetCancelledCompletedJobsQueryV2": "37eccd8bcd9668a5ac0487adbad4a05a",
    "JobCancelMutationV2": "ac99a9bf5c13c6a8448c205becefb42c",
    "JobUpdateStartTimeMutationV2": "b2916b8a63260a27699c65f6db2af1f4",
    "AssemblyInstructionsQueryV2": "283c52b4ab14fa8ca1c8abfcfb3c84c0",
    "GetJobPaymentMonthsQuery": "fb51eeeeac8851932731395a81cbe9da",
}


def load_gql_hashes() -> dict[str, str]:
    """Load hashes from JSON file, falling back to built-in defaults."""
    if HASHES_FILE.exists():
        try:
            data = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
            hashes = data.get("hashes", data)
            if isinstance(hashes, dict) and hashes:
                logger.info(
                    "Loaded %d GQL hashes from %s (APK %s)",
                    len(hashes),
                    HASHES_FILE.name,
                    data.get("apk_version", "unknown"),
                )
                return hashes
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s — using defaults", HASHES_FILE, exc)
    return dict(_DEFAULT_HASHES)


def save_gql_hashes(hashes: dict[str, str], apk_version: str = "unknown") -> None:
    """Persist hashes to JSON for future runs."""
    payload = {
        "apk_version": apk_version,
        "hashes": hashes,
    }
    try:
        HASHES_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved %d hashes to %s", len(hashes), HASHES_FILE.name)
    except OSError as exc:
        logger.error("Cannot save hashes: %s", exc)


GQL_HASHES: dict[str, str] = load_gql_hashes()

# ── Token settings ────────────────────────────────────────────────────────────
TOKEN_REFRESH_MARGIN_SECONDS: int = int(os.getenv("TOKEN_REFRESH_MARGIN", "300"))

# ── Polling ────────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS: float = float(os.getenv("POLL_INTERVAL_SECONDS", "2"))
CLAIM_RETRY_LIMIT: int = int(os.getenv("CLAIM_RETRY_LIMIT", "3"))

# ── HTTP Defaults ─────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))

# ── Headers (mimic Android app) ──────────────────────────────────────────────
USER_AGENT: str = (
    "WayfairServicePro/1.100.0 (Android; Build/1960400)"
)
X_GRAPH_TYPE_WAYHOME: str = "3"
X_GRAPH_TYPE_WAYFAIR: str = "1"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE: str = os.getenv("LOG_FILE", "wayfair_bot.log")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
