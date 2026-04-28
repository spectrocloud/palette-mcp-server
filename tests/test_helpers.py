# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import normalize_phoenix_endpoint_for_container, write_kubeconfig_to_temp


def test_rewrites_localhost_for_docker(monkeypatch):
    monkeypatch.setattr(
        "helpers.os.path.exists", lambda path: path == "/.dockerenv", raising=True
    )
    endpoint = "http://localhost:6006/v1/traces"
    got = normalize_phoenix_endpoint_for_container(endpoint)
    assert got == "http://host.docker.internal:6006/v1/traces"


def test_rewrites_localhost_for_podman(monkeypatch):
    monkeypatch.setattr(
        "helpers.os.path.exists",
        lambda path: path == "/run/.containerenv",
        raising=True,
    )
    endpoint = "http://127.0.0.1:6006/v1/traces"
    got = normalize_phoenix_endpoint_for_container(endpoint)
    assert got == "http://host.containers.internal:6006/v1/traces"


def test_env_override_wins(monkeypatch):
    monkeypatch.setattr(
        "helpers.os.path.exists",
        lambda path: path in {"/.dockerenv", "/run/.containerenv"},
        raising=True,
    )
    monkeypatch.setenv("PHOENIX_CONTAINER_HOST", "my-host")
    endpoint = "http://localhost:6006/v1/traces"
    got = normalize_phoenix_endpoint_for_container(endpoint)
    assert got == "http://my-host:6006/v1/traces"


def test_does_not_rewrite_non_localhost(monkeypatch):
    monkeypatch.setattr("helpers.os.path.exists", lambda _: True, raising=True)
    endpoint = "http://example.com:6006/v1/traces"
    got = normalize_phoenix_endpoint_for_container(endpoint)
    assert got == endpoint


def test_write_kubeconfig_creates_file_with_restricted_permissions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("helpers.tempfile.gettempdir", lambda: str(tmp_path))
    path = write_kubeconfig_to_temp("test-uid", "kubeconfig-content")
    assert oct(os.stat(path).st_mode & 0o777) == oct(0o600)


def test_write_admin_kubeconfig_creates_file_with_restricted_permissions(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("helpers.tempfile.gettempdir", lambda: str(tmp_path))
    path = write_kubeconfig_to_temp("test-uid", "kubeconfig-content", is_admin=True)
    assert oct(os.stat(path).st_mode & 0o777) == oct(0o600)


def test_write_admin_kubeconfig_uses_dot_admin_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr("helpers.tempfile.gettempdir", lambda: str(tmp_path))
    path = write_kubeconfig_to_temp("abc123", "content", is_admin=True)
    assert path.endswith("abc123.admin.kubeconfig")


def test_write_kubeconfig_fixes_permissions_on_existing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("helpers.tempfile.gettempdir", lambda: str(tmp_path))
    kubeconfig_dir = tmp_path / "kubeconfig"
    kubeconfig_dir.mkdir()
    existing = kubeconfig_dir / "test-uid.kubeconfig"
    existing.write_text("old content")
    os.chmod(existing, 0o644)
    path = write_kubeconfig_to_temp("test-uid", "new content")
    assert oct(os.stat(path).st_mode & 0o777) == oct(0o600)
