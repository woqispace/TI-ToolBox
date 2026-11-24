// verify-cands.js - check a list of candidate keys against one pak, keep the real one
//   node verify-cands.js --pak="D:\x.pak" cands.txt
//   node verify-cands.js --pak="D:\x.pak" --text="<hex>" "<hex>" ...
//
// Input: a file with hex strings (64 chars, with or without 0x). Everything that
// is not 64-hex is ignored. A hit is proven by index SHA1 equality, so it cannot
// be a false positive.
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

const pakPath = argStr('pak', '') || cfg.needPak();
const report = path.resolve(argStr('report', cfg.HIT_LOG));
const pakInfo = readPakInfo(pakPath);
if (!pakInfo) { console.error('cannot read FPakInfo from ' + pakPath); process.exit(2); }

const positional = process.argv.slice(2).filter(a => !a.startsWith('--'));
let lines = [];
if (positional.length > 0 && fs.existsSync(positional[0])) {
  lines = fs.readFileSync(positional[0], 'latin1').split(/\r?\n/);
} else if (positional.length > 0) {
  lines = positional;
} else {
  console.error('usage: node verify-cands.js --pak="<pak>" <cands.txt>');
  process.exit(2);
}

const HEX = /(?:0x)?([0-9a-fA-F]{64})(?![0-9a-fA-F])/g;
const cands = [];
for (const line of lines) {
  HEX.lastIndex = 0;
  let m;
  while ((m = HEX.exec(line)) !== null) cands.push(m[1].toLowerCase());
}
const uniq = [...new Set(cands)];

console.log('pak       : ' + pakPath);
console.log('index     : @' + pakInfo.indexOffset + ' size=' + pakInfo.indexSize);
console.log('candidates: ' + uniq.length);
console.log('');

let hits = 0;
for (const hex of uniq) {
  let v = null;
  try { v = verifyIndex(hex, pakPath, pakInfo); } catch { continue; }
  if (v.match) {
    hits++;
    console.log('[HIT] ' + hex);
    console.log('      head : ' + JSON.stringify(v.head.subarray(0, 64).toString('latin1')));
    fs.appendFileSync(report, hex + '\tVerifyCands\t' + pakPath + '\n');
  }
}

if (hits === 0) {
  console.log('done: 0 hits (' + uniq.length + ' candidates)');
  process.exit(1);
}
console.log('done: ' + hits + ' verified key(s), saved to ' + report);
