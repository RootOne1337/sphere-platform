'use strict';
// Loopback-only preview of the existing authenticated API and compiled UI.
// No retries: a failed command remains an unknown outcome for its caller.
const http = require('node:http');
const proxyModule = require('../../frontend/node_modules/next/dist/compiled/http-proxy');

function port(name, fallback, allowZero = false) {
  const index = process.argv.indexOf(name);
  const value = index < 0 ? fallback : Number(process.argv[index + 1]);
  if (!Number.isInteger(value) || value < (allowZero ? 0 : 1) || value > 65535) throw new Error(`Invalid ${name}`);
  return value;
}

const host = '127.0.0.1';
const listenPort = port('--listen-port', 3015, true);
const apiOrigin = `http://${host}:${port('--api-port', 18080)}`;
const uiOrigin = `http://${host}:${port('--ui-port', 3014)}`;
const proxy = proxyModule.createProxyServer({ changeOrigin: true, ws: true });
const sockets = new Set();

function protectSocket(socket) {
  // Upgraded sockets no longer have the HTTP server's usual error handler.
  // An upstream restart or client RST must close this connection, not Node.
  socket.on('error', () => socket.destroy());
}

proxy.on('error', (_error, _request, response) => {
  if (!response || response.destroyed) return;
  if (typeof response.writeHead === 'function') {
    if (response.headersSent) { response.destroy(); return; }
    response.writeHead(502, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
    response.end(JSON.stringify({ detail: 'Local preview upstream is unavailable.' }));
  } else response.destroy();
});

const server = http.createServer((req, res) => {
  let pathname;
  try { pathname = new URL(req.url || '/', `http://${host}`).pathname; }
  catch { res.writeHead(400); res.end(); return; }
  if (pathname === '/' && (req.method === 'GET' || req.method === 'HEAD')) {
    res.writeHead(307, { location: '/dashboard', 'cache-control': 'no-store' });
    res.end();
    return;
  }
  const isApi = pathname === '/api/v1' || pathname.startsWith('/api/v1/');
  if (isApi) {
    req.headers.origin = apiOrigin;
    req.headers.referer = `${apiOrigin}/`;
  }
  proxy.web(req, res, { target: isApi ? apiOrigin : uiOrigin });
});

server.on('connection', socket => {
  sockets.add(socket);
  protectSocket(socket);
  socket.once('close', () => sockets.delete(socket));
});
server.on('upgrade', (req, socket, head) => {
  let pathname;
  try { pathname = new URL(req.url || '/', `http://${host}`).pathname; }
  catch { socket.destroy(); return; }
  if (!pathname.startsWith('/ws/')) {
    socket.end('HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n');
    return;
  }
  req.headers.origin = apiOrigin;
  req.headers.referer = `${apiOrigin}/`;
  proxy.ws(req, socket, head, { target: apiOrigin });
});
server.on('clientError', (_error, socket) => socket.destroy());
proxy.on('proxyReqWs', request => {
  request.on('socket', socket => protectSocket(socket));
});

server.listen(listenPort, host, () => {
  process.stdout.write(JSON.stringify({ listening: true, host, port: server.address().port }) + '\n');
});
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => {
  server.close();
  for (const socket of sockets) socket.destroy();
  proxy.close();
});
