# Pull Request の Terraform plan と apply

Cloud Build が `main` 宛ての PR の作成・更新を検知します。リポジトリの書き込み権限を持たない投稿者の PR は、書き込み権限を持つユーザーの `/gcbrun` コメントで起動します。起動したビルドは Cloud Build の承認待ちを挟まずに plan を実行します。ビルドは PR のコードと Terraform 構成を実行し、後続の apply が使うファイルを書き込むため、外部投稿者の PR をコメントで起動する前に対象コミットとその実行内容をレビューしてください。[Cloud Build の GitHub トリガー](https://docs.cloud.google.com/build/docs/automating-builds/github/build-repos-from-github)

## 導入

1. 管理者の認証で `terraform/0-terraform-backends` を適用し、dev・test・prod のプロジェクトと state バケットを作成して、Cloud Build、Cloud Resource Manager、Secret Manager、IAM、Service Account Credentials、Security Token Service の API を有効にします。
2. Cloud Build で GitHub リポジトリを第 1 世代の GitHub App 接続として登録します。既定の対象は `10hin/trial-google-cloud-basics` の `main` です。
3. `terraform -chdir=terraform/1-dev/pr-plan init` と `terraform -chdir=terraform/1-dev/pr-plan apply` を実行します。`github_repository_id` の既定値はこのリポジトリの数値 ID（`1465617894`）です。`apply_project_roles` の既定値は空集合です。自動適用に必要なプロジェクトロールは、このルートの `terraform.tfvars` に指定します。別の state バケットを使う場合は、初期化時に `-backend-config=bucket=...` を渡し、`state_bucket` にも同じ値を指定します。
4. 対象リポジトリに限定した GitHub の fine-grained PAT を作成します。リポジトリ権限は **Contents: Read-only** と **Pull requests: Read and write** を指定し、Secret Manager の `terraform-pr-plan-github-token` に有効なシークレットバージョンとして登録します。[GitHub のコメント投稿 API](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment)
5. GitHub のリポジトリ設定で Actions の変数を登録します。

   | 変数 | 値 |
   | --- | --- |
   | `TF_APPLY_PROJECT` | `project_id`（既定値 `trial-gc-basics-dev`） |
   | `TF_APPLY_STATE_BUCKET` | `state_bucket`（既定値 `trial-gc-basics-dev-state`） |
   | `TF_APPLY_WORKLOAD_IDENTITY_PROVIDER` | Terraform 出力 `workload_identity_provider` |
   | `TF_APPLY_SERVICE_ACCOUNT` | Terraform 出力 `service_account_email` |

6. 後続の PR の対象コミットをレビューし、plan ビルドの成功を確認してからマージします。マージ後は GitHub Actions の結果を確認します。

plan と apply の CI リソースは、既存の GCS state プレフィックス `1-dev` を使います。旧構成で `google_project_service.pipeline` を管理していた場合、バックエンドルートが API を管理下に取り込み、このルートの `removed` ブロックが旧リソースを state から外します。すでに旧 `1-dev/pr-apply` state にリソースを作成している場合は、適用前にそのリソースの state を既存の `1-dev` state に移してください。Terraform リソースのアドレスは同じです。

plan と apply は専用サービスアカウントを個別に使います。plan は state を読み取り、ロックを取得せずに実行します。apply は Workload Identity Federation で短期認証します。このルートを自動適用するには、apply 用サービスアカウントに Cloud Build トリガー、IAM、Workload Identity Federation、state バケット IAM、Secret Manager を管理する権限が必要です。plan 用サービスアカウントに対する `iam.serviceAccounts.actAs` と、対象バケットの IAM 管理権限は、管理者がリソース単位で付与できます。[Google Cloud の Workload Identity Federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines)

## ルートモジュールの登録

[roots.json](roots.json) に `terraform/1-dev/` 配下のルートのリポジトリ相対パスと、登録済みルートへの依存関係を `depends_on` に指定します。現在の登録対象は `terraform/1-dev/pr-plan` です。依存する両方のルートに変更がある場合は依存先から plan し、片方にだけ変更がある場合はそのルートだけを plan します。別ルートの state を参照する plan には、適用済みの出力が使われます。

`gcs_backend: true` を指定したルートでは、初期化時に `state_bucket` を渡します。ルートの追加後は、そのディレクトリ配下のファイル差分が検出対象になります。比較範囲はベースブランチとビルド対象コミットの共通祖先から、ビルド対象コミットまでです。plan の失敗もコメントに含め、ビルドを失敗として記録します。長い結果はルート単位で投稿し、1 ルートの出力が約 48 KB を超える場合はコメント内で省略します。

## 保存済み plan

各ルートの plan が成功すると、ビルドは state バケットの `pr-plans/<PR番号>/<PRのhead SHA>/<Cloud Build ID>/<ルートパス>/terraform.tfplan` にバイナリを保存します。必要なファイルをすべてアップロードしてから、同じ PR と head SHA の直下に `index.json` を公開します。索引には Terraform が差分ありと判定したルートも記録します。再実行が成功すると index が新しいビルドを参照します。失敗したビルドは index を更新しません。GCS の一律のバケットレベル アクセスを有効にすると、条件付き IAM でビルドのオブジェクト書き込み権限を `pr-plans/` 配下に制限できます。既定の dev バケットはこの設定を使います。別バケットでも同じ設定を有効にしてください。

バイナリの plan には機密値が含まれる場合があります。state と同じ水準でアクセスを管理してください。[Terraform の保存済み plan](https://developer.hashicorp.com/terraform/cli/commands/plan#out-filename)

## PR マージ後の apply

GitHub Actions は `main` 宛ての PR がマージされると、そのマージ結果をチェックアウトします。同じ PR 番号と head SHA の保存済み plan を取得し、Terraform が差分ありと判定した保存済み plan をすべて依存順に `terraform apply <planファイル>` で適用します。差分のある plan がなければ適用をスキップします。[GitHub Actions のイベント](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)

マージ前に PR のブランチを `main` に追従させ、最新の head の Cloud Build が成功したことを確認してください。差分情報が記録される前の索引を使っている場合は、マージ前に plan を再実行してください。plan を取得できない場合、マージ結果のファイルツリーが plan 時点と異なる場合、Terraform が state の変更により plan を古いと判定した場合は停止します。複数ルートの適用中に失敗した場合、先に成功したルートの変更は適用済みです。
