/** Stable CI diagnostics; never publish arbitrary process output or secrets. */
export function packageCommandFailure(result) {
  const code = result.error?.code;
  if (code === 'ETIMEDOUT') return 'timeout';
  if (code === 'ENOBUFS') return 'output_budget';
  if (code === 'ENOENT') return 'program_unavailable';
  if (/toomanyrequests|429 Too Many Requests|unauthenticated pull rate limit/i.test(result.stderr ?? '')) {
    return 'registry_rate_limit';
  }
  try {
    const verdict = JSON.parse(result.stdout?.trim() ?? '');
    if (verdict.archiveAdmitted === false && verdict.runtimeInstalled === false
      && typeof verdict.reasonCode === 'string' && /^[a-z0-9_]{1,96}$/.test(verdict.reasonCode)) {
      return `archive_admission:${verdict.reasonCode}`;
    }
  } catch { /* No arbitrary process output in diagnostics. */ }
  return 'unclassified';
}
