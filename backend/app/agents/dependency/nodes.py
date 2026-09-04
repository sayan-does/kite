import re
from datetime import datetime, timedelta, timezone

import httpx
from langchain_core.messages import HumanMessage

from app.agents.common import groq_client, search
from app.db import supabase

TIMELINE_WINDOW_DAYS = 90
TIMELINE_MAX_VERSIONS = 50


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _within_window(published_at: datetime | None, cutoff: datetime) -> bool:
    if published_at is None:
        return True
    return published_at >= cutoff


def _upsert_timeline_rows(ecosystem: str, package_name: str, rows: list[dict]) -> None:
    if not rows:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = []
    for row in rows[:TIMELINE_MAX_VERSIONS]:
        payload.append({
            "ecosystem": ecosystem,
            "package_name": package_name,
            "version": row["version"],
            "published_at": row.get("published_at"),
            "summary": row.get("summary"),
            "is_security": bool(row.get("is_security", False)),
            "is_breaking": bool(row.get("is_breaking", False)),
            "citations": row.get("citations") or [],
            "ingested_at": now_iso,
        })
    supabase.table("package_version_timeline").upsert(
        payload,
        on_conflict="ecosystem, package_name, version",
    ).execute()


def _merge_timeline_flags(
    ecosystem: str,
    package_name: str,
    version: str,
    *,
    is_security: bool = False,
    is_breaking: bool = False,
    summary: str | None = None,
    citations: list | None = None,
) -> None:
    existing = (
        supabase.table("package_version_timeline")
        .select("*")
        .eq("ecosystem", ecosystem)
        .eq("package_name", package_name)
        .eq("version", version)
        .limit(1)
        .execute()
        .data
        or []
    )
    row = existing[0] if existing else {
        "ecosystem": ecosystem,
        "package_name": package_name,
        "version": version,
        "published_at": None,
        "summary": None,
        "is_security": False,
        "is_breaking": False,
        "citations": [],
    }
    merged_citations = list(row.get("citations") or [])
    seen = {c.get("url") for c in merged_citations if c.get("url")}
    for c in citations or []:
        url = c.get("url")
        if url and url not in seen:
            seen.add(url)
            merged_citations.append(c)

    supabase.table("package_version_timeline").upsert({
        "ecosystem": ecosystem,
        "package_name": package_name,
        "version": version,
        "published_at": row.get("published_at"),
        "summary": summary if summary is not None else row.get("summary"),
        "is_security": bool(row.get("is_security")) or is_security,
        "is_breaking": bool(row.get("is_breaking")) or is_breaking,
        "citations": merged_citations,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="ecosystem, package_name, version").execute()


async def _fetch_npm_history(pkg: str, cutoff: datetime) -> tuple[str | None, list[dict]]:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"https://registry.npmjs.org/{pkg}")
        if resp.status_code != 200:
            return None, []
        data = resp.json()
        latest = (data.get("dist-tags") or {}).get("latest")
        times = data.get("time") or {}
        rows = []
        for version, ts in times.items():
            if version in ("created", "modified"):
                continue
            published = _parse_iso(ts)
            if not _within_window(published, cutoff):
                continue
            rows.append({
                "version": version,
                "published_at": published.isoformat() if published else None,
            })
        rows.sort(key=lambda r: r.get("published_at") or "", reverse=True)
        return latest, rows[:TIMELINE_MAX_VERSIONS]


async def _fetch_pip_history(pkg: str, cutoff: datetime) -> tuple[str | None, list[dict]]:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(f"https://pypi.org/pypi/{pkg}/json")
        if resp.status_code != 200:
            return None, []
        data = resp.json()
        latest = (data.get("info") or {}).get("version")
        releases = data.get("releases") or {}
        rows = []
        for version, files in releases.items():
            published = None
            if files:
                # Prefer the earliest upload time for the version.
                times = [_parse_iso(f.get("upload_time_iso_8601") or f.get("upload_time")) for f in files]
                times = [t for t in times if t]
                if times:
                    published = min(times)
            if not _within_window(published, cutoff):
                continue
            rows.append({
                "version": version,
                "published_at": published.isoformat() if published else None,
            })
        rows.sort(key=lambda r: r.get("published_at") or "", reverse=True)
        return latest, rows[:TIMELINE_MAX_VERSIONS]


async def _fetch_maven_history(pkg: str, cutoff: datetime) -> tuple[str | None, list[dict]]:
    parts = pkg.split(":", 1)
    if len(parts) != 2:
        return None, []
    group_id, artifact_id = parts
    url = (
        f"https://search.maven.org/solrsearch/select"
        f"?q=g:{group_id}+AND+a:{artifact_id}&rows=20&core=gav&wt=json"
    )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            return None, []
        docs = resp.json().get("response", {}).get("docs", [])
        rows = []
        latest = None
        for doc in docs:
            version = doc.get("v") or doc.get("latestVersion")
            if not version:
                continue
            if latest is None:
                latest = version
            ts_ms = doc.get("timestamp")
            published = None
            if ts_ms is not None:
                published = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            if not _within_window(published, cutoff):
                continue
            rows.append({
                "version": version,
                "published_at": published.isoformat() if published else None,
            })
        rows.sort(key=lambda r: r.get("published_at") or "", reverse=True)
        return latest, rows[:TIMELINE_MAX_VERSIONS]


