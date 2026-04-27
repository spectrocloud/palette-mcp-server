# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import normalize_phoenix_endpoint_for_container


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
