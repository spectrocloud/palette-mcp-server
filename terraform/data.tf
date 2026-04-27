# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

data "spectrocloud_pack_simple" "hello-universe" {
  name         = "hello-universe"
  version      = "1.3.1"
  type         = "container"
  registry_uid = "64eaff5630402973c4e1856a"
}
