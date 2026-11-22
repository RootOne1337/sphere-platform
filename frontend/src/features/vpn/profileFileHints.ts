/** Local hints only. Never return key values, raw lines or the input config.
 * The server remains authoritative; a hint is not format/egress validation.
 */
export function profileFileHints(text: string): { protocol: 'wireguard' | 'amneziawg'; ipv6: 'block' | 'tunnel'; partialIpv6: boolean } | null {
  if (!text || text.length > 65536) return null;
  let section = ''; let interfaces = 0; let peers = 0; let awg = false;
  let address6 = false; let route6 = false;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/[#;].*$/, '').trim();
    if (!line) continue;
    const heading = /^\[([^\]]+)\]$/.exec(line);
    if (heading) {
      section = heading[1].toLowerCase();
      if (section === 'interface') interfaces++; else if (section === 'peer') peers++; else return null;
      continue;
    }
    const field = /^([a-z][a-z0-9]*)\s*=\s*(.*)$/i.exec(line);
    if (!field || !section) return null;
    const key = field[1].toLowerCase();
    if (section === 'interface' && /^(jc|jmin|jmax|s[1-4]|h[1-4]|i[1-5]|cps)$/.test(key)) awg = true;
    if (section === 'interface' && key === 'address') address6 ||= field[2].split(',').some(v => v.includes(':'));
    if (section === 'peer' && key === 'allowedips') route6 ||= field[2].split(',').some(v => v.trim() === '::/0');
  }
  if (interfaces !== 1 || peers !== 1) return null;
  return { protocol: awg ? 'amneziawg' : 'wireguard', ipv6: address6 && route6 ? 'tunnel' : 'block', partialIpv6: address6 !== route6 };
}
