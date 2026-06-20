"""
wayfair_api.py — HTTP client for the Wayfair Service Pro GraphQL API.

Handles authentication, automatic token refresh, hash validation,
and all GraphQL operations needed for the auto-claim bot.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from wayfair.wayfair_config import (
    CLAIM_RETRY_LIMIT,
    GQL_HASHES,
    REQUEST_TIMEOUT,
    TOKEN_REFRESH_MARGIN_SECONDS,
    USER_AGENT,
    WAYFAIR_AUTH_PATH,
    WAYFAIR_AUTH_TOKEN_PATH,
    WAYFAIR_BASE_URL,
    WAYFAIR_GRAPHQL_PATH,
    X_GRAPH_TYPE_WAYHOME,
)

logger = logging.getLogger("wayfair.api")


def _decode_jwt_exp(token: str) -> Optional[float]:
    """Extract expiration timestamp from a JWT token (without verification)."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return float(exp)
    except (json.JSONDecodeError, ValueError, IndexError, UnicodeDecodeError):
        pass
    return None


class WayfairAPI:
    """Async HTTP client for Wayfair Service Pro API with auto-refresh."""

    def __init__(self, email: str, password: str) -> None:
        self.email = email
        self.password = password
        self.access_token: Optional[str] = None
        self.token_obtained_at: float = 0.0
        self.token_expires_at: float = 0.0
        self.device_guid: str = str(uuid.uuid4())
        self._client: Optional[httpx.AsyncClient] = None
        self._auth_lock = asyncio.Lock()
        self._consecutive_hash_errors: int = 0

    # ── HTTP session ──────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=WAYFAIR_BASE_URL,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Token management ──────────────────────────────────────────────────

    def _store_token(self, token: str) -> None:
        self.access_token = token
        self.token_obtained_at = time.time()
        exp = _decode_jwt_exp(token)
        if exp and exp > self.token_obtained_at:
            self.token_expires_at = exp
            ttl = exp - self.token_obtained_at
            logger.info("Token stored (expires in %.0f min)", ttl / 60)
        else:
            self.token_expires_at = self.token_obtained_at + 3600
            logger.info("Token stored (no exp claim — assuming 60 min TTL)")

    def _token_needs_refresh(self) -> bool:
        if not self.access_token:
            return True
        now = time.time()
        if self.token_expires_at > 0:
            return now >= (self.token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS)
        return (now - self.token_obtained_at) > 2700

    # ── Authentication ────────────────────────────────────────────────────

    def _extract_token(self, data: dict[str, Any]) -> Optional[str]:
        """Find a token in auth response, trying common key names."""
        for key in ("token", "access_token", "authToken", "jwt"):
            val = data.get(key)
            if isinstance(val, str) and len(val) > 20:
                return val
        for key, val in data.items():
            if "token" in key.lower() and isinstance(val, str) and len(val) > 20:
                return val
        return None

    async def authenticate(self) -> bool:
        """Authenticate with email/password and obtain a Bearer token."""
        async with self._auth_lock:
            if self.access_token and not self._token_needs_refresh():
                return True
            return await self._do_authenticate()

    async def _do_authenticate(self) -> bool:
        client = self._get_client()
        payload = {
            "email_address": self.email,
            "password": self.password,
            "device_gu_id": self.device_guid,
        }
        txid = str(uuid.uuid4())
        headers = {"X-PARENT-TXID": txid}
        try:
            resp = await client.post(WAYFAIR_AUTH_PATH, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                token = self._extract_token(data)
                if token:
                    self._store_token(token)
                    return True
                logger.error("Auth response missing token: %s", list(data.keys()))
                return False
            logger.error("Auth failed HTTP %d: %s", resp.status_code, resp.text[:500])
            return False
        except httpx.HTTPError as exc:
            logger.error("Auth request error: %s", exc)
            return False

    async def refresh_token(self) -> bool:
        """Try to refresh the token using authenticate_with_token, falling back to full auth."""
        async with self._auth_lock:
            if not self._token_needs_refresh():
                return True

            if self.access_token:
                ok = await self._do_refresh_with_token()
                if ok:
                    return True
                logger.warning("Token refresh failed — falling back to full auth")

            return await self._do_authenticate()

    async def _do_refresh_with_token(self) -> bool:
        client = self._get_client()
        payload = {
            "email_address": self.email,
            "device_gu_id": self.device_guid,
        }
        txid = str(uuid.uuid4())
        headers = {
            "X-PARENT-TXID": txid,
            "Authorization": f"Bearer {self.access_token}",
        }
        try:
            resp = await client.post(WAYFAIR_AUTH_TOKEN_PATH, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                token = self._extract_token(data)
                if token:
                    self._store_token(token)
                    logger.info("Token refreshed via authenticate_with_token")
                    return True
            logger.warning(
                "authenticate_with_token HTTP %d: %s",
                resp.status_code,
                resp.text[:300],
            )
            return False
        except httpx.HTTPError as exc:
            logger.warning("Token refresh request error: %s", exc)
            return False

    async def ensure_authenticated(self) -> bool:
        """Ensure we have a valid token, refreshing proactively if needed."""
        if not self._token_needs_refresh():
            return True
        logger.info("Token expiring soon — refreshing…")
        return await self.refresh_token()

    # ── GraphQL helpers ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"x-graph-type": X_GRAPH_TYPE_WAYHOME}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _is_persisted_query_error(self, data: dict[str, Any]) -> bool:
        """Check if response indicates the persisted query hash is unknown."""
        errors = data.get("errors", [])
        for err in errors:
            msg = str(err.get("message", "")).lower()
            code = str(err.get("extensions", {}).get("code", "")).lower()
            if "persistedquerynotfound" in msg or "persistedquerynotfound" in code:
                return True
            if "persisted" in msg and "not found" in msg:
                return True
        return False

    async def _gql_request(
        self,
        operation_name: str,
        variables: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Execute a persisted GraphQL query/mutation."""
        await self.ensure_authenticated()
        client = self._get_client()
        query_hash = GQL_HASHES.get(operation_name)
        if not query_hash:
            logger.error("Unknown operation: %s", operation_name)
            return None

        body: dict[str, Any] = {
            "operationName": operation_name,
            "variables": variables,
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": query_hash,
                },
            },
        }
        try:
            resp = await client.post(
                WAYFAIR_GRAPHQL_PATH,
                json=body,
                headers=self._auth_headers(),
            )
            if resp.status_code == 401:
                logger.warning("Token rejected (401) — refreshing…")
                if await self.refresh_token():
                    resp = await client.post(
                        WAYFAIR_GRAPHQL_PATH,
                        json=body,
                        headers=self._auth_headers(),
                    )
                else:
                    return None
            if resp.status_code != 200:
                logger.error(
                    "GraphQL %s HTTP %d: %s",
                    operation_name,
                    resp.status_code,
                    resp.text[:500],
                )
                return None

            data = resp.json()

            if self._is_persisted_query_error(data):
                self._consecutive_hash_errors += 1
                logger.error(
                    "HASH OUTDATED  operation=%s  hash=%s  "
                    "consecutive_errors=%d  — update hashes with: "
                    "python -m wayfair.update_hashes",
                    operation_name,
                    query_hash,
                    self._consecutive_hash_errors,
                )
                return None

            if "errors" in data and not self._is_persisted_query_error(data):
                self._consecutive_hash_errors = 0
                logger.warning("GraphQL errors in %s: %s", operation_name, data["errors"])

            return data
        except httpx.HTTPError as exc:
            logger.error("GraphQL request error (%s): %s", operation_name, exc)
            return None

    # ── Public API methods ────────────────────────────────────────────────

    async def get_available_jobs(self, start_date: Optional[str] = None) -> list[dict[str, Any]]:
        """Fetch available jobs starting from a given date (YYYY-MM-DD)."""
        if start_date is None:
            start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = await self._gql_request("GetAvailableJobsQueryV2", {"startDate": start_date})
        if result is None:
            return []
        data = result.get("data", {})
        jobs: list[dict[str, Any]] = []
        for key, val in data.items():
            if isinstance(val, list):
                jobs.extend(val)
            elif isinstance(val, dict):
                nested = val.get("jobs") or val.get("edges") or val.get("nodes")
                if isinstance(nested, list):
                    jobs.extend(nested)
                elif val.get("proJobRoundId") or val.get("id"):
                    jobs.append(val)
        if not jobs and data:
            logger.debug("get_available_jobs raw data keys: %s", list(data.keys()))
        return jobs

    async def get_job_details(self, pro_job_round_id: int) -> Optional[dict[str, Any]]:
        """Fetch detailed information about a single job."""
        result = await self._gql_request(
            "GetJobDetailsQueryV2", {"proJobRoundId": pro_job_round_id}
        )
        if result is None:
            return None
        return result.get("data")

    async def claim_job(self, pro_job_round_id: int, date: str) -> dict[str, Any]:
        """
        Attempt to claim a job.

        Returns a dict with keys:
            success (bool), message (str), data (optional dict)
        """
        for attempt in range(1, CLAIM_RETRY_LIMIT + 1):
            result = await self._gql_request(
                "JobClaimMutationV2",
                {"proJobRoundId": pro_job_round_id, "date": date},
            )
            if result is None:
                if attempt < CLAIM_RETRY_LIMIT:
                    await asyncio.sleep(0.5)
                    continue
                return {"success": False, "message": "No response from server"}

            errors = result.get("errors")
            if errors:
                error_msg = errors[0].get("message", str(errors[0])) if errors else "unknown"
                already_claimed = any(
                    "already" in str(e).lower() or "claimed" in str(e).lower() for e in errors
                )
                if already_claimed:
                    return {
                        "success": False,
                        "message": f"Job already claimed: {error_msg}",
                    }
                logger.warning(
                    "Claim attempt %d/%d error: %s", attempt, CLAIM_RETRY_LIMIT, error_msg
                )
                if attempt < CLAIM_RETRY_LIMIT:
                    await asyncio.sleep(0.5)
                    continue
                return {"success": False, "message": error_msg}

            return {
                "success": True,
                "message": "Job claimed successfully",
                "data": result.get("data"),
            }
        return {"success": False, "message": "Claim failed after retries"}

    async def get_scheduled_jobs(self, from_date: Optional[str] = None) -> list[dict[str, Any]]:
        """Fetch scheduled (already claimed) jobs."""
        if from_date is None:
            from_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = await self._gql_request(
            "GetScheduledJobsQueryV2", {"fromDate": from_date}
        )
        if result is None:
            return []
        data = result.get("data", {})
        jobs: list[dict[str, Any]] = []
        for val in data.values():
            if isinstance(val, list):
                jobs.extend(val)
        return jobs
