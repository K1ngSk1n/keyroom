# Source provenance and build traceability

Keyroom 0.2.2 is the normal website edition: HTML/CSS/JavaScript frontend,
Python backend, no browser extension. Code for this adaptation was authored
with Codex in this chat. It is not an official Xiaomi or upstream release.

## Where the protocol came from

Upstream author: Piotr Machowski.

Repository: https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor

Pinned upstream commit: `c4db715dace9806e905153c2977608873e8ab7c9`.

Original script SHA-256:
`e4eb8220df0f68c945c21cde5dbc5a0a276e7a035857b568d9423788ef192a30`.

The user's downloaded script was byte-for-byte identical to that pinned
upstream script when checked on 2026-11-26. The exact URL and verification
data are in `upstream-reference.json`. MIT copyright/terms are retained in
`THIRD_PARTY_LICENSE`.

| File | Origin and changes |
| --- | --- |
| `app/upstream.py` | Upstream `XiaomiCloudConnector` class, extracted with its imports. Signing, nonce generation and RC4 operations retain upstream behavior. CLI initialization and password-login code are omitted. |
| `app/cloud.py` | New web adapter based on upstream QR login and device/home enumeration. Adds endpoint restrictions, timeouts, cancellation, limited outputs and cleanup. |
| `app/main.py` | New web API, session isolation, expiry, limits, consent and response security headers. |
| `app/static/*` | New browser interface: region picker, QR display, results, copy/reveal and local JSON export. |
| `tests/test_app.py` | New synthetic regression tests for sessions, security boundaries and protocol helpers. |
| `tools/package.py` | New build tool linking the distributable source to a clean Git commit. |
| Docker/Compose files | New deployment configuration. Runtime dependencies pinned in `requirements.lock`. |

## Inspect a running build

- `/source` downloads that packaged build's source, attribution, tests and
  per-file checksums. There are no credentials or runtime data in it.
- `/api/build` reports the app version, local Git commit, upstream commit
  and aggregate source-tree digest.
- The footer links to both. Source is readable and not minified or
  obfuscated. No remote scripts or dynamic source downloads are used.

The source archive does not recursively contain itself. It includes all
tracked source plus generated `BUILD_INFO.json` and `CHECKSUMS.sha256`.
The Git commit identifies tracked source, while the generated build files
are derived from that commit and excluded from Git to avoid a circular
commit-hash dependency.

## Verify a downloaded source archive

Unzip it, enter its `keyroom-source` directory, then run:

```sh
shasum -a 256 -c CHECKSUMS.sha256
```

Compare `BUILD_INFO.json` with the running `/api/build`. The supplied
`keyroom-history.bundle` contains the local Git history and can be cloned:

```sh
git clone keyroom-history.bundle keyroom
cd keyroom
git log --oneline
python3 tools/package.py
```

To publish changes, commit them, rerun `tools/package.py`, then rebuild the
container. Packaging rejects dirty or untracked source. Generated files
are ignored explicitly; untracked secrets are never swept into the zip.
Do not use `git add .` in a project with sensitive untracked files.

Checksums/Git IDs make this distribution traceable and detect accidental
changes; they do not independently prove the operator deployed the same
code, make malicious repackaging impossible, or replace a security audit.
The public source repository is https://github.com/K1ngSk1n/keyroom.
It preserves the original local commit history. Releases are not digitally
signed; Git history and SHA-256 checksums are integrity and provenance aids.
