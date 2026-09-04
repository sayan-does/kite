import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_manifest(filename: str, raw: bytes) -> list[tuple[str, str, str]]:
    name = Path(filename).name

    if name == "package.json":
        return _parse_package_json(raw)
    if name == "requirements.txt":
        return _parse_requirements_txt(raw)
    if name in ("pyproject.toml",):
        return _parse_pyproject_toml(raw)
    if name == "pom.xml":
        return _parse_pom_xml(raw)

    raise ValueError(f"Unsupported manifest file: {filename}")


def _parse_package_json(raw: bytes) -> list[tuple[str, str, str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Invalid package.json: not valid JSON")
    deps = []
    for section in ("dependencies", "devDependencies"):
        for pkg, ver in (data.get(section) or {}).items():
            deps.append(("npm", pkg, _clean_version(ver)))
    return deps


def _parse_requirements_txt(raw: bytes) -> list[tuple[str, str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File must be UTF-8 encoded")
    deps = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            continue
        if _is_editable_line(line):
            continue

        pkg, ver = _parse_pep508_line(line)
        if pkg:
            deps.append(("pip", pkg.lower(), _clean_version(ver) if ver else "*"))
    return deps


def _is_editable_line(line: str) -> bool:
    return bool(re.match(r"^\s*-[ef]\s+", line))


_PEP508_PATTERN = re.compile(
    r"^"
    r"([a-zA-Z0-9][a-zA-Z0-9_.-]*)"
    r"(?:\[[^\]]+\])?"
    r"\s*"
    r"((?:>=|<=|!=|==|~=|>|<)\s*[a-zA-Z0-9_.*]+"
    r"(?:\s*,\s*(?:>=|<=|!=|==|~=|>|<)\s*[a-zA-Z0-9_.*]+)*)?"
    r"\s*"
    r"(?:;\s*.+)?"
    r"$"
)


def _parse_pep508_line(line: str) -> tuple[str | None, str | None]:
    m = _PEP508_PATTERN.match(line)
    if m:
        pkg = m.group(1)
        ver = m.group(2)
        if ver:
            ver = ver.replace(" ", "")
        return pkg, ver
    m2 = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9_.-]*)\s*$", line)
    if m2:
        return m2.group(1), None
    return None, None


def _parse_pyproject_toml(raw: bytes) -> list[tuple[str, str, str]]:
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib
        except ImportError:
            raise ValueError("tomllib/tomli not available for parsing pyproject.toml")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("File must be UTF-8 encoded")
    try:
        data = tomllib.loads(text)
    except Exception:
        raise ValueError("Invalid pyproject.toml: not valid TOML")
    deps = []

    for dep_str in data.get("project", {}).get("dependencies") or []:
        pkg, ver = _parse_pep508_line(dep_str)
        if pkg:
            deps.append(("pip", pkg.lower(), _clean_version(ver) if ver else "*"))

    if not deps:
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies") or {}
        for pkg, constraint in poetry_deps.items():
            if pkg.lower() == "python":
                continue
            if isinstance(constraint, str):
                ver = _clean_version(constraint) if constraint not in ("*", "") else "*"
            elif isinstance(constraint, dict):
                ver = _clean_version(constraint.get("version", "*"))
                extras = constraint.get("extras")
                if extras:
                    pass
            else:
                ver = "*"
            deps.append(("pip", pkg.lower(), ver))

    return deps


def _parse_pom_xml(raw: bytes) -> list[tuple[str, str, str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError("Invalid pom.xml: not valid XML")
    ns = re.sub(r"\s.*", "", root.tag).replace("project", "").strip()
    ns = "{" + ns + "}" if ns else ""
    deps = []
    for dep in root.findall(f".//{ns}dependencies/{ns}dependency"):
        group_id = dep.findtext(f"{ns}groupId", "")
        artifact_id = dep.findtext(f"{ns}artifactId", "")
        version = dep.findtext(f"{ns}version", "")
        if group_id and artifact_id:
            pkg = f"{group_id}:{artifact_id}"
            deps.append(("maven", pkg, version or "*"))
    return deps


def _clean_version(ver: str) -> str:
    return ver.strip().lstrip("^~>=<!")
