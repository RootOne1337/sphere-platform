/** API metadata is canonical; `model` is a compatibility fallback for older responses. */
export function getReportedDeviceModel(device: { device_model?: unknown; model?: unknown }): string | null {
  for (const value of [device.device_model, device.model]) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}
