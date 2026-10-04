'use strict';
const assert = require('node:assert/strict');
const http = require('node:http');
const net = require('node:net');
const crypto = require('node:crypto');
const { once } = require('node:events');
const { spawn } = require('node:child_process');
const { resolve } = require('node:path');
const { test } = require('node:test');

async function listen(server, port = 0) {
  server.listen(port, '127.0.0.1');
  await once(server, 'listening');
  return server.address().port;
}
async function request(port, path, method = 'GET') {
  return new Promise((resolveRequest, reject) => {
    const req = http.request({ hostname: '127.0.0.1', port, path, method, timeout: 2000 }, res => {
      let body = '';
      res.on('data', data => { body += data; });
      res.on('end', () => resolveRequest({ status: res.statusCode, body }));
    });
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error('Request timeout')));
    req.end();
  });
}

test('client/upstream WebSocket resets preserve the relay and commands are never replayed', { timeout: 12000 }, async () => {
  let commands = 0;
  const upgraded = new Set();
  const api = http.createServer((req, res) => {
    if (req.method === 'POST') commands += 1;
    res.end('api');
  });
  api.on('upgrade', (req, socket) => {
    upgraded.add(socket);
    socket.on('error', () => socket.destroy());
    socket.on('close', () => upgraded.delete(socket));
    const accept = crypto.createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
    socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  });
  const ui = http.createServer((_req, res) => res.end('ui'));
  const apiPort = await listen(api);
  const uiPort = await listen(ui);
  const relayFile = resolve(__dirname, '../../scripts/pilot/preview_relay.cjs');
  const child = spawn(process.execPath, [relayFile, '--listen-port', '0', '--api-port', String(apiPort), '--ui-port', String(uiPort)], { stdio: ['ignore', 'pipe', 'pipe'] });
  let errors = '';
  child.stderr.on('data', data => { errors += data; });
  let client;
  try {
    const [output] = await once(child.stdout, 'data');
    const ready = JSON.parse(output.toString().trim());
    assert.equal(ready.host, '127.0.0.1');
    const port = ready.port;
    assert.deepEqual(await request(port, '/api/v1/probe', 'POST'), { status: 200, body: 'api' });
    assert.equal(commands, 1);
    for (const reset of ['client', 'upstream']) {
      client = net.connect(port, '127.0.0.1');
      client.on('error', () => {});
      await once(client, 'connect');
      client.write('GET /ws/probe HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n');
      const [handshake] = await once(client, 'data');
      assert.match(handshake.toString(), /^HTTP\/1.1 101/);
      // Keep traffic in flight: an idle TCP close need not produce ECONNRESET.
      client.pause();
      for (const socket of upgraded) socket.write(Buffer.alloc(256 * 1024));
      client.write(Buffer.alloc(64 * 1024));
      if (reset === 'client') client.resetAndDestroy();
      else for (const socket of upgraded) socket.resetAndDestroy();
      await new Promise(done => setTimeout(done, 100));
      assert.equal(child.exitCode, null, errors);
      assert.equal((await request(port, '/api/v1/probe')).status, 200);
      client.destroy();
    }
    for (const socket of upgraded) socket.destroy();
    await new Promise(done => api.close(done));
    assert.equal((await request(port, '/api/v1/probe', 'POST')).status, 502);
    assert.equal(commands, 1, 'No upstream command replay');
    assert.deepEqual(await request(port, '/dashboard'), { status: 200, body: 'ui' });
    const rejected = net.connect(port, '127.0.0.1');
    rejected.on('error', () => {});
    await once(rejected, 'connect');
    rejected.write('GET /not-websocket HTTP/1.1\r\nHost: localhost\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n');
    const [reply] = await once(rejected, 'data');
    assert.match(reply.toString(), /^HTTP\/1.1 404/);
    rejected.destroy();
    assert.equal(child.exitCode, null, errors);
  } finally {
    client?.destroy();
    child.kill();
    for (const socket of upgraded) socket.destroy();
    api.closeAllConnections();
    api.close();
    ui.closeAllConnections();
    ui.close();
  }
});
