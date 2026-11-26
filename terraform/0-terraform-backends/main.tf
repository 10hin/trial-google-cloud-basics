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

resource "google_storage_bucket" "dev_state" {
  name                     = "trial-gc-basics-dev-state"
  location                 = "ASIA-NORTHEAST1"
  project                  = google_project.dev.project_id
  public_access_prevention = "enforced"
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
