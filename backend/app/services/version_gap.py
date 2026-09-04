"""Semver-ish version comparison helpers for My Stack digest/detail."""
from __future__ import annotations

import re
from typing import Any


_VERSION_RE = re.compile(
    r"^v?(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.(?P<patch>\d+))?",
    re.IGNORECASE,
)


def parse_semver_parts(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    match = _VERSION_RE.match(version.strip())
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor") or 0),
        int(match.group("patch") or 0),
    )


def compute_version_gap(tracked: str | None, latest: str | None) -> dict[str, Any]:
    tracked = tracked or ""
    latest = latest or ""
    t_parts = parse_semver_parts(tracked)
    l_parts = parse_semver_parts(latest)
    if not t_parts or not l_parts:
        return {"kind": "unknown", "tracked": tracked, "latest": latest}

    if l_parts == t_parts:
        kind = "none"
    elif l_parts[0] != t_parts[0]:
        kind = "major"
    elif l_parts[1] != t_parts[1]:
        kind = "minor"
    else:
        kind = "patch"

    return {"kind": kind, "tracked": tracked, "latest": latest}


def versions_differ(tracked: str | None, latest: str | None) -> bool:
    if not tracked or not latest:
        return False
    t_parts = parse_semver_parts(tracked)
    l_parts = parse_semver_parts(latest)
    if t_parts and l_parts:
        return t_parts != l_parts
    return tracked.strip().lstrip("vV") != latest.strip().lstrip("vV")


def normalize_status(
    tracked: str | None,
    latest: str | None,
    update_type: str | None,
    *,
    has_security: bool = False,
    has_breaking: bool = False,
) -> str:
    """Priority: security > breaking > update_available > up_to_date. Buzz never wins."""
    if has_security or update_type == "security":
        return "security"
    if has_breaking or update_type == "breaking":
        return "breaking"
    if update_type == "release" or versions_differ(tracked, latest):
        return "update_available"
    return "up_to_date"


STATUS_SORT_ORDER = {
    "security": 0,
    "breaking": 1,
    "update_available": 2,
    "up_to_date": 3,
}
