# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import tempfile
import os
import glob
import signal
import sys
import httpx
from urllib.parse import urlparse, urlunparse
from typing import Dict, Any, Optional, Set, List


def write_kubeconfig_to_temp(
    cluster_uid: str, kubeconfig_content: str, is_admin: bool = False
) -> str:
    """Helper function to write kubeconfig content to a temporary file.

    Args:
        cluster_uid (str): The UID of the cluster to use in the filename
        kubeconfig_content (str): The kubeconfig content to write
        is_admin (bool): Whether this is an admin kubeconfig (adds .admin to filename)

    Returns:
        str: Path to the written kubeconfig file
    """
    temp_dir = tempfile.gettempdir()
    kubeconfig_dir = os.path.join(temp_dir, "kubeconfig")
    os.makedirs(kubeconfig_dir, exist_ok=True)

    if is_admin:
        filename = f"{cluster_uid}.admin.kubeconfig"
    else:
        filename = f"{cluster_uid}.kubeconfig"

    kubeconfig_path = os.path.join(kubeconfig_dir, filename)
    fd = os.open(kubeconfig_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(kubeconfig_content)
    return kubeconfig_path


def cleanup_temp_files():
    """Clean up temporary kubeconfig files created by the server"""
    try:
        temp_dir = tempfile.gettempdir()

        cleaned_count = 0

        # Clean up kubeconfig files in the subdirectory (current version)
        kubeconfig_dir = os.path.join(temp_dir, "kubeconfig")
        if os.path.exists(kubeconfig_dir):
            kubeconfig_pattern = os.path.join(kubeconfig_dir, "*.kubeconfig")
            kubeconfig_files = glob.glob(kubeconfig_pattern)

            for file_path in kubeconfig_files:
                try:
                    os.remove(file_path)
                    cleaned_count += 1
                except OSError:
                    # File might already be deleted or in use, skip silently
                    pass

        # Clean up legacy kubeconfig files directly in temp directory (previous version)
        legacy_pattern = os.path.join(temp_dir, "*.kubeconfig")
        legacy_files = glob.glob(legacy_pattern)

        for file_path in legacy_files:
            try:
                os.remove(file_path)
                cleaned_count += 1
            except OSError:
                # File might already be deleted or in use, skip silently
                pass

        if cleaned_count > 0:
            print(f"🧹 Cleaned up {cleaned_count} temporary kubeconfig file(s)")
        else:
            print("🧹 No temporary kubeconfig files to clean up")
    except Exception:
        # Cleanup should never fail the shutdown process
        pass


def create_signal_handler(logger=None):
    """Create a signal handler function for graceful shutdown.

    Args:
        logger: Optional logger instance. If None, uses print statements.

    Returns:
        function: Signal handler function
    """
    # Track if we've already handled a signal to avoid multiple shutdowns
    shutdown_initiated = False

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        nonlocal shutdown_initiated

        # Avoid handling multiple signals
        if shutdown_initiated:
            return
        shutdown_initiated = True

        signal_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else "SIGTERM"

        if logger:
            logger.info(f"Received {signal_name} signal")
            logger.info("Shutting down Palette MCP Server gracefully...")
        else:
            print(f"\n🛑 Received {signal_name} signal")
            print("🔄 Shutting down Palette MCP Server gracefully...")

        # Perform cleanup
        cleanup_temp_files()

        if logger:
            logger.info("Palette MCP Server stopped")
        else:
            print("✅ Palette MCP Server stopped")

        # Use os._exit to avoid threading issues during shutdown
        # This bypasses Python's normal shutdown process which can hang
        # with threading and stdio conflicts
        os._exit(0)

    return signal_handler


def normalize_phoenix_endpoint_for_container(endpoint: str) -> str:
    """Rewrite localhost endpoints when running inside Docker or Podman containers."""
    if not endpoint:
        return endpoint

    # Check for container environment
    is_docker = os.path.exists("/.dockerenv")
    is_podman = os.path.exists("/run/.containerenv")

    if not (is_docker or is_podman):
        return endpoint

    parsed = urlparse(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return endpoint

    # Allow override via environment variable
    host = os.environ.get("PHOENIX_CONTAINER_HOST")
    if not host:
        if is_docker:
            host = "host.docker.internal"
        elif is_podman:
            host = "host.containers.internal"

    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    else:
        netloc = host
    return urlunparse(parsed._replace(netloc=netloc))


def ensure_otlp_traces_path(endpoint: str) -> str:
    """Ensure endpoint targets the OTLP HTTP traces path."""
    parsed = urlparse(endpoint)
    path = (parsed.path or "").rstrip("/")
    if path.endswith("/v1/traces"):
        return endpoint
    if not path:
        path = "/v1/traces"
    else:
        path = f"{path}/v1/traces"
    return urlunparse(parsed._replace(path=path))


def build_headers(
    api_key: str,
    project_id: Optional[str] = None,
    include_content_type: bool = False,
    accept: str = "application/json",
) -> Dict[str, str]:
    """Build request headers for Palette API calls."""
    headers = {"Accept": accept, "apiKey": api_key}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    if project_id:
        headers["ProjectUid"] = project_id
    return headers


async def palette_api_request(
    palette_host: str,
    method: str,
    path: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    allowed_status_codes: Optional[Set[int]] = None,
) -> httpx.Response:
    """Execute a Palette API request with common validation and rate-limit handling."""
    async with httpx.AsyncClient(
        base_url=f"https://{palette_host}", timeout=30
    ) as client:
        response = await client.request(
            method=method, url=path, headers=headers, params=params, json=body
        )

    allowed_status_codes = allowed_status_codes or set()
    if response.status_code in allowed_status_codes:
        return response

    if response.status_code == 422:
        details = response.text
        try:
            details = response.json()
        except Exception:
            pass
        raise Exception(
            f"Validation error (422): The request was well-formed but contains semantic errors. Details: {details}"
        )

    if response.status_code == 429:
        raise Exception(
            f"Rate limit error (429): Too many requests. Please wait before retrying. Response: {response.text}"
        )

    if response.status_code >= 400:
        try:
            error_payload = response.json()
        except Exception:
            error_payload = {}

        if error_payload.get("code") == "EdgeHostDeviceNotRegistered":
            edgehost_message = error_payload.get(
                "message", "Edge host device is not yet registered."
            )
            raise Exception(
                "Edge host is not registered and cannot be tagged yet. "
                f"Details: {edgehost_message}"
            )

        raise Exception(
            f"API request failed with status {response.status_code}: {response.text}"
        )

    return response


def _normalize_tag_value(value: Any) -> List[str]:
    """Normalize common tag field formats into a string list."""

    def _strip_internal_marker(tag: str) -> str:
        text = (tag or "").strip()
        if not text:
            return ""
        if ":" in text:
            key, val = text.split(":", 1)
            if val.strip() == "spectro__tag":
                return key.strip()
        return text

    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "," in text and ":" in text:
            return [
                cleaned
                for cleaned in (
                    _strip_internal_marker(part) for part in text.split(",")
                )
                if cleaned
            ]
        cleaned = _strip_internal_marker(text)
        return [cleaned] if cleaned else []

    if isinstance(value, list):
        normalized: List[str] = []
        for item in value:
            if item is None:
                continue
            cleaned = _strip_internal_marker(str(item))
            if cleaned:
                normalized.append(cleaned)
        return normalized

    if isinstance(value, dict):
        tags = []
        for key, val in value.items():
            if val is None or str(val).strip() == "":
                tags.append(str(key))
            elif str(val).strip() == "spectro__tag":
                tags.append(str(key))
            else:
                tags.append(f"{key}:{val}")
        return tags

    return []


def extract_cluster_profile_tags(cluster_profile: Dict[str, Any]) -> List[str]:
    """Extract tags from cluster profile metadata only."""
    metadata = cluster_profile.get("metadata", {})
    tags: List[str] = []
    tags.extend(_normalize_tag_value(metadata.get("tags")))
    tags.extend(_normalize_tag_value(metadata.get("tag")))
    # Some profile APIs expose user metadata in labels.
    if not tags:
        tags.extend(_normalize_tag_value(metadata.get("labels")))
    deduped = list(dict.fromkeys(tag for tag in tags if tag and tag.strip()))
    return sorted(deduped)
