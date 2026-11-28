terraform {
  required_version = ">= 1.11"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.12"
    }
  }

  backend "gcs" {
    bucket = "trial-gc-basics-dev-state"
    prefix = "1-dev/artifact-repositories"
  }
}

provider "google" {
  project = "trial-gc-basics-dev"
}

locals {
  repository_ids = toset(["echo"])
}

resource "google_artifact_registry_repository" "repositories" {
  for_each = local.repository_ids

  location      = "asia-northeast1"
  repository_id = each.key
  format        = "DOCKER"
}
