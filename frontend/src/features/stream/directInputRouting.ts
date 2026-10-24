/** Prefer the first shared negotiation; background retries cannot starve fallback admission. */
export function deferLegacyInput(
  historyReady: boolean,
  admission: { admissionKnown: boolean; admitted: boolean; active: boolean; sharedInput?: boolean;
    result?: { state: string } | null; attempts?: number },
  endpoint: { readyState: number; sharedInput?: boolean } | null,
): boolean {
  if (!historyReady) return false; // Older servers retain their existing input path.
  if (!admission.admissionKnown) return true;
  // A failed/stopped direct attempt has no usable shared transport. Its exact
  // peer is retired before this observation is published. Let the server admit
  // a fresh fallback owner; permission/cleanup checks still belong to APK/API.
  // A new direct attempt waits for that owner's RELEASE before route promotion.
  if (!admission.active && ['failed', 'stopped', 'finished'].includes(admission.result?.state ?? '')) return false;
  // A fallback capability requested after failure may return after the one-
  // second retry has begun. Re-blocking that reply on every new ICE attempt
  // can leave healthy server video without any input owner. Direct negotiation
  // itself acquires no injector; DeviceStream still requires exact fallback
  // RELEASE before promoting an actual open shared endpoint.
  if (!admission.active && (admission.attempts ?? 0) > 1) return false;
  return admission.admitted && admission.sharedInput === true
    && !(admission.active && endpoint?.readyState === 1 && endpoint.sharedInput === true);
}
