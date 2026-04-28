# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0
#
# Infrastructure helpers for the e2e test suite.
# Test definitions and the main entrypoint live in tests/e2e.py.

import json
import os
import re
import shlex
import subprocess
import time

import httpx
from mcp import StdioServerParameters

# ---------------------------------------------------------------------------
# Infrastructure constants
# ---------------------------------------------------------------------------

MCP_DOCKER_IMAGE = os.environ.get(
    "MCP_IMAGE", "public.ecr.aws/palette-ai/palette-mcp-server:test"
)

TERRAFORM_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "terraform"
)

POLL_INTERVAL_SECONDS = 30
POLL_TIMEOUT_SECONDS = 900  # 15 minutes


# ---------------------------------------------------------------------------
# Terraform helpers
# ---------------------------------------------------------------------------


def _read_terraform_outputs() -> dict:
    """Run terraform output -json and return the parsed output dict."""
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=TERRAFORM_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"terraform output failed:\n{result.stderr}")
    try:
        return json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError(f"Failed to parse terraform output JSON: {exc}") from exc


def get_cluster_uid_from_terraform() -> str:
    """Read the cluster UID from terraform output."""
    outputs = _read_terraform_outputs()
    cluster_uid = (outputs.get("cluster_uid") or {}).get("value", "").strip()
    if not cluster_uid:
        raise RuntimeError("terraform output returned empty cluster_uid.")
    return cluster_uid


def get_hello_universe_pack_uid_from_terraform() -> str:
    """Read the hello-universe pack UID from terraform output."""
    outputs = _read_terraform_outputs()
    pack_uid = (outputs.get("hello_universe_pack_uid") or {}).get("value", "").strip()
    if not pack_uid:
        raise RuntimeError("terraform output returned empty hello_universe_pack_uid.")
    return pack_uid


def setup_kubectl() -> str:
    """Register the KinD cluster with Palette and return the cluster UID."""
    print("Fetching terraform outputs...")
    outputs = _read_terraform_outputs()

    kubectl_cmd = (outputs.get("kubectl_command") or {}).get("value", "").strip()
    if not kubectl_cmd:
        raise RuntimeError("terraform output returned empty kubectl_command.")

    cluster_uid = (outputs.get("cluster_uid") or {}).get("value", "").strip()
    if not cluster_uid:
        raise RuntimeError("terraform output returned empty cluster_uid.")

    print("Registering KinD cluster with Palette...")
    reg = subprocess.run(shlex.split(kubectl_cmd), shell=False, check=False, text=True)
    if reg.returncode != 0:
        raise RuntimeError("kubectl registration command failed.")
    print("KinD cluster registered.")
    return cluster_uid


# ---------------------------------------------------------------------------
# Cluster polling
# ---------------------------------------------------------------------------