# ── 2.6 RegistryCheckNode ──────────────────────────────────────────────

async def registry_check_node(state: dict) -> dict:
    ecosystem = state["ecosystem"]
    pkg = state["package_name"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=TIMELINE_WINDOW_DAYS)
    latest = None
    history_rows: list[dict] = []

    try:
        if ecosystem == "npm":
            latest, history_rows = await _fetch_npm_history(pkg, cutoff)
        elif ecosystem == "pip":
            latest, history_rows = await _fetch_pip_history(pkg, cutoff)
        elif ecosystem == "maven":
            latest, history_rows = await _fetch_maven_history(pkg, cutoff)
    except Exception:
        latest = None
        history_rows = []

    # Fallback: latest-only endpoints if history fetch failed.
    if latest is None:
        try:
            if ecosystem == "npm":
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(f"https://registry.npmjs.org/{pkg}/latest")
                    if resp.status_code == 200:
                        latest = resp.json().get("version")
            elif ecosystem == "pip":
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(f"https://pypi.org/pypi/{pkg}/json")
                    if resp.status_code == 200:
                        latest = resp.json().get("info", {}).get("version")
            elif ecosystem == "maven":
                parts = pkg.split(":", 1)
                if len(parts) == 2:
                    group_id, artifact_id = parts
                    url = (
                        f"https://search.maven.org/solrsearch/select"
                        f"?q=g:{group_id}+AND+a:{artifact_id}&rows=1&wt=json"
                    )
                    async with httpx.AsyncClient(timeout=15) as client:
                        resp = await client.get(url)
                        if resp.status_code == 200:
                            docs = resp.json().get("response", {}).get("docs", [])
                            if docs:
                                latest = docs[0].get("latestVersion")
        except Exception:
            pass

    if history_rows:
        _upsert_timeline_rows(ecosystem, pkg, history_rows)
    elif latest:
        _upsert_timeline_rows(ecosystem, pkg, [{"version": latest, "published_at": None}])

    cached = (
        supabase.table("package_registry_cache")
        .select("latest_version")
        .eq("ecosystem", ecosystem)
        .eq("package_name", pkg)
        .execute()
    )
    cached_version = cached.data[0]["latest_version"] if cached.data else None

    new_version = None
    if latest and latest != cached_version:
        new_version = latest

    if latest:
        supabase.table("package_registry_cache").upsert({
            "ecosystem": ecosystem,
            "package_name": pkg,
            "latest_version": latest,
            "last_checked_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="ecosystem, package_name").execute()

    return {
        **state,
        "new_version": new_version,
        "latest_version": latest,
        "timeline_versions": [r["version"] for r in history_rows],
    }


# ── 2.7 VulnCheckNode ──────────────────────────────────────────────────

async def vuln_check_node(state: dict) -> dict:
    pkg = state["package_name"]
    eco = state["ecosystem"]
    eco_map = {"npm": "npm", "pip": "PyPI", "maven": "Maven"}

    purl = f"pkg:{eco_map.get(eco, eco)}/{pkg}"
    payload = {"version": state.get("latest_version", ""), "package": {"purl": purl}}

    findings = list(state.get("findings", []))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://api.osv.dev/v1/query", json=payload)
            if resp.status_code == 200:
                vulns = resp.json().get("vulns", [])
                for v in vulns:
                    summary = v.get("summary", v.get("id", "Unknown advisory"))
                    citations = [{"type": "official_docs", "url": f"https://osv.dev/{v['id']}", "title": v["id"]}]
                    findings.append({
                        "update_type": "security",
                        "summary": summary,
                        "citations": citations,
                    })
                    affected_version = state.get("latest_version") or state.get("new_version")
                    if affected_version:
                        _merge_timeline_flags(
                            eco,
                            pkg,
                            affected_version,
                            is_security=True,
                            summary=summary[:500],
                            citations=citations,
                        )
    except Exception:
        pass

    return {**state, "findings": findings}


# ── 2.8 ChangelogFetchNode ─────────────────────────────────────────────

async def changelog_fetch_node(state: dict) -> dict:
    new_version = state.get("new_version") or state.get("latest_version")
    if not new_version:
        return state

    pkg = state["package_name"]
    eco = state["ecosystem"]
    repo_url = _guess_repo_url(pkg)
    if not repo_url:
        return state

    findings = list(state.get("findings", []))
    feed_url = f"{repo_url.rstrip('/')}/releases.atom"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(feed_url)
            if resp.status_code != 200:
                return {**state, "findings": findings}
            text = resp.text
            entries = re.findall(r"<entry>.*?</entry>", text, re.DOTALL)
            for entry in entries:
                title_m = re.search(r"<title[^>]*>(.*?)</title>", entry)
                if not title_m:
                    continue
                title = title_m.group(1)
                version_hint = None
                for candidate in state.get("timeline_versions") or [new_version]:
                    if candidate in title or candidate.replace("v", "") in title:
                        version_hint = candidate
                        break
                if not version_hint and (new_version in title or new_version.replace("v", "") in title):
                    version_hint = new_version
                if not version_hint:
                    continue

                link_m = re.search(r'<link[^>]*href="([^"]+)"', entry)
                url = link_m.group(1) if link_m else ""
                summary_m = re.search(r"<content[^>]*>(.*?)</content>", entry, re.DOTALL)
                summary = summary_m.group(1).strip()[:500] if summary_m else f"Release {version_hint}"

                is_breaking = any(w in summary.lower() for w in ["breaking", "deprecat", "migration", "major"])
                citations = [{"type": "github", "url": url or repo_url, "title": title}]
                findings.append({
                    "update_type": "breaking" if is_breaking else "release",
                    "summary": summary,
                    "citations": citations,
                })
                _merge_timeline_flags(
                    eco,
                    pkg,
                    version_hint,
                    is_breaking=is_breaking,
                    summary=summary,
                    citations=citations,
                )
                if version_hint == new_version:
                    break
    except Exception:
        pass

    return {**state, "findings": findings}


def _guess_repo_url(pkg: str) -> str | None:
    if ":" in pkg:
        parts = pkg.split(":")
        return f"https://github.com/{parts[0]}/{parts[1]}"
    known = {
        "react": "https://github.com/facebook/react",
        "express": "https://github.com/expressjs/express",
        "typescript": "https://github.com/microsoft/TypeScript",
        "lodash": "https://github.com/lodash/lodash",
        "flask": "https://github.com/pallets/flask",
        "requests": "https://github.com/psf/requests",
        "click": "https://github.com/pallets/click",
        "django": "https://github.com/django/django",
    }
    return known.get(pkg)


# ── 2.9 ConditionalBuzzSearchNode ──────────────────────────────────────

async def conditional_buzz_node(state: dict) -> dict:
    findings = state.get("findings", [])
    if findings:
        return state

    pkg = state["package_name"]
    query = f"{pkg} latest news updates 2026"
    try:
        results = await search(query)
        summaries = []
        for r in results[:3]:
            summaries.append(f"- {r['title']}: {r['snippet'][:300]}")
        if summaries:
            findings = list(findings)
            findings.append({
                "update_type": "buzz",
                "summary": " | ".join(summaries),
                "citations": [{"type": "blog", "url": r["url"], "title": r["title"]} for r in results[:3]],
            })
    except Exception:
        pass

    return {**state, "findings": findings}


# ── 2.10 SummarizeNode ─────────────────────────────────────────────────

async def dep_summarize_node(state: dict) -> dict:
    findings = state.get("findings", [])
    if not findings:
        return {**state, "update": None}

    # Prefer security/breaking/release over buzz for the headline update.
    priority = {"security": 0, "breaking": 1, "release": 2, "buzz": 3}
    sorted_findings = sorted(findings, key=lambda f: priority.get(f.get("update_type", "buzz"), 9))

    top = sorted_findings[0]
    highest_type = top["update_type"]

    prompt = (
        f"You are a dependency update analyzer. Summarize the following findings for "
        f"{state['ecosystem']} package {state['package_name']} "
        f"(new version: {state.get('new_version', 'unknown')}). "
        f"Provide a concise 1-2 sentence summary.\n\nFindings:\n"
    )
    for f in sorted_findings[:3]:
        prompt += f"- [{f['update_type']}] {f['summary'][:500]}\n"

    msg = HumanMessage(content=prompt)
    try:
        response = groq_client.invoke([msg])
        summary = response.content.strip()
    except Exception:
        summary = top["summary"][:300]

    all_citations = []
    seen_urls = set()
    for f in sorted_findings:
        for c in f.get("citations", []):
            url = c.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_citations.append(c)

    update = {
        "summary": summary,
        "update_type": highest_type,
        "version": state.get("new_version") or state.get("latest_version", ""),
        "citations": all_citations,
    }

    return {**state, "update": update}


# ── 2.11 SaveUpdateNode ─────────────────────────────────────────────────

def save_update_node(state: dict) -> dict:
    update = state.get("update")
    if not update:
        return state

    supabase.table("dependency_updates").upsert({
        "ecosystem": state["ecosystem"],
        "package_name": state["package_name"],
        "version": update["version"],
        "update_type": update["update_type"],
        "summary": update["summary"],
        "citations": update.get("citations", []),
    }, on_conflict="ecosystem, package_name, version, update_type").execute()

    return state
