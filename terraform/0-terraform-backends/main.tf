data "google_billing_account" "main" {
  display_name = "main"
  open         = true
}

resource "google_project" "dev" {
  name            = "trial-gc-basics-dev"
  project_id      = "trial-gc-basics-dev"
  billing_account = data.google_billing_account.main.id
}

resource "google_project" "test" {
  name            = "trial-gc-basics-test"
  project_id      = "trial-gc-basics-test"
  billing_account = data.google_billing_account.main.id
}

resource "google_project" "prod" {
  name            = "trial-gc-basics-prod"
  project_id      = "trial-gc-basics-prod"
  billing_account = data.google_billing_account.main.id
}

locals {
  project_services = toset([
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
  ])
}

resource "google_project_service" "dev" {
  for_each = local.project_services

  project            = google_project.dev.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service" "test" {
  for_each = local.project_services

  project            = google_project.test.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_project_service" "prod" {
  for_each = local.project_services

  project            = google_project.prod.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "dev_state" {
  name                        = "trial-gc-basics-dev-state"
  location                    = "ASIA-NORTHEAST1"
  project                     = google_project.dev.project_id
  public_access_prevention    = "enforced"
  uniform_bucket_level_access = true
}

resource "google_storage_bucket" "test_state" {
  name                     = "trial-gc-basics-test-state"
  location                 = "ASIA-NORTHEAST1"
  project                  = google_project.test.project_id
  public_access_prevention = "enforced"
}

resource "google_storage_bucket" "prod_state" {
  name                     = "trial-gc-basics-prod-state"
  location                 = "ASIA-NORTHEAST1"
  project                  = google_project.prod.project_id
  public_access_prevention = "enforced"
}
