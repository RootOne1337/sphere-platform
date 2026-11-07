const GIT_SHA_PATTERN = /^[0-9a-f]{7,40}$/i;

export function normalizeBuildRevision(value: string | undefined): string | undefined {
  const candidate = value?.trim();
  if (!candidate || !GIT_SHA_PATTERN.test(candidate)) return undefined;
  return candidate.toLowerCase();
}

export function formatBuildRevision(value: string | undefined): string {
  return normalizeBuildRevision(value)?.slice(0, 8) ?? 'unknown';
}

export function hasBuildRevisionMismatch(frontend: string | undefined, backend: string | undefined): boolean {
  const frontendSha = normalizeBuildRevision(frontend);
  const backendSha = normalizeBuildRevision(backend);
  return frontendSha !== undefined && backendSha !== undefined && frontendSha !== backendSha;
}

export const FRONTEND_BUILD_SHA = normalizeBuildRevision(process.env.NEXT_PUBLIC_BUILD_SHA);
export const FRONTEND_BUILD_REVISION = FRONTEND_BUILD_SHA?.slice(0, 8) ?? 'unknown';
