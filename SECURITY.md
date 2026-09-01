# Security policy

Do not open public issues for vulnerabilities. Email `nknguyen92@gmail.com` with the affected revision, reproduction, impact, and suggested mitigation. You should receive acknowledgment within seven days. Coordinated disclosure timing will reflect severity and deployment exposure.

M1 is pre-1.0 and receives security fixes on `main`. It has no built-in authentication or multi-tenant authorization; deploy it only behind operator-controlled access and TLS. Never expose the example database password. Source text is untrusted data and must not be interpolated into prompts, logs, SQL, or shell commands.
