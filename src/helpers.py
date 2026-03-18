# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import tempfile
import os
import json
import glob
import signal
import sys
import httpx
from typing import Dict, Any, Optional, Set, List
from contextlib import nullcontext

# Only import and setup OpenTelemetry if Phoenix is configured
if os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)
else:
    tracer = None


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
    with open(kubeconfig_path, "w") as f:
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


def create_span(name: str):
    """Helper function to create a span or return a no-op context manager"""
    if tracer is None:
        # Phoenix not configured, return a no-op context manager
        return nullcontext()

    try:
        # Try Phoenix-style span first
        return tracer.start_as_current_span(
            name, openinference_span_kind="tool", set_status_on_exception=False
        )
    except (TypeError, AttributeError):
        # Phoenix attributes not supported, try basic span
        try:
            return tracer.start_as_current_span(name)
        except (TypeError, AttributeError):
            # Even basic span doesn't work, return no-op
            return nullcontext()


def safe_set_tool(span, name: str, description: str, parameters: dict):
    """Safely set tool attributes, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_tool"):
            span.set_tool(name=name, description=description, parameters=parameters)
    except:
        pass


def safe_set_input(span, data: dict):
    """Safely set input attributes, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_input"):
            span.set_input(data)
    except:
        pass


def safe_set_output(span, data: dict):
    """Safely set output attributes, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_output"):
            span.set_output(data)
    except:
        pass


def safe_set_status(span, status):
    """Safely set status, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_status"):
            span.set_status(status)
    except:
        pass


def set_tool_metadata(span, name: str, description: str, parameters: dict):
    """Helper function to set tool metadata with error handling"""
    try:
        span.set_tool(name=name, description=description, parameters=parameters)
    except (TypeError, AttributeError):
        pass


def set_span_data(
    span, input_data: dict = None, output_data: dict = None, status: tuple = None
):
    """Helper function to set span input/output data and status with error handling"""
    try:
        if input_data is not None:
            # Convert input data to string to ensure valid type
            span.set_input(json.dumps(input_data))
    except (TypeError, AttributeError):
        pass

    try:
        if output_data is not None:
            # Convert output data to string to ensure valid type
            span.set_output(json.dumps(output_data))
    except (TypeError, AttributeError):
        pass

    try:
        if status is not None:
            span.set_status(status)
    except (TypeError, AttributeError):
        pass


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
    async with httpx.AsyncClient(base_url=f"https://{palette_host}", timeout=30) as client:
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


TAG_LIST_ENDPOINTS = {
    "spectroclusters": "/v1/spectroclusters/tags",
    "clusterTemplates": "/v1/clusterTemplates/tags",
    "edgehosts": "/v1/edgehosts/tags",
    "spcPolicies": "/v1/spcPolicies/tags",
}


TAG_UPDATE_ENDPOINTS = {
    "spectroclusters": {
        "get_path": "/v1/spectroclusters/{uid}",
        "get_method": "GET",
        "update_path": "/v1/spectroclusters/{uid}/metadata",
        "update_method": "PATCH",
    },
    "clusterprofiles": {
        "get_path": "/v1/clusterprofiles/{uid}",
        "get_method": "GET",
        "update_path": "/v1/clusterprofiles/{uid}/metadata",
        "update_method": "PATCH",
    },
    "clusterTemplates": {
        "get_path": "/v1/clusterTemplates/{uid}",
        "get_method": "GET",
        "update_path": "/v1/clusterTemplates/{uid}/metadata",
        "update_method": "PATCH",
    },
    "edgehosts": {
        "get_path": "/v1/edgehosts/{uid}",
        "get_method": "GET",
        "update_path": "/v1/edgehosts/{uid}/meta",
        "update_method": "PUT",
    },
    "spcPolicies": {
        "get_path": "/v1/spcPolicies/{policy_type}/{uid}",
        "get_method": "GET",
        "update_path": "/v1/spcPolicies/{policy_type}/{uid}",
        "update_method": "PUT",
    },
}


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


def merge_tags(
    existing_tags: Any, requested_tags: List[str], operation: str
) -> tuple[List[str], List[str]]:
    """Merge tags for add/remove operations using list semantics."""
    current = set(_normalize_tag_value(existing_tags))
    requested = [tag.strip() for tag in requested_tags if tag and tag.strip()]

    def _tag_key(tag: str) -> str:
        if ":" in tag:
            key, _ = tag.split(":", 1)
            return key.strip()
        return tag.strip()

    if operation == "add":
        updated = set(current)
        # Upsert by tag key so create can replace stale values (env:dev -> env:prod).
        for requested_tag in requested:
            requested_key = _tag_key(requested_tag)
            updated = {tag for tag in updated if _tag_key(tag) != requested_key}
            updated.add(requested_tag)
    elif operation == "remove":
        updated = set(current)
        for requested_tag in requested:
            if ":" in requested_tag:
                updated.discard(requested_tag)
            else:
                requested_key = _tag_key(requested_tag)
                updated = {tag for tag in updated if _tag_key(tag) != requested_key}
    else:
        raise ValueError(
            "Invalid operation for merge_tags. Supported values are 'add' and 'remove'."
        )

    before = sorted(current)
    after = sorted(updated)
    return before, after


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
