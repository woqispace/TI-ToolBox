// cleanup.js — 清理残留（内存转储 mem\ 等）
//   node cleanup.js                 看现在有多少残留（默认）
//   node cleanup.js show            同上
//   node cleanup.js do              真的删（mem 下所有 .bin 与空目录）
//   node cleanup.js auto on|off     一次性开关「自动清理」
//   node cleanup.js before on|off   抓内存前自动清
//   node cleanup.js after on|off    扫完内存后自动清
//   node cleanup.js keep 2          清理时保留最近 2 次转储目录
// 自动清理的钩子（run.bat 会调用，手动跑也行）：
//   node cleanup.js --auto-before-dump
//   node cleanup.js --auto-after-scan
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.dirname(require.main.filename);
const MEM = path.join(ROOT, 'mem');
const CFG_FILE = path.join(ROOT, 'cleanup.config.json');
const DEFAULTS = { autoCleanBeforeDump: false, autoCleanAfterScan: false, keepNewestDumps: 0 };

function loadCfg() {
  try {
    const j = JSON.parse(fs.readFileSync(CFG_FILE, 'utf8'));
    return Object.assign({}, DEFAULTS, j);
  } catch (e) {
    return Object.assign({}, DEFAULTS);
  }
}

function saveCfg(c) {
  fs.writeFileSync(CFG_FILE, JSON.stringify(c, null, 2) + '\n', 'utf8');
}

