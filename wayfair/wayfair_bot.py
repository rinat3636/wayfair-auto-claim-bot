"""
wayfair_bot.py — Auto-claim bot for Wayfair Service Pro.

Continuously polls for new available jobs and instantly claims them.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone
from typing import Any, Optional

from wayfair.wayfair_api import WayfairAPI
from wayfair.wayfair_config import (
    LOG_FILE,
    LOG_LEVEL,
    POLL_INTERVAL_SECONDS,
    WAYFAIR_EMAIL,
    WAYFAIR_PASSWORD,
)

logger = logging.getLogger("wayfair.bot")


def _extract_job_id(job: dict[str, Any]) -> Optional[int]:
    """Extract proJobRoundId from a job dict, handling nested structures."""
    for key in ("proJobRoundId", "id", "jobId", "pro_job_round_id"):
        val = job.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    node = job.get("node")
    if isinstance(node, dict):
        return _extract_job_id(node)
    return None


def _extract_job_date(job: dict[str, Any]) -> Optional[str]:
    """Extract a date string (YYYY-MM-DD) from the job."""
    for key in ("date", "startDate", "scheduledDate", "serviceDate", "start_date"):
        val = job.get(key)
        if isinstance(val, str) and len(val) >= 10:
            return val[:10]
    node = job.get("node")
    if isinstance(node, dict):
        return _extract_job_date(node)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class WayfairAutoClaimBot:
    """Monitors available jobs and auto-claims them."""

    def __init__(self, email: str, password: str) -> None:
        self.api = WayfairAPI(email, password)
        self.seen_jobs: set[int] = set()
        self.claimed_jobs: set[int] = set()
        self.running = False
        self._stats = {
            "polls": 0,
            "jobs_seen": 0,
            "claims_attempted": 0,
            "claims_success": 0,
            "claims_failed": 0,
            "errors": 0,
        }

    async def start(self) -> None:
        """Start the auto-claim loop."""
        logger.info("=" * 60)
        logger.info("Wayfair Service Pro Auto-Claim Bot starting…")
        logger.info("Poll interval: %.1f s", POLL_INTERVAL_SECONDS)
        logger.info("=" * 60)

        if not await self.api.authenticate():
            logger.critical("Initial authentication failed — exiting")
            return

        self.running = True
        try:
            await self._poll_loop()
        except asyncio.CancelledError:
            logger.info("Bot cancelled")
        finally:
            self.running = False
            await self.api.close()
            self._log_stats()
            logger.info("Bot stopped")

    async def _poll_loop(self) -> None:
        while self.running:
            try:
                await self._poll_once()
            except Exception:
                self._stats["errors"] += 1
                logger.exception("Unhandled error during poll")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_once(self) -> None:
        self._stats["polls"] += 1
        ts_start = datetime.now(timezone.utc)

        jobs = await self.api.get_available_jobs()
        if not jobs:
            return

        for job in jobs:
            job_id = _extract_job_id(job)
            if job_id is None:
                logger.debug("Skipping job without parseable ID: %s", job)
                continue

            if job_id in self.claimed_jobs:
                continue

            self._stats["jobs_seen"] += 1
            job_date = _extract_job_date(job)

            if job_id not in self.seen_jobs:
                self.seen_jobs.add(job_id)
                logger.info(
                    "NEW JOB  id=%d  date=%s  appeared=%s",
                    job_id,
                    job_date,
                    ts_start.isoformat(),
                )

            await self._try_claim(job_id, job_date, ts_start)

    async def _try_claim(
        self,
        job_id: int,
        date: Optional[str],
        appeared_at: datetime,
    ) -> None:
        if date is None:
            date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        self._stats["claims_attempted"] += 1
        claim_ts = datetime.now(timezone.utc)
        logger.info("CLAIM ATTEMPT  id=%d  date=%s  ts=%s", job_id, date, claim_ts.isoformat())

        result = await self.api.claim_job(job_id, date)
        elapsed_ms = (datetime.now(timezone.utc) - appeared_at).total_seconds() * 1000

        if result["success"]:
            self._stats["claims_success"] += 1
            self.claimed_jobs.add(job_id)
            logger.info(
                "CLAIM SUCCESS  id=%d  reaction=%.0f ms  msg=%s",
                job_id,
                elapsed_ms,
                result["message"],
            )
        else:
            self._stats["claims_failed"] += 1
            logger.warning(
                "CLAIM FAILED   id=%d  reaction=%.0f ms  msg=%s",
                job_id,
                elapsed_ms,
                result["message"],
            )
            if "already" in result["message"].lower():
                self.claimed_jobs.add(job_id)

    def _log_stats(self) -> None:
        logger.info("─── Session Statistics ───")
        for k, v in self._stats.items():
            logger.info("  %s: %s", k, v)
        logger.info("  unique_jobs_seen: %d", len(self.seen_jobs))
        logger.info("  jobs_claimed: %d", len(self.claimed_jobs))


def setup_logging() -> None:
    """Configure console + file logging."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)

    if LOG_FILE:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)


async def _main() -> None:
    if not WAYFAIR_EMAIL or not WAYFAIR_PASSWORD:
        print(
            "ERROR: Set WAYFAIR_EMAIL and WAYFAIR_PASSWORD environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)

    setup_logging()
    bot = WayfairAutoClaimBot(WAYFAIR_EMAIL, WAYFAIR_PASSWORD)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: setattr(bot, "running", False))

    await bot.start()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
