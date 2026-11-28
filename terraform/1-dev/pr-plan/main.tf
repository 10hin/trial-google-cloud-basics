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
    prefix = "1-dev"
  }
}

provider "google" {
  project = var.project_id
}

variable "project_id" {
  type    = string
  default = "trial-gc-basics-dev"
}

variable "github_repository" {
  type    = string
  default = "10hin/trial-google-cloud-basics"

  validation {
    condition     = can(regex("^[a-zA-Z0-9-]+/[a-zA-Z0-9_.-]+$", var.github_repository))
    error_message = "Specify the GitHub repository as OWNER/REPO."
  }
}

variable "base_branch_pattern" {
  type    = string
  default = "^main$"
}

variable "state_bucket" {
  type    = string
  default = "trial-gc-basics-dev-state"
}

removed {
  from = google_project_service.pipeline

  lifecycle {
    destroy = false
  }
}

resource "google_service_account" "plan" {
  account_id   = "terraform-pr-plan"
  display_name = "Terraform PR plan"
}

resource "google_project_iam_member" "plan" {
  for_each = toset(["roles/iam.viewer", "roles/logging.logWriter", "roles/viewer"])

  project = var.project_id
  role    = each.value
  member  = google_service_account.plan.member
}

resource "google_storage_bucket_iam_member" "plan" {
  bucket = var.state_bucket
  role   = "roles/storage.objectViewer"
  member = google_service_account.plan.member
}

resource "google_storage_bucket_iam_member" "plan_artifacts" {
  bucket = var.state_bucket
  role   = "roles/storage.objectUser"
  member = google_service_account.plan.member

  condition {
    title      = "terraform-pr-plan-artifacts"
    expression = "resource.name.startsWith('projects/_/buckets/${var.state_bucket}/objects/pr-plans/')"
  }
}

moved {
  from = google_storage_bucket_iam_member.artifact_repositories_state_init
  to   = google_storage_bucket_iam_member.plan_state_init
}

resource "google_storage_bucket_iam_member" "plan_state_init" {
  bucket = var.state_bucket
  role   = "roles/storage.objectUser"
  member = google_service_account.plan.member

  condition {
    title = "terraform-pr-plan-dev-state-init"
    expression = join(" && ", [
      "resource.type == 'storage.googleapis.com/Object'",
      "resource.name.startsWith('projects/_/buckets/${var.state_bucket}/objects/1-dev/')",
      "(resource.name.endsWith('/default.tfstate') || resource.name.endsWith('/default.tflock'))",
      # The PR pipeline itself stores state directly under 1-dev/.
      "resource.name != 'projects/_/buckets/${var.state_bucket}/objects/1-dev/default.tfstate'",
      "resource.name != 'projects/_/buckets/${var.state_bucket}/objects/1-dev/default.tflock'",
    ])
  }
}

resource "google_project_iam_custom_role" "state_bucket_iam_reader" {
  project     = var.project_id
  role_id     = "terraformPrPlanStateBucketIamReader"
  title       = "Terraform PR plan state bucket IAM reader"
  permissions = ["storage.buckets.getIamPolicy"]
}

resource "google_storage_bucket_iam_member" "plan_iam_reader" {
  bucket = var.state_bucket
  role   = google_project_iam_custom_role.state_bucket_iam_reader.name
  member = google_service_account.plan.member
}

resource "google_secret_manager_secret" "github_token" {
  secret_id = "terraform-pr-plan-github-token"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "github_token" {
  secret_id = google_secret_manager_secret.github_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.plan.member
}

resource "google_cloudbuild_trigger" "plan" {
  name            = "terraform-pr-plan"
  location        = "global"
  service_account = google_service_account.plan.id
  filename        = "terraform/1-dev/pr-plan/cloudbuild.yaml"

  github {
    owner = split("/", var.github_repository)[0]
    name  = split("/", var.github_repository)[1]

    pull_request {
      branch          = var.base_branch_pattern
      comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    }
  }

  approval_config {
    approval_required = false
  }

  substitutions = {
    _GITHUB_REPOSITORY       = var.github_repository
    _TF_PROJECT              = var.project_id
    _TF_STATE_BUCKET         = var.state_bucket
    _BASE_BRANCH_PATTERN_B64 = base64encode(var.base_branch_pattern)
    _APPLY_PROJECT_ROLES     = jsonencode(sort(tolist(var.apply_project_roles)))
  }

  depends_on = [
    google_project_iam_member.plan,
    google_storage_bucket_iam_member.plan,
    google_storage_bucket_iam_member.plan_iam_reader,
    google_storage_bucket_iam_member.plan_artifacts,
    google_secret_manager_secret_iam_member.github_token,
  ]
}

output "github_token_secret_id" {
  value = google_secret_manager_secret.github_token.secret_id
}
