# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

resource "spectrocloud_cluster_profile" "add-on-profile" {


  name        = "add-on-profile"
  description = "A deployment test profile the Palette MCP server e2e tests"
  tags        = concat(var.tags, ["env:test"])
  cloud       = "all"
  type        = "add-on"
  version     = "1.0.0"

  pack {
    name   = data.spectrocloud_pack_simple.hello-universe.name
    tag    = data.spectrocloud_pack_simple.hello-universe.version
    uid    = data.spectrocloud_pack_simple.hello-universe.id
    values = data.spectrocloud_pack_simple.hello-universe.values
  }
}


resource "spectrocloud_cluster_profile" "delete-profile" {


  name        = "to-be-deleted"
  description = "A deployment test profile the Palette MCP server e2e tests"
  tags        = concat(var.tags, ["env:test"])
  cloud       = "all"
  type        = "add-on"
  version     = "1.0.0"

  pack {
    name   = data.spectrocloud_pack_simple.hello-universe.name
    tag    = data.spectrocloud_pack_simple.hello-universe.version
    uid    = data.spectrocloud_pack_simple.hello-universe.id
    values = data.spectrocloud_pack_simple.hello-universe.values
  }
}
