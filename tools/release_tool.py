import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


SEMVER_TAG_RE = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?$")
VERSION_RE = re.compile(r'APP_VERSION\s*=\s*"([^"]+)"')
MIN_VERSION = (1, 38, 0)


def _run_git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _parse_tag(tag: str) -> Optional[Tuple[int, int, int]]:
    match = SEMVER_TAG_RE.match(tag.strip())
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def _latest_semver_tag() -> Tuple[Optional[str], Optional[Tuple[int, int, int]]]:
    tags = _run_git("tag").splitlines()
    versions: List[Tuple[Tuple[int, int, int], str]] = []
    for tag in tags:
        parsed = _parse_tag(tag)
        if parsed is None:
            continue
        versions.append((parsed, tag))
    if not versions:
        return None, None
    versions.sort(key=lambda item: item[0], reverse=True)
    return versions[0][1], versions[0][0]


def _collect_commits(range_spec: str) -> List[Tuple[str, str]]:
    log = _run_git("log", range_spec, "--pretty=format:%s%x1f%b%x1e")
    entries: List[Tuple[str, str]] = []
    for record in log.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f", 1)
        subject = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else ""
        entries.append((subject, body))
    return entries


def _classify_commit(subject: str, body: str) -> str:
    subject_lower = subject.lower()
    text = f"{subject}\n{body}".lower()
    if "breaking change" in text or "!:" in text:
        return "breaking"
    if subject_lower.startswith("feat") or "feature" in text:
        return "feature"
    if subject_lower.startswith("fix") or "fix" in text or "bug" in text:
        return "fix"
    return "other"


def _determine_bump(commits: Iterable[Tuple[str, str]]) -> str:
    bump = "patch"
    for subject, body in commits:
        category = _classify_commit(subject, body)
        if category == "breaking":
            return "major"
        if category == "feature":
            bump = "minor"
    return bump


def _next_version(current: Optional[Tuple[int, int, int]], bump: str) -> Tuple[int, int, int]:
    if current is None:
        return 1, 4, 2
    major, minor, patch = current
    if bump == "major":
        return major + 1, 0, 0
    if bump == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def _render_release_notes(commits: List[Tuple[str, str]]) -> str:
    groups = {"breaking": [], "feature": [], "fix": [], "other": []}
    for subject, body in commits:
        groups[_classify_commit(subject, body)].append(subject)

    sections: List[str] = []
    if groups["breaking"]:
        sections.append("## Breaking")
        sections.extend(f"- {item}" for item in groups["breaking"])
        sections.append("")
    if groups["feature"]:
        sections.append("## Features")
        sections.extend(f"- {item}" for item in groups["feature"])
        sections.append("")
    if groups["fix"]:
        sections.append("## Fixes")
        sections.extend(f"- {item}" for item in groups["fix"])
        sections.append("")
    if groups["other"]:
        sections.append("## Other")
        sections.extend(f"- {item}" for item in groups["other"])
        sections.append("")
    return "\n".join(sections).strip() + "\n"


def _update_version_file(path: Path, version: str) -> None:
    content = path.read_text(encoding="utf-8")
    if not VERSION_RE.search(content):
        raise RuntimeError(f"APP_VERSION not found in {path}")
    updated = VERSION_RE.sub(f'APP_VERSION = "{version}"', content)
    path.write_text(updated, encoding="utf-8")


def _compute(args: argparse.Namespace) -> int:
    last_tag, last_version = _latest_semver_tag()
    range_spec = f"{last_tag}..HEAD" if last_tag else "HEAD"
    commits = _collect_commits(range_spec)
    bump = _determine_bump(commits)
    next_version = _next_version(last_version, bump)
    if last_version is not None and next_version < MIN_VERSION:
        next_version = MIN_VERSION
    version_str = f"{next_version[0]}.{next_version[1]}.{next_version[2]}"
    if args.version_file and args.apply:
        _update_version_file(Path(args.version_file), version_str)
    if args.notes_file:
        notes = _render_release_notes(commits)
        Path(args.notes_file).write_text(notes, encoding="utf-8")

    print(f"NEXT_VERSION={version_str}")
    print(f"NEXT_TAG=v{version_str}")
    print(f"LAST_TAG={last_tag or ''}")
    return 0


def _manifest(args: argparse.Namespace) -> int:
    notes = ""
    if args.notes_file:
        notes = Path(args.notes_file).read_text(encoding="utf-8").strip()
        if len(notes) > 2000:
            notes = notes[:1997] + "..."
    manifest = {
        "version": args.version,
        "asset": args.asset_name,
        "download_url": args.download_url,
        "sha256": args.sha256,
        "published_at": args.published_at,
        "notes": notes,
    }
    Path(args.output).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Release helper for Plexible.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compute_parser = subparsers.add_parser("compute")
    compute_parser.add_argument("--version-file", dest="version_file")
    compute_parser.add_argument("--notes-file", dest="notes_file")
    compute_parser.add_argument("--apply", action="store_true")
    compute_parser.set_defaults(func=_compute)

    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--version", required=True)
    manifest_parser.add_argument("--asset-name", required=True)
    manifest_parser.add_argument("--download-url", required=True)
    manifest_parser.add_argument("--sha256", required=True)
    manifest_parser.add_argument("--published-at", required=True)
    manifest_parser.add_argument("--notes-file")
    manifest_parser.add_argument("--output", required=True)
    manifest_parser.set_defaults(func=_manifest)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
