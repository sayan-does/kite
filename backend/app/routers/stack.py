from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.db import supabase
from app.services import github_client
from app.services.github_client import GitHubError, MANIFEST_NAMES
from app.services.manifest_parser import parse_manifest
from app.services.rate_limit import check_rate_limit
from app.services.version_gap import compute_version_gap, normalize_status
from app.services.whats_new import compose_whats_new

router = APIRouter()

TIMELINE_WINDOW_DAYS = 90
PROJECT_NAME_MAX_LEN = 80


def _normalize_project_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="project_name is required")
    if len(name) > PROJECT_NAME_MAX_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"project_name must be at most {PROJECT_NAME_MAX_LEN} characters",
        )
    return name


def _parse_manifest_or_http(filename: str, raw: bytes) -> list[tuple[str, str, str]]:
    try:
        return parse_manifest(filename, raw)
    except ValueError as e:
        detail = str(e)
        if "Unsupported" in detail:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported file type: {filename}. "
                    "Supported: package.json, requirements.txt, pyproject.toml, pom.xml"
                ),
            ) from e
        raise HTTPException(status_code=422, detail=detail) from e


def _upsert_parsed_deps(
    user_id: str,
    deps: list[tuple[str, str, str]],
    *,
    source: str,
    project_name: str,
    github_repo: str | None = None,
    github_path: str | None = None,
) -> dict:
    seen: set[tuple[str, str]] = set()
    unique_deps: list[tuple[str, str, str]] = []
    for ecosystem, pkg, ver in deps:
        key = (ecosystem, pkg)
        if key not in seen:
            seen.add(key)
            unique_deps.append((ecosystem, pkg, ver))

    rows = []
    for ecosystem, pkg, ver in unique_deps:
        row: dict = {
            "user_id": user_id,
            "project_name": project_name,
            "ecosystem": ecosystem,
            "package_name": pkg,
            "version": ver,
            "source": source,
        }
        if github_repo is not None:
            row["github_repo"] = github_repo
        if github_path is not None:
            row["github_path"] = github_path
        rows.append(row)

    if rows:
        supabase.table("tracked_dependencies").upsert(
            rows,
            on_conflict="user_id, project_name, ecosystem, package_name",
            ignore_duplicates=False,
        ).execute()

    return {
        "count": len(rows),
        "project_name": project_name,
        "dependencies": [
            {
                "project_name": project_name,
                "ecosystem": eco,
                "package_name": pkg,
                "version": ver,
            }
            for eco, pkg, ver in unique_deps
        ],
    }


def _require_github_token(x_github_token: str | None) -> str:
    token = (x_github_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="GitHub token required. Sign in with GitHub and reconnect if needed.",
        )
    return token


def _github_http(exc: GitHubError) -> HTTPException:
    status = exc.status_code if exc.status_code in (401, 403, 404) else 502
    return HTTPException(status_code=status, detail=exc.message)


@router.post("/stack/upload", status_code=201)
async def upload_manifest(
    file: UploadFile,
    project_name: str = Form(...),
    user_id: str = Depends(get_current_user_id),
):
    check_rate_limit(user_id)
    normalized_project = _normalize_project_name(project_name)

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    filename = file.filename or "unknown"
    deps = _parse_manifest_or_http(filename, raw)
    return _upsert_parsed_deps(
        user_id,
        deps,
        source="upload",
        project_name=normalized_project,
    )


class GitHubImportBody(BaseModel):
    repo: str = Field(..., min_length=3, description="owner/name")
    path: str = ""
    filename: str


@router.get("/stack/github/repos")
async def github_repos(
    user_id: str = Depends(get_current_user_id),
    x_github_token: str | None = Header(None, alias="X-GitHub-Token"),
):
    check_rate_limit(user_id)
    token = _require_github_token(x_github_token)
    try:
        repos = github_client.list_repos(token)
    except GitHubError as e:
        raise _github_http(e) from e
    return {"repos": repos}


