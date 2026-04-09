# E2E Test Coverage

## Tested

| Tool | Action | Notes |
|------|--------|-------|
| `gather_or_delete_clusterprofiles` | `list` | compact=True (default) |
| `gather_or_delete_clusterprofiles` | `get` | by UID |
| `gather_or_delete_clusterprofiles` | `delete` | `to-be-deleted` profile |
| `gather_or_delete_clusters` | `list` | `active_only=True` |
| `gather_or_delete_clusters` | `get` | by UID |
| `gather_or_delete_clusters` | `delete` | normal delete |
| `search_and_manage_resource_tags` | `get` | clusterprofiles + spectroclusters |
| `search_and_manage_resource_tags` | `create` | clusterprofiles + spectroclusters |
| `search_and_manage_resource_tags` | `delete` | clusterprofiles + spectroclusters |

## Not Tested

| Tool | Gap |
|------|-----|
| `getKubeconfig` | Completely untested — both regular and admin kubeconfig paths |
| `gather_or_delete_clusters` | `active_only=False` (list all clusters) |
| `gather_or_delete_clusters` | `force_delete=True` |
| `gather_or_delete_clusterprofiles` | `compact=False` (full payload) |
| `gather_or_delete_clusters` | `compact=False` (full payload) |
| `gather_or_delete_*` | Pagination via `limit` + `continue_token` |
| `search_and_manage_resource_tags` | `action=list` (list all tags for a type) |
| `search_and_manage_resource_tags` | `resource_type=clusterTemplates` |
| `search_and_manage_resource_tags` | `resource_type=edgehosts` |
| `search_and_manage_resource_tags` | `resource_type=policy` |
