"""
update_hashes.py — Extract GraphQL operation hashes from the latest Wayfair APK.

Downloads the APK, decompiles it with apktool, searches for operation hashes
in the smali output, and saves them to gql_hashes.json.

Usage:
    python -m wayfair.update_hashes                    # auto-download latest APK
    python -m wayfair.update_hashes /path/to/file.apk  # use local APK file

Requirements:
    apktool must be installed: sudo apt-get install apktool
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from wayfair.wayfair_config import HASHES_FILE, save_gql_hashes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("wayfair.update_hashes")

APK_DOWNLOAD_URL = (
    "https://d.apkpure.net/b/APK/com.wayfair.wayhome?version=latest"
)
KNOWN_OPERATIONS = [
    "GetAvailableJobsQueryV2",
    "GetJobDetailsQueryV2",
    "JobClaimMutationV2",
    "GetScheduledJobsQueryV2",
    "JobStatusQueryV2",
    "GetCancelledCompletedJobsQueryV2",
    "JobCancelMutationV2",
    "JobUpdateStartTimeMutationV2",
    "AssemblyInstructionsQueryV2",
    "GetJobPaymentMonthsQuery",
    "GetJobPaymentsInvoicedQueryV2",
    "GetQuestionnaireResponsesQueryV2",
    "ProductDetailsQueryV2",
    "SubmitQuestionnaireResponseQueryV2",
    "JobCheckInWithLocationMutationV2",
    "JobCheckInWithoutLocationMutationV2",
    "JobCheckOutWithLocationMutationV2",
    "JobCheckOutWithoutLocationMutationV2",
    "JobGeofenceEnterMutation",
    "JobGeofenceExitMutation",
]

_MD5_PATTERN = re.compile(r'const-string [a-z]\d+, "([0-9a-f]{32})"')
_OP_NAME_PATTERN = re.compile(r'\.source "(\w+(?:Query|Mutation)\w*)\.kt"')


def download_apk(dest: Path) -> bool:
    """Download the latest APK from APKPure."""
    logger.info("Downloading APK from APKPure…")
    try:
        with httpx.Client(
            timeout=120,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
        ) as client:
            resp = client.get(APK_DOWNLOAD_URL)
            if resp.status_code != 200:
                logger.error("Download failed: HTTP %d", resp.status_code)
                return False
            dest.write_bytes(resp.content)
            size_mb = len(resp.content) / 1024 / 1024
            logger.info("Downloaded %.1f MB → %s", size_mb, dest)
            return True
    except httpx.HTTPError as exc:
        logger.error("Download error: %s", exc)
        return False


def decompile_apk(apk_path: Path, output_dir: Path) -> bool:
    """Run apktool to decompile the APK."""
    if not shutil.which("apktool"):
        logger.error("apktool not found — install: sudo apt-get install apktool")
        return False
    logger.info("Decompiling %s…", apk_path.name)
    result = subprocess.run(
        ["apktool", "d", str(apk_path), "-o", str(output_dir), "-f"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error("apktool failed:\n%s", result.stderr[:1000])
        return False
    logger.info("Decompiled to %s", output_dir)
    return True


def extract_hashes(decompiled_dir: Path) -> dict[str, str]:
    """Walk smali files and pair operation names with their hashes."""
    hashes: dict[str, str] = {}
    smali_dirs = list(decompiled_dir.glob("smali*"))
    if not smali_dirs:
        logger.warning("No smali directories found")
        return hashes

    for smali_dir in smali_dirs:
        for smali_file in smali_dir.rglob("*.smali"):
            try:
                content = smali_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            op_match = _OP_NAME_PATTERN.search(content)
            if not op_match:
                continue

            op_name = op_match.group(1)
            md5_matches = _MD5_PATTERN.findall(content)
            if md5_matches:
                hashes[op_name] = md5_matches[0]

    logger.info("Extracted %d operation hashes", len(hashes))
    for name, h in sorted(hashes.items()):
        logger.info("  %s: %s", name, h)
    return hashes


def extract_apk_version(decompiled_dir: Path) -> str:
    """Try to read the app version from apktool.yml."""
    apktool_yml = decompiled_dir / "apktool.yml"
    if apktool_yml.exists():
        for line in apktool_yml.read_text(encoding="utf-8").splitlines():
            if "versionName" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip("'\"")
    return "unknown"


def run(apk_path: Optional[str] = None) -> bool:
    """Main entry point: download (if needed), decompile, extract hashes."""
    with tempfile.TemporaryDirectory(prefix="wayfair_hashes_") as tmpdir:
        tmp = Path(tmpdir)

        if apk_path:
            apk = Path(apk_path)
            if not apk.exists():
                logger.error("APK not found: %s", apk)
                return False
        else:
            apk = tmp / "wayfair.apk"
            if not download_apk(apk):
                return False

        decompiled = tmp / "decompiled"
        if not decompile_apk(apk, decompiled):
            return False

        hashes = extract_hashes(decompiled)
        if not hashes:
            logger.error("No hashes found — APK structure may have changed")
            return False

        version = extract_apk_version(decompiled)
        logger.info("APK version: %s", version)

        old_hashes: dict[str, str] = {}
        if HASHES_FILE.exists():
            try:
                data = json.loads(HASHES_FILE.read_text(encoding="utf-8"))
                old_hashes = data.get("hashes", {})
            except (json.JSONDecodeError, OSError):
                pass

        changed = {k: v for k, v in hashes.items() if old_hashes.get(k) != v}
        new_ops = {k: v for k, v in hashes.items() if k not in old_hashes}
        removed = {k for k in old_hashes if k not in hashes}

        if changed or new_ops or removed:
            logger.info("─── Changes detected ───")
            for k, v in changed.items():
                if k in old_hashes:
                    logger.info("  UPDATED  %s: %s → %s", k, old_hashes[k], v)
            for k, v in new_ops.items():
                logger.info("  NEW      %s: %s", k, v)
            for k in removed:
                logger.info("  REMOVED  %s (was %s)", k, old_hashes[k])
        else:
            logger.info("No hash changes — all operations up to date")

        save_gql_hashes(hashes, version)
        return True


def main() -> None:
    apk_path = sys.argv[1] if len(sys.argv) > 1 else None
    success = run(apk_path)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
