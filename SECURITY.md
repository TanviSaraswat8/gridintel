# Security policy

## Reporting
Please report vulnerabilities privately to the maintainer (GitHub "Report a vulnerability" / security advisory). Do not open public issues for security problems.

## Controls in this project
- Authentication: JWT (HS256) with expiry; roles ADMIN > ENGINEER > OPERATOR > VIEWER enforced per endpoint.
- Passwords: PBKDF2-SHA256 (240k iterations, random salt). No plaintext passwords are stored; the bootstrap admin comes from environment variables.
- Production guards: startup fails without `JWT_SECRET` (≥ 32 chars) or with wildcard `CORS_ORIGINS`.
- Rate limiting per IP (general + stricter login limit), Redis-backed when available.
- Input validation via Pydantic; structured error responses with request IDs (no stack traces to clients).
- Security headers: CSP, X-Frame-Options DENY, nosniff, Referrer-Policy, Permissions-Policy, HSTS in production.
- Audit log: logins (success/failure), replay control, CSV exports, investigation notes, alert acknowledgements.
- Secrets only via environment variables; `.env*` git-ignored. Container runs as a non-root user.
- Private datasets (HVPNL records) and everything derived from them are excluded from Git and from the Docker build context.

## Scope note
GridIntel is a research decision-support prototype. It must not be connected to control systems or used as a protection system.
