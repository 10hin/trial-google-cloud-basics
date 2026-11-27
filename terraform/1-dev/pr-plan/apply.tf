variable "github_repository_id" {
  type    = string
  default = "1465617894"

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "Specify the numeric GitHub repository ID."
  }
}

variable "apply_project_roles" {
  description = "Project roles required by the roots managed by this CI."
  type        = set(string)
  default     = []
}

resource "google_service_account" "apply" {
  account_id   = "terraform-pr-apply"
  display_name = "Terraform PR apply"
}

resource "google_project_iam_member" "apply" {
  for_each = var.apply_project_roles

  project = var.project_id
  role    = each.value
  member  = google_service_account.apply.member
}

resource "google_storage_bucket_iam_member" "apply" {
  bucket = var.state_bucket
  role   = "roles/storage.objectAdmin"
  member = google_service_account.apply.member
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "terraform-pr-apply"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"

  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
  }

  attribute_condition = <<-CEL
    assertion.repository_id == '${var.github_repository_id}' &&
    assertion.event_name == 'pull_request_target' &&
    assertion.ref == 'refs/heads/main' &&
    assertion.workflow_ref == assertion.repository + '/.github/workflows/pr-apply.yml@refs/heads/main'
  CEL

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github" {
  service_account_id = google_service_account.apply.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "service_account_email" {
  value = google_service_account.apply.email
}
