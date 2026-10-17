# Contributing

## Development setup

Work from the source code, in a virtual environment (Windows notes: [INSTALL.md](INSTALL.md)):

```bash
git clone https://github.com/hashtagRR/AnonTestLab.git
cd AnonTestLab
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,dashboard]"
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

Tests and lint are what CI runs on every push (`.github/workflows/ci.yml`). Describe each change
under **Unreleased** at the top of [CHANGELOG.md](CHANGELOG.md).

## Releasing

Releases run from GitHub Actions; nothing is uploaded from a personal machine.

1. Make sure the changelog's **Unreleased** section describes the release.
2. On GitHub, open **Actions**, choose **release**, press **Run workflow** on `main`, and give the
   version (for example `0.5.1`) and, optionally, words for the title.
3. The workflow tests `main`, sets the version in `pyproject.toml` and `anontestlab/__init__.py`,
   dates the changelog section (leaving an empty **Unreleased** heading for the next changes),
   builds and checks the packages, and pushes the commit "Release X.Y.Z" and the tag `vX.Y.Z`.
4. The PyPI upload then waits for approval in the `pypi` environment. Approving it publishes to
   PyPI with Trusted Publishing (no token), and the GitHub release is created with the changelog
   section as its notes. Zenodo archives that release and gives it a DOI.

`python scripts/release.py X.Y.Z --notes notes.md` shows locally what step 3 changes (`git diff`;
undo with `git checkout .`). If the run stops after step 3 (approval declined, upload failed), the
commit and tag are already on GitHub: either approve a rerun of the failed jobs, or delete the tag
(`git push origin :refs/tags/vX.Y.Z`) and release the next version.

One-time setup: on PyPI, **Publishing**, add a GitHub publisher for project `anontestlab`, owner
`hashtagRR`, repository `AnonTestLab`, workflow `release.yml`, environment `pypi` (before the first
release, add it as a pending publisher under your account's **Publishing** page). On GitHub,
**Settings**, **Environments**, create `pypi` and add yourself as a required reviewer. Zenodo's
GitHub switch for this repository must be on before the release is published.
