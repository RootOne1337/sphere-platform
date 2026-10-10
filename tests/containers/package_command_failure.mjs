/** Stable CI diagnostics; never publish arbitrary process output or secrets. */
export function packageCommandFailure(result) {
  const code = result.error?.code;
  if (code === 'ETIMEDOUT') return 'timeout';
  if (code === 'ENOBUFS') return 'output_budget';
  if (code === 'ENOENT') return 'program_unavailable';
  if (/toomanyrequests|429 Too Many Requests|unauthenticated pull rate limit/i.test(result.stderr ?? '')) {
    return 'registry_rate_limit';
  }
  return 'unclassified';
}
