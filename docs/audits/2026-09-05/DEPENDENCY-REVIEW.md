# Python dependency review — 6 September 2026

The backend CI run on `d7839fb` reported **17 advisory records across three
packages**. Deduplicating GHSA identifiers yields 11 advisories, not 17 distinct
application exploits. [CI evidence](evidence/ci-security-d7839fb.txt).

| Package | Previous resolution | Selected version | Repository relevance |
| --- | --- | --- | --- |
| PyJWT | 2.12.0 | 2.13.0 | Five upstream fixes. Current access/logout verifiers use one configured algorithm and a fixed secret; there is no PyJWKClient, attacker-selected key or detached-payload verification path. An application authentication bypass from these advisories was not demonstrated. |
| Starlette | 0.50.0 | 1.3.1 | Five advisories. Host poisoning is reachable in audit/log/metrics middleware and is reproduced/fixed as AUD-38. No backend StaticFiles/HTTPEndpoint/form-parser usage was found for the other affected APIs; this is a code review result, not a guarantee about every deployment or future route. |
| pytest | 8.0.2 | 9.0.3 | Upstream insecure temporary-directory fix. This is a test-tool surface; no remote Sphere API exploit or local multi-user exploit was performed. |

Primary sources: [PyJWT security release](https://github.com/jpadilla/pyjwt/releases/tag/2.13.0),
[Starlette Host advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr),
[Starlette releases](https://github.com/Kludex/starlette/releases),
[pytest 9.0.3 changes](https://docs.pytest.org/en/stable/changelog.html#pytest-9-0-3-2026-04-07).

## Compatibility changes

FastAPI 0.125.0 required Starlette below 0.51.0. FastAPI 0.136.3 supports the
patched Starlette and requires Pydantic >=2.9.0, so Pydantic moves from 2.6.3 to
2.9.2. The selected FastAPI stays before the separately documented 0.137 routing
changes. These are deliberate compatibility pins, not a claim to use every latest
feature release. [FastAPI release notes](https://fastapi.tiangolo.com/release-notes/).

pytest-asyncio moves from 0.23.5 to 1.3.0 for pytest 9 support.
[Upstream compatibility notes](https://pytest-asyncio.readthedocs.io/en/stable/reference/changelog.html).
Existing fixture and test scopes remain unchanged; no tests, auth checks or
coverage thresholds were disabled to obtain a passing result.

The PC agent pinned pydantic-settings 2.2 while backend pinned 2.2.1. A joint
resolver rejected this combination: [before](evidence/dependencies-joint-before.txt).
Both now require 2.2.1. Backend CI installs both requirements in one transaction,
runs `pip check`, and audits both lists. Sequential installations previously hid
the conflict by replacing the first package selection with the second.

## Validation and limits

Testing used a separate Python 3.12.12 environment, isolated PostgreSQL/Redis and
the complete ordinary regression command. The initial compatibility run passed
1035 cases before adding 12 explicit JWT verifier controls. Those controls already
passed on the old dependency version; they preserve the application's security
boundary and are **not** evidence of a previously exploitable JWT bypass. They
cover unsigned/disallowed-algorithm/wrong-key tokens, required claims and ensuring
`jku`/`kid` headers cannot select an external signing key, including the logout
verification path. No header URL is fetched by the tests.

At the dependency-change revision the run passed **1047 tests**, coverage
**66.61%**, at the unchanged strict 65% gate. The rolling
[combined-suite-current.txt](evidence/combined-suite-current.txt) now records later
audit fixes; consult the main audit report for its current count and coverage.
The final environment passes [dependency consistency](evidence/dependencies-final-check.txt);
its installed versions are captured in [the package snapshot](evidence/dependencies-final-freeze.txt).
The joint backend/PC scan reports no known vulnerabilities:
[scanner output](evidence/dependencies-final-audit.txt),
[machine-readable result](evidence/dependencies-final-audit.json).
Bandit reports no medium/high findings under the existing configuration:
[output](evidence/dependencies-bandit.txt). Existing low findings/suppressions were
not newly introduced or hidden.

The scan is limited to the resolved Python dependency set and advisory database
at scan time. It does not close frontend/npm, Gradle/Android, container OS,
deployment, RLS or application logic findings. Several transitive dependencies
still use ranges; the version snapshot is evidence, not an enforced hash lock.
Future installation needs fresh resolution/scanning. Python 3.12 joint testing
does not establish every standalone PC-agent Python 3.11 deployment behavior.
No production environment was upgraded during the audit.

GitHub CI independently passed on `748bb3e`: all backend jobs, including the
joint Security scan and Tests, and Android build/tests. The
[backend snapshot](evidence/ci-748bb3e-backend.json) and
[Android snapshot](evidence/ci-748bb3e-android.json) identify the exact revision.

## GitHub alert triage — 7 September 2026

The repository API reports **137 open default-branch alerts**: 1 critical,
61 high, 62 medium and 13 low. These are manifest-level alerts, including duplicate
package/lockfile entries, not 137 proven application exploits or the state of
this unmerged audit branch. The snapshot has 105 frontend lockfile alerts,
23 frontend manifest alerts, 3 n8n lockfile alerts and 6 backend manifest alerts:
[API projection](evidence/dependabot-open-current.jsonl).

The critical entry (#53) concerns **Handlebars 4.7.8**, present as a development
transitive dependency of ts-jest. The [upstream advisory](https://github.com/handlebars-lang/handlebars.js/security/advisories/GHSA-2w6w-674q-4c4q)
requires passing an attacker-controlled AST object into `compile()` and lists
4.7.9 as the first patched release. Inspection of the installed ts-jest CLI found
`compile(JEST_CONFIG_TEMPLATE)` with a constant string; repository frontend source
search found no direct Handlebars use. This does not establish a reachable HTTP
RCE in Sphere and does not excuse retaining the affected development package.
Dependency remediation, compatibility tests and a fresh npm scan remain required.
Next.js production dependency alerts also remain and need separate reachability
and upgrade validation; the Python scan result does not cover them.
