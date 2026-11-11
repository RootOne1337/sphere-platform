// Run from the repository root with the frontend's installed dependencies.
const { execFileSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const root = process.cwd();
const ts = require(path.join(root, 'frontend/node_modules/typescript'));
const files = execFileSync('git', ['ls-files', '-z', 'frontend/app', 'frontend/src', 'frontend/components', 'frontend/lib', 'frontend/middleware.ts'], { encoding: 'utf8' })
  .split('\0').filter(file => /\.tsx?$/.test(file) && fs.existsSync(file)).sort();
const fileSet = new Set(files);
const short = (value, limit = 240) => value.replace(/\s+/g, ' ').trim().slice(0, limit);
const posix = path.posix;
const native = new Set(['a', 'button', 'input', 'select', 'textarea', 'option', 'summary', 'form', 'details', 'iframe']);
const namedControl = /(?:Button|Trigger|Select|SelectItem|Switch|Checkbox|Radio|Slider|Input|Textarea|Link|CommandItem|Pagination|Tab|MenuItem|DialogClose|Collapsible)$/;
const eventProp = /^on[A-Z]/;
const controlAttr = /^(id|name|type|role|aria-label|aria-labelledby|title|label|placeholder|href|action|value|disabled|checked|readOnly|tabIndex|asChild|download|src|contentEditable)$/;
const requests = /^(?:api|publicApi|authApi|axios)\.(get|post|patch|put|delete|request|head|options)$|^(?:fetch|globalThis\.fetch|window\.fetch|navigator\.sendBeacon|reconstructionRequest|WebSocket|EventSource|RTCPeerConnection)$/;
const attributesThatSignalControl = /^(onClick|onSubmit|onChange|onValueChange|onCheckedChange|onSelect|onKeyDown|onPointerDown|href|contentEditable|tabIndex)$/;

function resolveImport(file, moduleName) {
  const base = moduleName.startsWith('@/') ? `frontend/${moduleName.slice(2)}`
    : moduleName.startsWith('.') ? posix.join(posix.dirname(file), moduleName) : null;
  if (!base) return null;
  return [base, `${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`].find(candidate => fileSet.has(candidate)) ?? null;
}

function ownerOf(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isFunctionDeclaration(current) || ts.isMethodDeclaration(current)) return current.name?.getText() ?? '<default>';
    if (ts.isVariableDeclaration(current) && (ts.isArrowFunction(current.initializer ?? {}) || ts.isFunctionExpression(current.initializer ?? {}))) return current.name.getText();
  }
  return '<module>';
}

function directText(children) {
  return children.map(child => {
    if (ts.isJsxText(child)) return child.getText();
    if (ts.isJsxExpression(child) && child.expression && !ts.isJsxElement(child.expression)) return `{${short(child.expression.getText(), 80)}}`;
    if (ts.isJsxElement(child) && child.openingElement.tagName.getText().toLowerCase() === child.openingElement.tagName.getText()) return directText(child.children);
    return '';
  }).filter(Boolean).join(' ');
}

function scan(file) {
  const contents = fs.readFileSync(file);
  const source = ts.createSourceFile(file, contents.toString('utf8'), ts.ScriptTarget.Latest, true);
  const line = node => source.getLineAndCharacterOfPosition(node.getStart()).line + 1;
  const dependencies = new Set();
  const controls = [];
  const transport = [];

  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const match = resolveImport(file, node.moduleSpecifier.text);
      if (match) dependencies.add(match);
    }
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      const callee = node.expression.getText();
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword && node.arguments?.[0] && ts.isStringLiteral(node.arguments[0])) {
        const match = resolveImport(file, node.arguments[0].text);
        if (match) dependencies.add(match);
      }
      if (requests.test(callee)) {
        const url = node.arguments?.[0] ? short(node.arguments[0].getText()) : null;
        const options = node.arguments?.find(argument => ts.isObjectLiteralExpression(argument) && argument.properties.some(property => property.name?.getText() === 'method'));
        const method = options?.properties.find(property => property.name?.getText() === 'method')?.initializer?.getText();
        transport.push({ line: line(node), owner: ownerOf(node), callee, url, ...(method ? { method } : {}) });
      }
    }
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText();
      const attributes = node.attributes.properties.filter(ts.isJsxAttribute);
      const names = attributes.map(attribute => attribute.name.getText());
      if (native.has(tag) || namedControl.test(tag) || names.some(name => attributesThatSignalControl.test(name))) {
        const props = Object.fromEntries(attributes.filter(attribute => eventProp.test(attribute.name.getText()) || controlAttr.test(attribute.name.getText()))
          .map(attribute => [attribute.name.getText(), attribute.initializer ? short(attribute.initializer.getText()) : true]));
        const text = ts.isJsxOpeningElement(node) ? short(directText(node.parent.children)) : '';
        const spreads = node.attributes.properties.filter(ts.isJsxSpreadAttribute).map(attribute => short(attribute.expression.getText()));
        controls.push({ line: line(node), owner: ownerOf(node), tag, ...(text ? { text } : {}), props, ...(spreads.length ? { spreads } : {}) });
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(source);
  return { sha256: createHash('sha256').update(contents).digest('hex'), dependencies: [...dependencies].sort(), controls, transport };
}

const source = Object.fromEntries(files.map(file => [file, scan(file)]));

function collectFiles(roots) {
  const visited = new Set();
  const queue = roots.slice();
  for (const file of queue) {
    if (visited.has(file)) continue;
    visited.add(file);
    queue.push(...source[file].dependencies);
  }
  return [...visited].sort();
}

function routeFor(file) {
  const parts = file.split('/').slice(2, -1).filter(part => !part.startsWith('('));
  return '/' + parts.join('/');
}

const routes = files.filter(file => file.startsWith('frontend/app/') && /\/(page\.tsx|route\.ts)$/.test(file)).map(entry => {
  const chain = [entry];
  if (entry.endsWith('/page.tsx')) {
    for (let dir = posix.dirname(entry); dir.startsWith('frontend/app'); dir = posix.dirname(dir)) {
      const layout = `${dir}/layout.tsx`;
      if (fileSet.has(layout)) chain.push(layout);
    }
  }
  const allFiles = collectFiles(chain);
  const routeFiles = collectFiles([entry]);
  return { path: routeFor(entry), entry, kind: entry.endsWith('/page.tsx') ? 'page' : 'handler', layouts: chain.slice(1), routeFiles, allFiles };
}).sort((left, right) => left.path.localeCompare(right.path));

const frontendChanges = execFileSync('git', ['status', '--short', '--', 'frontend'], { encoding: 'utf8' }).trimEnd().split(/\r?\n/).filter(Boolean);
const head = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
const output = { head, frontendChanges, counts: { pages: routes.filter(route => route.kind === 'page').length,
  serverHandlers: routes.filter(route => route.kind === 'handler').length, files: files.length,
  jsxDeclarations: files.reduce((total, file) => total + source[file].controls.length, 0),
  recognizedTransportCalls: files.reduce((total, file) => total + source[file].transport.length, 0) }, routes, source };
// Preserve one entry per line in the JSON arrays of controls and transports.
const compact = JSON.stringify(output, null, 2).replace(/\{\n {10}"line": [\s\S]*?\n {8}\}/g, entry => JSON.stringify(JSON.parse(entry)));
fs.writeFileSync(path.join(__dirname, 'web-inventory.json'), `${compact}\n`);
console.log(JSON.stringify(output.counts));
