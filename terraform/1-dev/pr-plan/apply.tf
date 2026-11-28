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
  for_each = setunion(var.apply_project_roles, toset(["roles/logging.logWriter"]))

  project = var.project_id
  role    = each.value
  member  = google_service_account.apply.member
}

resource "google_storage_bucket_iam_member" "apply" {
  bucket = var.state_bucket
  role   = "roles/storage.objectAdmin"
  member = google_service_account.apply.member
}

resource "google_secret_manager_secret_iam_member" "apply_github_token" {
  secret_id = google_secret_manager_secret.github_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.apply.member
}

resource "google_cloudbuild_trigger" "apply" {
  name            = "terraform-pr-apply"
  location        = "global"
  service_account = google_service_account.apply.id
  filename        = "terraform/1-dev/pr-plan/cloudbuild-apply.yaml"

  github {
    owner = split("/", var.github_repository)[0]
    name  = split("/", var.github_repository)[1]

    push {
      branch = var.base_branch_pattern
    }
  }

  substitutions = {
    _GITHUB_REPOSITORY = var.github_repository
    _TF_PROJECT        = var.project_id
    _TF_STATE_BUCKET   = var.state_bucket
  }

  depends_on = [
    google_project_iam_member.apply,
    google_storage_bucket_iam_member.apply,
    google_secret_manager_secret_iam_member.apply_github_token,
  ]
}

output "service_account_email" {
  value = google_service_account.apply.email
}
