import http.client
import json
from typing import Dict, TypedDict, Any, List, Optional, Union
from pydantic import BaseModel
from kubernetes import client, config
from datetime import datetime, timedelta
import pytz
from fastmcp import FastMCP, Context
from context import MCPSessionContext
from helpers import (
    write_kubeconfig_to_temp,
    create_span,
    safe_set_tool,
    safe_set_input,
    safe_set_output,
    safe_set_status,
)

def get_session_context(ctx: Context) -> MCPSessionContext:
    """Helper function to get our custom MCP session context from FastMCP context"""
    return ctx.fastmcp.session_context


"""
  This file contains the tools that are used by the Palette MCP server.
  The tools are used to get information about the clusters that are managed by Palette.
  The tools are also used to get information about the Palette platform itself.

"""


class Cluster(BaseModel):
    name: str
    uid: Optional[str] = None
    state: Optional[str] = None
    cloud_type: Optional[str] = None
    location: Optional[str] = None

class OutputModel(BaseModel):
    clusters: List[Cluster]
    summary: str

class MCPResult(TypedDict):
    """Type definition for MCP tool results"""
    content: list[dict]
    isError: bool

class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder for datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


"""
  This function masks sensitive data by only showing the last 8 characters.
  It is used to mask the API key and project ID in the trace.
"""
def mask_sensitive_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Masks sensitive data by only showing the last 8 characters."""
    masked = data.copy()
    if 'api_key' in masked:
        api_key = masked['api_key']
        masked['api_key'] = f"{'*' * (len(api_key) - 8)}{api_key[-8:]}" if len(api_key) > 8 else api_key
    return masked

def safe_set_span_status(span, status_code: str, description: str = None):
    """Helper to safely set span status without importing trace when Phoenix is not configured"""
    if span is None:
        return
    try:
        from opentelemetry import trace
        if status_code == "OK":
            safe_set_status(span, trace.Status(trace.StatusCode.OK))
        elif status_code == "ERROR":
            safe_set_status(span, trace.Status(trace.StatusCode.ERROR, description or ""))
    except ImportError:
        # OpenTelemetry not available, skip
        pass


"""
  This tool queries the Palette API to find all clusters in a given project.
  It returns the cluster metadata with the values.yaml removed from the return payload.
