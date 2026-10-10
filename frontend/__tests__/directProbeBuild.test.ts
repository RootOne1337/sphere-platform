const original = { gate: process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY,
  url: process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL, relay: process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY };
beforeEach(() => { jest.resetModules(); delete process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL;
  delete process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY; delete process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY; });
afterAll(() => {
  for (const [key, value] of Object.entries({ NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY: original.gate,
    NEXT_PUBLIC_DIRECT_PROBE_STUN_URL: original.url, NEXT_PUBLIC_DIRECT_PROBE_RELAY: original.relay })) {
    if (value === undefined) delete process.env[key]; else process.env[key] = value;
  }
});

test('ordinary configuration remains valid without a diagnostic endpoint', async () => {
  await expect(import('../next.config')).resolves.toBeDefined();
});

test.each(['', 'false', '1', 'TRUE'])('STUN build setting cannot accompany inactive diagnostic gate: %s', async gate => {
  process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL = 'stun:stun.cloudflare.com:3478';
  process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY = gate;
  await expect(import('../next.config')).rejects.toThrow('Diagnostic STUN requires NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY=true');
});

test('explicit diagnostic build permits its matching profile setting', async () => {
  process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL = 'stun:stun.cloudflare.com:3478';
  process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY = 'true';
  await expect(import('../next.config')).resolves.toBeDefined();
});

test('relay grant diagnostics require the canary gate and cannot mix static STUN', async () => {
  process.env.NEXT_PUBLIC_DIRECT_PROBE_RELAY = 'true';
  await expect(import('../next.config')).rejects.toThrow('Relay diagnostics require');
  jest.resetModules(); process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY = 'true';
  await expect(import('../next.config')).resolves.toBeDefined();
  jest.resetModules(); process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL = 'stun:stun.cloudflare.com:3478';
  await expect(import('../next.config')).rejects.toThrow('Relay diagnostics require');
});
