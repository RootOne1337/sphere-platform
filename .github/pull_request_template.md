<!-- .github/pull_request_template.md -->
## Description
<!-- Brief description of changes -->

## Type of change
- [ ] feat: new feature
- [ ] fix: bug fix
- [ ] security: security fix
- [ ] refactor: refactoring
- [ ] docs: documentation
- [ ] perf: performance improvement
- [ ] chore: build / infra / tooling

## Linked to
<!-- SPHERE-XXX or link to issue -->

## Checklist
- [ ] Tests written and passing
- [ ] `ruff check` passes without errors
- [ ] `mypy` passes without errors
- [ ] No secrets in code (detect-secrets clean)
- [ ] Migrations are reversible (downgrade works)
- [ ] API is backward-compatible (or BREAKING CHANGE noted below)

## Security Checklist
- [ ] No SQL injection (ORM / parameterized queries only)
- [ ] No XSS (templates sanitize output)
- [ ] No IDOR (org_id/user_id verified on every request)
- [ ] RBAC checks on all endpoints
- [ ] Rate limiting on public endpoints

## Breaking Changes
<!-- List any breaking API changes or migration steps. Write "None" if N/A -->
None

## Deployment Notes
<!-- DB migrations, env vars, infra changes required for this PR -->
