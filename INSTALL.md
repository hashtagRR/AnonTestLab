# Installing AnonTestLab

## Prerequisites

Python 3.9 or later. **3.11 or 3.12 is strongly recommended**, especially
on Windows. Very new Python versions (3.13+) sometimes don't have
prebuilt wheels yet for numpy/cryptography on every platform, which
forces pip to compile them from source: slow, and a much larger chance
of hitting a broken toolchain.

## Linux

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

If `python3 -m venv` fails with something like `ensurepip is not
available`, your distro split the venv module out of the base Python
package (common on Debian/Ubuntu):

```bash
sudo apt install python3-venv
```

Optional extras:

```bash
.venv/bin/pip install -e ".[dashboard]"   # local web UI
```

Verify:

```bash
.venv/bin/atl run examples/tor_like.yaml
.venv/bin/python -m pytest -q
```

## Windows

**Use a standard python.org CPython build, not the Python that ships
inside MSYS2/Git Bash's `mingw64` environment.** MSYS2's Python has
non-standard wheel tags, so pip usually can't find prebuilt packages for
numpy/cryptography there and falls back to compiling them from source,
which then needs cmake, ninja, and a working C/C++ toolchain, and is
prone to failing partway through on a slow or flaky connection. If a
`pip install` for this project is dragging in `cmake`/`ninja`/`meson`,
that's the tell that you're on the wrong Python.

### 1. Check what Python installs you have

Open PowerShell and run:

```powershell
py -0
```

Look for a `3.11` or `3.12` entry. If nothing suitable shows up, install
one from [python.org/downloads](https://www.python.org/downloads/), and
during setup, check **"Add python.exe to PATH"**.

### 2. Create and activate the venv with that specific version

```powershell
cd path\to\AnonTestLab
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell refuses to run the activation script with an
execution-policy error, run this once (scoped to your user only, doesn't
need admin) and retry:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 3. Install

```powershell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

This should pull prebuilt wheels for everything, no compiler needed.

### 4. Verify

```powershell
atl run examples\tor_like.yaml
python -m pytest -q
```

### Using Git Bash instead of PowerShell

Same idea, just invoke the launcher explicitly rather than letting
`python3`/`python` resolve to whatever's first on `PATH`:

```bash
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/atl run examples/tor_like.yaml
```

### Optional dashboard extra

```powershell
pip install -e ".[dashboard]"
atl dashboard
```

## Windows-specific things worth knowing

**Loopback binding.** Each relay node binds its own address in
`127.0.0.0/8` (`127.0.0.1`, `127.0.0.2`, ...). Windows has treated the
whole `127.0.0.0/8` range as loopback since Vista, so this should work
with no extra configuration, unlike macOS, which needs an explicit
`ifconfig lo0 alias` for anything past `127.0.0.1`. This hasn't been
verified against a live Windows run as part of this project yet, so if
you hit it: the symptom would be a `relay nN on port ... did not start
in time` error from `spawn_relays`, not a silent hang. If you see that,
it's the first thing to suspect.

**First-run firewall prompt.** The first time you run an experiment,
Windows Defender Firewall may prompt to allow `python.exe` to accept
connections on a private network. That's expected: the relay
subprocesses are real TCP servers on loopback. Allow it; nothing here
needs to leave your machine (everything binds to `127.0.0.0/8`).

**Antivirus overhead.** Real-time scanning can add noticeable latency to
spawning many short-lived `python.exe` processes. If experiments with a
large `network.nodes` count feel slow to start on Windows relative to
Linux, this is the likely reason. It doesn't affect correctness, only
wall-clock startup time.

## Troubleshooting checklist

- `pip install` wants to build numpy/cryptography from source, and pulls
  in cmake/ninja/rust: you're on a non-standard Python (MSYS2/mingw). Use
  `py -3.12` (or another python.org install) instead.
- `ModuleNotFoundError` for `fastapi`/`uvicorn` when running `atl
  dashboard`: install the optional extra, `pip install -e ".[dashboard]"`.
- A relay never reaches `READY` (`did not start in time` error): check
  nothing else on the machine is bound to a huge range of loopback ports,
  and on Windows check the firewall prompt wasn't silently dismissed as
  "deny".
- Tests hang instead of failing: this would be a real bug, not an
  environment issue. Please report it with the OS, Python version, and
  which test.
