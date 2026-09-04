import base64
from unittest.mock import MagicMock, patch

import pytest

from app.services import github_client
from app.services.github_client import GitHubError


def test_normalize_repo_path_root():
    assert github_client.normalize_repo_path("") == ""
    assert github_client.normalize_repo_path("/") == ""
    assert github_client.normalize_repo_path(None) == ""


def test_normalize_repo_path_strips_and_rejects_dotdot():
    assert github_client.normalize_repo_path("/backend/") == "backend"
    assert github_client.normalize_repo_path("./backend/app") == "backend/app"
    with pytest.raises(ValueError, match="\\.\\."):
        github_client.normalize_repo_path("../secrets")


def test_list_repos_maps_fields():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "full_name": "acme/api",
            "private": True,
            "default_branch": "main",
            "description": "API",
        }
    ]
    with patch("app.services.github_client.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        repos = github_client.list_repos("tok")
    assert repos == [
        {
            "full_name": "acme/api",
            "private": True,
            "default_branch": "main",
            "description": "API",
        }
    ]


def test_list_directory_marks_manifests():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"name": "README.md", "path": "backend/README.md", "type": "file"},
        {"name": "requirements.txt", "path": "backend/requirements.txt", "type": "file"},
        {"name": "app", "path": "backend/app", "type": "dir"},
    ]
    with patch("app.services.github_client.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        entries = github_client.list_directory("tok", "acme/api", "backend")
    names = [e["name"] for e in entries]
    assert names[0] == "requirements.txt"
    assert entries[0]["is_manifest"] is True


def test_get_file_content_decodes_base64():
    raw = b"requests==2.31.0\n"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(raw).decode(),
    }
    with patch("app.services.github_client.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        content = github_client.get_file_content("tok", "acme/api", "backend/requirements.txt")
    assert content == raw


def test_list_repos_unauthorized():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "bad credentials"
    with patch("app.services.github_client.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        with pytest.raises(GitHubError) as exc:
            github_client.list_repos("bad")
    assert exc.value.status_code == 401