@router.get("/stack/github/tree")
async def github_tree(
    repo: str = Query(..., min_length=3),
    path: str = Query(""),
    user_id: str = Depends(get_current_user_id),
    x_github_token: str | None = Header(None, alias="X-GitHub-Token"),
):
    check_rate_limit(user_id)
    token = _require_github_token(x_github_token)
    if "/" not in repo or repo.count("/") != 1:
        raise HTTPException(status_code=422, detail="repo must be owner/name")
    try:
        clean_path = github_client.normalize_repo_path(path)
        entries = github_client.list_directory(token, repo, clean_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except GitHubError as e:
        raise _github_http(e) from e
    return {"repo": repo, "path": clean_path, "entries": entries}


@router.post("/stack/github/import", status_code=201)
async def github_import(
    body: GitHubImportBody,
    user_id: str = Depends(get_current_user_id),
    x_github_token: str | None = Header(None, alias="X-GitHub-Token"),
):
    check_rate_limit(user_id)
    token = _require_github_token(x_github_token)

    if "/" not in body.repo or body.repo.count("/") != 1:
        raise HTTPException(status_code=422, detail="repo must be owner/name")

    filename = Path(body.filename).name
    if filename not in MANIFEST_NAMES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unsupported file type: {filename}. "
                "Supported: package.json, requirements.txt, pyproject.toml, pom.xml"
            ),
        )

    try:
        dir_path = github_client.normalize_repo_path(body.path)
        file_path = f"{dir_path}/{filename}" if dir_path else filename
        raw = github_client.get_file_content(token, body.repo, file_path)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except GitHubError as e:
        raise _github_http(e) from e

    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    deps = _parse_manifest_or_http(filename, raw)
    project_name = _normalize_project_name(body.repo.rsplit("/", 1)[-1])
    result = _upsert_parsed_deps(
        user_id,
        deps,
        source="github",
        project_name=project_name,
        github_repo=body.repo,
        github_path=file_path,
    )
    return {
        **result,
        "repo": body.repo,
        "path": file_path,
        "filename": filename,
        "project_name": project_name,
    }


class AddDepBody(BaseModel):
    ecosystem: str
    package_name: str
    version: str
    project_name: str


