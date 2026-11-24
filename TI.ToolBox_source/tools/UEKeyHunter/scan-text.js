// scan-text.js - find 64-hex AES keys written in scripts / configs / docs
//   node scan-text.js --dir="E:\game"                      scan a folder (recursive)
//   node scan-text.js --dir="E:\game" --pak="D:\x.pak"     verify against that pak
//   node scan-text.js --file="D:\x.py"                     single file
//   node scan-text.js --dir=... --maxSize=8388608          skip big files (default 4 MiB)
//
// Any 64-hex run (with or without 0x prefix) is a candidate. Each candidate is
// verified against the pak index SHA1, so there is no such thing as a false hit.
'use strict';
const fs = require('fs');
const path = require('path');
const cfg = require('./config');
const { readPakInfo } = require('./lib/pak');
const { verifyIndex } = require('./lib/oracle');

function argStr(name, def) {
  const p = process.argv.find(a => a.startsWith('--' + name + '='));
  if (!p) return def;
  return p.slice(name.length + 3).replace(/^"|"$/g, '').trim();
}
function argNum(name, def) {
  const p = process.argv.find(a => a.startsWith('--' + name + '='));
  if (!p) return def;
  return parseInt(p.slice(name.length + 3).replace(/^"|"$/g, ''), 10) || def;
}

const dirArg = argStr('dir', '');
const fileArg = argStr('file', '');
const maxSize = argNum('maxSize', 4 * 1024 * 1024);
const depthMax = argNum('depth', 12);
const report = path.resolve(argStr('report', cfg.HIT_LOG));
const pakPath = argStr('pak', '') || cfg.needPak();
const pakInfo = readPakInfo(pakPath);
if (!pakInfo) { console.error('cannot read FPakInfo from ' + pakPath); process.exit(2); }

const HEX = /(?:0x)?([0-9a-fA-F]{64})(?![0-9a-fA-F])/g;
const seen = new Map(); // keyhex -> first file
const skipExt = new Set(['.pak', '.ucas', '.utoc', '.sig', '.dll', '.exe', '.pdb', '.bin', '.ufont', '.locres', '.uasset', '.uexp', '.umap']);

function walk(dir, depth, out) {
  if (depth < 0) return out;
  let ents = [];
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return out; }
  for (const e of ents) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { walk(p, depth - 1, out); continue; }
    if (!e.isFile()) continue;
    if (skipExt.has(path.extname(e.name).toLowerCase())) continue;
    let st;
    try { st = fs.statSync(p); } catch { continue; }
    if (st.size > maxSize) continue;
    out.push(p);
  }
  return out;
}

const files = [];
if (fileArg) files.push(path.resolve(fileArg));
else if (dirArg) walk(path.resolve(dirArg), depthMax, files);
else { console.error('usage: node scan-text.js --dir="<folder>" [--pak="<pak>"]'); process.exit(2); }

console.log('pak    : ' + pakPath);
console.log('files  : ' + files.length + (dirArg ? '  (under ' + path.resolve(dirArg) + ')' : ''));
console.log('');

let scanned = 0, cands = 0, hits = 0;
for (const f of files) {
  let buf;
  try { buf = fs.readFileSync(f); } catch { continue; }
  scanned++;
  const s = buf.toString('latin1');
  HEX.lastIndex = 0;
  let m;
  while ((m = HEX.exec(s)) !== null) {
    const hex = m[1].toLowerCase();
    if (!seen.has(hex)) seen.set(hex, f);
  }
  if (scanned % 200 === 0) process.stdout.write('\r  scanned ' + scanned + '/' + files.length + '  candidates ' + seen.size + '   ');
}
cands = seen.size;
process.stdout.write('\r  scanned ' + scanned + '/' + files.length + '  candidates ' + cands + '        \n');
console.log('');

for (const [hex, src] of seen) {
  let v = null;
  try { v = verifyIndex(hex, pakPath, pakInfo); } catch { continue; }
  if (v.match) {
    hits++;
    console.log('[HIT] ' + hex);
    console.log('      file  : ' + src);
    console.log('      index : @' + pakInfo.indexOffset + ' size=' + pakInfo.indexSize);
    console.log('      head  : ' + JSON.stringify(v.head.subarray(0, 64).toString('latin1')));
    fs.appendFileSync(report, hex + '\tTextScan\t' + src + '\n');
    console.log('      saved : ' + report);
    console.log('');
  }
}

if (hits === 0) {
  console.log('done: 0 hits (' + cands + ' candidates checked against pak index SHA1)');
  console.log('tip : the key may live in memory only, or in a DPAPI blob -> use scan-dpapi.ps1');
} else {
  console.log('done: ' + hits + ' verified key(s)');
}
