# RELEASE.md — Publishing cross-ai-core to PyPI

This document covers everything needed to publish and update the `cross-ai-core`
package on PyPI, from first-time account setup through routine version bumps.

---

## One-time setup

### 1. Create a PyPI account

Go to <https://pypi.org/account/register/> and create an account.  
Enable two-factor authentication — PyPI requires it for publishing.

Also create an account on **TestPyPI** at <https://test.pypi.org/account/register/>  
(separate account, same process).  TestPyPI is a sandbox — always do a trial
upload there before hitting the real index.

### 2. Create API tokens

Passwords are not accepted for uploads — use API tokens.

**PyPI token** (for real releases):
1. Log in at <https://pypi.org>
2. Account Settings → API tokens → Add API token
3. Scope: "Entire account" for the first upload; after the project exists, scope it
   to `cross-ai-core` only
4. Copy the token — it starts with `pypi-` and is shown only once

**TestPyPI token** (for trial uploads):
Same process at <https://test.pypi.org>

### 3. Configure `~/.pypirc`

`~/.pypirc` is organized by **index server**, not by package.  A single token
covers every package you own on that account — if you already publish another
package (e.g. `yakyak`), your existing file already works for `cross-ai-core`
with no changes.

The minimal working format — this is all `twine` needs:

```ini
[pypi]
  username = __token__
  password = pypi-AgEIcHlwaS5vcmc...
```

- `[distutils]` with `index-servers =` is **not required** — it is an old
  convention for legacy tools.  Modern `twine` ignores it.
- `repository = https://upload.pypi.org/legacy/` is **not required** — `[pypi]`
  is the default target when you run `twine upload dist/*`.
- You do **not** need a new token.  An "Entire account" token publishes any
  package on your account.  If you created a second token, you can safely
  delete it at <https://pypi.org> → Account Settings → API tokens.

#### Adding TestPyPI (optional)

Only needed if you want to do trial uploads to the sandbox before the real
release.  Add a second section using a **separate** token from
<https://test.pypi.org>:

```ini
[pypi]
  username = __token__
  password = pypi-<your-pypi-token>

[testpypi]
  username = __token__
  password = pypi-<your-testpypi-token>
```

Then trial-upload with `twine upload --repository testpypi dist/*`.

#### If you want per-project tokens (optional, more secure)

A project-scoped token can only publish one named package.  Add a named
section and pass `--repository` to `twine`:

```ini
[pypi]
  username = __token__
  password = pypi-<account-wide-token>     ← covers yakyak, cross-ai-core, etc.

[cross-ai-core]
  repository = https://upload.pypi.org/legacy/
  username = __token__
  password = pypi-<cross-ai-core-only-token>
```

Upload with: `twine upload --repository cross-ai-core dist/*`

Worth doing once the package has external users; overkill for a new package.

`~/.pypirc` is read automatically by `twine` — never commit this file.
Add it to your global `~/.gitignore` if not already there:

```bash
echo ".pypirc" >> ~/.gitignore
```

### 4. Install build tools (once, in the cross-ai-core venv)

```bash
cd ~/github/cross-ai-core
source .venv/bin/activate
pip install build twine
```

---

## Publishing a release

### Step 1 — Bump the version

Edit **`pyproject.toml`** only — this is the single source of truth:

```toml
version = "2026.8.0"
```

`cross_ai_core/__init__.py` reads the version at runtime via `importlib.metadata`
and does **not** contain a hardcoded version string.

Version numbers follow Calendar Versioning (`YYYY.M.R`):

| Segment | Meaning | Example |
|---|---|---|
| `YYYY` | 4-digit year | `2026` |
| `M` | Month `1-12` (no leading zero) | `8` |
| `R` | Release index within that month, starting at `0` | `0`, `1`, `2` |

Examples: `2026.8.0` (first August release), `2026.8.1` (second August release).

Tags follow the same value prefixed with `v` (for example `v2026.8.0`).

### Step 2 — Run the tests

```bash
cd ~/github/cross-ai-core
source .venv/bin/activate
python -m pytest tests/ -v
```