function human(n) {
  if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(2) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

// 列出 mem 下的转储目录与散落文件
function survey() {
  const out = { dirs: [], looseFiles: [], totalFiles: 0, totalBytes: 0, exists: fs.existsSync(MEM) };
  if (!out.exists) return out;
  for (const name of fs.readdirSync(MEM)) {
    const p = path.join(MEM, name);
    let st;
    try { st = fs.statSync(p); } catch (e) { continue; }
    if (st.isDirectory()) {
      let files = 0, bytes = 0, newest = 0;
      (function walk(d) {
        for (const f of fs.readdirSync(d)) {
          const fp = path.join(d, f);
          let s;
          try { s = fs.statSync(fp); } catch (e) { continue; }
          if (s.isDirectory()) walk(fp);
          else { files++; bytes += s.size; if (s.mtimeMs > newest) newest = s.mtimeMs; }
        }
      })(p);
      out.dirs.push({ name, path: p, files, bytes, mtime: st.mtimeMs, newest });
      out.totalFiles += files;
      out.totalBytes += bytes;
    } else {
      out.looseFiles.push({ name, path: p, bytes: st.size, mtime: st.mtimeMs });
      out.totalFiles += 1;
      out.totalBytes += st.size;
    }
  }
  out.dirs.sort((a, b) => b.mtime - a.mtime);
  return out;
}

function printSurvey(s, cfg) {
  console.log('残留检查 —— ' + MEM);
  if (!s.exists) {
    console.log('  （还没有 mem 目录，没有残留）');
  } else if (!s.dirs.length && !s.looseFiles.length) {
    console.log('  （mem 目录是空的，没有残留）');
  } else {
    console.log('  目录：');
    s.dirs.forEach((d, i) => {
      console.log(`    ${i === 0 ? '*' : ' '} ${d.name}   ${d.files} 个文件 / ${human(d.bytes)}   最后写入 ${new Date(d.newest).toLocaleString()}`);
    });
    if (s.looseFiles.length) {
      console.log('  散落文件：');
      s.looseFiles.forEach(f => console.log(`    - ${f.name}   ${human(f.bytes)}`));
    }
    console.log(`  合计：${s.totalFiles} 个文件 / ${human(s.totalBytes)}`);
  }
  console.log('');
  console.log('自动清理设置（cleanup.config.json）：');
  console.log('  抓内存前清理 (autoCleanBeforeDump): ' + (cfg.autoCleanBeforeDump ? '开' : '关'));
  console.log('  扫完内存后清理 (autoCleanAfterScan): ' + (cfg.autoCleanAfterScan ? '开' : '关'));
  console.log('  清理时保留最近几份 (keepNewestDumps): ' + cfg.keepNewestDumps);
}

// 真的删；keepNewest>0 时保留最近 N 个目录
function doClean(cfg, silent) {
  const s = survey();
  if (!s.exists) {
    if (!silent) console.log('没有 mem 目录，无需清理。');
    return { removedFiles: 0, freedBytes: 0 };
  }
  const keep = Math.max(0, Number(cfg.keepNewestDumps) || 0);
  const keepSet = new Set(s.dirs.slice(0, keep).map(d => d.name));
  let removedFiles = 0, freedBytes = 0;

  for (const d of s.dirs) {
    if (keepSet.has(d.name)) {
      if (!silent) console.log(`  保留 ${d.name}（${d.files} 个文件 / ${human(d.bytes)}）`);
      continue;
    }
    fs.rmSync(d.path, { recursive: true, force: true });
    removedFiles += d.files;
    freedBytes += d.bytes;
    if (!silent) console.log(`  已删目录 ${d.name}（${d.files} 个文件 / ${human(d.bytes)}）`);
  }
  for (const f of s.looseFiles) {
    try {
      fs.rmSync(f.path, { force: true });
      removedFiles += 1;
      freedBytes += f.bytes;
      if (!silent) console.log(`  已删文件 ${f.name}（${human(f.bytes)}）`);
    } catch (e) {
      if (!silent) console.log(`  删不掉 ${f.name}: ${e.message}`);
    }
  }
  // 空目录一并收走
  try {
    if (fs.existsSync(MEM) && fs.readdirSync(MEM).length === 0) fs.rmdirSync(MEM);
  } catch (e) { /* 忽略 */ }

  const msg = `清理完成：删掉 ${removedFiles} 个文件，释放 ${human(freedBytes)}`;
  console.log((silent ? '[auto] ' : '') + msg);
  return { removedFiles, freedBytes };
}

const argv = process.argv.slice(2);
const cmd = (argv[0] || 'show').toLowerCase();
let cfg = loadCfg();

if (cmd === 'auto') {
  const v = (argv[1] || '').toLowerCase();
  if (v !== 'on' && v !== 'off') { console.log('用法: node cleanup.js auto on|off'); process.exit(1); }
  cfg.autoCleanBeforeDump = v === 'on';
  cfg.autoCleanAfterScan = v === 'on';
  saveCfg(cfg);
  console.log('自动清理已' + (v === 'on' ? '打开' : '关闭') + '（抓内存前 + 扫完后都' + (v === 'on' ? '自动清' : '不自动清') + '）');
  process.exit(0);
}

if (cmd === 'before' || cmd === 'after') {
  const v = (argv[1] || '').toLowerCase();
  if (v !== 'on' && v !== 'off') { console.log(`用法: node cleanup.js ${cmd} on|off`); process.exit(1); }
  const key = cmd === 'before' ? 'autoCleanBeforeDump' : 'autoCleanAfterScan';
  cfg[key] = v === 'on';
  saveCfg(cfg);
  console.log((cmd === 'before' ? '抓内存前清理' : '扫完后清理') + ' 已' + (v === 'on' ? '打开' : '关闭'));
  process.exit(0);
}

if (cmd === 'keep') {
  const n = parseInt(argv[1], 10);
  if (!Number.isFinite(n) || n < 0) { console.log('用法: node cleanup.js keep <保留份数，0 = 全删>'); process.exit(1); }
  cfg.keepNewestDumps = n;
  saveCfg(cfg);
  console.log('清理时保留最近 ' + n + ' 份转储目录');
  process.exit(0);
}

if (cmd === 'do') {
  const s = survey();
  if (!s.exists || (!s.dirs.length && !s.looseFiles.length)) { console.log('没有残留，无需清理。'); process.exit(0); }
  printSurvey(s, cfg);
  console.log('');
  doClean(cfg, false);
  process.exit(0);
}

if (cmd === '--auto-before-dump') {
  if (cfg.autoCleanBeforeDump) { console.log(''); console.log('[auto] 抓内存前清理残留…'); doClean(cfg, false); }
  process.exit(0);
}

if (cmd === '--auto-after-scan') {
  if (cfg.autoCleanAfterScan) { console.log(''); console.log('[auto] 扫完后清理残留…'); doClean(cfg, false); }
  process.exit(0);
}

// 默认 / show
printSurvey(survey(), cfg);
console.log('');
console.log('可用命令：');
console.log('  node cleanup.js do           真的删（按上面的保留设置）');
console.log('  node cleanup.js auto on|off  打开/关闭自动清理（两项一起）');
console.log('  node cleanup.js before on|off  抓内存前自动清');
console.log('  node cleanup.js after on|off   扫完后自动清');
console.log('  node cleanup.js keep 2       清理时保留最近 2 份');
