# Pull Request の Terraform plan

Cloud Build が `main` 宛ての PR の作成・更新を検知します。リポジトリの書き込み権限を持たない投稿者の PR は、書き込み権限を持つユーザーの `/gcbrun` コメントで起動します。ビルドは PR のコードと Terraform 構成を実行するため、コメントで起動する前にその内容を確認してください。[Cloud Build の GitHub トリガー](https://docs.cloud.google.com/build/docs/automating-builds/github/build-repos-from-github)

## 導入

1. `terraform/0-terraform-backends` を適用し、開発用プロジェクトと state バケットを作成します。
2. 開発用プロジェクトで Cloud Build API を有効にし、Cloud Build で GitHub リポジトリを第 1 世代の GitHub App 接続として登録します。`main.tf` のデフォルトは `10hin/trial-google-cloud-basics` と `main` です。
3. この構成をリポジトリへ配置し、`terraform -chdir=terraform/1-dev/pr-plan init` と `terraform -chdir=terraform/1-dev/pr-plan apply` を実行します。別の state バケットを使う場合は、初期化時の `-backend-config=bucket=...` と `state_bucket` 変数に同じ名前を指定します。
4. 対象リポジトリに限定した GitHub の fine-grained PAT を作成します。リポジトリ権限は **Contents: Read-only** と **Pull requests: Read and write** を指定し、Secret Manager の `terraform-pr-plan-github-token` に有効なシークレットバージョンとして登録します。[GitHub のコメント投稿 API](https://docs.github.com/en/rest/issues/comments#create-an-issue-comment)
5. 登録済みルートのファイルを変更する PR を作成し、Cloud Build の実行と PR コメントを確認します。

ビルド用サービスアカウントには開発用プロジェクトの参照権限と指定バケットのオブジェクト参照権限を付与します。plan は state のロックを取得せずに実行します。

## ルートモジュールの登録

[roots.json](roots.json) に `terraform/1-dev/` 配下のルートのリポジトリ相対パスと、登録済みルートへの依存関係を `depends_on` に指定します。現在の登録対象は `terraform/1-dev/pr-plan` です。依存する両方のルートに変更がある場合は依存先から plan し、片方にだけ変更がある場合はそのルートだけを plan します。別ルートの state を参照する plan には、適用済みの出力が使われます。

`gcs_backend: true` を指定したルートでは、初期化時に `state_bucket` を渡します。ルートの追加後は、そのディレクトリ配下のファイル差分が検出対象になります。比較範囲はベースブランチとビルド対象コミットの共通祖先から、ビルド対象コミットまでです。plan の失敗もコメントに含め、ビルドを失敗として記録します。長い結果はルート単位で投稿し、1 ルートの出力が約 48 KB を超える場合はコメント内で省略します。