All tests must pass before building.  If any fail, fix them first.

### Step 3 — Clean and build

```bash
# Remove any previous build artefacts first
rm -rf dist/ build/ cross_ai_core.egg-info/

# Build both the source distribution and the wheel
python -m build
```

This produces two files in `dist/`:
- `cross_ai_core-2026.8.0.tar.gz` — source distribution
- `cross_ai_core-2026.8.0-py3-none-any.whl` — wheel

### Step 4 — Validate the build

```bash
twine check dist/*
```

Fix any warnings before uploading.  Common issues: missing README, malformed
classifiers, long description rendering errors.

### Step 5 — Trial upload to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

Then verify it installs cleanly from the sandbox:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            cross-ai-core==2026.8.0
python -c "import cross_ai_core; print(cross_ai_core.__version__)"
```

The `--extra-index-url` fallback is needed because TestPyPI doesn't have
`anthropic`, `openai`, etc. — they're fetched from the real PyPI.

### Step 6 — Upload to PyPI

```bash
twine upload dist/*
```

The package is now live at <https://pypi.org/project/cross-ai-core/>.

### Step 7 — Tag the release in git

```bash
git add pyproject.toml
git commit -m "Release v2026.8.0"
git tag v2026.8.0
git push && git push --tags
```

### Step 8 — Update cross-ai to use the new version

In `~/github/cross/pyproject.toml`, update the lower bound if the new release
is required:

```toml
"cross-ai-core>=2026.8.0",
```

Then reinstall Cross:

```bash
cd ~/github/cross
source .venv/bin/activate
pip install -e .
python -m pytest tests/ -q    # confirm nothing broke
```

---

## Routine version bump — quick reference

```bash
# 1. Edit version in pyproject.toml
# 2. Test
cd ~/github/cross-ai-core && source .venv/bin/activate
python -m pytest tests/ -v

# 3. Build + check
rm -rf dist/ && python -m build && twine check dist/*

# 4. Trial upload
twine upload --repository testpypi dist/*

# 5. Real upload
twine upload dist/*

# 6. Tag
git add pyproject.toml
git commit -m "Release vYYYY.M.R"
git tag vYYYY.M.R && git push && git push --tags
```

---

## Maintenance release process

For an urgent bug fix without new features:

1. Create a branch: `git checkout -b hotfix/2026.8.1`
2. Fix the bug, bump `pyproject.toml` to the next monthly release index
3. Run tests, build, upload to TestPyPI, upload to PyPI
4. `git tag v2026.8.1 && git push --tags`
5. Merge back to `main`: `git checkout main && git merge hotfix/2026.8.1`

---

## Troubleshooting

**`twine upload` says "File already exists"**  
PyPI does not allow re-uploading the same version number, even if you delete the
release. Bump to the next CalVer release (e.g. `2026.8.1`) and upload again.

**`twine check` fails on long description**  
The README must be valid reStructuredText or Markdown. Run `python -m build`
and inspect `dist/*.tar.gz` to confirm `README.md` is included.

**`pip install cross-ai-core` gets the old version**  
PyPI has a propagation delay of a few minutes.  Wait and retry, or install
with the explicit version: `pip install cross-ai-core==2026.8.0`.

**Token rejected**  
Confirm `~/.pypirc` has `username = __token__` (literally, not your username)
and the password is the full token string starting with `pypi-`.

---

## Relationship to cross-ai

`cross-ai` depends on `cross-ai-core`.  After publishing a new `cross-ai-core`
version, the workflow in the `cross-ai` repo is:

```
cross-ai-core releases 2026.8.0
    ↓
pip install cross-ai-core==2026.8.0   (test in cross-ai's venv)
    ↓
Update cross-ai/pyproject.toml lower bound if needed
    ↓
Run cross-ai test suite
    ↓
Commit + release cross-ai if needed
```

During active development on both repos simultaneously, use the editable
sibling install so you never need to publish just to test:

```bash
# In cross-ai's venv:
pip install -e ../cross-ai-core/
```

Changes to `cross_ai_core/` are immediately visible without any reinstall.

