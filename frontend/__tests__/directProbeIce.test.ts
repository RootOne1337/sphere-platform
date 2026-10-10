import { directProbeIceConfig, DirectProbeConfigurationError } from '@/src/features/stream/directProbeIce';

test('ordinary profile stays host-only, with no default external server', () => {
  expect(directProbeIceConfig()).toEqual({ profile: 'host', iceServers: [] });
  expect(directProbeIceConfig('')).toEqual({ profile: 'host', iceServers: [] });
});

test('the documented public service requires exact explicit selection, without a fallback list', () => {
  expect(directProbeIceConfig('stun:stun.cloudflare.com:3478')).toEqual({ profile: 'public-stun',
    iceServers: [{ urls: 'stun:stun.cloudflare.com:3478' }] });
  for (const url of ['stun:stun.cloudflare.com:19302', 'stun:stun.cloudflare.com:3478?transport=udp',
    'stun:STUN.cloudflare.com:3478', 'stun:stun.cloudflare.com.evil:3478'])
    expect(() => directProbeIceConfig(url)).toThrow('invalid_controlled_stun');
});

test.each(['stun:10.0.2.2:3478', 'stun:172.16.1.1:1024', 'stun:172.31.255.255:65535',
  'stun:192.168.1.2:19302'])('one controlled local endpoint is admitted: %s', url => {
  expect(directProbeIceConfig(url)).toEqual({ profile: 'controlled-stun', iceServers: [{ urls: url }] });
});

test.each(['stun:example.com:3478', 'stun:8.8.8.8:3478', 'stun:127.0.0.1:3478',
  'stun:172.15.1.1:3478', 'stun:172.32.1.1:3478', 'stun:192.169.1.1:3478',
  'stun:10.0.2.256:3478', 'stun:010.0.2.2:3478', 'stun:10.0.2:3478', 'stun:10.0.2.2.1:3478',
  'stun:10.0..2:3478', 'stun:10.0.2.2:03478', 'stun:10.0.2.2:65536', 'stun:10.0.2.2:1023',
  'stun:10.0.2.2:9999999999999999999999', 'STUN:10.0.2.2:3478', 'stuns:10.0.2.2:3478',
  'turn:10.0.2.2:3478', 'stun://10.0.2.2:3478', 'stun:user@10.0.2.2:3478',
  'stun:10.0.2.2:3478?transport=udp', 'stun:10.0.2.2:3478/path', 'stun:10.0.2.2:3478#fragment',
  'stun:10.0.2.2:3478,stun:10.0.2.3:3478', ' stun:10.0.2.2:3478', 'stun:10.0.2.2:3478\n',
  'stun:[fd00::1]:3478'])('bad profile fails without disclosing its endpoint: %s', url => {
  expect(() => directProbeIceConfig(url)).toThrow(DirectProbeConfigurationError);
  expect(() => directProbeIceConfig(url)).toThrow('invalid_controlled_stun');
});
