"""Minimal GitHub Contents API client for stack manifest import."""

from __future__ import annotations

import base64
from typing import Any

import httpx

GITHUB_API = "https://api.github.com"
MANIFEST_NAMES = frozenset(
    {"package.json", "requirements.txt", "pyproject.toml", "pom.xml"}
)


class GitHubError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


def normalize_repo_path(path: str | None) -> str:
    """Normalize a repo-relative path; empty means repo root."""
    if not path:
        return ""
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = cleaned.strip("/")
    if ".." in cleaned.split("/"):
        raise ValueError("Path must not contain '..'")
    return cleaned


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def list_repos(token: str, *, per_page: int = 100) -> list[dict[str, Any]]:
    url = f"{GITHUB_API}/user/repos"
    params = {
        "per_page": per_page,
        "sort": "updated",
        "affiliation": "owner,collaborator,organization_member",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_headers(token), params=params)
    if resp.status_code == 401:
        raise GitHubError(401, "Invalid or expired GitHub token")
    if resp.status_code >= 400:
        raise GitHubError(resp.status_code, resp.text[:300] or "GitHub API error")
    data = resp.json()
    return [
        {
            "full_name": r["full_name"],
            "private": r.get("private", False),
            "default_branch": r.get("default_branch") or "main",
            "description": r.get("description"),
        }
        for r in data
    ]


def list_directory(
    token: str,
    repo: str,
    path: str = "",
    *,
    ref: str | None = None,
) -> list[dict[str, Any]]:
    clean_path = normalize_repo_path(path)
    url = f"{GITHUB_API}/repos/{repo}/contents"
    if clean_path:
        url = f"{url}/{clean_path}"
    params = {}
    if ref:
        params["ref"] = ref

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_headers(token), params=params or None)
    if resp.status_code == 404:
        raise GitHubError(404, f"Path not found: {clean_path or '/'}")
    if resp.status_code == 401:
        raise GitHubError(401, "Invalid or expired GitHub token")
    if resp.status_code == 403:
        raise GitHubError(403, "GitHub access denied for this repository")
    if resp.status_code >= 400:
        raise GitHubError(resp.status_code, resp.text[:300] or "GitHub API error")

    payload = resp.json()
    if isinstance(payload, dict):
        # Single file response when path points at a file
        payload = [payload]
    if not isinstance(payload, list):
        raise GitHubError(502, "Unexpected GitHub contents response")

    entries = []
    for item in payload:
        name = item.get("name") or ""
        entry_type = item.get("type") or "file"
        entries.append(
            {
                "name": name,
                "path": item.get("path") or name,
                "type": entry_type,
                "is_manifest": entry_type == "file" and name in MANIFEST_NAMES,
            }
        )
    entries.sort(key=lambda e: (0 if e["is_manifest"] else 1, e["type"] != "dir", e["name"].lower()))
    return entries


def get_file_content(
    token: str,
    repo: str,
    path: str,
    *,
    ref: str | None = None,
) -> bytes:
    clean_path = normalize_repo_path(path)
    if not clean_path:
        raise ValueError("File path is required")

    url = f"{GITHUB_API}/repos/{repo}/contents/{clean_path}"
    params = {}
    if ref:
        params["ref"] = ref

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_headers(token), params=params or None)
    if resp.status_code == 404:
        raise GitHubError(404, f"File not found: {clean_path}")
    if resp.status_code == 401:
        raise GitHubError(401, "Invalid or expired GitHub token")
    if resp.status_code == 403:
        raise GitHubError(403, "GitHub access denied for this repository")
    if resp.status_code >= 400:
        raise GitHubError(resp.status_code, resp.text[:300] or "GitHub API error")

    data = resp.json()
    if isinstance(data, list):
        raise GitHubError(400, "Path is a directory, not a file")
    if data.get("type") != "file":
        raise GitHubError(400, "Path is not a file")

    encoding = data.get("encoding")
    content = data.get("content")
    if encoding == "base64" and isinstance(content, str):
        return base64.b64decode(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    raise GitHubError(502, "Could not decode file content from GitHub")