@router.get("/stack")
async def list_stack(user_id: str = Depends(get_current_user_id)):
    result = (
        supabase.table("tracked_dependencies")
        .select("id, project_name, ecosystem, package_name, version, source, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"dependencies": result.data or []}


def _disabled_citation_types(user_id: str) -> set[str]:
    prefs_resp = (
        supabase.table("citation_prefs")
        .select("source_type, enabled")
        .eq("user_id", user_id)
        .execute()
    )
    return {
        row["source_type"]
        for row in (prefs_resp.data or [])
        if not row["enabled"]
    }


def _project_sort_key(name: str) -> tuple:
    return (1 if name == "Uncategorized" else 0, name.lower())


@router.get("/stack/projects")
async def list_projects(user_id: str = Depends(get_current_user_id)):
    deps = (
        supabase.table("tracked_dependencies")
        .select("id, project_name, ecosystem, package_name, version")
        .eq("user_id", user_id)
        .execute()
    )
    if not deps.data:
        return {"projects": []}

    disabled_types = _disabled_citation_types(user_id)
    by_project: dict[str, dict[str, int]] = {}
    for dep in deps.data:
        project = dep.get("project_name") or "Uncategorized"
        item = _build_digest_item(dep, disabled_types)
        status = item["status"]
        if project not in by_project:
            by_project[project] = {
                "security": 0,
                "breaking": 0,
                "update_available": 0,
                "up_to_date": 0,
            }
        if status in by_project[project]:
            by_project[project][status] += 1
        else:
            by_project[project]["up_to_date"] += 1

    projects = [
        {
            "project_name": name,
            "dep_count": sum(counts.values()),
            "counts": counts,
        }
        for name, counts in sorted(by_project.items(), key=lambda kv: _project_sort_key(kv[0]))
    ]
    return {"projects": projects}


class RenameProjectBody(BaseModel):
    old_name: str
    new_name: str


# Fixed paths must be registered before `/stack/projects/{project_name:path}/...`
@router.patch("/stack/projects/rename")
async def rename_project(
    body: RenameProjectBody,
    user_id: str = Depends(get_current_user_id),
):
    """Rename via JSON body to avoid path-encoding / route-matching issues."""
    old_name = (body.old_name or "").strip()
    if not old_name:
        raise HTTPException(status_code=422, detail="old_name is required")

    new_name = _normalize_project_name(body.new_name)
    if old_name == new_name:
        return {"project_name": new_name, "renamed": 0}

    old_deps = (
        supabase.table("tracked_dependencies")
        .select("id, ecosystem, package_name")
        .eq("user_id", user_id)
        .eq("project_name", old_name)
        .execute()
    )
    if not old_deps.data:
        raise HTTPException(status_code=404, detail="Project not found")

    target_deps = (
        supabase.table("tracked_dependencies")
        .select("ecosystem, package_name")
        .eq("user_id", user_id)
        .eq("project_name", new_name)
        .execute()
    )
    if target_deps.data:
        old_keys = {(d["ecosystem"], d["package_name"]) for d in old_deps.data}
        new_keys = {(d["ecosystem"], d["package_name"]) for d in target_deps.data}
        overlap = old_keys & new_keys
        if overlap:
            raise HTTPException(
                status_code=409,
                detail="Cannot rename: some packages already exist in the target project name",
            )

    supabase.table("tracked_dependencies").update({
        "project_name": new_name,
    }).eq("user_id", user_id).eq("project_name", old_name).execute()

    return {"project_name": new_name, "renamed": len(old_deps.data)}


@router.delete("/stack/projects/by-name", status_code=204)
async def delete_project(
    project_name: str = Query(..., min_length=1),
    user_id: str = Depends(get_current_user_id),
):
    name = project_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="project_name is required")

    existing = (
        supabase.table("tracked_dependencies")
        .select("id")
        .eq("user_id", user_id)
        .eq("project_name", name)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Project not found")

    supabase.table("tracked_dependencies").delete().eq(
        "user_id", user_id
    ).eq("project_name", name).execute()


@router.get("/stack/projects/{project_name:path}/digest")
async def get_project_digest(
    project_name: str,
    page: int = Query(1, ge=1),
    user_id: str = Depends(get_current_user_id),
):
    project_name = unquote(project_name).strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="project_name is required")

    deps = (
        supabase.table("tracked_dependencies")
        .select("id, project_name, ecosystem, package_name, version")
        .eq("user_id", user_id)
        .eq("project_name", project_name)
        .execute()
    )
    if not deps.data:
        return {"items": [], "page": page, "has_next": False, "project_name": project_name}

    disabled_types = _disabled_citation_types(user_id)
    page_size = 50
    offset = (page - 1) * page_size
    all_items = [_build_digest_item(dep, disabled_types) for dep in deps.data]
    page_slice = all_items[offset: offset + page_size]
    has_next = len(all_items) > offset + page_size

    return {
        "items": page_slice,
        "page": page,
        "has_next": has_next,
        "project_name": project_name,
    }


@router.post("/stack", status_code=201)
async def add_dependency(
    body: AddDepBody,
    user_id: str = Depends(get_current_user_id),
):
    check_rate_limit(user_id)

    if body.ecosystem not in ("npm", "pip", "maven"):
        raise HTTPException(status_code=422, detail="Ecosystem must be npm, pip, or maven")

    project_name = _normalize_project_name(body.project_name)

    existing = (
        supabase.table("tracked_dependencies")
        .select("id")
        .eq("user_id", user_id)
        .eq("project_name", project_name)
        .eq("ecosystem", body.ecosystem)
        .eq("package_name", body.package_name)
        .execute()
    )
    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=409, detail="Duplicate dependency")

    result = (
        supabase.table("tracked_dependencies")
        .insert({
            "user_id": user_id,
            "project_name": project_name,
            "ecosystem": body.ecosystem,
            "package_name": body.package_name,
            "version": body.version,
            "source": "manual",
        })
        .execute()
    )
    return result.data[0]