"""
async def getClusters(ctx: Context, project_id: Optional[str] = None, api_key: Optional[str] = None) -> MCPResult:
    """Queries the Palette API to find all clusters in a given project."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()
    
    if not api_key:
        return {
            "content": [{"type": "text", "text": "Error: No api_key provided and no default API key configured"}],
            "isError": True
        }
    
    with create_span("getClusters") as span:
        safe_set_tool(
            span,
            name="getClusters",
            description="Queries Palette API for all clusters in a project, returning cluster metadata with values.yaml removed",
            parameters={
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"}
            }
        )
        
        safe_set_input(span, mask_sensitive_data({
            "api_key": api_key, 

        }))

        try:
            conn = http.client.HTTPSConnection(palette_host)
            payload = ''
            headers = {
                'Accept': 'application/json',
                'apiKey': api_key
            }
            
            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers['ProjectUid'] = project_id

            all_clusters = []
            continue_token = None

            while True:
                if continue_token:
                    headers['Continue'] = continue_token

                conn.request("GET", "/v1/spectroclusters/", payload, headers)
                res = conn.getresponse()
                data = res.read()

                if res.status >= 400:
                    raise Exception(f"API request failed with status {res.status}: {data.decode('utf-8')}")

                json_data = json.loads(data.decode("utf-8"))
                all_clusters.extend(json_data.get('items', []))

                continue_token = json_data.get('listmeta', {}).get('continue')
                if not continue_token:
                    break

            # Clean up values.yaml from cluster profile templates
            for cluster in all_clusters:
                if 'spec' in cluster:
                    spec = cluster['spec']
                    if 'clusterProfileTemplates' in spec:
                        for template in spec['clusterProfileTemplates']:
                            if 'packs' in template:
                                for pack in template['packs']:
                                    if 'values' in pack:
                                        del pack['values']

            result = {"clusters": {'items': all_clusters}}
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")
            
            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def getActiveClusters(ctx: Context, project_id: Optional[str] = None, api_key: Optional[str] = None) -> MCPResult:
    """Queries the Palette API to find all active clusters in a given project.
    
    Args:
        api_key (str): The API key for the Palette API. Optional, uses the API key from the context if not provided.
        project_id (str): The ID of the project to query. Optional, uses the project ID from the context if not provided.
        
    Returns:
        MCPResult: Result object containing active cluster metadata or error information
    """
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()
    
    if not api_key:
        return {
            "content": [{"type": "text", "text": "Error: No api_key provided and no default API key configured"}],
            "isError": True
        }
    with create_span("getActiveClusters") as span:
        safe_set_tool(
            span,
            name="getActiveClusters",
            description="Queries Palette API for active clusters in a project, returning cluster metadata",
            parameters={
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"}
            }
        )
        
        safe_set_input(span, mask_sensitive_data({
            "api_key": api_key
        }))

        try:
            conn = http.client.HTTPSConnection(palette_host)
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'apiKey': api_key
            }
            
            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers['ProjectUid'] = project_id

            payload = json.dumps({
                "filter": {
                    "conjunction": "and",
                    "filterGroups": [
                        {
                            "conjunction": "and",
                            "filters": [
                                {
                                    "property": "clusterState",
                                    "type": "string",
                                    "condition": {
                                        "string": {
                                            "operator": "eq",
                                            "negation": False,
                                            "match": {
                                                "conjunction": "or",
                                                "values": ["Running"]
                                            },
                                            "ignoreCase": False
                                        }
                                    }
                                }
                            ]
                        },
                        {
                            "conjunction": "and",
                            "filters": [
                                {
                                    "property": "environment",
                                    "type": "string",
                                    "condition": {
                                        "string": {
                                            "operator": "eq",
                                            "negation": True,
                                            "match": {
                                                "conjunction": "or",
                                                "values": ["nested"]
                                            },
                                            "ignoreCase": False
                                        }
                                    }
                                },
                                {
                                    "property": "isDeleted",
                                    "type": "bool",
                                    "condition": {
                                        "bool": {
                                            "value": False
                                        }
                                    }
                                }
                            ]
                        }
                    ]
                },
                "sort": [
                    {
                        "field": "clusterName",
                        "order": "asc"
                    }
                ]
            })

            active_clusters = []
            continue_token = None

            while True:
                if continue_token:
                    headers['Continue'] = continue_token

                conn.request("POST", "/v1/dashboard/spectroclusters/search", payload, headers)
                res = conn.getresponse()
                data = res.read()

                if res.status >= 400:
                    raise Exception(f"API request failed with status {res.status}: {data.decode('utf-8')}")

                json_data = json.loads(data.decode("utf-8"))
                active_clusters.extend(json_data.get('items', []))

                continue_token = json_data.get('listmeta', {}).get('continue')
                if not continue_token:
                    break

            result = {"clusters": {'items': active_clusters}}
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")
            
            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def getClusterDetailsByUID(ctx: Context, cluster_uid: str, project_id: Optional[str] = None, api_key: Optional[str] = None) -> MCPResult:
    """Queries the Palette API to find detailed information about a specific cluster."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()
    
    if not api_key:
        return {
            "content": [{"type": "text", "text": "Error: No api_key provided and no default API key configured"}],
            "isError": True
        }
    
    with create_span("getClusterDetailsByUID") as span:
        safe_set_tool(
            span,
            name="getClusterDetailsByUID",
            description="Queries Palette API for detailed information about a specific cluster",
            parameters={
                "cluster_uid": {"type": "string", "description": "The UID of the cluster to query"},
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"}
            }
        )
        
        safe_set_input(span, mask_sensitive_data({
            "api_key": api_key
        }))

        try:
            conn = http.client.HTTPSConnection(palette_host)
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'apiKey': api_key
            }
            
            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers['ProjectUid'] = project_id
                
            url = f"/v1/spectroclusters/{cluster_uid}?includeTags=true&resolvePackValues=true&includePackMeta=false&profileType=%3Cstring%3E&includeNonSpectroLabels=false"
            
            conn.request("GET", url, {}, headers)
            res = conn.getresponse()
            data = res.read()

            if res.status >= 400:
                raise Exception(f"API request failed with status {res.status}: {data.decode('utf-8')}")

            result = {"cluster": json.loads(data.decode("utf-8"))}
            safe_set_output(span, result)
            
            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def deleteClusterByUID(ctx: Context, cluster_uid: str, project_id: Optional[str] = None, api_key: Optional[str] = None, force_delete: bool = False) -> MCPResult:
    """Deletes a specific cluster using its UID. Specifying force_delete=True will force the deletion of the cluster. Keep in mind that force delete can only work if the cluster is in the delete state. A delete request must be initiated without the force delete flag prior to using force delete.
    
    Args:
        cluster_uid (str): The UID of the cluster to delete
        project_id (str): The ID of the project to query (optional, omits the ProjectUid header if not provided)
        api_key (str): The API key for the Palette API (optional, uses default if not provided)
        force_delete (bool): Whether to force delete the cluster (optional, defaults to false)
    """
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()
    
    if not api_key:
        return {
            "content": [{"type": "text", "text": "Error: No api_key provided and no default API key configured"}],
            "isError": True
        }
    
    with create_span("deleteClusterByUID") as span:
        safe_set_tool(
            span,
            name="deleteClusterByUID",
            description="Deletes a specific cluster from Palette using its UID",
            parameters={
                "cluster_uid": {"type": "string", "description": "The UID of the cluster to delete"},
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"},
                "force_delete": {"type": "boolean", "description": "Whether to force delete the cluster (optional, defaults to false)"}
            }
        )
        
        safe_set_input(span, mask_sensitive_data({
            "api_key": api_key, 
            "project_id": project_id,
            "cluster_uid": cluster_uid,
            "force_delete": force_delete
        }))

        try:
            conn = http.client.HTTPSConnection(palette_host)
            headers = {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'apiKey': api_key
            }
            
            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers['ProjectUid'] = project_id
                
            url = f"/v1/spectroclusters/{cluster_uid}?forceDelete={str(force_delete).lower()}"
            
            conn.request("DELETE", url, {}, headers)
            res = conn.getresponse()
            data = res.read()

            if res.status >= 400:
                raise Exception(f"API request failed with status {res.status}: {data.decode('utf-8')}")

            result = {"status": json.loads(data.decode("utf-8"))}
            safe_set_output(span, result)
            
            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def getAdminKubeconfig(ctx: Context, cluster_uid: str, project_id: Optional[str] = None, api_key: Optional[str] = None) -> MCPResult:
    """Gets the admin kubeconfig file for a specific cluster."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()
    
    if not api_key:
        return {
            "content": [{"type": "text", "text": "Error: No api_key provided and no default API key configured"}],
            "isError": True
        }
    
    with create_span("getAdminKubeconfig") as span:
        safe_set_tool(
            span,
            name="getAdminKubeconfig",
            description="Gets the admin kubeconfig file for a specific cluster",
            parameters={
                "cluster_uid": {"type": "string", "description": "The UID of the cluster to get the kubeconfig for"},
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"}
            }
        )
        
        safe_set_input(span, mask_sensitive_data({
            "api_key": api_key, 
            "project_id": project_id,
            "cluster_uid": cluster_uid
        }))

        try:
            conn = http.client.HTTPSConnection(palette_host)
            headers = {
                'Accept': 'application/octet-stream',
                'apiKey': api_key
            }
            
            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers['ProjectUid'] = project_id
                
            url = f"/v1/spectroclusters/{cluster_uid}/assets/adminKubeconfig"
            
            conn.request("GET", url, {}, headers)
            res = conn.getresponse()
            data = res.read()

            # If admin kubeconfig is not available, try regular kubeconfig with frp=true
            if res.status == 404:
                url = f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig?frp=true"
                conn.request("GET", url, {}, headers)
                res = conn.getresponse()
                data = res.read()

            if res.status >= 400:
                raise Exception(f"API request failed with status {res.status}: {data.decode('utf-8')}")
              
              
            

            result = {"admin_kubeconfig": data.decode("utf-8")}
            
            # Write kubeconfig to temp directory with cluster UID
            try:
                kubeconfig_path = write_kubeconfig_to_temp(cluster_uid, result["admin_kubeconfig"])
                # Set the kubeconfig path in context
                session_ctx.kubeconfig.set_path(kubeconfig_path)
            except Exception as e:
                print(f"Warning: Failed to write kubeconfig to temp file: {str(e)}")
                kubeconfig_path = None
                
            safe_set_output(span, {"status": "Kubeconfig retrieved successfully"})
            
            return {
                "content": [
                    {"type": "text", "text": result["admin_kubeconfig"]},
                    {"type": "text", "text": f"\nKubeconfig written to: {kubeconfig_path}" if kubeconfig_path else "\nWarning: Failed to write kubeconfig to temp file"}
                ],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def getKubeconfig(ctx: Context, cluster_uid: str, project_id: Optional[str] = None, api_key: Optional[str] = None) -> MCPResult:
    """Gets the regular (non-admin) kubeconfig file for a specific cluster.  Preferably use getAdminKubeconfig instead."""
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use values from context.config, with optional overrides
    api_key = session_ctx.get_api_key(api_key)
    project_id = session_ctx.get_project_id(project_id)
    palette_host = session_ctx.get_host()
    
    if not api_key:
        return {
            "content": [{"type": "text", "text": "Error: No api_key provided and no default API key configured"}],
            "isError": True
        }
    
    with create_span("getKubeconfig") as span:
        safe_set_tool(
            span,
            name="getKubeconfig",
            description="Gets the regular (non-admin) kubeconfig file for a specific cluster",
            parameters={
                "cluster_uid": {"type": "string", "description": "The UID of the cluster to get the kubeconfig for"},
                "project_id": {"type": "string", "description": "The ID of the project to query (optional, omits the ProjectUid header if not provided)"},
                "api_key": {"type": "string", "description": "The API key for the Palette API (optional, uses default if not provided)"}
            }
        )
        
        safe_set_input(span, mask_sensitive_data({
            "api_key": api_key, 
            "project_id": project_id,
            "cluster_uid": cluster_uid
        }))

        try:
            conn = http.client.HTTPSConnection(palette_host)
            headers = {
                'Accept': 'application/octet-stream',
                'apiKey': api_key
            }
            
            # Only add ProjectUid header if project_id is provided
            if project_id:
                headers['ProjectUid'] = project_id
                
            url = f"/v1/spectroclusters/{cluster_uid}/assets/kubeconfig"
            
            conn.request("GET", url, {}, headers)
            res = conn.getresponse()
            data = res.read()

            if res.status >= 400:
                raise Exception(f"API request failed with status {res.status}: {data.decode('utf-8')}")
              
              
            # Write kubeconfig to temp directory with cluster UID
            try:
                kubeconfig_path = write_kubeconfig_to_temp(cluster_uid, data.decode("utf-8"))
                # Set the kubeconfig path in context
                session_ctx.kubeconfig.set_path(kubeconfig_path)
            except Exception as e:
                print(f"Warning: Failed to write kubeconfig to temp file: {str(e)}")
                kubeconfig_path = None

            result = {"kubeconfig": data.decode("utf-8")}
            safe_set_output(span, {"status": "Kubeconfig retrieved successfully"})
            
            return {
                "content": [
                    {"type": "text", "text": result["kubeconfig"]},
                    {"type": "text", "text": f"\nKubeconfig written to: {kubeconfig_path}" if kubeconfig_path else "\nWarning: Failed to write kubeconfig to temp file"}
                ],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error during API call: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def getPodsInCluster(ctx: Context, kubeconfig_path: Optional[str] = None) -> MCPResult:
    """Gets all the pods in a specific Kubernetes cluster.
    
    Args:
        kubeconfig_path (str): Path to the kubeconfig file (optional, uses path from context if not provided)
        
    Returns:
        MCPResult: List of pods in the cluster with their status
    """
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use kubeconfig path from context if not provided
    if not kubeconfig_path:
        kubeconfig_path = session_ctx.kubeconfig.path
    
    if not kubeconfig_path:
        return {
            "content": [{"type": "text", "text": "Error: No kubeconfig_path provided and no kubeconfig path set in context"}],
            "isError": True
        }
    with create_span("getPodsInCluster") as span:
        safe_set_tool(
            span,
            name="getPodsInCluster",
            description="Gets the pods in a specific Kubernetes cluster",
            parameters={
                "kubeconfig_path": {"type": "string", "description": "Path to the kubeconfig file (optional, uses path from context if not provided)"}
            }
        )
        
        safe_set_input(span, {"kubeconfig_path": kubeconfig_path})

        try:
            # First try using Python client
            try:
                # Load the kubeconfig from the file
                config.load_kube_config(config_file=kubeconfig_path)
                
                # Get API client
                v1_client = client.CoreV1Api()
                
                # Test connection by getting API resources
                api_resources = v1_client.get_api_resources()
                if not api_resources:
                    raise Exception("Failed to connect to cluster")
                
                # Get pods
                pods = v1_client.list_pod_for_all_namespaces(watch=False)
                
                # Extract names, namespaces, and statuses
                pod_info = [
                    {
                        "name": pod.metadata.name,
                        "namespace": pod.metadata.namespace,
                        "status": pod.status.phase
                    }
                    for pod in pods.items
                ]
                
                jsonPods = json.dumps(pod_info, indent=2, cls=DateTimeEncoder)
                safe_set_output(span, {"pods": jsonPods})
                
                return {
                    "content": [{"type": "text", "text": jsonPods}],
                    "isError": False
                }
            
            except Exception as e:
                # If Python client fails, try kubectl
                import subprocess
                cmd = ["kubectl", "--kubeconfig", kubeconfig_path, "get", "pods", "--all-namespaces", "-o", "json"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    raise Exception(f"Both Python client and kubectl failed. kubectl error: {result.stderr}")
                
                pods_json = json.loads(result.stdout)
                pod_info = [
                    {
                        "name": pod["metadata"]["name"],
                        "namespace": pod["metadata"]["namespace"],
                        "status": pod["status"]["phase"]
                    }
                    for pod in pods_json["items"]
                ]
                
                jsonPods = json.dumps(pod_info, indent=2)
                safe_set_output(span, {"pods": jsonPods})
                
                return {
                    "content": [{"type": "text", "text": jsonPods}],
                    "isError": False
                }
                
        except Exception as e:
            error_message = f"Error getting pods: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def analyzeCluster(ctx: Context, kubeconfig_path: Optional[str] = None) -> MCPResult:
    """Analyzes a Kubernetes cluster using k8sgpt The output contains the explaination of issues in the cluster. You can use the  output to help formualte a message to the user that better helps them understand the issues in the cluster.
    
    Args:
        kubeconfig_path (str): Path to the kubeconfig file (optional, uses path from context if not provided)
        
    Returns:
        MCPResult: Analysis results from k8sgpt
    """
    # Get our custom MCP session context
    session_ctx = get_session_context(ctx)
    
    # Use kubeconfig path from context if not provided
    if not kubeconfig_path:
        kubeconfig_path = session_ctx.kubeconfig.path
    
    if not kubeconfig_path:
        return {
            "content": [{"type": "text", "text": "Error: No kubeconfig_path provided and no kubeconfig path set in context"}],
            "isError": True
        }
    with create_span("analyzeCluster") as span:
        safe_set_tool(
            span,
            name="analyzeCluster",
            description="Analyzes a Kubernetes cluster using k8sgpt analyze --explain",
            parameters={
                "kubeconfig_path": {"type": "string", "description": "Path to the kubeconfig file (optional, uses path from context if not provided)"}
            }
        )
        
        safe_set_input(span, {
            "kubeconfig_path": kubeconfig_path
        })

        try:
            # Run k8sgpt analyze with the provided kubeconfig
            import subprocess, os
            
            # First authenticate k8sgpt with OpenAI
            if "K8SGPT_OPENAI_API_KEY" in os.environ:
                print("Authenticating k8sgpt with OpenAI")
                auth_cmd = ["k8sgpt", "auth", "add", "--backend", "openai", "--model", "gpt-4", "--password", os.environ["K8SGPT_OPENAI_API_KEY"]]
                _ = subprocess.run(auth_cmd, capture_output=True, text=True, env=os.environ)    
            else:
                raise Exception("K8SGPT_OPENAI_API_KEY environment variable not set")
            print("Authenticated k8sgpt with OpenAI")
            # Run the analysis
            cmd = ["k8sgpt", "analyze", "--explain", "--kubeconfig", kubeconfig_path]
            
            result = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
            
            if result.returncode != 0:
                error_details = f"Exit code: {result.returncode}\nStderr: {result.stderr}\nStdout: {result.stdout}"
                safe_set_output(span, {
                    "error": "k8sgpt analyze failed",
                    "exit_code": result.returncode,
                    "stderr": result.stderr,
                    "stdout": result.stdout
                })
                raise Exception(f"k8sgpt analyze failed:\n{error_details}")

            analysis_output = result.stdout
            safe_set_output(span, {"analysis": analysis_output})
            
            return {
                "content": [{"type": "text", "text": analysis_output}],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error analyzing cluster: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def sendSlackNotificationForUnhealthyCluster(message: dict, webhook_url: str) -> MCPResult:
    """Sends a Slack notification message for unhealthy clusters. Requires a message block created by prepareUnhealthyClusterNotificationMessage. Use prepareUnhealthyClusterNotificationMessage to create the input for this tool.
    Make sure to prepare the message block before sending it to this tool. Otherwise you may get errors like  "error": "Invalid message format: Message must be a dictionary containing 'blocks' created by createUnhealthyClusterNotificationMessage"
    
    Exaple Input that will be successful
    
    {
     "message": "{\"blocks\": [{\"type\": \"header\", \"text\": {\"type\": \"plain_text\", \"text\": \"Cluster Analysis Failed\", \"emoji\": true}}, {\"type\": \"section\", \"text\": {\"type\": \"mrkdwn\", \"text\": \"*Details:*\\nThe analysis of cluster 'compute-1' failed due to an issue with initializing the Kubernetes client. Please check the connectivity to the API server.\"}}, {\"type\": \"section\", \"fields\": [{\"type\": \"mrkdwn\", \"text\": \"*Cluster Name:*\\ncompute-1\"}, {\"type\": \"mrkdwn\", \"text\": \"*Cluster ID:*\\n6829f138ae13263d8013bf0a\"}, {\"type\": \"mrkdwn\", \"text\": \"*Project ID:*\\n6356fc6e381bfda21b2859c6\"}]}, {\"type\": \"section\", \"fields\": [{\"type\": \"mrkdwn\", \"text\": \"*Approximate Timestamp:*\\nMay 18, 2025 07:57 AM PST\"}]}]}",
     "webhook_url": "***********************************************************************eugELWnk"
    }
    
    Args:
        message (dict): The message blocks created by createUnhealthyClusterNotificationMessage
        webhook_url (str): The Slack webhook URL to send the message to
        
    Returns:
        MCPResult: Status of the notification delivery
    """
    with create_span("sendSlackNotificationForUnhealthyCluster") as span:
        safe_set_tool(
            span,
            name="sendSlackNotificationForUnhealthyCluster",
            description="Sends a notification message to Slack for unhealthy clusters",
            parameters={
                "message": {"type": "object", "description": "The message blocks from createUnhealthyClusterNotificationMessage"},
                "webhook_url": {"type": "string", "description": "The Slack webhook URL"}
            }
        )
        
        # Mask webhook URL in logs/traces
        masked_inputs = {
            "message": json.dumps(message),
            "webhook_url": f"{'*' * (len(webhook_url) - 8)}{webhook_url[-8:]}" if len(webhook_url) > 8 else webhook_url
        }
        safe_set_input(span, masked_inputs)

        try:
            # Validate message format
            if not isinstance(message, dict) or "blocks" not in message:
                raise ValueError("Message must be a dictionary containing 'blocks' created by createUnhealthyClusterNotificationMessage")

            blocks = message["blocks"]
            if not isinstance(blocks, list) or len(blocks) < 4:
                raise ValueError("Invalid message blocks format")

            # Validate required sections
            required_sections = ["header", "section"]
            for block in blocks:
                if "type" not in block or block["type"] not in required_sections:
                    raise ValueError("Message blocks missing required sections")

            # Parse the webhook URL to get host and path
            from urllib.parse import urlparse
            parsed_url = urlparse(webhook_url)
            
            # Set up the connection
            conn = http.client.HTTPSConnection(parsed_url.netloc)
            headers = {
                'Content-Type': 'application/json'
            }
            
            # Send the request
            payload = json.dumps(message)
            conn.request("POST", parsed_url.path, payload, headers)
            res = conn.getresponse()
            data = res.read()

            if res.status >= 400:
                raise Exception(f"Slack API request failed with status {res.status}: {data.decode('utf-8')}")

            result = {
                "status": "success",
                "message": "Unhealthy cluster notification sent successfully",
                "response": data.decode("utf-8")
            }
            safe_set_output(span, result)
            safe_set_span_status(span, "OK")
            
            return {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "isError": False
            }

        except ValueError as ve:
            error_message = f"Invalid message format: {str(ve)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(ve))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }
        except Exception as e:
            error_message = f"Error sending notification: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }

async def prepareUnhealthyClusterNotificationMessage(title: str, details: str, cluster_name: str, cluster_id: str, project_id: str) -> MCPResult:
    """Creates a formatted Slack block message for notifications about unhealthy clusters. Use this tool before sending a notification to Slack. Do not modify the output of this tool. You can convert it to a string and pass it to sendSlackNotificationForUnhealthyCluster. 
    Make sure all the fields are filled out correctly with the values received from the input.
    
    Args:
        title (str): The title for the notification header
        details (str): The details/description of the notification
        cluster_name (str): The name of the cluster
        cluster_id (str): The ID of the cluster
        project_id (str): The ID of the project
        
    Returns:
        MCPResult: The formatted Slack blocks message
    """
    with create_span("createUnhealthyClusterNotification") as span:
        safe_set_tool(
            span,
            name="createUnhealthyClusterNotification",
            description="Creates a formatted Slack block message for unhealthy cluster notifications",
            parameters={
                "title": {"type": "string", "description": "The title for the notification header"},
                "details": {"type": "string", "description": "The details/description of the notification"},
                "cluster_name": {"type": "string", "description": "The name of the cluster"},
                "cluster_id": {"type": "string", "description": "The ID of the cluster"},
                "project_id": {"type": "string", "description": "The ID of the project"}
            }
        )
        
        safe_set_input(span, {
            "title": title,
            "details": details,
            "cluster_name": cluster_name,
            "cluster_id": cluster_id,
            "project_id": project_id
        })

        try:
            pst = pytz.timezone('America/Los_Angeles')
            current_time = datetime.now(pst) - timedelta(minutes=10)
            current_timestamp = current_time.strftime("%B %d, %Y %H:%M %p PST")

            blocks = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{title}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Details:*\n{details}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Cluster Name:*\n{cluster_name}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Cluster ID:*\n{cluster_id}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Project ID:*\n{project_id}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Approximate Timestamp:*\n{current_timestamp}"
                            }
                        ]
                    }
                ]
            }

            safe_set_output(span, {"blocks": blocks})
            safe_set_span_status(span, "OK")
            
            return {
                "content": [{"type": "text", "text": json.dumps(blocks, indent=2)}],
                "isError": False
            }

        except Exception as e:
            error_message = f"Error creating notification blocks: {str(e)}"
            safe_set_output(span, {"error": error_message})
            safe_set_span_status(span, "ERROR", str(e))
            
            return {
                "content": [{"type": "text", "text": error_message}],
                "isError": True
            }
            
            
            
            
            