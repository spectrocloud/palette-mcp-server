# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

resource "spectrocloud_cluster_brownfield" "kind-cluster" {
  name        = "kind-cli-cluster-${regex("^([a-f0-9]{8})-", uuid())[0]}"
  cloud_type  = "generic"
  context     = "project"
  import_mode = "full"

  description      = "Palette MCP server e2e test cluster"
  cluster_timezone = "America/Phoenix"
  tags             = concat(var.tags, ["environment:test", "team:ai-research-team"])

  cluster_profile {
    id = spectrocloud_cluster_profile.add-on-profile.id
  }
}


output "kubectl_command" {
  value     = spectrocloud_cluster_brownfield.kind-cluster.kubectl_command
  sensitive = false
}

output "cluster_uid" {
  value     = spectrocloud_cluster_brownfield.kind-cluster.id
  sensitive = false
}
