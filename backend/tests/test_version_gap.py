from app.services.version_gap import compute_version_gap, normalize_status, versions_differ


def test_compute_version_gap_major_minor_patch():
    assert compute_version_gap("1.2.0", "2.0.0")["kind"] == "major"
    assert compute_version_gap("1.2.0", "1.3.0")["kind"] == "minor"
    assert compute_version_gap("1.2.0", "1.2.1")["kind"] == "patch"
    assert compute_version_gap("1.2.0", "1.2.0")["kind"] == "none"


def test_compute_version_gap_unknown():
    assert compute_version_gap("latest", "1.0.0")["kind"] == "unknown"


def test_versions_differ():
    assert versions_differ("18.0.0", "19.0.0")
    assert not versions_differ("19.0.0", "19.0.0")
    assert versions_differ("v1.0.0", "1.0.1")


def test_normalize_status_priority():
    assert normalize_status("1.0.0", "1.0.0", "buzz", has_security=True) == "security"
    assert normalize_status("1.0.0", "2.0.0", "buzz", has_breaking=True) == "breaking"
    assert normalize_status("1.0.0", "2.0.0", "buzz") == "update_available"
    assert normalize_status("1.0.0", "1.0.0", None) == "up_to_date"
    assert normalize_status("1.0.0", "2.0.0", None) == "update_available"
