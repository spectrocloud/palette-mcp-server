# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

terraform {
  required_providers {
    spectrocloud = {
      source  = "spectrocloud/spectrocloud"
      version = "0.28.4"
    }
  }
}

provider "spectrocloud" {
  api_key      = var.api_key
  project_name = var.project_name
}
