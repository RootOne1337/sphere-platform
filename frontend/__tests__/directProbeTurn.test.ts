import { parseTurnReady, validTurnUrl } from '@/src/features/stream/directProbeTurn';

const sid = 'a'.repeat(32);
const ready = () => ({ type: 'direct_probe_ready', protocol: 'sphere-probe-v2', session_id: sid, ice: {
  urls: ['turn:192.168.1.5:3478?transport=udp', 'turns:relay.example.test:443?transport=tcp'],
  username: `1791605120:${sid}:browser`, credential: 'A'.repeat(27) + '=', ttl_ms: 120000, policy: 'all',
} });

test('server grant produces browser ICE configuration with the exact session binding', () => {
  const config = parseTurnReady(ready());
  expect(config).toEqual({ session: sid, configuration: { bundlePolicy: 'max-bundle', iceTransportPolicy: 'all',
    iceServers: [{ urls: ready().ice.urls, username: ready().ice.username, credential: ready().ice.credential }] } });
  const relay = ready(); relay.ice.policy = 'relay';
  expect(parseTurnReady(relay)?.configuration.iceTransportPolicy).toBe('relay');
});

test.each([null, [], { ...ready(), tap: 1 }, { ...ready(), session_id: sid + '\n' },
  { ...ready(), protocol: 'sphere-probe-v3' }, { ...ready(), ice: null }])('rejects malformed ready envelope %#', value => {
  expect(parseTurnReady(value)).toBeNull();
});

test.each([{ username: `1791605120:${sid}:agent` }, { username: `1791605120:${'b'.repeat(32)}:browser` },
  { username: ready().ice.username + '\n' }, { credential: ready().ice.credential + '\n' },
  { ttl_ms: true }, { ttl_ms: 120001 }, { policy: 'any' }, { urls: [] },
  { urls: [ready().ice.urls[0], ready().ice.urls[0]] }, { action: 'tap' }])('rejects unbound or extended grant %#', change => {
  expect(parseTurnReady({ ...ready(), ice: { ...ready().ice, ...change } })).toBeNull();
});

test.each(['turn:127.0.0.1:3478?transport=udp', 'turn:0.1.2.3:3478?transport=udp',
  'turn:224.0.0.1:3478?transport=udp', 'turn:240.0.0.1:3478?transport=udp',
  'turn:169.254.1.1:3478?transport=udp', 'turn:0172.16.1.2:3478?transport=udp',
  'turn:256.1.2.3:3478?transport=udp', 'turn:relay.example.test:03478?transport=udp',
  'turn:relay.example.test:65536?transport=udp', 'turn:relay.example.test:0?transport=udp',
  'turns:relay.example.test:443?transport=udp', 'turn:user@relay.example.test:3478?transport=udp',
  'turn:relay.example.test:3478/path?transport=udp', 'turn:relay.example.test:3478?transport=udp\n',
  'turn:relay.example.test:3478?transport=udp&credential=secret', 'turn:RELAY.example.test:3478?transport=udp',
  'turn:[::1]:3478?transport=udp', 'turn:' + 'a'.repeat(64) + '.test:3478?transport=udp',
  'turn:relay:3478?transport=udp'])('rejects unsafe or ambiguous endpoint %s', value => {
  expect(validTurnUrl(value)).toBe(false);
});
