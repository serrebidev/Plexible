"""Linux and macOS half of a release from the Windows release host.

Run once the Windows release is published: dispatches macos-release.yml on the
Forgejo Mac runner, builds Linux over SSH with tools/build_linux_remote.sh,
uploads it to the Forgejo release (needs FORGEJO_TOKEN), and waits for the
macOS asset. cloud-release.yml (Muse and cloud agents) has its own jobs for
both, so this does nothing on Actions.

    python tools/release_other_platforms.py vX.Y.Z
"""
import json
import os
import posixpath
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import forgejo_release as fj  # noqa: E402

HOST = os.environ.get("LINUX_BUILD_HOST", "wsl-build")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_PATH = f"/repos/{fj.DEFAULT_OWNER}/{fj.DEFAULT_REPO}"


def run(*cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, check=True, **kw)


def main(tag):
    if os.environ.get("GITHUB_ACTIONS"):
        return
    token = os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        sys.exit("FORGEJO_TOKEN is not set.")
    fj._request("POST", fj._api_url(fj.DEFAULT_HOST, f"{REPO_PATH}/actions/workflows/macos-release.yml/dispatches"),
                token, json.dumps({"ref": "main", "inputs": {"release_tag": tag}}).encode("utf-8"),
                "application/json")

    print(f"Building Linux for {tag} on {HOST}...", flush=True)
    with open(os.path.join(ROOT, "tools", "build_linux_remote.sh"), "rb") as script:
        out = run("ssh", "-o", "BatchMode=yes", HOST, "bash", "-s", "--", tag,
                  stdin=script, stdout=subprocess.PIPE).stdout
    remote = out.decode().strip().splitlines()[-1]
    local = os.path.join(ROOT, "dist", posixpath.basename(remote))
    os.makedirs(os.path.dirname(local), exist_ok=True)
    run("scp", "-o", "BatchMode=yes", f"{HOST}:{remote}", local)
    if remote.startswith("/tmp/"):
        run("ssh", "-o", "BatchMode=yes", HOST, "rm -rf -- " + posixpath.dirname(remote))
    run(sys.executable, os.path.join(ROOT, "tools", "forgejo_release.py"),
        "upload", tag, local)

    mac_asset = f"Plexible-{tag}-macos.zip"
    print(f"Waiting for the macOS asset ({mac_asset})...", flush=True)
    deadline = time.time() + 60 * 60
    while time.time() < deadline:
        release = fj.get_release_by_tag(fj.DEFAULT_HOST, fj.DEFAULT_OWNER, fj.DEFAULT_REPO, tag, token) or {}
        if any(a.get("name") == mac_asset for a in release.get("assets") or []):
            print(f"{tag}: Linux and macOS assets attached.")
            return
        time.sleep(30)
    sys.exit(f"{tag}: macOS asset never arrived; check macos-release.yml on Forgejo and "
             f"redispatch with release_tag={tag}.")


if __name__ == "__main__":
    main(sys.argv[1])
