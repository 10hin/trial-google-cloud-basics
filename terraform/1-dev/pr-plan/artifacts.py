"""Publish and retrieve saved plans in the state bucket's artifact prefix."""

import json
import os
from pathlib import Path
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from hashlib import file_digest


def artifact_prefix(number, head):
    if int(number) <= 0 or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("Invalid PR number or head commit")
    return f"pr-plans/{int(number)}/{head}"


def plan_object(prefix, build, root):
    if not re.fullmatch(r"[0-9a-f-]{36}", build):
        raise ValueError("Invalid Cloud Build ID")
    return f"{prefix}/{build}/{root}/terraform.tfplan"


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def build_access_token():
    request = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            token = json.load(response)["access_token"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError(f"Could not obtain Cloud Build service account token: {error}") from error
    if not isinstance(token, str) or not token:
        raise RuntimeError("Cloud Build metadata server returned an empty or invalid access token")
    return token


class Storage:
    def __init__(self, bucket):
        self.bucket = urllib.parse.quote(bucket, safe="")
        token = build_access_token()
        self.headers = {"Authorization": f"Bearer {token}"}

    def upload(self, name, path):
        query = urllib.parse.urlencode({"uploadType": "media", "name": name})
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o?{query}"
        headers = {
            **self.headers,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(path.stat().st_size),
        }
        with path.open("rb") as stream:
            request = urllib.request.Request(url, data=stream, headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=120):
                pass

    def open(self, name):
        object_name = urllib.parse.quote(name, safe="")
        url = f"https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/{object_name}?alt=media"
        return urllib.request.urlopen(urllib.request.Request(url, headers=self.headers), timeout=120)

    def download(self, name, path):
        with self.open(name) as source, path.open("xb") as destination:
            shutil.copyfileobj(source, destination)


def publish(directory):
    manifest_path = directory / "index.json"
    manifest = json.loads(manifest_path.read_bytes())
    prefix = artifact_prefix(manifest["number"], manifest["head"])
    storage = Storage(os.environ["TF_STATE_BUCKET"])
    for root in manifest["plans"]:
        local_plan = directory / root / "terraform.tfplan"
        manifest["plans"][root] = digest(local_plan)
        storage.upload(plan_object(prefix, manifest["build"], root), local_plan)
    # Publish the index only after every referenced object is available.
    manifest_path.write_text(json.dumps(manifest))
    storage.upload(f"{prefix}/index.json", manifest_path)


def main(directory):
    from plan import post_comment

    token = os.environ.pop("GITHUB_TOKEN")
    build = os.environ["BUILD_ID"]
    print(f"Publishing saved Terraform plans for Cloud Build {build}", flush=True)
    try:
        publish(directory)
    except Exception as error:
        if isinstance(error, urllib.error.HTTPError):
            detail = f"Cloud Storage HTTP {error.code} ({error.reason})"
        else:
            detail = f"{type(error).__name__}: {error}"
        print(f"Saved Terraform plan upload failed: {detail}", file=sys.stderr, flush=True)
        body = (
            f"## Terraform plan の保存に失敗しました\n\n"
            f"Cloud Build `{build}`\n\n"
            f"{detail}"
        )
        try:
            post_comment(os.environ["GITHUB_REPOSITORY"], int(os.environ["PR_NUMBER"]), token, body)
        except Exception as comment_error:
            print(f"Could not post the failure comment: {comment_error}", file=sys.stderr, flush=True)
        return 1
    print("Saved Terraform plans uploaded", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
