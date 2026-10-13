/** V1 owns the entire injector. Never race it against a negotiated shared media peer. */
export function deferLegacyInput(
  historyReady: boolean,
  admission: { admissionKnown: boolean; admitted: boolean; active: boolean; sharedInput?: boolean },
  endpoint: { readyState: number; sharedInput?: boolean } | null,
): boolean {
  if (!historyReady) return false; // Older servers retain their existing input path.
  if (!admission.admissionKnown) return true;
  return admission.admitted && admission.sharedInput === true
    && !(admission.active && endpoint?.readyState === 1 && endpoint.sharedInput === true);
}
