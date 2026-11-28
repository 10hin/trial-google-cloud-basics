"""Plan changed Terraform roots and report the results to GitHub."""

import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import urllib.request
from graphlib import TopologicalSorter


DEV_DIRECTORY = PurePosixPath("terraform/1-dev")
MANIFEST = f"{DEV_DIRECTORY}/pr-plan/roots.json"
COMMENT_LIMIT = 60000


def git(*args, env=None):
    return subprocess.check_output(["git", *args], env=env)


def is_dev_root(path):
    return path.is_relative_to(DEV_DIRECTORY) and path != DEV_DIRECTORY and ".." not in path.parts


def load_roots(contents):
    roots = json.loads(contents)
    for root, settings in roots.items():
        path = PurePosixPath(root)
        if not is_dev_root(path) or path.as_posix() != root:
            raise ValueError(f"Invalid root path: {root}")
        unknown = set(settings["depends_on"]) - roots.keys()
        if unknown:
            raise ValueError(f"{root} has unregistered dependencies: {sorted(unknown)}")
    return roots


def ordered_roots(roots, changed):
    graph = TopologicalSorter({root: info["depends_on"] for root, info in roots.items()})
    return [root for root in graph.static_order() if root in changed]


def changed_roots(roots, files):
    return {
        root for root in roots
        if any(path.startswith(root + "/") for path in files)
    }


def post_comment(repository, number, token, body):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/issues/{number}/comments",
        data=json.dumps({"body": body}).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "cloud-build-terraform-plan",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30):
        pass


def run_terraform(root, settings, plan_file):
    directory = Path(root).resolve()
    dev_directory = Path.cwd() / DEV_DIRECTORY
    if directory == dev_directory or not directory.is_relative_to(dev_directory) or not (
        list(directory.glob("*.tf")) or list(directory.glob("*.tf.json"))
    ):
        return "対象パスに Terraform 構成がありません。", 1

    env = {
        **os.environ,
        "TF_IN_AUTOMATION": "1",
        "GOOGLE_PROJECT": os.environ["TF_PROJECT"],
        "TF_VAR_project_id": os.environ["TF_PROJECT"],
    }
    # Triggers created before these substitutions were added can pass empty values.
    if env.get("TF_VAR_apply_project_roles") == "":
        del env["TF_VAR_apply_project_roles"]
    branch_pattern = env.pop("BASE_BRANCH_PATTERN_B64", "")
    if branch_pattern:
        env["TF_VAR_base_branch_pattern"] = base64.b64decode(
            branch_pattern, validate=True
        ).decode()
    command = [os.environ["TERRAFORM"], f"-chdir={directory}"]
    init = ["init", "-input=false", "-no-color"]
    if settings.get("gcs_backend"):
        init.append(f"-backend-config=bucket={os.environ['TF_STATE_BUCKET']}")

    result = subprocess.run(
        command + init, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    if result.returncode:
        return result.stdout.decode(errors="replace"), 1

    plan_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        command + [
            "plan", "-input=false", "-no-color", "-lock=false", "-detailed-exitcode",
            f"-out={plan_file}",
        ],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return result.stdout.decode(errors="replace"), result.returncode


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    number = int(os.environ["PR_NUMBER"])
    branch = os.environ["BASE_BRANCH"]
    token = os.environ.pop("GITHUB_TOKEN")
    git("check-ref-format", f"refs/heads/{branch}")
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    git_env = {
        **os.environ,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {auth}",
        "GIT_TERMINAL_PROMPT": "0",
    }
    shallow = git("rev-parse", "--is-shallow-repository").strip() == b"true"
    git(
        "fetch", "--no-tags", *(["--unshallow"] if shallow else []),
        f"https://github.com/{repository}.git",
        f"+refs/heads/{branch}:refs/terraform-plan/base",
        f"+refs/pull/{number}/head:refs/terraform-plan/head",
        env=git_env,
    )
    base = git("merge-base", "refs/terraform-plan/base", "HEAD").decode().strip()
    head = git("rev-parse", "HEAD").decode().strip()
    if git("rev-parse", "refs/terraform-plan/head").decode().strip() != head:
        raise ValueError("The build checkout does not match the current PR head")
    artifact_directory = Path(os.environ["PLAN_ARTIFACT_DIRECTORY"]).resolve()
    artifact_directory.mkdir()
    manifest = {
        "number": number,
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "project": os.environ["TF_PROJECT"],
        "build": os.environ["BUILD_ID"],
        "plans": {},
        "changed_roots": [],
    }
    files = os.fsdecode(git("diff", "--no-renames", "--name-only", "-z", base, head)).split("\0")
    files = [path for path in files if path]
    roots = load_roots(Path(MANIFEST).read_bytes())
    old_manifest = git("ls-tree", "--name-only", base, "--", MANIFEST)
    old_roots = json.loads(git("show", f"{base}:{MANIFEST}")) if old_manifest else {}
    old_dev_roots = {root for root in old_roots if is_dev_root(PurePosixPath(root))}
    selected = changed_roots(roots, files)
    removed = changed_roots(old_dev_roots - roots.keys(), files)
    sections = [f"## Terraform plan\n\nCommit `{head}` · Cloud Build `{os.environ['BUILD_ID']}`"]
    failed = False

    for root in sorted(removed):
        sections.append(f"旧ルート `{root}` は定義から削除されています。状態の扱いは別途確認してください。")
    for root in ordered_roots(roots, selected):
        plan_file = artifact_directory / root / "terraform.tfplan"
        output, exit_code = run_terraform(root, roots[root], plan_file)
        error = exit_code not in (0, 2)
        if not error:
            manifest["plans"][root] = None
        if exit_code == 2:
            manifest["changed_roots"].append(root)
        failed |= error
        output = output.replace("\x00", "")
        print(f"Terraform {root}: {'failed' if error else 'completed'}", flush=True)
        truncated = len(output.encode("utf-8")) > 48000
        if truncated:
            output = output.encode("utf-8")[:48000].decode("utf-8", errors="ignore")
        # Escape fence-like lines so arbitrary plan output stays inside the code block.
        output = re.sub(r"(?m)^([ \t]*)(````+)[ \t]*$", r"\1|\2", output)
        status = "失敗" if error else "完了"
        section = f"### `{root}` · {status}\n\n````text\n{output}\n````"
        if truncated:
            section += "\n\n出力が長いため省略しました。"
        sections.append(section)
    if not selected and not removed:
        sections.append("差分のある Terraform ルートモジュールはありません。")

    body = "\n\n".join(sections)
    if len(body.encode("utf-8")) <= COMMENT_LIMIT:
        post_comment(repository, number, token, body)
    else:
        for section in sections[1:]:
            post_comment(repository, number, token, f"{sections[0]}\n\n{section}")
    if not failed:
        (artifact_directory / "index.json").write_text(json.dumps(manifest))
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
