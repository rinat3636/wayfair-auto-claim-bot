"""
wayfair_bot.py — Auto-claim bot for Wayfair Service Pro.

Logic:
  1. Poll for available jobs every N seconds
  2. New job detected → IMMEDIATELY send claim (no delay)
  3. Multiple new jobs → claim ALL in parallel (asyncio.gather)
  4. Already claimed by someone else → skip forever
  5. Transient error → retry on next poll cycle only
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
    """
    Extract proJobRoundId from a job edge dict.

    Expected structure from API:
      {"id": 12345, "jobRound": {"id": ..., "desiredServiceDate": ...}, "status": "..."}
    The top-level "id" in an edge IS the proJobRoundId.
    """
    # Direct field (edge-level id = proJobRoundId)
    for key in ("id", "proJobRoundId", "jobId", "pro_job_round_id"):
        val = job.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    # Nested node structure
    node = job.get("node")
    if isinstance(node, dict):
        return _extract_job_id(node)
    return None


def _extract_job_date(job: dict[str, Any]) -> Optional[str]:
    """
    Extract a date string (YYYY-MM-DD) from the job.

    Expected: jobRound.desiredServiceDate
    """
    # Check jobRound.desiredServiceDate first (primary source)
    job_round = job.get("jobRound")
    if isinstance(job_round, dict):
        ds = job_round.get("desiredServiceDate")
        if isinstance(ds, str) and len(ds) >= 10:
            return ds[:10]

    # Direct fields fallback
    for key in ("desiredServiceDate", "date", "startDate", "scheduledDate", "serviceDate"):
        val = job.get(key)
        if isinstance(val, str) and len(val) >= 10:
            return val[:10]

    node = job.get("node")
    if isinstance(node, dict):
        return _extract_job_date(node)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class WayfairAutoClaimBot:
    """
    Monitors available jobs and INSTANTLY claims them.

    Flow:
        poll → detect new jobs → fire parallel claims → log results
    """

    def __init__(self, email: str, password: str) -> None:
        self.api = WayfairAPI(email, password)
        self.claimed_jobs: set[int] = set()
        self.failed_jobs: set[int] = set()
        self.running = False
        self._stats = {
            "polls": 0,
            "new_jobs_detected": 0,
            "claims_attempted": 0,
            "claims_success": 0,
            "claims_already_taken": 0,
            "claims_error": 0,
        }

    async def start(self) -> None:
        """Start the auto-claim loop."""
        logger.info("=" * 60)
        logger.info("Wayfair Service Pro Auto-Claim Bot")
        logger.info("Strategy: detect → INSTANT parallel claim")
        logger.info("Poll interval: %.1f s", POLL_INTERVAL_SECONDS)
        logger.info("=" * 60)

        if not await self.api.authenticate():
            logger.critical("Authentication failed — exiting")
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
                await self._poll_and_claim()
            except Exception:
                self._stats["claims_error"] += 1
                logger.exception("Unhandled error during poll cycle")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_and_claim(self) -> None:
        """Single poll cycle: get jobs → instantly claim all new ones in parallel."""
        self._stats["polls"] += 1
        detected_at = datetime.now(timezone.utc)

        jobs = await self.api.get_available_jobs()
        if not jobs:
            return

        # Filter: only jobs we haven't already claimed or permanently failed
        new_jobs: list[tuple[int, str]] = []
        for job in jobs:
            job_id = _extract_job_id(job)
            if job_id is None:
                continue
            if job_id in self.claimed_jobs or job_id in self.failed_jobs:
                continue
            job_date = _extract_job_date(job) or detected_at.strftime("%Y-%m-%d")
            new_jobs.append((job_id, job_date))

        if not new_jobs:
            return

        self._stats["new_jobs_detected"] += len(new_jobs)
        logger.info(
            "DETECTED %d new job(s) at %s — claiming NOW",
            len(new_jobs),
            detected_at.isoformat(),
        )

        # Fire ALL claims in parallel — speed is critical
        tasks = [
            self._claim_one(job_id, job_date, detected_at)
            for job_id, job_date in new_jobs
        ]
        await asyncio.gather(*tasks)

    async def _claim_one(
        self,
        job_id: int,
        date: str,
        detected_at: datetime,
    ) -> None:
        """Claim a single job as fast as possible."""
        self._stats["claims_attempted"] += 1

        # CLAIM FIRST — no delays, no extra logging before the request
        result = await self.api.claim_job(job_id, date)

        # Measure reaction time
        claimed_at = datetime.now(timezone.utc)
        reaction_ms = (claimed_at - detected_at).total_seconds() * 1000

        if result["success"]:
            self._stats["claims_success"] += 1
            self.claimed_jobs.add(job_id)
            logger.info(
                "✓ CLAIMED  id=%d  date=%s  reaction=%d ms",
                job_id,
                date,
                int(reaction_ms),
            )
        else:
            msg = result["message"]
            already_taken = "already" in msg.lower() or "claimed" in msg.lower()

            if already_taken:
                self._stats["claims_already_taken"] += 1
                self.failed_jobs.add(job_id)
                logger.warning(
                    "✗ TAKEN    id=%d  date=%s  reaction=%d ms  (someone was faster)",
                    job_id,
                    date,
                    int(reaction_ms),
                )
            else:
                self._stats["claims_error"] += 1
                # Transient error — don't add to failed_jobs, will retry next cycle
                logger.error(
                    "✗ ERROR    id=%d  date=%s  reaction=%d ms  msg=%s",
                    job_id,
                    date,
                    int(reaction_ms),
                    msg,
                )

    def _log_stats(self) -> None:
        logger.info("─── Session Statistics ───")
        for k, v in self._stats.items():
            logger.info("  %s: %s", k, v)


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
