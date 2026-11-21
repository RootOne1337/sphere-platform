import { parseSphereFrame } from '@/lib/sphere-frame';

function golden(): ArrayBuffer {
  const hex = '020100000000000030390000000600112233445566778899aabbccddeeff000000016542';
  return Uint8Array.from(hex.match(/../g)!, byte => parseInt(byte, 16)).buffer;
}

it('parses the independent network-order v2 fixture without converting the NAL bytes', () => {
  const input = golden();
  const envelope = parseSphereFrame(input)!;
  expect(envelope).toMatchObject({ version: 2, timestampUs: 12345000,
    captureEpoch: '00112233-4455-6677-8899-aabbccddeeff' });
  expect(envelope.payload.buffer).toBe(input);
  expect([...envelope.payload]).toEqual([0, 0, 0, 1, 0x65, 0x42]);
});

it('reads the v1 header without inventing a capture identity', () => {
  const modern = new Uint8Array(golden());
  const legacy = new Uint8Array(20);
  legacy.set(modern.subarray(0, 14)); legacy[0] = 1; legacy.set(modern.subarray(30), 14);
  expect(parseSphereFrame(legacy.buffer)).toMatchObject({ version: 1, captureEpoch: null, timestampUs: 12345000 });
});

it.each(['short', 'version', 'size', 'nil', 'flags', 'empty', 'oversize', 'negative', 'unsafe'])
('rejects a malformed %s capture envelope without throwing', damage => {
  let data = golden(); const view = new DataView(data);
  if (damage === 'short') data = data.slice(0, 29);
  if (damage === 'version') view.setUint8(0, 3);
  if (damage === 'size') view.setUint32(10, 999);
  if (damage === 'nil') new Uint8Array(data, 14, 16).fill(0);
  if (damage === 'flags') view.setUint8(1, 3);
  if (damage === 'empty') { data = data.slice(0, 30); new DataView(data).setUint32(10, 0); }
  if (damage === 'oversize') {
    const bytes = new Uint8Array(30 + 1024 * 1024 + 1); bytes.set(new Uint8Array(data));
    new DataView(bytes.buffer).setUint32(10, bytes.length - 30); data = bytes.buffer;
  }
  if (damage === 'negative') view.setBigInt64(2, -1n);
  if (damage === 'unsafe') view.setBigInt64(2, 9007199254740991n);
  expect(() => parseSphereFrame(data)).not.toThrow();
  expect(parseSphereFrame(data)).toBeNull();
});
