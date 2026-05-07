# Build and Release

Plexible releases are produced from Windows because the packaged app depends on
PyInstaller, wxPython, LibVLC, and Authenticode signing.

## Local Build

```batch
build_exe.bat build
```

This builds, signs, zips, and writes local update metadata without creating a
git tag or GitHub release.

## Release

```batch
build_exe.bat release
```

This is the release path. It computes the next version from git tags, updates
`plex_client/version.py`, builds from `plexible.spec`, signs `Plexible.exe`,
creates the release zip and `Plexible-update.json`, commits the version bump,
tags it, pushes the commit and tag, and creates the GitHub release.

## Draft Release Policy

Draft releases are not allowed for Plexible.

- Do not use `gh release create --draft`.
- Do not use the GitHub UI's draft release flow.
- Before a release, delete any GitHub release where `draft == true`.
- After a release, verify that the latest release has `draft == false` and that
  no release returned by the GitHub Releases API is a draft.

The `Codex Release` GitHub Actions workflow follows this policy and still uses
`build_exe.bat release` as the release command.
