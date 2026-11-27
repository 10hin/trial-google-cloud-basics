"""Apply saved Terraform plans from the merged PR."""

import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from artifacts import Storage, artifact_prefix, digest, plan_object
from plan import DEV_DIRECTORY, MANIFEST, git, load_roots, ordered_roots


def apply_plan(root, settings, plan_file):
    directory = Path(root).resolve()
    dev_directory = Path(DEV_DIRECTORY).resolve()
    if directory == dev_directory or not directory.is_relative_to(dev_directory) or not (
        list(directory.glob("*.tf")) or list(directory.glob("*.tf.json"))
    ):
        raise ValueError(f"No Terraform configuration in {root}")

    print(f"Applying saved plan for {root}", flush=True)
    terraform = ["terraform", f"-chdir={directory}"]
    init = ["init", "-input=false", "-no-color"]
    if settings.get("gcs_backend"):
        init.append(f"-backend-config=bucket={os.environ['TF_STATE_BUCKET']}")

    subprocess.run(terraform + init, check=True)
    subprocess.run(
        terraform + ["apply", "-input=false", "-no-color", "-lock-timeout=5m", str(plan_file)],
        check=True,
    )


def main():
    project = os.environ["GOOGLE_PROJECT"]
    bucket = os.environ["TF_STATE_BUCKET"]
    if not project or not bucket:
        raise ValueError("Set TF_APPLY_PROJECT and TF_APPLY_STATE_BUCKET in GitHub Actions.")

    number = int(os.environ["PR_NUMBER"])
    head = os.environ["PR_HEAD"]
    prefix = artifact_prefix(number, head)
    storage = Storage(bucket)
    with storage.open(f"{prefix}/index.json") as index:
        manifest = json.load(index)

    if (manifest["number"], manifest["head"], manifest["project"]) != (number, head, project):
        raise ValueError("Saved plan index does not match this PR and project")

    roots = load_roots(Path(MANIFEST).read_bytes())
    plans = manifest["plans"]
    if plans.keys() - roots.keys():
        raise ValueError("Saved plan index contains unregistered roots")
    if "changed_roots" not in manifest:
        raise ValueError("Saved plan index has no change information. Rerun the PR plan build.")
    changed = set(manifest["changed_roots"])
    if changed - plans.keys():
        raise ValueError("Saved plan index lists changed roots without plan files")
    selected = ordered_roots(roots, changed)
    if not selected:
        print("No saved plans with Terraform changes.")
        return
    if manifest["tree"] != git("rev-parse", "HEAD^{tree}").decode().strip():
        raise ValueError("The merged source tree differs from the planned PR source tree")

    with TemporaryDirectory(prefix="terraform-pr-plans-") as temp:
        downloaded = {}
        for root in selected:
            local_plan = Path(temp) / root / "terraform.tfplan"
            local_plan.parent.mkdir(parents=True, exist_ok=True)
            storage.download(plan_object(prefix, manifest["build"], root), local_plan)
            if digest(local_plan) != plans[root]:
                raise ValueError(f"Saved plan checksum mismatch for {root}")
            downloaded[root] = local_plan

        for root in selected:
            apply_plan(root, roots[root], downloaded[root])


if __name__ == "__main__":
    main()
