/** Read-only scalar telemetry from the same bound reply; never input authority. */
export type LocalizationDiagnostic={schema:'sphere-localization-observation-diagnostic-v1';candidateCount:number|null;maxRetainedLkCount:number|null;verifiedCandidateCount:number|null;
  candidateReferenceIndices?:number[]};
export function readLocalizationDiagnostic(value:unknown):LocalizationDiagnostic|null {
  const v=value as LocalizationDiagnostic;
  const count=(n:unknown,max:number)=>n===null||typeof n==='number'&&Number.isInteger(n)&&n>=0&&n<=max;
  if(!v||v.schema!=='sphere-localization-observation-diagnostic-v1'||!count(v.candidateCount,8)
    ||!count(v.maxRetainedLkCount,65536)||!count(v.verifiedCandidateCount,8)
    ||v.candidateCount!==null&&v.verifiedCandidateCount!==null&&v.verifiedCandidateCount>v.candidateCount)return null;
  const indices=v.candidateReferenceIndices;
  return {schema:v.schema,candidateCount:v.candidateCount,maxRetainedLkCount:v.maxRetainedLkCount,verifiedCandidateCount:v.verifiedCandidateCount,
    ...(Array.isArray(indices)&&indices.length===v.candidateCount&&indices.every(n=>n!==null&&count(n,255))
      ?{candidateReferenceIndices:[...indices]}:{})};
}
