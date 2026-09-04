import os
import tempfile

import pytest

from app.services.manifest_parser import parse_manifest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(name: str) -> bytes:
    with open(os.path.join(FIXTURES, name), "rb") as f:
        return f.read()


def test_package_json():
    raw = _read_fixture("package.json")
    result = parse_manifest("package.json", raw)
    assert ("npm", "react", "18.2.0") in result
    assert ("npm", "express", "4.18.0") in result
    assert ("npm", "typescript", "5.0.0") in result
    assert ("npm", "jest", "29.0.0") in result


def test_requirements_txt():
    raw = _read_fixture("requirements.txt")
    result = parse_manifest("requirements.txt", raw)
    assert ("pip", "flask", "2.3.0") in result
    assert ("pip", "requests", "2.31.0") in result
    assert ("pip", "numpy", "1.24.0") in result


def test_requirements_advanced():
    raw = _read_fixture("requirements_advanced.txt")
    result = parse_manifest("requirements.txt", raw)
    assert ("pip", "flask", "2.3.0") in result
    assert ("pip", "requests", "2.31.0") in result
    assert ("pip", "numpy", "1.24.0,<2.0") in result
    assert ("pip", "click", "8.1") in result
    assert ("pip", "urllib3", "2.0") in result
    assert ("pip", "toml", "0.10") in result
    assert ("pip", "rich", "*") in result
    assert len(result) == 7, f"expected 7 deps, got {len(result)}"


def test_requirements_editable_and_options_skipped():
    raw = _read_fixture("requirements_advanced.txt")
    result = parse_manifest("requirements.txt", raw)
    pkgs = [p for _, p, _ in result]
    assert "black" not in pkgs


def test_pyproject_toml():
    raw = _read_fixture("pyproject.toml")
    result = parse_manifest("pyproject.toml", raw)
    assert ("pip", "click", "8.0") in result
    assert ("pip", "pydantic", "2.0") in result


def test_pyproject_pep621_with_extras_markers():
    raw = _read_fixture("pyproject_pep621.toml")
    result = parse_manifest("pyproject.toml", raw)
    assert ("pip", "click", "8.0") in result
    assert ("pip", "pydantic", "2.0") in result
    assert ("pip", "toml", "0.10") in result
    assert ("pip", "cryptography", "41.0") in result
    assert ("pip", "rich", "*") in result


def test_pyproject_poetry():
    raw = _read_fixture("pyproject_poetry.toml")
    result = parse_manifest("pyproject.toml", raw)
    assert ("pip", "requests", "2.31.0") in result
    assert ("pip", "click", "8.0") in result
    assert ("pip", "numpy", "1.24.0") in result
    assert ("pip", "python", "*") not in result, "python marker should be skipped"
    assert len(result) == 3, f"expected 3 deps from poetry, got {len(result)}"


def test_pom_xml():
    raw = _read_fixture("pom.xml")
    result = parse_manifest("pom.xml", raw)
    assert ("maven", "org.springframework.boot:spring-boot-starter-web", "3.1.0") in result
    assert ("maven", "com.google.guava:guava", "32.0.0") in result


def test_corrupt_json_raises():
    raw = _read_fixture("corrupt.json")
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_manifest("package.json", raw)


def test_corrupt_xml_raises():
    with pytest.raises(ValueError, match="not valid XML"):
        parse_manifest("pom.xml", b"<not xml")


def test_unsupported_file_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        parse_manifest("Gemfile", b"")


def test_no_temp_file_created():
    raw = _read_fixture("package.json")
    tmpdir = tempfile.gettempdir()
    before = set(os.listdir(tmpdir))
    parse_manifest("package.json", raw)
    after = set(os.listdir(tmpdir))
    assert after == before, "parser created a temp file - forbidden by spec"
