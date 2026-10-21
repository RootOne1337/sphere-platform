import { profileFileHints } from '@/src/features/vpn/profileFileHints';

describe('profile file hints', () => {
  const wg = '[Interface]\nPrivateKey = secret-not-to-project\nAddress=10.0.0.2/32,fd42::2/128\nDNS=1.1.1.1\n[Peer]\nPublicKey=public\nPresharedKey=another-secret\nAllowedIPs=0.0.0.0/0, ::/0\n';
  it('recognizes the WG + IPv6 import without projecting any config values', () => {
    expect(profileFileHints(wg)).toEqual({ protocol: 'wireguard', ipv6: 'tunnel', partialIpv6: false });
    expect(JSON.stringify(profileFileHints(wg))).not.toMatch(/secret|fd42|1\.1\.1/);
  });
  it('requires actual interface fields to identify AWG and never guesses its version', () => {
    expect(profileFileHints(wg.replace('[Peer]', 'H1 = 1-10\n[Peer]'))?.protocol).toBe('amneziawg');
    expect(profileFileHints(wg + '# H1=1\n')?.protocol).toBe('wireguard');
    expect(profileFileHints(wg.replace('[Peer]', '[Peer]\nH1=1'))?.protocol).toBe('wireguard');
  });
  it('does not silently enable an incomplete IPv6 configuration', () => {
    expect(profileFileHints(wg.replace(', ::/0', ''))).toEqual({ protocol: 'wireguard', ipv6: 'block', partialIpv6: true });
  });
  it('leaves malformed, oversized and multi-peer files to the server', () => {
    for (const text of ['', 'x'.repeat(65537), wg + '[Peer]\n', wg + '[Unknown]\n', wg + 'invalid']) expect(profileFileHints(text)).toBeNull();
  });
});