@router.patch("/stack/{dep_id}")
async def update_dependency(
    dep_id: str,
    body: AddDepBody,
    user_id: str = Depends(get_current_user_id),
):
    existing = (
        supabase.table("tracked_dependencies")
        .select("id, user_id")
        .eq("id", dep_id)
        .execute()
    )
    if not existing.data or len(existing.data) == 0:
        raise HTTPException(status_code=404, detail="Dependency not found")
    if existing.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Dependency not found")

    project_name = _normalize_project_name(body.project_name)

    supabase.table("tracked_dependencies").update({
        "project_name": project_name,
        "ecosystem": body.ecosystem,
        "package_name": body.package_name,
        "version": body.version,
    }).eq("id", dep_id).execute()

    return {
        "id": dep_id,
        "project_name": project_name,
        "ecosystem": body.ecosystem,
        "package_name": body.package_name,
        "version": body.version,
    }


@router.delete("/stack/{dep_id}", status_code=204)
async def delete_dependency(
    dep_id: str,
    user_id: str = Depends(get_current_user_id),
):
    existing = (
        supabase.table("tracked_dependencies")
        .select("id, user_id")
        .eq("id", dep_id)
        .execute()
    )
    if not existing.data or len(existing.data) == 0:
        raise HTTPException(status_code=404, detail="Dependency not found")
    if existing.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Dependency not found")

    supabase.table("tracked_dependencies").delete().eq("id", dep_id).execute()


def _headline_update_type(updates: list[dict]) -> str | None:
    if not updates:
        return None
    priority = {"security": 0, "breaking": 1, "release": 2, "buzz": 3}
    ranked = sorted(updates, key=lambda u: priority.get(u.get("update_type", "buzz"), 9))
    top = ranked[0].get("update_type")
    return top


def _build_digest_item(dep: dict, disabled_types: set[str]) -> dict:
    ecosystem = dep["ecosystem"]
    package_name = dep["package_name"]
    tracked = dep["version"]

    cache = (
        supabase.table("package_registry_cache")
        .select("latest_version")
        .eq("ecosystem", ecosystem)
        .eq("package_name", package_name)
        .limit(1)
        .execute()
    )
    latest_version = cache.data[0]["latest_version"] if cache.data else None

    updates = (
        supabase.table("dependency_updates")
        .select("*")
        .eq("ecosystem", ecosystem)
        .eq("package_name", package_name)
        .order("published_at", desc=True)
        .execute()
        .data
        or []
    )

    timeline_flags = (
        supabase.table("package_version_timeline")
        .select("is_security, is_breaking")
        .eq("ecosystem", ecosystem)
        .eq("package_name", package_name)
        .execute()
        .data
        or []
    )
    has_security = any(r.get("is_security") for r in timeline_flags) or any(
        u.get("update_type") == "security" for u in updates
    )
    has_breaking = any(r.get("is_breaking") for r in timeline_flags) or any(
        u.get("update_type") == "breaking" for u in updates
    )

    if not latest_version and updates:
        latest_version = updates[0].get("version")

    update_type = _headline_update_type(updates)
    # Prefer non-buzz headline for the teaser row when higher-priority updates exist.
    headline = None
    if updates:
        priority = {"security": 0, "breaking": 1, "release": 2, "buzz": 3}
        ranked = sorted(updates, key=lambda u: priority.get(u.get("update_type", "buzz"), 9))
        headline = ranked[0]

    citations = (headline or {}).get("citations") or []
    if disabled_types:
        citations = [c for c in citations if c.get("type") not in disabled_types]

    status = normalize_status(
        tracked,
        latest_version,
        update_type,
        has_security=has_security,
        has_breaking=has_breaking,
    )
    version_gap = compute_version_gap(tracked, latest_version)

    return {
        "id": dep.get("id"),
        "project_name": dep.get("project_name") or "Uncategorized",
        "ecosystem": ecosystem,
        "package_name": package_name,
        "tracked_version": tracked,
        "latest_version": latest_version,
        "status": status,
        "version_gap": version_gap,
        "update": {
            "version": headline.get("version") if headline else latest_version,
            "update_type": headline.get("update_type") if headline else None,
            "summary": headline.get("summary") if headline else None,
            "citations": citations,
            "published_at": headline.get("published_at") if headline else None,
        } if headline else (
            {
                "version": latest_version,
                "update_type": "release" if status == "update_available" else None,
                "summary": None,
                "citations": [],
                "published_at": None,
            }
            if status == "update_available"
            else None
        ),
    }


