"""Versioned, approval-gated publisher for an already provisioned staging host.

This module writes only UTF-8 static website assets to a private, managed
staging directory. It does not modify DNS, Nginx, certificates or production.
The approval issuer MUST be a separate, owner-authenticated backend.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

from automation.site_engine import SiteError, _clean_project, _consume_approval, _safe_absolute_path

REVISION = re.compile(r"(?:bootstrap|[a-f0-9]{64})\Z")
FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
EXTENSIONS = frozenset({".html", ".css", ".js", ".json", ".txt", ".svg", ".xml"})
MAX_FILES = 64
MAX_BYTES = 1024 * 1024


def _release_files(files: dict[str, str]) -> tuple[dict[str, bytes], str]:
    if not isinstance(files, dict) or not 1 <= len(files) <= MAX_FILES:
        raise SiteError("Release must contain 1-64 files")
    if "index.html" not in files:
        raise SiteError("Release must include index.html")
    normalized = {}
    size = 0
    for path, value in files.items():
        if not isinstance(path, str) or not isinstance(value, str) or len(path) > 180:
            raise SiteError("Release paths and contents must be strings")
        pure = PurePosixPath(path)
        parts = path.split("/")
        if (pure.is_absolute() or "\\" in path or
            len(parts) > 5 or any(not p or p in {".", ".."} or p.startswith(".") or
            not FILENAME.fullmatch(p) for p in parts) or
            pure.suffix not in EXTENSIONS):
            raise SiteError("Unsafe release file path")
        if path in normalized:
            raise SiteError("Duplicate file")
        data = value.encode("utf-8")
        size += len(data)
        if size > MAX_BYTES:
            raise SiteError("Release exceeds 1 MiB total")
        normalized[path] = data
    manifest = json.dumps(
        {name: hashlib.sha256(data).hexdigest() for name, data in sorted(normalized.items())},
        sort_keys=True, separators=(",", ":"),
    )
    release_id = hashlib.sha256(manifest.encode("utf-8")).hexdigest()
    return normalized, release_id


def _revision(value: str) -> str:
    if not isinstance(value, str) or not REVISION.fullmatch(value):
        raise SiteError("Expected revision must be bootstrap or a 64-character SHA-256")
    return value


def _stage_path(project: str) -> Path:
    root = _safe_absolute_path(os.environ.get("BULQ_SITE_ROOT", "/var/www/bulq-sites"))
    return root / _clean_project(project) / "staging"


def plan_site_release(project: str, files: dict[str, str], expected_revision: str) -> dict:
    """Create a deterministic, non-mutating plan tied to a specific revision."""
    slug = _clean_project(project)
    expected = _revision(expected_revision)
    normalized, release_id = _release_files(files)
    stage = _stage_path(slug)
    details = {
        "action": "publish-staging-v1",
        "project": slug,
        "staging_path": str(stage),
        "expected_revision": expected,
        "release_id": release_id,
        "file_count": len(normalized),
        "total_bytes": sum(map(len, normalized.values())),
    }
    details["plan_id"] = hashlib.sha256(
        json.dumps(details, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    details["requires_approval"] = True
    details["production_live"] = False
    return details


def _managed_staging(stage: Path, project: str) -> None:
    if not stage.is_dir() or stage.is_symlink() or stage.parent.is_symlink():
        raise SiteError("Staging directory does not exist or is a symlink")
    marker = stage / ".bulq-managed.json"
    if marker.is_symlink() or not marker.is_file():
        raise SiteError("Refusing to publish to an unmanaged directory")
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SiteError("Invalid staging management marker") from exc
    if value.get("project") != project or value.get("version") != 1:
        raise SiteError("Staging marker belongs to a different project")
    releases = stage / "releases"
    if releases.is_symlink() or not releases.is_dir():
        raise SiteError("Missing managed release directory")


def _active_release(stage: Path) -> str:
    link = stage / "current"
    if not link.is_symlink():
        raise SiteError("Staging current must be a managed release symlink")
    target = os.readlink(link)
    if not target.startswith("releases/"):
        raise SiteError("Unmanaged current release target")
    version = _revision(target[len("releases/"):])
    revision_path = stage / "releases" / version
    if revision_path.is_symlink() or not revision_path.is_dir():
        raise SiteError("Active release directory is missing")
    return version


def site_release_status(project: str) -> dict:
    slug = _clean_project(project)
    stage = _stage_path(slug)
    _managed_staging(stage, slug)
    return {"project": slug, "active_revision": _active_release(stage),
            "production_live": False}


def publish_approved_site_release(project: str, files: dict[str, str],
                                  expected_revision: str, approval_token: str) -> dict:
    """Publish an approved static revision with an atomic switch.

    File writes use only a managed staging root. The process must be a restricted
    deployment identity, NOT a root process or web-facing HTTP service.
    """
    plan = plan_site_release(project, files, expected_revision)
    if os.geteuid() == 0:
        raise SiteError("Site release worker must not run as root")
    stage = Path(plan["staging_path"])
    _managed_staging(stage, plan["project"])
    if not (stage / "releases").is_dir():
        raise SiteError("Release directory missing")
    lock = stage / ".release.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "r+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            current = _active_release(stage)
            if current != expected_revision:
                raise SiteError("Staging changed since approval; re-plan the release")
            target = stage / "releases" / plan["release_id"]
            if target.exists() or target.is_symlink():
                raise SiteError("This release already exists; refusing to overwrite")
            # Single-use approval is checked only after all read-only preflight
            # and before any website content is created.
            _consume_approval(plan["plan_id"], approval_token)
            contents, _ = _release_files(files)
            temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=stage / "releases"))
            switched = False
            next_link = stage / (".next-" + plan["release_id"])
            try:
                for name, data in contents.items():
                    filename = temporary / name
                    filename.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    filename.write_bytes(data)
                    filename.chmod(0o644)
                # tempfile starts at 0700, inaccessible to the Nginx worker.
                temporary.chmod(0o755)
                temporary.rename(target)
                next_link.symlink_to("releases/" + plan["release_id"])
                os.replace(next_link, stage / "current")
                switched = True
            finally:
                if next_link.is_symlink():
                    next_link.unlink()
                if not switched:
                    if temporary.exists():
                        shutil.rmtree(temporary)
                    if target.is_dir() and not target.is_symlink():
                        shutil.rmtree(target)
            return {"status": "staging_published", "project": plan["project"],
                    "previous_revision": current, "active_revision": plan["release_id"],
                    "production_live": False}
    finally:
        # fdopen owns the descriptor after success or exception.
        pass
