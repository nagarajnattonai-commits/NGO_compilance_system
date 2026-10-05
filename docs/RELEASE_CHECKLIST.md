# Production release checklist

Record one of `VERIFIED`, `NOT VERIFIED`, or `NOT APPLICABLE` beside every item and attach evidence. Do not interpret this template as proof of readiness.

| Status | Check | Evidence |
|---|---|---|
| NOT VERIFIED | Production configuration validation passed without secret disclosure | |
| NOT VERIFIED | Reviewed images share the intended commit SHA/digest | |
| NOT VERIFIED | PostgreSQL is reachable and pool sizing is approved | |
| NOT VERIFIED | Schema bootstrap/migrations completed explicitly and `production_ops --check` passed | |
| NOT VERIFIED | Encrypted pre-deploy backup completed and backup age is within policy | |
| NOT VERIFIED | Restore procedure was recently rehearsed in isolated infrastructure | |
| NOT VERIFIED | Private document and brand buckets block public access and have encryption/versioning | |
| NOT VERIFIED | Malware scanning status is understood; `NOT_SCANNED` is not treated as clean | |
| NOT VERIFIED | Automation worker and integration worker are running | |
| NOT VERIFIED | Scheduler is running and duplicate protection was verified | |
| NOT VERIFIED | Secret store and required secret references are configured; no plaintext secrets are deployed | |
| NOT VERIFIED | HTTPS, trusted host/proxy path, certificates, security headers, and Secure cookies were verified | |
| NOT VERIFIED | `/health` and `/ready` are green and report the expected build | |
| NOT VERIFIED | Focused production tests, backend suite, TypeScript/build, en-IN regression, and container validation are green | |
| NOT VERIFIED | Optional provider configuration and cached health were reviewed | |
| NOT VERIFIED | Monitoring and recommended alerts are enabled and routed | |
| NOT VERIFIED | Bounded production smoke checks passed | |
| NOT VERIFIED | Rollback owner, compatible image, and migration/data considerations are recorded | |
| NOT VERIFIED | Target RPO/RTO were measured; any gap is accepted by the release owner | |
