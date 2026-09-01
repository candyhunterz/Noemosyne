# M1 security verification

Verified 2026-09-01 against the committed lockfiles and locally built release images.

- `uvx pip-audit`: no known Python dependency vulnerabilities.
- `pnpm audit --audit-level high`: no known JavaScript dependency vulnerabilities.
- Trivy 0.74: web runtime has no fixable high/critical finding after excluding package managers from the runtime stage.
- Trivy reports `msgpack 1.1.2` and `setuptools 70.3.0` from the Python base image's third-party SBOM. Neither distribution exists in the final API filesystem (`importlib.metadata` returns `PackageNotFoundError`), and the environment installed from `uv.lock` is clean under `pip-audit`. These are documented scanner/SBOM false positives, not runtime exceptions.

Release scans fail on any other fixable high/critical finding. A false-positive exception must identify the scanner and advisory, show that the affected package/code is absent or unreachable in the final artifact, name a reviewer, and include an expiry date or upstream tracking condition. Exceptions never suppress a finding merely because exploitation seems unlikely.
