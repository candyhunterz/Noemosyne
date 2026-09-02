# M1 security verification

Verified 2026-09-01 against the committed lockfiles and locally built release images.

- `uvx pip-audit`: no known Python dependency vulnerabilities.
- `pnpm audit --audit-level high`: no known JavaScript dependency vulnerabilities.
- Trivy 0.74: both API and web runtime images have zero HIGH/CRITICAL findings. The API runtime removes uv/pip, build caches, and pip-vendored metadata after constructing the locked virtual environment, eliminating stale `msgpack`/`setuptools` scanner metadata without suppressions.

Release scans fail on any fixable high/critical finding in either runtime image. A future false-positive exception must identify the scanner and advisory, show that the affected package/code is absent or unreachable in the final artifact, name a reviewer, and include an expiry date or upstream tracking condition. Exceptions never suppress a finding merely because exploitation seems unlikely.