@router.get("/stack/digest")
async def get_digest(
    page: int = Query(1, ge=1),
    user_id: str = Depends(get_current_user_id),
):
    deps = (
        supabase.table("tracked_dependencies")
        .select("id, project_name, ecosystem, package_name, version")
        .eq("user_id", user_id)
        .execute()
    )
    if not deps.data:
        return {"items": [], "page": page, "has_next": False}

    disabled_types = _disabled_citation_types(user_id)

    page_size = 20
    offset = (page - 1) * page_size
    all_items = [_build_digest_item(dep, disabled_types) for dep in deps.data]

    page_slice = all_items[offset: offset + page_size]
    has_next = len(all_items) > offset + page_size

    return {"items": page_slice, "page": page, "has_next": has_next}


@router.get("/stack/packages/{ecosystem}/{package_name:path}")
async def get_package_detail(
    ecosystem: str,
    package_name: str,
    user_id: str = Depends(get_current_user_id),
):
    package_name = unquote(package_name)
    if ecosystem not in ("npm", "pip", "maven"):
        raise HTTPException(status_code=422, detail="Ecosystem must be npm, pip, or maven")

    tracked = (
        supabase.table("tracked_dependencies")
        .select("version")
        .eq("user_id", user_id)
        .eq("ecosystem", ecosystem)
        .eq("package_name", package_name)
        .limit(1)
        .execute()
    )
    if not tracked.data:
        raise HTTPException(status_code=404, detail="Dependency not found")

    tracked_version = tracked.data[0]["version"]
    item = _build_digest_item(
        {"ecosystem": ecosystem, "package_name": package_name, "version": tracked_version},
        disabled_types=set(),
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=TIMELINE_WINDOW_DAYS)
    cutoff_iso = cutoff.isoformat()

    rows = (
        supabase.table("package_version_timeline")
        .select("version, published_at, summary, is_security, is_breaking, citations, ingested_at")
        .eq("ecosystem", ecosystem)
        .eq("package_name", package_name)
        .order("published_at", desc=True)
        .execute()
        .data
        or []
    )

    timeline = []
    for row in rows:
        published_at = row.get("published_at")
        ingested_at = row.get("ingested_at")
        ref = published_at or ingested_at
        if ref and ref < cutoff_iso:
            continue
        citations = row.get("citations") or []
        timeline.append({
            "version": row["version"],
            "published_at": published_at,
            "summary": row.get("summary"),
            "is_security": bool(row.get("is_security")),
            "is_breaking": bool(row.get("is_breaking")),
            "citations": citations,
        })

    # Stable sort: published_at desc, then version.
    timeline.sort(key=lambda r: (r.get("published_at") or "", r["version"]), reverse=True)

    headline_summary = (item.get("update") or {}).get("summary")
    summary = compose_whats_new(
        item["status"],
        tracked_version,
        item["latest_version"],
        item["version_gap"],
        headline_summary,
        timeline,
    )

    return {
        "ecosystem": ecosystem,
        "package_name": package_name,
        "tracked_version": tracked_version,
        "latest_version": item["latest_version"],
        "status": item["status"],
        "version_gap": item["version_gap"],
        "summary": summary,
        "timeline": timeline,
    }