def wait_for_cluster_running(cluster_uid: str) -> None:
    """Poll GET /v1/spectroclusters/{uid} until the cluster reaches Running state.

    Raises RuntimeError if the cluster does not reach Running within POLL_TIMEOUT_SECONDS.
    """
    api_key = os.environ["SPECTROCLOUD_APIKEY"]
    _raw_host = (
        os.environ.get("SPECTROCLOUD_HOST", "")
        .strip()
        .removeprefix("https://")
        .removeprefix("http://")
        .rstrip("/")
    )
    host = _raw_host or "api.spectrocloud.com"
    project_uid = os.environ.get("SPECTROCLOUD_PROJECT_UID") or os.environ.get(
        "SPECTROCLOUD_DEFAULT_PROJECT_ID", ""
    )

    headers: dict = {
        "apiKey": api_key,
        "Accept": "application/json",
        "ProjectUid": project_uid,
    }

    print(f"  Connecting to host: {repr(host)}")
    print(
        f"  Using ProjectUid: {'(not set)' if not project_uid else project_uid[:8] + '...'}"
    )

    print(f"Waiting for cluster (uid={cluster_uid}) to reach Running state...")
    deadline = time.time() + POLL_TIMEOUT_SECONDS

    with httpx.Client(
        base_url=f"https://{host}", headers=headers, timeout=30
    ) as client:
        while time.time() < deadline:
            try:
                resp = client.get(f"/v1/spectroclusters/{cluster_uid}")
            except httpx.RequestError as exc:
                print(f"  Transport error (retrying): {exc}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            if not resp.is_success:
                print(f"  API error {resp.status_code}: {resp.text}")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            state = resp.json().get("status", {}).get("state", "")
            print(f"  Cluster state: {state}")
            if state == "Running":
                print(f"Cluster is Running (uid={cluster_uid}).")
                return
            time.sleep(POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"Cluster (uid={cluster_uid}) did not reach Running state within "
        f"{POLL_TIMEOUT_SECONDS // 60} minutes."
    )


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------


def build_mcp_server_params() -> StdioServerParameters:
    """Build StdioServerParameters to launch the Palette MCP server via Docker stdio."""
    api_key = os.environ.get("SPECTROCLOUD_APIKEY", "")
    host = os.environ.get("SPECTROCLOUD_HOST", "api.spectrocloud.com")
    if not api_key:
        raise RuntimeError("SPECTROCLOUD_APIKEY is required.")
    env_args = [
        "-e",
        f"SPECTROCLOUD_APIKEY={api_key}",
        "-e",
        f"SPECTROCLOUD_HOST={host}",
        "-e",
        "ALLOW_DANGEROUS_ACTIONS=1",
    ]
    project_id = os.environ.get("SPECTROCLOUD_DEFAULT_PROJECT_ID", "")
    if project_id:
        env_args += ["-e", f"SPECTROCLOUD_DEFAULT_PROJECT_ID={project_id}"]
    return StdioServerParameters(
        command="docker",
        args=["run", "--rm", "-i"] + env_args + [MCP_DOCKER_IMAGE],
    )


# ---------------------------------------------------------------------------
# smolagents utilities
# ---------------------------------------------------------------------------


def fix_tool_schemas(tools) -> None:
    """Flatten anyOf schemas in MCP tool inputs for OpenAI and smolagents compatibility.

    Two bugs in the mcpadapt → smolagents pipeline require this patch:

    1. mcpadapt sets type="string" as a fallback for every Optional[X] parameter
       because anyOf schemas have no top-level "type" key.  smolagents argument
       validation reads tool.inputs[key]["type"] directly (not the post-processed
       copy produced by get_tool_json_schema), so it sees "string" for Optional[int]
       and sees no "nullable" for Optional[str], causing null-value rejections.

    2. smolagents' get_tool_json_schema flattens anyOf by extracting the type name
       but does not carry over type-specific fields such as "items", so OpenAI
       rejects array schemas that are missing "items".

    Fix: walk every tool input and flatten anyOf in-place, preserving the correct
    type, nullable flag, and (for arrays) the items sub-schema.
    """
    for tool in tools:
        for key, schema in list(tool.inputs.items()):
            if "anyOf" not in schema:
                continue
            array_items = None
            nullable = False
            non_null_type = None
            for entry in schema["anyOf"]:
                entry_type = entry.get("type")
                if entry_type == "null":
                    nullable = True
                else:
                    non_null_type = entry_type
                    if entry_type == "array":
                        array_items = entry.get("items")
            if non_null_type is None:
                continue
            patched = {k: v for k, v in schema.items() if k != "anyOf"}
            patched["type"] = non_null_type
            patched["nullable"] = nullable
            if array_items is not None:
                patched["items"] = array_items
            tool.inputs[key] = patched


def make_step_callback():
    """Return a callback that prints each tool call and a truncated response."""
    step = [0]

    def callback(step_log):
        obs_str = str(getattr(step_log, "observations", "") or "")
        is_error = '"isError": true' in obs_str or "'isError': True" in obs_str
        if hasattr(step_log, "tool_calls") and step_log.tool_calls:
            for call in step_log.tool_calls:
                step[0] += 1
                tool_name = getattr(call, "name", "unknown")
                args = getattr(call, "arguments", {})
                action = args.get("action", "")
                resource_type = args.get("resource_type", "")
                label = f"{tool_name}({action}"
                if resource_type:
                    label += f", {resource_type}"
                label += ")"
                status = "ERROR" if is_error else "done"
                print(f"[STEP {step[0]}] {label} → {status}")
            if obs_str:
                snippet = obs_str[:600].replace("\n", " ")
                print(f"  response: {snippet}")

    return callback


def extract_tool_summary(agent) -> str:
    """Build a compact tool call summary from agent logs for the LLM judge."""
    lines = []
    i = 0
    for log in agent.memory.steps:
        if hasattr(log, "tool_calls") and log.tool_calls:
            for call in log.tool_calls:
                i += 1
                name = getattr(call, "name", "?")
                args = getattr(call, "arguments", {})
                action = args.get("action", "")
                resource_type = args.get("resource_type", "")
                obs_str = str(log.observations) if hasattr(log, "observations") else ""
                is_error = '"isError": true' in obs_str or "'isError': True" in obs_str
                status = "ERROR" if is_error else "OK"
                uid = args.get("uid", "")
                parts = [f"action={action}"]
                if resource_type:
                    parts.append(f"resource_type={resource_type}")
                if uid:
                    parts.append(f"uid={uid}")
                line = f"{i}. {name}({', '.join(parts)}) → {status}"
                if obs_str and not is_error:
                    snippet = obs_str[:800].replace("\n", " ")
                    line += f"\n   response: {snippet}"
                lines.append(line)
    return "\n".join(lines)


def extract_uid(text: str, prefix: str) -> str | None:
    """Extract '<PREFIX>: <uid>' from agent output. Returns None if not found."""
    m = re.search(rf"{re.escape(prefix)}:\s*(\S+)", text)
    return m.group(1) if m else None
