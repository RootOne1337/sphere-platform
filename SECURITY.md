# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 4.x (latest) | ✅ Active security patches |
| 3.x | ⚠️ Critical fixes only |
| 2.x and below | ❌ End of life — no patches |

We strongly encourage all deployments to stay on the latest `4.x` release.

---

## Reporting a Vulnerability

**Please do not open a public GitHub Issue for security vulnerabilities.**
Public disclosure before a fix is available could endanger live deployments.

### Preferred channel

Send a detailed report to **security@yourdomain.com** using the following format:

```
Subject: [SECURITY] <brief description>

Component: backend-api | android-agent | pc-agent | frontend | infrastructure
Severity (your estimate): critical | high | medium | low
CVSS score (if known): e.g. 9.1

Description:
  A clear description of the vulnerability.

Steps to reproduce:
  1. ...
  2. ...
  3. Observe: ...

Impact:
  What could an attacker achieve by exploiting this?

Suggested fix (optional):
  If you have a recommendation.

Reporter contact:
  How to reach you for follow-up (optional).
```

### PGP key

For sensitive reports you may encrypt your submission using our public PGP key.
Key fingerprint: `AAAA BBBB CCCC DDDD EEEE  FFFF 0000 1111 2222 3333`

Retrieve via:
```bash
gpg --keyserver keys.openpgp.org --recv-keys 0x000011112222333
```

---

## Response Timeline

| Severity | CVSS Range | Initial Response | Fix Target |
|----------|-----------|-----------------|-----------|
| Critical | 9.0–10.0 | 24 hours | 7 days |
| High | 7.0–8.9 | 48 hours | 14 days |
| Medium | 4.0–6.9 | 5 business days | 30 days |
| Low | 0.1–3.9 | 10 business days | Next release |
| Informational | N/A | Best effort | Next release |

We will keep you informed of our progress throughout the fix process.

---

## Severity Definitions

### Critical

- Unauthenticated remote code execution
- Authentication bypass (complete token forgery)
- Direct data exfiltration of all organizations' data
- Complete VPN infrastructure compromise from internet

### High

- Privilege escalation across organization boundaries (tenant isolation break)
- WebSocket authentication bypass
- Horizontal privilege escalation (user A accessing user B's devices)
- SQL injection in any endpoint

### Medium

- CSRF on state-changing endpoints (where applicable)
- Stored XSS in device names or script fields
- Information disclosure of internal infrastructure details
- Insecure Direct Object Reference (IDOR) within same organization

### Low

- Self-XSS
- Rate limiting bypass in non-sensitive endpoints
- Missing security headers on static assets
- Verbose error messages leaking stack traces

---

## Disclosure Policy

We follow coordinated vulnerability disclosure:

1. Reporter submits vulnerability to our private channel.
2. We confirm receipt within the response timeline above.
3. We work on a fix and keep the reporter updated.
4. We release the fix and update `CHANGELOG.md` with a security advisory.
5. After the fix is deployed (or after a reasonable embargo period), we publish
   a GitHub Security Advisory for the issue.
6. We credit the reporter in the advisory (unless they prefer to remain anonymous).

We do **not** pursue legal action against researchers operating in good faith.

---

## Safe Harbor

Sphere Platform is committed to working with security researchers. If you discover
a vulnerability and report it in good faith — without data destruction, without
disrupting production systems, and without publicly disclosing the issue before
we have released a fix — we will not take any legal action against you.

In return, we ask that you:

- Avoid accessing, modifying, or deleting data you do not own.
- Limit testing to your own accounts and test environments.
- Not perform denial-of-service attacks.
- Not use automated scanners on production systems without prior authorization.
- Report your findings to us before public disclosure.

---

## Security Architecture Overview

For detailed security architecture, see [docs/security.md](docs/security.md).

Key security controls at a glance:

| Control | Implementation |
|---------|---------------|
| Authentication | JWT HS256 (15-min access token) + bcrypt(12) passwords |
| MFA | TOTP (RFC 6238) via `pyotp` |
| Authorization | RBAC (7 roles) + PostgreSQL Row-Level Security |
| Transport | TLS 1.2+ everywhere; WSS for WebSocket |
| Secrets | Environment variables; production: HashiCorp Vault or cloud KMS |
| API rate limiting | nginx `limit_req_zone` per-IP |
| Dependency scanning | `pip-audit`, Dependabot, GitHub Actions |
| SBOM | Generated on every release (`cyclonedx-bom`) |
| Audit log | Immutable append-only `audit_logs` DB table |
| VPN kill switch | `iptables` + WireGuard network namespace |

---

## Known Limitations

The following are known design trade-offs that are not considered vulnerabilities:

- **JWT tokens cannot be revoked before expiry** — use short token lifetimes (default 15 min)
  and the refresh token rotation to limit blast radius.
- **Device commands are signed only at the API level** — end-to-end command signing
  is planned for v5.0.
- **VPN IP pool is sequential** — this is acceptable for private RFC-1918 ranges
  where IPs must not be guessed.

---

## Version History

| Release | Security Relevance |
|---------|-------------------|
| v4.0.0 | Initial hardened release. JWT refresh rotation, RLS, API key hashing. |
| v3.x | Legacy. Upgrade not supported. |

---

*This security policy was last updated with Sphere Platform v4.0.0.*
