# Terraform の構成ルール

Google Cloud API の有効化が必要になった場合は、`google_project_service` リソースを `terraform/0-terraform-backends/` ルートモジュールで管理する。API を利用するルートモジュールの適用前に、`0-terraform-backends` を適用する。

dev・test・prod の全環境で有効にする API は、`terraform/0-terraform-backends/main.tf` の `local.project_services` に追加する。
