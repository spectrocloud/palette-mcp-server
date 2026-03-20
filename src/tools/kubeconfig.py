# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

from typing import Optional

from fastmcp import Context

from helpers import (
    build_headers,
    palette_api_request,
    write_kubeconfig_to_temp,
)
from tracing import create_span, safe_set_input, safe_set_output, safe_set_tool
from tools.common import (
    MCPResult,
    get_session_context,
    mask_sensitive_data,
    safe_set_span_status,
)


async def getKubeconfig(
    ctx: Context,
    cluster_uid: str,
    admin_config: bool = False,
    project_id: Optional[str] = None,
    api_key: Optional[str] = None,
) -> MCPResult:
    session_ctx = get_session_context(ctx)
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()

    if not api_key:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Error: No api_key provided and no default API key configured",
                }
            ],
            "isError": True,
        }

    with create_span("getKubeconfig") as span:
        safe_set_tool(
            span,
            name="getKubeconfig",
            description="Gets the kubeconfig or admin kubeconfig file for a specific cluster. To use the admin kubeconfig, set admin_config to True.",
            parameters={
                "cluster_uid": {
                    "type": "string",
                    "description": "The UID of the cluster to get the kubeconfig for",
                },
                "admin_config": {
                    "type": "boolean",
                    "description": "If True, retrieves the admin kubeconfig. Default is False.",
                },
                "project_id": {
                    "type": "string",
                    "description": "The ID of the project to query (optional)",
                },
                "api_key": {
                    "type": "string",
                    "description": "The API key for the Palette API (optional)",
                },
            },
        )
        safe_set_input(
            span,
            mask_sensitive_data(
                {
                    "api_key": api_key,
                    "project_id": project_id,
                    "cluster_uid": cluster_uid,
                    "admin_config": admin_config,
                }
            ),
        )

        try:
            headers = build_headers(
                api_key=api_key,
                project_id=project_id,
                accept="application/octet-stream",
            )
            url = (
                f"/v1/spectroclusters/{cluster_uid}/assets/adminKubeconfig"
                if admin_config
                else f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig"
            )
            actual_admin_config = admin_config
            res = await palette_api_request(
                palette_host=palette_host,
                method="GET",
                path=url,
                headers=headers,
                allowed_status_codes={404} if admin_config else None,
            )
            if admin_config and res.status_code == 404:
                actual_admin_config = False
                res = await palette_api_request(
                    palette_host=palette_host,
                    method="GET",
                    path=f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig",
                    headers=headers,
                    params={"frp": "true"},
                )

            kubeconfig_content = res.text
            try:
                kubeconfig_path = write_kubeconfig_to_temp(
                    cluster_uid, kubeconfig_content, is_admin=actual_admin_config
                )
                session_ctx.kubeconfig.set_path(kubeconfig_path)
            except OSError as e:
                print(f"Warning: Failed to write kubeconfig to temp file: {e!s}")
                kubeconfig_path = None

            safe_set_output(
                span,
                {
                    "status": "Kubeconfig retrieved successfully",
                    "admin_config": actual_admin_config,
                },
            )
            config_type = "Admin kubeconfig" if actual_admin_config else "Kubeconfig"
            return {
                "content": [
                    {"type": "text", "text": kubeconfig_content},
                    {
                        "type": "text",
                        "text": (
                            f"\n{config_type} written to: {kubeconfig_path}"
                            if kubeconfig_path
                            else f"\nWarning: Failed to write {config_type.lower()} to temp file"
                        ),
                    },
                ],
                "isError": False,
            }
        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True,
            }


__all__ = ["getKubeconfig"]
