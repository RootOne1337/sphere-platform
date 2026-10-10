const original = { gate: process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY,
  url: process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL };
beforeEach(() => { jest.resetModules(); delete process.env.NEXT_PUBLIC_DIRECT_PROBE_STUN_URL;
  delete process.env.NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY; });
afterAll(() => {
  for (const [key, value] of Object.entries({ NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY: original.gate,
    NEXT_PUBLIC_DIRECT_PROBE_STUN_URL: original.url })) {
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
