window.onerror = function(m, src, l, c, e) { document.title = 'ERR: ' + m + ' @' + l; };
'use strict';

/* 全部模块与任务都来自 catalog.json，新增工具只改那个文件 */
let CATALOG = { modules: [], vars: {} };
let VARS = {};
let state = { target: {}, aeskeys: [] };
let curMod = null;
let curTask = null;
let jobId = null;
let since = 0;
let timer = null;

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

async function api(path, body) {
  const opt = body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {};
  const r = await fetch(path, opt);
  return r.json();
}

/* ---------------- 侧边栏：一个按钮内分左右两段 ---------------- */
function syncRail() {
  const side = document.querySelector('.side');
  const nav = document.querySelector('#nav');
  if (!side || !nav) return;
  const items = nav.querySelectorAll('.nav-item');
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const navTop = nav.offsetTop;
  const top = navTop + first.offsetTop + 4;
  const bottom = navTop + last.offsetTop + last.offsetHeight - 4;
  side.style.setProperty('--rail-top', top + 'px');
  side.style.setProperty('--rail-h', Math.max(40, bottom - top) + 'px');
}

function syncRailSoon() {
  [0, 120, 260, 420, 900, 1500, 2100].forEach((d) => setTimeout(syncRail, d));
}

window.addEventListener('resize', syncRail);
document.addEventListener('transitionend', (e) => {
  if (e.target && e.target.classList && e.target.classList.contains('nav-item')) syncRail();
}, true);
window.addEventListener('load', syncRailSoon);


function staggerPanel() {
  const main = document.querySelector('.main');
  if (!main) return;
  if (document.body.classList.contains('no-anim')) return;
  let n = 0;
  const groups = ['#subnav > *', '.panel-head', '#params > *', '.actions > *', '.console-wrap', '.keybar'];
  groups.forEach((sel) => {
    main.querySelectorAll(sel).forEach((el) => {
      el.style.setProperty('--i', String(n++));
    });
  });
}


function pageIn() {
  const main = document.querySelector('.main');
  if (!main) return;
  if (document.body.classList.contains('no-anim')) { main.classList.remove('page-in', 'page-out'); return; }
  staggerPanel();
  main.classList.remove('page-out');
  main.classList.remove('page-in');
  void main.offsetWidth;
  main.classList.add('page-in');
  clearTimeout(pageIn._t);
  pageIn._t = setTimeout(() => main.classList.remove('page-in'), 900);
}

function pageOut(cb) {
  const main = document.querySelector('.main');
  if (!main || !window.CATALOG || document.body.classList.contains('no-anim')) { cb(); return; }
  main.classList.remove('page-in');
  main.classList.add('page-out');
  clearTimeout(pageOut._t);
  pageOut._t = setTimeout(() => {
    main.classList.remove('page-out');
    cb();
  }, 130);
}

function renderNav() {
  const nav = $('#nav');
  // 已经渲染过就别整块重建（重建会让侧栏闪一下 = 抽搐）
  if (nav.childElementCount === (CATALOG.modules || []).length) {
    nav.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.mod === curMod));
    syncRailSoon();
    return;
  }
  nav.innerHTML = CATALOG.modules.map((m) => {
    const soon = m.status !== 'ready';
    return '<div class="nav-item' + (soon ? ' soon' : '') + (m.id === curMod ? ' active' : '') + '" data-mod="' + esc(m.id) + '">' +
        '<button class="ni-main" id="nav_' + esc(m.id) + '"' + (soon ? ' disabled' : '') + '>' +
          '<span class="ni-name">' + esc(m.name) + '</span>' +
          '<span class="ni-ver">' + esc(m.ver || '') + (soon ? ' · 开发中' : '') + '</span>' +
        '</button>' +
        '<button class="ni-intro" title="看简介"><span class="ni-ico">\u203a</span><span class="ni-txt">\u7b80\u4ecb</span></button>' +
      '</div>';
  }).join('');
  nav.querySelectorAll('.nav-item').forEach((box) => {
    const id = box.dataset.mod;
    box.querySelector('.ni-main').onclick = () => {
      if (box.classList.contains('soon')) return;
      // 已经选中同一个工具就别再播一次切换动画（m18098）
      if (id === curMod) return;
      selectModule(id);
    };
    box.querySelector('.ni-intro').onclick = (e) => { e.stopPropagation(); openIntro(id); };
  });
  syncRailSoon();
}

function moduleById(id) {
  return CATALOG.modules.find((m) => m.id === id);
}


/* ---------- 主页 ---------- */
let homeTyped = false;
let homeAnimated = false;   // 主页入场动画只播一次（m18133）

/* 署名渐显：加动画类，同时兜底把最终态写死（动画因任何原因没跑也不会消失） */
function signFinal(sign) {
  if (!sign) return;
  sign.classList.remove('show');
  sign.style.opacity = '1';
  sign.style.filter = 'none';
  sign.style.transform = 'none';
  sign.style.clipPath = 'none';
  sign.dataset.done = '1';
}

function revealSign(sign, instant) {
  if (!sign) return;
  if (instant || sign.dataset.done === '1') { signFinal(sign); return; }   // 已经播过就别再播
  sign.classList.add('show');
  setTimeout(() => signFinal(sign), 1350);
}

let homeTimer = null;
let homePlayed = false;

function typeHome() {
  const box = $('#homeType');
  const sign = document.querySelector('.home-sign');
  if (!box) return;
  const text = '欢迎使用TI工具箱';
  box.textContent = '';
  if (sign) { sign.classList.remove('show'); delete sign.dataset.done; }
  let i = 0;
  // 兜底：动画/定时器万一被节流，4 秒后强制定格（不会出现"文字没了"
  const guard = setTimeout(() => {
    const b2 = $('#homeType');
    if (b2) b2.textContent = text;
    signFinal(document.querySelector('.home-sign'));   // 直接定格，绝不重播
  }, 4000);
  const tick = () => {
    if (i <= text.length) {
      box.textContent = text.slice(0, i);
      i += 1;
      homeTimer = setTimeout(tick, 150);
      } else if (sign) {
      // 大字打完，署名从左往右缓缓浮出
      revealSign(sign, false);
    }
  };
  tick();
}

async function loadChangelog() {
  const box = $('#homeLog');
  if (!box) return;
  box.textContent = '加载中…';
  try {
    const r = await api('/api/changelog', {});
    box.textContent = (r && r.text) ? r.text : '（还没有更新日志，写 changelog.md 放在 exe 旁边即可）';
  } catch (e) { box.textContent = '读取失败：' + e.message; }
}

function showHome(on) {
  const home = $('#homePane');
  if (!home) return;
  home.hidden = !on;                       // 覆盖层显隐，下面的面板不动 → 无重排
  if (on) {
    // 入场动画只在第一次进主页时播；之后来回切都不再重播（m18133）
    if (!homeAnimated) {
      homeAnimated = true;
      home.classList.remove('home-in');
      void home.offsetWidth;
      home.classList.add('home-in');
      clearTimeout(showHome._t);
      showHome._t = setTimeout(() => home.classList.remove('home-in'), 900);
    }
  }
  const main = document.querySelector('.main');
  if (main) main.classList.toggle('home-mode', !!on);
  document.body.classList.toggle('on-home', !!on);
  syncRailSoon();
  if (on) {
    clearTimeout(homeTimer);
    if (!homePlayed) {
      homePlayed = true;
      typeHome();
    } else {
      const box = $('#homeType');
      if (box) box.textContent = '欢迎使用TI工具箱';
      const sign = document.querySelector('.home-sign');
      if (sign) {
        sign.classList.remove('show');        // 去掉动画类，避免 display 切换时重播
        sign.style.opacity = '1';
        sign.style.filter = 'none';
        sign.style.transform = 'none';
        sign.style.clipPath = 'none';
      }
    }
    const _hb = document.getElementById('homeLogBox');
    if (_hb) setLogCollapsed(_hb, true);
    loadChangelog();
  }
}


/* 每个工具的目录标签 / key 面板策略 */
function applyModuleChrome(mod) {
  const kmode = (mod && mod.keysPanel) || 'none';
  document.body.classList.toggle('key-module', kmode !== 'none');
  const keys = document.querySelector('.keys');
  const mode = (mod && mod.keysPanel) || 'none';
  if (keys) {
    keys.hidden = (mode === 'none');
    keys.classList.toggle('collapsed', mode === 'collapsible');
      document.body.classList.toggle('key-collapsed', mode === 'collapsible');
      const kb = keys.parentElement;
      if (kb && kb.classList.contains('keybar')) kb.classList.toggle('open', mode === 'always');   // 其它工具默认折叠
    keys.classList.remove('drawer', 'open');
  }
  if (!mod) return;
  const LABELS = { keys: '游戏目录', text: '资产目录（解包后的 CONTENT）', sig: '游戏 Shipping 路径（.exe）', unpack: '游戏目录' };
  const lab = document.querySelector('#dirbar .topbar label');
  if (lab) lab.textContent = mod.dirLabel || LABELS[mod.id] || '游戏目录';
  const paths = document.querySelector('#dirbar .paths');
  if (paths) paths.hidden = !(mod.id === 'keys' || mod.id === 'unpack');
  const ok = document.getElementById('openkey');
  if (ok) ok.hidden = (mode === 'none');
  const ab = document.getElementById('assetbox');
  if (ab) ab.hidden = (mod.id !== 'uasset');
  const lb = document.getElementById('locresbox');
  if (lb) lb.hidden = (mod.id !== 'uasset');
}


/* 自定义历史下拉：点输入框就列出用过的路径（WebView2 不给 datalist 画箭头）*/
let _histPop = null;
function closeHistPop() { if (_histPop) { _histPop.remove(); _histPop = null; } }
function attachHist(inp, getList) {
  if (!inp || inp.dataset.histPopBound) return;
  inp.dataset.histPopBound = '1';
  const open = () => {
    const vals = (getList() || []).filter((v) => !!v);
    closeHistPop();
    if (!vals.length) return;
    const pop = document.createElement('div');
    pop.className = 'hist-pop';
    const cur = (inp.value || '').trim();
    pop.innerHTML = vals.map((v) => '<div class="hist-item' + (v === cur ? ' cur' : '') + '" data-v="' + esc(v) + '">' + esc(v) + '</div>').join('');
    document.body.appendChild(pop);
    const r = inp.getBoundingClientRect();
    // absolute 相对文档，避免 .main 的 transform 把 fixed 拉去当包含块（会与输入框重叠）
    pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 260)) + 'px';
    pop.style.top = (r.bottom + window.scrollY + 6) + 'px';
    pop.style.width = Math.max(240, r.width) + 'px';
    pop.onmousedown = (e) => e.preventDefault();   // 别抢走输入框焦点
    pop.addEventListener('click', (e) => {
      const it = e.target.closest('.hist-item'); if (!it) return;
      inp.value = it.dataset.v;
      inp.dispatchEvent(new Event('change'));
      closeHistPop();
    });
    _histPop = pop;
  };
  inp.addEventListener('focus', open);
  inp.addEventListener('click', open);
  inp.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeHistPop(); });
  inp.addEventListener('blur', () => setTimeout(closeHistPop, 150));
  window.addEventListener('resize', closeHistPop);
}

function dirStoreKey(modId, field) { return 'dir:' + modId + (field === 'pak' ? ':pak' : ''); }

/* 每个工具各自记住自己的目录（不再全局固定） */
function dirHistKey(id) { return 'dirhist:' + id; }

function dirHistRead(id) {
  try { return JSON.parse(localStorage.getItem(dirHistKey(id)) || '[]') || []; } catch (e) { return []; }
}

function pushDirHist(id, val) {
  val = (val || '').trim();
  if (!id || !val) return;
  const arr = dirHistRead(id).filter((x) => x !== val);
  arr.unshift(val);
  try { localStorage.setItem(dirHistKey(id), JSON.stringify(arr.slice(0, 10))); } catch (e) {}
}

/* 调试钩子：?seedhist=<路径> 往当前模块的历史里塞一条，便于自测下拉 */
function _seedHistOnce() {
  const m = location.search.match(/[?&]seedhist=([^&]+)/);
  if (!m) return;
  try {
    const v = decodeURIComponent(m[1]);
    pushDirHist(curMod, v);
    fillDirHist(curMod);
    if (location.search.includes('seedhist=')) document.title = 'SEEDED ' + curMod + ' ' + dirHistRead(curMod).length;
  } catch (e) {}
}

function toolHistKey(key) { return 'toolhist:' + key; }

function toolHistRead(key) {
  try { return JSON.parse(localStorage.getItem(toolHistKey(key)) || '[]') || []; } catch (e) { return []; }
}

function pushToolHist(key, val) {
  const v = (val || '').trim();
  if (!key || !v) return;
  const arr = toolHistRead(key).filter((x) => x !== v);
  arr.unshift(v);
  try { localStorage.setItem(toolHistKey(key), JSON.stringify(arr.slice(0, 12))); } catch (e) {}
}

function fillDirHist(id) {
  const dl = document.getElementById('dirhist');
  if (!dl) return;
  const arr = dirHistRead(id).slice();
  const cur2 = (($('#game') && $('#game').value) || '').trim();
  if (cur2 && arr.indexOf(cur2) < 0) arr.unshift(cur2);
  dl.innerHTML = arr.map((v) => '<option value="' + esc(v) + '"></option>').join('');
}

function applyDir(mod) {
  const bar = document.getElementById('dirbar');
  const need = !!(mod && mod.dir);
  if (bar) bar.hidden = !need;
  if (!need) return;
  const saved = localStorage.getItem(dirStoreKey(mod.id)) || '';
  const gEl = $('#game');
  if (gEl) gEl.value = saved;   /* 切模块必须无条件覆盖，否则会残留上一个工具的目录（m17888） */
  fillDirHist(mod.id);
  _seedHistOnce();
  const gi = $('#game');
  if (gi) attachHist(gi, () => { const a = dirHistRead(curMod).slice(); const v = (gi.value || '').trim(); if (v && a.indexOf(v) < 0) a.unshift(v); return a; });
  if (gi && !gi.dataset.histBound) {
    gi.dataset.histBound = '1';
    const commit = () => { if (curMod) { saveDir(curMod, 'game', gi.value.trim()); pushDirHist(curMod, gi.value); fillDirHist(curMod); } };
    gi.addEventListener('change', commit);
    gi.addEventListener('blur', commit);
  }
  const savedPak = localStorage.getItem(dirStoreKey(mod.id, 'pak')) || '';
  const pkEl = $('#pak'); if (pkEl) pkEl.textContent = savedPak || '—';
  const exEl = $('#exe'); if (exEl) exEl.textContent = localStorage.getItem(dirStoreKey(mod.id, 'exe')) || '—';
  fillDirParams(mod);
  if (mod.id === 'uasset') {
    const ab = $('#assetbox');
    if (ab) ab.hidden = false;
    loadAssets((localStorage.getItem(dirStoreKey(mod.id)) || '').trim());
    const lp = document.getElementById('locresPath');
    if (lp && !lp.value) lp.value = (localStorage.getItem('locres:last') || '');
    loadLocres(lp ? lp.value.trim() : '');
  }
}

/* ---------- 资产查看：列出“资产路径”内的 UE 资产 ---------- */
async function loadAssets(dir) {
  const box = $('#assetbox');
  const list = $('#assetList');
  const cnt = $('#assetCount');
  if (!box || !list) return;
  box.hidden = false;
  if (!dir) {
    if (cnt) cnt.textContent = '—';
    list.innerHTML = '<div class="asset-empty">在上方填写或选择「资产路径」（解包后的 Content 目录）。</div>';
    return;
  }
  list.innerHTML = '<div class="asset-empty">正在读取…</div>';
  const r = await api('/api/listassets', { dir: dir, limit: 1200 }).catch(() => null);
  if (!r || !r.ok) {
    if (cnt) cnt.textContent = '—';
    list.innerHTML = '<div class="asset-empty">' + esc((r && r.error) || '读取失败') + '</div>';
    return;
  }
  const c = r.counts || {};
  if (cnt) cnt.textContent = (c.total || 0) + ' 项（uasset ' + (c.uasset || 0) + ' · umap ' + (c.umap || 0) + ' · uexp ' + (c.uexp || 0) + '）';
  const items = r.items || [];
  if (!items.length) {
    list.innerHTML = '<div class="asset-empty">该路径下没有 .uasset / .umap / .uexp。</div>';
    return;
  }
  list.innerHTML = items.map((it) => {
    const dot = it.lastIndexOf('.');
    const ext = dot >= 0 ? it.slice(dot + 1).toLowerCase() : '';
    return '<div class="asset-row"><span class="ext">' + esc(ext) + '</span><span class="p">' + esc(it) + '</span></div>';
  }).join('');
}

/* 把该工具记住的目录填进任务参数里的 dir / pak 输入框 */
function fillDirParams(mod) {
  const d = localStorage.getItem(dirStoreKey(mod.id)) || '';
  const pk = localStorage.getItem(dirStoreKey(mod.id, 'pak')) || '';
  const pd = $('#p_dir'); if (pd) pd.value = d;      /* 切模块无条件覆盖（m17888） */
  const pp = $('#p_pak'); if (pp && pk) pp.value = pk;
}

function saveDir(modId, field, val) {
  if (!modId) return;
  try { localStorage.setItem(dirStoreKey(modId, field), val || ''); } catch (e) {}
}



/* ---------- 参数历史（每个工具/任务/参数各自独立） ---------- */
function histKey(modId, taskId, pid) {
  return 'hist:' + modId + ':' + taskId + ':' + pid;
}

function histRead(modId, taskId, pid) {
  try {
    const raw = localStorage.getItem(histKey(modId, taskId, pid));
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch (e) { return []; }
}

function histPush(modId, taskId, pid, val) {
  const v = String(val || '').trim();
  if (!v) return;
  const arr = histRead(modId, taskId, pid).filter((x) => x !== v);
  arr.unshift(v);
  try { localStorage.setItem(histKey(modId, taskId, pid), JSON.stringify(arr.slice(0, 12))); } catch (e) {}
}

function attachHistory(modId, taskId, pid, input) {
  if (!input) return;
  const dlId = 'dl_' + pid;
  let dl = document.getElementById(dlId);
  if (!dl) {
    dl = document.createElement('datalist');
    dl.id = dlId;
    document.body.appendChild(dl);
  }
  const fill = () => {
    dl.innerHTML = histRead(modId, taskId, pid)
      .map((v) => '<option value="' + v.replace(/"/g, '&quot;') + '"></option>')
      .join('');
  };
  fill();
  input.setAttribute('list', dlId);
  input.addEventListener('change', () => { histPush(modId, taskId, pid, input.value); fill(); });
}

function renderCacheInfo() {
  const el = document.getElementById('s_cacheinfo');
  if (!el) return;
  let n = 0;
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf('hist:') === 0) n++;
    }
  } catch (e) {}
  el.textContent = n ? ('已记录 ' + n + ' 条参数历史') : '暂无参数历史';
}

async function clearCache() {
  try {
    const r = await api('/api/clearcache', 'POST', {});
    setStatus('已清理缓存 · 临时文件 ' + ((r && r.removed) || 0) + ' 个', 'ok');
  } catch (e) {
    setStatus('清理失败', 'bad');
  }
  try {
    const ks = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf('hist:') === 0) ks.push(k);
    }
    ks.forEach((k) => localStorage.removeItem(k));
  } catch (e) {}
  renderCacheInfo();
}

/* ---------- 资产查看：查看 .locres 内容（key / source / target） ---------- */
async function loadLocres(path) {
  const box = $('#locresbox');
  const list = $('#locresList');
  const cnt = $('#locresCount');
  if (!box || !list) return;
  box.hidden = false;
  const p0 = (path || '').trim();
  if (!p0) {
    if (cnt) cnt.textContent = '—';
    list.innerHTML = '<div class="asset-empty">选择一个 .locres 文件后点「查看」。</div>';
    return;
  }
  list.innerHTML = '<div class="asset-empty">正在解析…</div>';
  const r = await api('/api/locres', { path: p0, limit: 600 }).catch(() => null);
  if (!r || !r.ok) {
    if (cnt) cnt.textContent = '—';
    list.innerHTML = '<div class="asset-empty">' + esc((r && r.error) || '解析失败') + '</div>';
    return;
  }
  if (cnt) cnt.textContent = r.count + ' 条' + (r.truncated ? ' · 前 ' + (r.entries || []).length : '');
  const rows = (r.entries || []).map((e) => (
    '<div class="locres-row">' +
    '<span class="lk" title="' + esc(e.key) + '">' + esc(e.key) + '</span>' +
    '<span class="ls">' + esc(e.source || '') + '</span>' +
    '<span class="lt">' + esc(e.target || '') + '</span>' +
    '</div>'
  )).join('');
  list.innerHTML = rows || '<div class="asset-empty">该文件没有条目。</div>';
}

function verNum(v) {
  const m = String(v || '').match(/\d+(?:\.\d+)*/);
  return (m ? m[0] : '').split('.').map((n) => parseInt(n, 10) || 0);
}

function verGt(a, b) {
  const A = verNum(a);
  const B = verNum(b);
  const n = Math.max(A.length, B.length);
  for (let i = 0; i < n; i++) {
    const x = A[i] || 0;
    const y = B[i] || 0;
    if (x !== y) return x > y;
  }
  return false;
}

/* ROUND 20: SELF UPDATE —— 徽标即更新按钮 */
function markUpdate(tag) {
  const btn = $('#newVer');
  if (!btn) return;
  const cur = (CATALOG.app && CATALOG.app.version) || '1.0.0';
  const ok = /^\s*v?\d+(?:\.\d+){1,3}\s*$/i.test(String(tag || ''));
  const yes = ok && verGt(tag, cur);
  btn.hidden = !yes;
  if (yes) {
    btn.textContent = '更新版本';
    btn.dataset.tag = tag;
    btn.title = '下载 ' + tag + ' 并替换当前版本（V' + cur + '）';
    localStorage.setItem('ti-upd-tag', tag);
  } else {
    btn.textContent = '更新版本';
    delete btn.dataset.tag;
    btn.removeAttribute('title');
    localStorage.removeItem('ti-upd-tag');
  }
}

async function runUpdate() {
  const btn = $('#newVer');
  const st = $('#ghStatus');
  let repo = ($('#s_ghrepo') && $('#s_ghrepo').value.trim()) || '';
  if (!repo) {
    /* ROUND 20D: REPO FALLBACK —— 设置面板没打开时也能拿到仓库地址 */
    const cfg = await api('/api/settings').catch(() => null);
    repo = (cfg && cfg.settings && cfg.settings.github_repo) || '';
  }
  if (!repo) {
    if (st) st.textContent = '先在「设置 → 版本」里填写 GitHub 仓库地址，再点更新';
    if (btn) btn.title = '缺少仓库地址';
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = '正在下载…'; }
  if (st) st.textContent = '正在下载新版本…';
  let r = null;
  try { r = await api('/api/update', { repo }); } catch (e) { r = { ok: false, error: e.message }; }
  if (!r || !r.ok) {
    if (btn) { btn.disabled = false; btn.textContent = '更新版本'; }
    const msg = (r && r.error) || '未知错误';
    if (r && r.tag && r.current) {
      /* 服务端比对后判定已经是最新：收掉徽标，不算故障，更不该弹下载页 */
      markUpdate('');
      if (st) st.textContent = msg;
      return;
    }
    /* ROUND 20E: OPEN RELEASE PAGE —— 自带下载走不通就把发布页打开，让人手动拿 */
    const page = (r && r.page) ||
      (repo.replace(/\.git$/i, '').replace(/\/+$/, '') + '/releases/latest');
    const opened = await api('/api/link', { url: page }).catch(() => null);
    if (opened && opened.ok) {
      if (st) st.textContent = '自动更新失败（' + msg + '），已打开下载页：' + page;
      if (btn) btn.title = '自动更新失败，已打开下载页';
    } else {
      if (st) st.textContent = '更新失败：' + msg;
      if (btn) btn.title = '更新失败：' + msg;
    }
    return;
  }
  if (btn) btn.textContent = '正在重启…';
  if (st) st.textContent = '已下载 ' + Math.round((r.size || 0) / 1024 / 1024) + ' MB，正在替换并重启…';
}

async function autoCheckUpdate() {
  const cached = localStorage.getItem('ti-upd-tag');
  if (cached) markUpdate(cached);
  const st = await api('/api/settings').catch(() => null);
  const repo = (st && st.settings && st.settings.github_repo) || '';
  if (!repo) return;
  const last = parseInt(localStorage.getItem('ti-upd-check') || '0', 10) || 0;
  if (Date.now() - last < 6 * 3600 * 1000) return;
  const r = await api('/api/ghcheck', { repo }).catch(() => null);
  if (!r || !r.ok) return;
  localStorage.setItem('ti-upd-check', String(Date.now()));
  markUpdate(r.tag || '');
}

function bindVersionExtra() {
  const nv = $('#newVer');
  if (nv) nv.onclick = () => {
    if (nv.dataset && nv.dataset.tag) runUpdate();
    else openMenu('version');
  };
  setTimeout(autoCheckUpdate, 3500);
  const save = $('#s_ghsave');
  if (save) save.onclick = async () => {
    const v = ($('#s_ghrepo') && $('#s_ghrepo').value.trim()) || '';
    const tk = ($('#s_ghtoken') && $('#s_ghtoken').value.trim()) || '';
    const r = await api('/api/settings', { github_repo: v, github_token: tk }).catch(() => null);
    const st = $('#ghStatus');
    if (st) st.textContent = (r && r.ok) ? ('仓库已保存：' + (v || '（已清空）') + (tk ? '（含 token）' : '')) : '保存失败';
  };
  const chk = $('#s_ghcheck');
  if (chk) chk.onclick = async () => {
    const v = ($('#s_ghrepo') && $('#s_ghrepo').value.trim()) || '';
    const st = $('#ghStatus');
    if (!v) { if (st) st.textContent = '先填写 GitHub 仓库地址'; return; }
    if (st) st.textContent = '正在检查…';
    const tk2 = ($('#s_ghtoken') && $('#s_ghtoken').value.trim()) || '';
    if (tk2) await api('/api/settings', { github_token: tk2 }).catch(() => null);
    const r = await api('/api/ghcheck', { repo: v }).catch(() => null);
    if (!r) { if (st) st.textContent = '检查失败：网络不可用'; return; }
    if (!r.ok) { if (st) st.textContent = '检查失败：' + (r.error || ''); return; }
    const curVer = (CATALOG.app && CATALOG.app.version) || '1.0.0';
    const cur = 'V' + curVer;
    const latest = r.tag || '';
    markUpdate(latest);
    const hasNew = /^\s*v?\d+(?:\.\d+){1,3}\s*$/i.test(latest) && verGt(latest, curVer);
    if (st) st.textContent = '最新 Release：' + latest + (r.name ? '（' + r.name + '）' : '') +
      (hasNew ? ' \u00b7 \u6709\u66f4\u65b0' : ' \u00b7 \u5df2\u662f\u6700\u65b0');
  };
}

function bindLocresExtra() {
  const pick = document.getElementById('locresPick');
  const view = document.getElementById('locresView');
  const inp = document.getElementById('locresPath');
  if (inp && !inp.dataset.bound) {
    inp.dataset.bound = '1';
    inp.addEventListener('change', () => {
      const v = inp.value.trim();
      try { localStorage.setItem('locres:last', v); } catch (e) {}
      loadLocres(v);
    });
  }
  if (pick && !pick.dataset.bound) {
    pick.dataset.bound = '1';
    pick.addEventListener('click', async () => {
      const r = await api('/api/pickfile', { filter: 'locres 文件 (*.locres)|*.locres|所有文件 (*.*)|*.*' }).catch(() => null);
      if (r && r.path) {
        if (inp) inp.value = r.path;
        try { localStorage.setItem('locres:last', r.path); } catch (e) {}
        loadLocres(r.path);
      }
    });
  }
  if (view && !view.dataset.bound) {
    view.dataset.bound = '1';
    view.addEventListener('click', () => loadLocres(inp ? inp.value.trim() : ''));
  }
}

function bindAssetExtra() {
  const btn = document.getElementById('assetRefresh');
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => {
      const g = document.getElementById('game');
      loadAssets(g ? g.value.trim() : '');
    });
  }
}

function bindSettingsExtra() {
  const mapInp = $('#s_mapdir');
  const mapPick = $('#s_mapdir_pick');
  if (mapInp) {
    mapInp.addEventListener('change', () => api('/api/settings', { mapping_dir: mapInp.value.trim() }).catch(() => {}));
  }
  if (mapPick) {
    mapPick.onclick = async () => {
      const r = await api('/api/pick', {}).catch(() => null);
      if (r && r.path) {
        if (mapInp) mapInp.value = r.path;
        await api('/api/settings', { mapping_dir: r.path }).catch(() => {});
      }
    };
  }
  const od = $('#s_outdir');
  if (od) {
    od.addEventListener('change', async () => {
      const val = od.value.trim();
      try {
        await api('/api/settings', 'POST', { outdir: val });
        setStatus(val ? ('默认输出目录已保存：' + val) : '默认输出目录已恢复', 'ok');
      } catch (e) { setStatus('保存失败', 'bad'); }
    });
  }
  const c = $('#s_clear');
  if (c) c.onclick = clearCache;
}

let booted = false;


try {
  if (localStorage.getItem('ti-noanim') === '1') document.body.classList.add('no-anim');
} catch (e) {}


function applyNoAnim(on) {
  document.body.classList.toggle('no-anim', !!on);
  try { localStorage.setItem('ti-noanim', on ? '1' : '0'); } catch (e) {}
}

/* ---------- 设置 · 性能 ---------- */
let PERF = { noAnim: false, gpu: true };

function swSet(btn, on) {
  if (!btn) return;
  btn.setAttribute('aria-checked', on ? 'true' : 'false');
}

function swOn(btn) {
  return !!btn && btn.getAttribute('aria-checked') === 'true';
}

function renderPerf() {
  swSet($('#perf_noanim'), !!PERF.noAnim);
  swSet($('#perf_gpu'), PERF.gpu !== false);
}

async function loadPerf() {
  try {
    const d = await api('/api/settings');
    const saved = (d && d.saved) || {};
    const perf = saved.perf || {};
    PERF = { noAnim: !!perf.noAnim, gpu: perf.gpu !== false };
    applyNoAnim(PERF.noAnim);
  } catch (e) {}
  renderPerf();
}

async function savePerf(patch) {
  PERF = Object.assign({}, PERF, patch);
  applyNoAnim(PERF.noAnim);
  renderPerf();
  try {
    await api('/api/settings', 'POST', { perf: { noAnim: !!PERF.noAnim, gpu: PERF.gpu !== false } });
  } catch (e) {}
}

function bindPerf() {
  const a = $('#perf_noanim');
  if (a) a.onclick = () => savePerf({ noAnim: !swOn(a) });
  const g = $('#perf_gpu');
  if (g) g.onclick = () => savePerf({ gpu: !swOn(g) });
}

function playEntrance() {
  const body = document.body;
  if (!body || window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const items = [...document.querySelectorAll('#nav .nav-item')].filter((n) => n.dataset.mod !== 'home');
  items.forEach((n, i) => n.style.setProperty('--i', String(i)));
  body.classList.remove('entrance');
  void body.offsetWidth;
  body.classList.add('entrance');
  clearTimeout(playEntrance._t);
  playEntrance._t = setTimeout(() => body.classList.remove('entrance'), 1500);
}

function selectModule(id) {
  const mod = (CATALOG.modules || []).find((m) => m.id === id);
  if (!mod) return;
  // 切走之前，把当前工具的目录存进它自己那份（互不影响）
  const gIn = $('#game');
  if (gIn && curMod && curMod !== id) saveDir(curMod, 'game', gIn.value.trim());
  curMod = id;            // 先定当前模块，再渲染，否则高亮会落后一拍
  renderNav();
  // 先快速模糊掉右边，再渲染新内容，最后整块 + 子项自上而下弹入
  pageOut(() => { applyModuleView(mod); pageIn(); });
}

function applyModuleView(mod) {
  if (mod.kind === 'home' || mod.id === 'home') {
    $('#subnav').innerHTML = '';
    applyDir(mod);
    applyModuleChrome(mod);
    showHome(true);
    return;
  }
  showHome(false);
  applyDir(mod);
  applyModuleChrome(mod);
  const m = moduleById(mod.id);
  if (m && m.kind === 'tool') {
    $('#subnav').innerHTML = '';
    if ($('#run')) $('#run').style.display = 'none';
    if ($('#stop')) $('#stop').style.display = 'none';
    renderToolPanel(m);
    setStatus('就绪');
    return;
  }
  if ($('#run')) $('#run').style.display = '';
  if ($('#stop')) $('#stop').style.display = '';
  const tasks = (m && m.tasks) || [];
  curTask = tasks.length ? tasks[0].id : null;
  renderSubnav();
  renderPanel();
  fillDirParams(m);
  setStatus('就绪');
}

function renderSubnav() {
  const m = moduleById(curMod);
  const tasks = (m && m.tasks) || [];
  const box = $('#subnav');
  box.innerHTML = tasks.map((t) => {
    const cls = (t.id === curTask ? 'on ' : '') + (t.soon ? 'soon' : '');
    const tt = t.soon ? ' title="开发中"' : '';
    return '<button data-t="' + esc(t.id) + '"' + (cls ? ' class="' + cls.trim() + '"' : '') + tt + '>' + esc(t.nav || t.title) + '</button>';
  }).join('');
  box.querySelectorAll('button').forEach((b) => {
    b.onclick = () => {
      // 同一个子功能不重复播弹出动画（m18098）
      if (b.dataset.t === curTask) return;
      const mm = document.querySelector('.main');
      if (mm) { mm.classList.remove('page-in'); clearTimeout(pageIn._t); }
      curTask = b.dataset.t; renderSubnav(); renderPanel(); setStatus('就绪'); tabPop();
    };
  });
}

function tabPop() {
  if (document.body.classList.contains('no-anim')) return;
  /* 只弹功能框（.panel），不动整列：切模块才整页动（m18005/m18006） */
  const p = document.querySelector('.main .panel');
  if (!p) return;
  p.classList.remove('tab-pop');
  void p.offsetWidth;
  p.classList.add('tab-pop');
  // 保留 tab-pop：动画填充 both，结束后停在 translateZ(0) 合成层，
  // 与下一次切换前的基线完全一致，避免摘类瞬间重栅格化导致文字/阴影偏移 1-2px（m17849）
  clearTimeout(tabPop._t);
}

function taskDef() {
  const m = moduleById(curMod);
  return ((m && m.tasks) || []).find((t) => t.id === curTask) || null;
}

/* ---------------- 工具面板：uasset / fmodel / dump ----------------
   每个工具面板顶上是「工具设置路径」：可检测、可手选、缺失显示「未安装」 */
const TP_FIELDS = {
  uasset: [
    { k: 'uasset', label: 'UAssetGUI 路径', pick: 'exe', ph: '例如 F:\\模型\\UAssetGUI.exe' },
    { k: 'uasset_mapping', label: 'Mapping（.usmap）', pick: 'usmap', ph: '选填；UAssetGUI 打开映射时要用' },
  ],
  fmodel: [
    { k: 'fmodel', label: 'FModel 路径', pick: 'exe', ph: '例如 F:\\模型\\UEHanHua\\FModel\\FModel.exe' },
    { k: 'fmodel_mapping', label: 'Mapping（.usmap）', pick: 'usmap', ph: '手动指定 FModel 用的 .usmap' },
  ],
  dump: [
    { k: 'dumper_dll', label: 'Dumper-7.dll 路径', pick: 'dll', ph: '例如 F:\\模型\\Dumper-7.dll' },
    { k: 'dumper', label: 'jmap_dumper 路径（备用）', pick: 'exe', ph: '例如 …\\jmap_dumper.exe' },
    { k: 'dump_out', label: '输出目录', pick: 'dir', ph: '留空 = 工具自己的默认位置' },
  ],
};
const HAS_LIST = ['exe', 'dll', 'usmap', 'dir'];
const TP_FILTER = {
  exe: '可执行文件 (*.exe)|*.exe|所有文件 (*.*)|*.*',
  dll: '动态库 (*.dll)|*.dll|所有文件 (*.*)|*.*',
  usmap: '映射文件 (*.usmap)|*.usmap|所有文件 (*.*)|*.*',
};

async function tpSave(key, val) {
  try { await api('/api/settings', { [key]: val }); } catch (e) {}
}

async function renderToolPanel(m) {
  const fields = TP_FIELDS[m.id] || [];
  $('#title').textContent = '工具路径';
  $('#desc').textContent = m.desc || '';
  const box = $('#params');
  box.innerHTML = '';
  const rb = $('#run');
  if (rb) rb.disabled = true;
  const sb0 = $('#stop');
  if (sb0) sb0.disabled = true;

  const stResp = (await api('/api/toolstate', {}).catch(() => null)) || {};
  const st = stResp.state || {};
  const wrap = document.createElement('div');
  wrap.className = 'tp-wrap';
  box.appendChild(wrap);

  function rowFor(f) {
    const cur = (st[f.k] && st[f.k].path) || '';
    const exists = !!(st[f.k] && st[f.k].exists);
    const row = document.createElement('label');
    row.className = 'tp-row';
    row.innerHTML =
      '<span class="tp-label">' + esc(f.label) + '</span>' +
      '<input class="tp-in" id="tp_' + f.k + '" spellcheck="false" title="可直接 Ctrl+V 粘贴路径" placeholder="' + esc(f.ph || '') + '" value="' + esc(cur) + '">' +
      '<span class="tp-badge ' + (exists ? 'ok' : 'bad') + '" id="tp_badge_' + f.k + '">' + (f.k === 'dump_out' ? (cur ? '已设置' : '默认') : (exists ? '已安装' : '未安装')) + '</span>' +
      '<button class="btn ghost tp-pick" type="button">选择</button>';
    wrap.appendChild(row);
    const inp = row.querySelector('.tp-in');
    const bad = row.querySelector('.tp-badge');
    inp.onchange = async () => {
      await tpSave(f.k, inp.value.trim());
      const r = await api('/api/toolstate', {}).catch(() => null);
      const s2 = (r && r.state) || {};
      if (s2[f.k]) {
        const ok = !!s2[f.k].exists;
        bad.className = 'tp-badge ' + (ok ? 'ok' : 'bad');
        bad.textContent = f.k === 'dump_out' ? (inp.value.trim() ? '已设置' : '默认') : (ok ? '已安装' : '未安装');
      }
    };
    const mkHist = () => {
      const dls = 'dl_' + f.k;
      let dl = document.getElementById(dls);
      if (!dl) { dl = document.createElement('datalist'); dl.id = dls; row.appendChild(dl); }
      const cur2 = (inp.value || '').trim();
      const vals = toolHistRead(f.k).slice();
      if (cur2 && vals.indexOf(cur2) < 0) vals.unshift(cur2);
      dl.innerHTML = vals.map((v) => '<option value="' + esc(v) + '"></option>').join('');
      if (HAS_LIST.indexOf(f.pick) >= 0) inp.setAttribute('list', dls);
    };
    mkHist();
    attachHist(inp, () => { const a = toolHistRead(f.k).slice(); const v = (inp.value || '').trim(); if (v && a.indexOf(v) < 0) a.unshift(v); return a; });
    inp.addEventListener('change', () => { pushToolHist(f.k, inp.value); mkHist(); });
    row.querySelector('.tp-pick').onclick = async () => {
      const r = f.pick === 'dir'
        ? await api('/api/pick', { dry: false }).catch(() => null)
        : await api('/api/pickfile', { filter: TP_FILTER[f.pick] }).catch(() => null);
      const got = r && r.path;
      if (!got) return;
      inp.value = got;
      pushToolHist(f.k, got);
      mkHist();
      await tpSave(f.k, got);
      bad.className = 'tp-badge ok';
      bad.textContent = f.k === 'dump_out' ? '已设置' : '已安装';
    };
    return row;
  }

  fields.forEach(rowFor);

  // ---- 快速切换 .usmap（仅 uasset / fmodel；dump 不做 mapping 选择，用户 m17340）----
  if (m.id === 'uasset' || m.id === 'fmodel') {
    const mapKey = m.id === 'uasset' ? 'uasset_mapping' : (m.id === 'fmodel' ? 'fmodel_mapping' : 'dump_mapping');
    const dirKey = m.id === 'uasset' ? 'uasset_mapping_dir' : (m.id === 'fmodel' ? 'fmodel_mapping_dir' : 'mapping_dir');
    const cfg = (await api('/api/settings').catch(() => null)) || {};
    const curDir = (cfg && cfg.settings && (cfg.settings[dirKey] || cfg.settings.mapping_dir)) || '';
    const row = document.createElement('div');
    row.className = 'tp-row';
    row.innerHTML = '<span class="tp-label">快速换 mapping</span>' +
      '<select class="tp-in" id="tp_mapsel" style="flex:1 1 auto;min-width:0;max-width:100%"><option value="">（未选 .usmap）</option></select>';
    wrap.appendChild(row);

    const dirInp = row.querySelector('#tp_mapdir');
    const pickBtn = row.querySelector('#tp_mapdir_pick');
    const sel = row.querySelector('#tp_mapsel');

    async function loadMaps(dir) {
      if (!dir) { sel.innerHTML = '<option value="">（未选 .usmap）</option>'; return; }
      const r = await api('/api/listdir', { dir: dir, ext: 'usmap' }).catch(() => null);
      const files = (r && r.files) || [];
      const curMap = (st[mapKey] && st[mapKey].path) || '';
      sel.innerHTML = '<option value="">（未选 .usmap）</option>' +
        files.map((f) => {
          const full = dir.replace(/[\\/]+$/, '') + '\\' + f.replace(/\//g, '\\');
          return '<option value="' + esc(full) + '">' + esc(f) + '</option>';
        }).join('');
      if (curMap) {
        const hit = Array.from(sel.options).find((o) => o.value.toLowerCase() === curMap.toLowerCase());
        if (hit) sel.value = hit.value;
      }
      if (r && r.ok === false) setStatus(r.error || '目录读取失败');
    }
    loadMaps(curDir);

    if (dirInp) dirInp.onchange = async () => {
      const d = dirInp.value.trim();
      await api('/api/settings', { [dirKey]: d, mapping_dir: d }).catch(() => {});
      loadMaps(d);
    };
    if (pickBtn) pickBtn.onclick = async () => {
      const r = await api('/api/pick', {}).catch(() => null);
      if (!r || !r.path) return;
      if (dirInp) dirInp.value = r.path;
      await api('/api/settings', { [dirKey]: r.path, mapping_dir: r.path }).catch(() => {});
      loadMaps(r.path);
    };
    sel.onchange = async () => {
      const v = sel.value;
      if (!v) return;
      await tpSave(mapKey, v);
      setStatus('已选映射：' + v.split('\\').pop());
    };
  }

  // ---- DUMP：注入前等待秒数 ----
  if (m.id === 'dump') {
    const cfg2 = (await api('/api/settings').catch(() => null)) || {};
    const w = (cfg2 && cfg2.settings && cfg2.settings.dump_wait) || '';
    const row = document.createElement('div');
    row.className = 'tp-row';
    row.innerHTML = '<span class="tp-label">注入前等待（秒）</span>' +
      '<input class="tp-in" id="tp_wait" type="number" min="0" max="60" step="1" placeholder="0 = 选完立刻注入" value="' + esc(w) + '">';
    wrap.appendChild(row);
    row.querySelector('#tp_wait').onchange = () => {
      const v = String(Math.max(0, Math.min(60, parseInt(row.querySelector('#tp_wait').value || '0', 10) || 0)));
      row.querySelector('#tp_wait').value = v;
      api('/api/settings', { dump_wait: v }).catch(() => {});
    };
  }


  const acts = document.createElement('div');
  acts.className = 'tp-acts';
  wrap.appendChild(acts);

  if (m.id === 'dump') {
    // DUMP：进程列表 + 注入
    const row = document.createElement('div');
    row.className = 'tp-row';
    row.innerHTML = '<span class="tp-label">目标进程</span>' +
      '<select class="tp-in" id="tp_pid"><option value="">点「刷新」列出进程</option></select>' +
      '<button class="btn ghost" type="button" id="tp_refresh">刷新</button>';
    wrap.insertBefore(row, acts);
    row.querySelector('#tp_refresh').onclick = async () => {
      const r = await api('/api/procs', {}).catch(() => null);
      const sel = row.querySelector('#tp_pid');
      if (!r || !r.procs) return;
      const list = r.procs.filter((x) => !/^(conhost|dllhost|svchost|csrss|wininit|services|lsass|smss|fontdrvhost|WmiPrvSE|tasklist)\.exe$/i.test(x.name));
      sel.innerHTML = '<option value="">选一个进程（' + list.length + ' 个）</option>' +
        list.map((x) => '<option value="' + x.pid + '">' + esc(x.name) + '  ·  ' + x.pid + '</option>').join('');
      setStatus('已列出 ' + list.length + ' 个进程');
    };

    const inj = document.createElement('button');
    inj.className = 'btn primary';
    inj.type = 'button';
    inj.textContent = '注入 DLL';
    acts.appendChild(inj);
    inj.onclick = async () => {
      const pid = Number(($('#tp_pid') || {}).value || 0);
      const dll = ($('#tp_dumper_dll') || {}).value || '';
      if (!pid) { setStatus('先选目标进程', 'bad'); return; }
      if (!dll) { setStatus('先填 Dumper-7.dll 路径', 'bad'); return; }
      setStatus('注入中…');
      const r = await api('/api/inject', { pid, dll }).catch((e) => ({ ok: false, error: String(e) }));
      appendLog(['$ inject ' + dll + ' -> pid ' + pid, JSON.stringify(r)]);
      setStatus(r && r.ok ? '注入完成' : ('注入失败：' + ((r && r.error) || '未知')), r && r.ok ? 'ok' : 'bad');
    };
  }

  const run = document.createElement('button');
  run.className = 'btn primary';
  run.type = 'button';
  run.textContent = m.id === 'dump' ? '启动 Dumper' : '启动';
  acts.appendChild(run);
  run.onclick = async () => {
    const key = (fields[0] || {}).k;
    let exe = ($('#tp_' + key) || {}).value || '';
    if (m.id === 'dump') exe = ($('#tp_dumper') || {}).value || '';
    if (!exe) { setStatus('先设置程序路径', 'bad'); return; }
    const r = await api('/api/launch', { exe }).catch((e) => ({ ok: false, error: String(e) }));
    if (r && r.ok) { setStatus('已启动'); appendLog(['$ ' + exe]); }
    else setStatus('启动失败：' + ((r && r.error) || '未知'), 'bad');
  };

  const open = document.createElement('button');
  open.className = 'btn ghost';
  open.type = 'button';
  open.textContent = '打开程序目录';
  acts.appendChild(open);
  open.onclick = async () => {
    const key = m.id === 'dump' ? 'dumper' : (fields[0] || {}).k;
    const exe = ($('#tp_' + key) || {}).value || '';
    if (!exe) { setStatus('先设置程序路径', 'bad'); return; }
    await api('/api/launch', { exe: 'explorer.exe', params: {} }).catch(() => null);
    const dir = exe.replace(/[\\\/][^\\\/]+$/, '');
    await fetch('/api/launch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ exe: dir }) }).catch(() => null);
  };
}

function renderPanel() {
  const t = taskDef();
  if (!t) {
    $('#title').textContent = '—';
    $('#desc').textContent = '这个模块还在路上，先用 01 吧。';
    $('#params').innerHTML = '';
    return;
  }
  $('#title').textContent = t.title;
  $('#desc').textContent = t.desc || '';
  { const rb2 = $('#run'); if (rb2) rb2.disabled = true; const sb2 = $('#stop'); if (sb2) sb2.disabled = true; }
  const box = $('#params');
  box.innerHTML = '';
  if (t.soon) {
    const note = document.createElement('div');
    note.className = 'p wide';
    note.innerHTML = '<label>状态</label><div class="soon-note">开发中 · 先走 UE4 通道</div>';
    box.appendChild(note);
    const rb = $('#run');
    if (rb) rb.disabled = true;
    setStatus('开发中');
    return;
  }
  { const rb = $('#run'); if (rb) rb.disabled = false; }
  const modDef = moduleById(curMod) || {};
  (t.params || []).forEach((p) => {
    if (p.id === 'dir' && modDef.dir) return;   // 顶部已有「资产目录」，面板不再重复
    if (p.type === 'check') {
      const l = document.createElement('label');
      l.className = 'chk sw-row';
      l.innerHTML = '<span>' + esc(p.label) + '</span>' +
        '<button class="sw" type="button" role="switch" aria-checked="false" id="p_' + p.id + '"><i></i></button>';
      box.appendChild(l);
      const sw = l.querySelector('.sw');
      sw.onclick = () => sw.setAttribute('aria-checked', sw.getAttribute('aria-checked') === 'true' ? 'false' : 'true');
      return;
    }
    const d = document.createElement('div');
    d.className = 'p' + (p.wide ? ' wide' : '');
    d.innerHTML = '<label>' + esc(p.label) + '</label>' +
      '<input id="p_' + p.id + '" spellcheck="false" placeholder="' + esc(p.ph || '') + '">';
    box.appendChild(d);
  });
  (t.params || []).forEach((p) => {
    const el = document.getElementById('p_' + p.id);
    if (el && el.tagName === 'INPUT') attachHistory(curMod, t.id, p.id, el);
  });
  (t.params || []).forEach((p) => {
    if (p.id !== 'out' && p.id !== 'csv') return;
    const el = document.getElementById('p_' + p.id);
    if (el && !el.getAttribute('placeholder')) el.setAttribute('placeholder', '留空 = 默认输出目录');
  });
  if (t.id === 'verify' && state.aeskeys && state.aeskeys[0] && $('#p_key')) {
    $('#p_key').value = state.aeskeys[0].key;
  }
  const pk = $('#p_pak');
  if (pk) {
    pk.addEventListener('change', () => { if (pk.value.trim()) previewPak(pk.value.trim()); });
  }
  const pa = $('#p_aes');
  if (pa) pa.addEventListener('change', () => { if (pk && pk.value.trim()) previewPak(pk.value.trim()); });
}

function collect() {
  const t = taskDef();
  const out = {};
  if (!t) return out;
  const modDef = moduleById(curMod) || {};
  (t.params || []).forEach((p) => {
    const el = $('#p_' + p.id);
    if (!el) {
      if (p.id === 'dir' && modDef.dir) {         // 用顶部那条目录
        const g = $('#game'); const v = g ? g.value.trim() : '';
        if (v) out.dir = v;
      }
      return;
    }
    if (p.type === 'check') out[p.id] = el.getAttribute('aria-checked') === 'true';
    else if (el.value.trim()) out[p.id] = el.value.trim();
  });
  return out;
}

/* ---------------- 简介抽屉（右侧滑出） ---------------- */
function openIntro(id) {
  const m = moduleById(id);
  if (!m) return;
  const tasks = m.tasks || [];
  $('#introTitle').textContent = m.name + '  ' + (m.ver || '');
  $('#introSub').textContent = m.sub || '';
  $('#introBody').innerHTML =
    '<p class="idesc">' + esc(m.desc || m.note || '这个工具还在路上。') + '</p>' +
    (tasks.length ? '<div class="ilist">' + tasks.map((t) => '<span>' + esc(t.nav || t.title) + '</span>').join('') + '</div>' : '') +
    '<div class="istate">' + (m.status === 'ready' ? '可用' : '开发中') + '</div>';
  $('#intro').classList.add('on');
  $('#iscrim').classList.add('on');
}

function closeIntro() {
  $('#intro').classList.remove('on');
  $('#iscrim').classList.remove('on');
}

/* ---------------- 运行 ---------------- */
function setStatus(text, cls) {
  const s = $('#status');
  s.textContent = text;
  s.className = 'status' + (cls ? ' ' + cls : '');
}

function appendLog(lines) {
  const log = $('#log');
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 40;
  let html = '';
  lines.forEach((ln) => {
    let cls = '';
    if (/\[HIT\]|\[OK\]/i.test(ln)) cls = 'hit';
    else if (/成功|命中|match|✔/i.test(ln)) cls = 'ok';
    else if (/失败|error|错误|exception/i.test(ln)) cls = 'err';
    else if (/^\s*\$|node |powershell /i.test(ln)) cls = 'cmd';
    html += '<span class="' + cls + '">' + esc(ln) + '</span>\n';
  });
  log.insertAdjacentHTML('beforeend', html);
  if (atBottom) log.scrollTop = log.scrollHeight;
}

async function poll() {
  if (!jobId) return;
  const r = await api('/api/log?id=' + jobId + '&since=' + since);
  if (r.error) { jobId = null; return; }
  if (r.lines && r.lines.length) {
    since += r.lines.length;
    appendLog(r.lines);
    if (r.lines.some((l) => /\[HIT\]/i.test(l))) refreshState();
  }
  if (r.done) {
    clearInterval(timer); timer = null;
    setStatus(r.rc === 0 ? '完成（exit 0）' : '结束，退出码 ' + r.rc, r.rc === 0 ? 'ok' : 'err');
    $('#run').disabled = false;
    $('#stop').disabled = true;
    jobId = null;
    refreshState();
  }
}

async function previewPak(pakPath) {
  const p = (pakPath || ($('#p_pak') && $('#p_pak').value) || '').trim();
  if (!p) return;
  const aes = ($('#p_aes') && $('#p_aes').value.trim()) || '';
  setStatus('读取 pak 信息…', 'run');
  const r = await api('/api/pakpreview', { pak: p, aes });
  if (!r.ok) {
    $('#log').textContent = '[pak] ' + (r.error || '读取失败');
    setStatus('pak 读取失败', 'err');
    return;
  }
  const rows = (r.list || '').split('\n').filter((x) => x.trim());
  const bad = /^Error/i.test((r.info || '').trim());
  const head = ['$ repak info ' + p, '', '== pak 头信息 ==', r.info || '(空)', '',
                '== 文件清单 · ' + r.count + ' 条 =='];
  const body = rows.slice(0, 400);
  if (rows.length > 400) body.push('', '… 只显示前 400 行；解包后在目录里看全量');
  $('#log').textContent = '';
  appendLog(head.concat(body));
  const lg = $('#log'); if (lg) lg.scrollTop = 0;
  setStatus(bad ? 'repak 打不开这个 pak（版本/密钥）' : ('pak 已读取 · ' + r.count + ' 个文件'), bad ? 'err' : 'ok');
}

async function runTask() {
  if (!curTask) { setStatus('这个模块还没做', 'err'); return; }
  $('#run').disabled = true;
  $('#stop').disabled = false;
  $('#log').textContent = '';
  since = 0;
  setStatus('运行中…', 'run');
  const r = await api('/api/run', { task: curTask, params: collect() });
  if (!r.ok) {
    setStatus('起不来：' + (r.error || '未知错误'), 'err');
    $('#run').disabled = false;
    $('#stop').disabled = true;
    return;
  }
  appendLog(['$ ' + r.cmd]);
  jobId = r.id;
  since = 1;
  timer = setInterval(poll, 700);
}

async function stopTask() {
  if (!jobId) return;
  await api('/api/stop', { id: jobId });
  setStatus('已发送停止', 'err');
}

/* ---------------- 目标 / keys ---------------- */
async function refreshState() {
  state = await api('/api/state');
  $('#game').value = state.target.game || '';
  $('#exe').textContent = state.target.exe || '—';
  $('#pak').textContent = state.target.pak || '—';
  const keys = state.aeskeys || [];
  $('#keycount').textContent = keys.length;
  const _pill = document.getElementById('keyPill');
  if (_pill) _pill.textContent = keys.length ? `AES KEY · ${keys.length}` : 'AES KEY';
  const list = $('#keylist');
  list.innerHTML = keys.map((k, i) =>
    '<div class="krow"><code title="' + esc(k.key) + '">' + esc(k.key) + '</code>' +
    '<span class="kgame">' + esc(k.game || '未标注') + '</span><span>' + esc(k.how || '') + '</span><button data-copy="' + i + '">复制</button></div>'
  ).join('') || '<div class="dim" style="font-size:11.5px">还没有收录，跑一次扫描试试</div>';
  list.querySelectorAll('button[data-copy]').forEach((b) => {
    b.onclick = () => {
      navigator.clipboard.writeText(keys[Number(b.dataset.copy)].key);
      b.textContent = '已复制';
      setTimeout(() => (b.textContent = '复制'), 1200);
    };
  });
}

async function detect() {
  const game = $('#game').value.trim();
  if (!game) { setStatus('先填游戏目录', 'err'); return; }
  setStatus('探测中…', 'run');
  const r = await api('/api/detect', { game });
  if (r.ok) {
    const f = r.found;
    $('#game').value = f.game || game;
    $('#exe').textContent = f.exe || '（没找到 exe）';
    $('#pak').textContent = f.pak || '（没找到 pak）';
    await api('/api/target', f);
    setStatus('探测完成，记得点保存目标', 'ok');
    refreshState();
  } else {
    setStatus('探测失败：' + (r.error || ''), 'err');
  }
}

async function saveTarget() {
  await api('/api/target', { game: $('#game').value.trim() });
  setStatus('目标已保存', 'ok');
  refreshState();
}

/* ---------------- 齿轮菜单：左侧栏目 + 右侧面板 ---------------- */
const MENU_PANES = ['theme', 'settings', 'version', 'about'];

function fillRoot() {
  const el = $('#s_root');
  if (!el) return;
  const root = (VARS && VARS.app) || '';
  el.value = root;
}

function openMenu(pane) {
  fillRoot();
  showPane(pane || 'theme', true);
  $('#menu').classList.add('on');
  api('/api/settings').then((r) => {
    const s = r.settings || {};
    const saved = r.saved || {};
    const stEl = $('#s_tool'); if (stEl) stEl.value = s.tool || '';
    const snEl = $('#s_node'); if (snEl) snEl.value = saved.node || '';
    const od = $('#s_outdir');
    if (od) od.value = saved.outdir || (s.outdir && s.outdir !== s.app ? s.outdir : '') || '';
    const md = $('#s_mapdir');
    if (md) md.value = saved.mapping_dir || '';
    const gt = $('#s_ghtoken');
    if (gt) gt.value = saved.github_token || '';
    const gh = $('#s_ghrepo');
    if (gh) gh.value = saved.github_repo || '';
    const vb = $('#verBig');
    if (vb) vb.textContent = 'V' + ((CATALOG.app && CATALOG.app.version) || '1.0.0');
    try { renderCacheInfo(); } catch (e) {}
  }).catch(() => {});
}

function closeMenu() {
  const m = $('#menu');
  if (!m.classList.contains('on') || m.classList.contains('closing')) return;
  m.classList.add('closing');
  setTimeout(() => { m.classList.remove('closing'); m.classList.remove('on'); curPane = null; }, 180);
}

const PANE_TITLE = { theme: '个性化', settings: '设置', version: '版本', about: '关于' };
let curPane = null;

function showPane(name, force) {
  const same = (name === curPane);
  document.querySelectorAll('#menuNav button').forEach((b) => {
    b.classList.toggle('on', b.dataset.pane === name);
  });
  const t = document.getElementById('menuTitle');
  if (t) t.textContent = PANE_TITLE[name] || '菜单';
  const noAnim = document.body.classList.contains('no-anim');
  MENU_PANES.forEach((p) => {
    const el = document.getElementById('pane_' + p);
    if (!el) return;
    const show = p === name;
    el.style.display = show ? '' : 'none';
    if (show && !noAnim && (!same || force)) {
      // 菜单内部栏目切换动画（m18186）
      el.classList.remove('pane-in');
      void el.offsetWidth;
      el.classList.add('pane-in');
    }
  });
  curPane = name;
}

async function saveSettings() {
  const r = await api('/api/settings', {});
  setStatus(r.ok ? '设置已保存' : '保存失败', r.ok ? 'ok' : 'err');
}

/* ---------------- 绑定 ---------------- */
function bind() {
  $('#run').onclick = runTask;
  $('#stop').onclick = stopTask;
  
  $('#browse').onclick = async () => {
  const btn = $('#browse');
  btn.disabled = true; setStatus('正在打开目录选择…');
  try {
    const r = await api('/api/pick', {});
    if (r && r.path) {
      $('#game').value = r.path;
      saveDir(curMod, 'game', r.path);
      fillDirParams(moduleById(curMod));
      await detect();
      setStatus('已选择目录', 'ok');
    }
    else setStatus('已取消', '');
  } catch (e) { setStatus('打开失败: ' + e.message, 'err'); }
  btn.disabled = false;
};
  const gameInput = $('#game');
  if (gameInput) gameInput.addEventListener('change', async () => {
    const v = gameInput.value.trim();
    saveDir(curMod, 'game', v);
    if (/\.exe$/i.test(v)) { await api('/api/target', { exe: v }); await refreshState(); }
  });
  $('#clear').onclick = () => { $('#log').textContent = ''; };
  $('#openkey').onclick = () => api('/api/open', { what: 'key' });
  $('#gear').onclick = () => openMenu('theme');
  $('#mclose').onclick = closeMenu;
  const sroot = $('#s_root');
  if (sroot) sroot.value = '';
  $('#s_open').onclick = () => api('/api/open', { what: 'app' });
  document.querySelectorAll('#menuNav button').forEach((b) => {
    b.onclick = () => showPane(b.dataset.pane);
  });
  $('#menu').addEventListener('click', (e) => { if (e.target.id === 'menu') closeMenu(); });
  $('#iclose').onclick = closeIntro;
  $('#iscrim').onclick = closeIntro;
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeMenu(); closeIntro(); } });

  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('drop', async (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (!f || !f.path) return;
    const p = f.path;
    if (/\.pak$/i.test(p)) { await api('/api/target', { pak: p }); setStatus('已填入 pak', 'ok'); }
    else if (/\.exe$/i.test(p)) { await api('/api/target', { exe: p }); setStatus('已填入 exe', 'ok'); }
    else { $('#game').value = p; setStatus('已填入目录，点自动探测', 'ok'); }
    refreshState();
  });
}

function hideSplash() {
  const sp = document.getElementById('splash');
  if (!sp || sp.dataset.done) return;
  sp.dataset.done = '1';
  sp.classList.add('hide');
  // 闪屏退场与主界面进场同时开始（交叉过渡），闪屏只负责淡出+模糊
  booted = true;
  setTimeout(playEntrance, 20);
  setTimeout(() => sp.remove(), 400);
}

try {
  const _lt = localStorage.getItem('ti-theme');
  if (_lt) document.documentElement.setAttribute('data-theme', _lt === 'dark' || _lt === 'pink' ? _lt : 'light');
} catch (e) {}

function applyTheme(t) {
  const name = (t === 'dark' || t === 'pink') ? t : 'light';
  document.documentElement.setAttribute('data-theme', name);
  try { localStorage.setItem('ti-theme', name); } catch (e) {}
  document.querySelectorAll('.theme-opt').forEach((b) => {
    b.classList.toggle('on', b.dataset.theme === name);
  });
  return name;
}

async function setTheme(t) {
  applyTheme(t);
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme: t }),
    });
  } catch (e) { /* 离线也要能切 */ }
}

function paintLang(l) {
  const name = l === 'en' ? 'en' : 'zh';
  document.querySelectorAll('.theme-opt').forEach((b) => {
    if (b.dataset.lang === 'zh' || b.dataset.lang === 'en') {
      b.classList.toggle('on', b.dataset.lang === name);
    }
  });
  try { localStorage.setItem('ti-lang', name); } catch (e) {}
  if (window.I18N) window.I18N.apply(name);
  return name;
}

async function setLang(l) {
  const name = paintLang(l);
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang: name }),
    });
  } catch (e) { /* 离线也要能切 */ }
}

function bindResize() {
  const win = (action, edge) => api('/api/win', { action, edge });
  document.querySelectorAll('.rz').forEach((el) => {
    el.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      let ticking = false;
      win('resize_begin', el.dataset.edge);
      const move = () => {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(() => { win('resize_tick', el.dataset.edge); ticking = false; });
      };
      const up = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
        win('resize_end', el.dataset.edge);
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    });
  });
}

function bindWindow() {
  const win = (action) => api('/api/win', { action });

  const wmin = document.getElementById('wmin');
  const wmax = document.getElementById('wmax');
  const wclose = document.getElementById('wclose');
  if (wmin) wmin.onclick = () => win('minimize');
  if (wmax) wmax.onclick = () => win('toggle_max');
  if (wclose) wclose.onclick = () => win('close');

  const dz = document.getElementById('dragzone');
  if (!dz) return;
  let dragging = false;
  let ticking = false;
  dz.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    win('drag_begin');
    e.preventDefault();
  });
  window.addEventListener('mousemove', () => {
    if (!dragging || ticking) return;
    ticking = true;
    requestAnimationFrame(() => { win('drag_tick'); ticking = false; });
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    win('drag_end');
  });
  dz.addEventListener('dblclick', () => win('toggle_max'));
}

async function init() {
  const _t0 = performance.now();
  const r = await api('/api/catalog');
  CATALOG = r.catalog || { modules: [] };
  VARS = r.vars || {};
  const ready = CATALOG.modules[0];
  curMod = ready ? ready.id : null;
  bind();
  if ($('#logRefresh')) $('#logRefresh').onclick = loadChangelog;
  bindKeyDrawer();
  bindHomeLog();
  bindWindow();
  bindPerf();
  loadPerf();
  bindSettingsExtra();
bindVersionExtra();
bindLocresExtra();
  bindAssetExtra();
  // 调试钩子：?menu=theme|settings|about 直接打开菜单（截图/自测用）
  (function () {
    const q = new URLSearchParams(location.search);
    const m = q.get('menu');
    if (m) setTimeout(() => openMenu(m), 40);
  })();
  bindResize();
  // 自测钩子：?clickself=wmin 自动点一次（用于验证 JS 接线）
  if (new URLSearchParams(location.search).get('dbg') === 'log') {
    setTimeout(() => {
      const b = document.getElementById('homeLogBox');
      const cs = getComputedStyle(b);
      const r = b.getBoundingClientRect();
      document.title = `style=[${b.getAttribute('style')}] cls=${b.className} pos=${cs.position} rect=${Math.round(r.left)},${Math.round(r.width)}`;
    }, 1500);
  }
  const _lo = new URLSearchParams(location.search).get('logopen');
  if (_lo) setTimeout(() => { const b = document.getElementById('homeLogBox'); if (b) setLogCollapsed(b, _lo === '0'); }, 900);
  const _cs = new URLSearchParams(location.search).get('clickself');
  if (_cs) _cs.split(',').forEach((id, i) => setTimeout(() => {
    const el = document.getElementById(id.trim()); if (el) el.click();
  }, 1200 + i * 700));
  await refreshState();
  selectModule(curMod);
  // 深链接：?mod=pack 直接打开某个工具
  if (new URLSearchParams(location.search).get('keys') === 'open') {
    setTimeout(() => {
      const ks = document.querySelector('.keys');
      if (ks) ks.classList.remove('collapsed');
    }, 400);   // 等 selectModule 渲染完再展开
  }
  const _hv = new URLSearchParams(location.search).get('hover');
  if (_hv !== null && _hv !== '') {
    const items = document.querySelectorAll('#nav .nav-item');
    const it = items[Number(_hv) || 0];
    if (it) it.classList.add('force-hover');
  }
  const _mp = new URLSearchParams(location.search).get('menu');
  if (_mp) setTimeout(() => openMenu(_mp), 700);
  { const _nh = new URLSearchParams(location.search).get('navhover');
    if (_nh) setTimeout(() => {
      const it = document.querySelector('.nav-item[data-mod="' + _nh + '"]');
      if (it) it.classList.add('force-hover');
    }, 900); }
  if (new URLSearchParams(location.search).get('menuscroll') === 'bottom') {
    setTimeout(() => {
      const pane = [...document.querySelectorAll('.pane')].find(x => x.offsetParent);
      if (pane) pane.scrollTop = pane.scrollHeight;
    }, 1400);
  }
  const _m = new URLSearchParams(location.search).get('mod');
  if (_m) { try { selectModule(_m); } catch (e) {} }
  const _t = new URLSearchParams(location.search).get('task');
  if (_t) { try { curTask = _t; renderSubnav(); renderPanel(); } catch (e) {} }
  document.querySelectorAll('.theme-opt').forEach((b) => {
    if (b.dataset.lang) { b.onclick = () => setLang(b.dataset.lang); return; }
    b.onclick = () => setTheme(b.dataset.theme);
  });
  try {
    const st = await (await fetch('/api/settings')).json();
    applyTheme((st.settings && st.settings.theme) || 'light');  /* ROUND 19: DEFAULT THEME LIGHT */
    paintLang((st.settings && st.settings.lang) || localStorage.getItem('ti-lang') || 'zh');
  } catch (e) { applyTheme('light'); paintLang('zh'); }
  const ml = /[?&]lang=([a-z]+)/.exec(location.search);
  if (ml) paintLang(ml[1]);
  const mt = /[?&]theme=([a-z]+)/.exec(location.search);
  if (mt) setTheme(mt[1]);

  $('#ver').textContent = 'V' + ((CATALOG && CATALOG.app && CATALOG.app.version) || '1.0.0');
  const mo = /[?&]open=([a-z]+)/.exec(location.search);
  if (mo) openMenu(mo[1]);
  const mi = /[?&]intro=([A-Za-z0-9_-]+)/.exec(location.search);
  if (mi) openIntro(mi[1]);

  // 闪屏：至少显示 620ms，让呼吸动画看得见；?splash=hold 可卡住不消失（自测用）
  if (new URLSearchParams(location.search).get('splash') === 'hold') return;
  setTimeout(hideSplash, Math.max(0, 620 - (performance.now() - _t0)));
}

init().catch((e) => { try { document.title = 'ERR: ' + (e && e.message); } catch (_) {} hideSplash(); });

function keyPillWidth() {
  const pill = document.getElementById('keyPill');
  if (!pill) return 132;
  const was = pill.style.display;
  pill.style.display = 'inline-flex';
  const w = Math.ceil(pill.offsetWidth) || 132;
  pill.style.display = was;
  return w;
}

function keybarOf(keys) { return keys.parentElement; }

function setKeysOpen(keys, open) {
  if (!keys) return;
  const collapsed = keys.classList.contains('collapsed');
  if (open === !collapsed) return;
  const pw = keyPillWidth();
  const kb = keys.parentElement;
  const D = document.body.classList.contains('no-anim') ? 0 : 340;                              // 展开/收起共用同一时长
  const EASE = 'cubic-bezier(.22,.61,.36,1)';
  const kids = keys.querySelectorAll('.keys-side, .keys-body');
  keys.getAnimations().forEach(a => a.cancel());
  kids.forEach(k => k.getAnimations().forEach(a => a.cancel()));

  if (open) {
    document.body.classList.remove('key-collapsed');
    if (kb) kb.classList.add('open');
    keys.classList.remove('collapsed', 'collapsing');
    keys.style.height = ''; keys.style.width = ''; keys.style.overflow = 'hidden';
    void keys.offsetHeight;
    const th = keys.offsetHeight, tw = Math.ceil(keys.offsetWidth);
    const a = keys.animate(
      [{ width: pw + 'px', height: '32px' }, { width: tw + 'px', height: th + 'px' }],
      { duration: D, easing: EASE, fill: 'both' }
    );
    kids.forEach(k => k.animate([{ opacity: 0 }, { opacity: 1 }],
      { duration: D, easing: 'ease', fill: 'both', delay: D * 0.25 }));
    a.onfinish = () => {
      keys.getAnimations().forEach(x => x.cancel());
      kids.forEach(k => k.getAnimations().forEach(x => x.cancel()));
      keys.style.height = ''; keys.style.width = ''; keys.style.overflow = '';
    };
  } else {
    const th = keys.offsetHeight, tw = Math.ceil(keys.offsetWidth);
    keys.style.overflow = 'hidden';
    keys.classList.add('collapsing');
    const a = keys.animate(
      [{ width: tw + 'px', height: th + 'px' }, { width: pw + 'px', height: '32px' }],
      { duration: D, easing: EASE, fill: 'both' }
    );
    kids.forEach(k => k.animate([{ opacity: 1 }, { opacity: 0 }],
      { duration: D * 0.72, easing: 'ease', fill: 'both' }));
    setTimeout(() => {
      document.body.classList.add('key-collapsed');
      if (kb) kb.classList.remove('open');
    }, Math.round(D * 0.7));
    a.onfinish = () => {
      keys.getAnimations().forEach(x => x.cancel());
      kids.forEach(k => k.getAnimations().forEach(x => x.cancel()));
      keys.classList.remove('collapsing');
      keys.classList.add('collapsed');
      keys.style.height = ''; keys.style.width = ''; keys.style.overflow = '';
      document.body.classList.add('key-collapsed');
    };
  }
}

function bindKeyDrawer() {
  const keys = document.querySelector('.keys');
  const pill = document.getElementById('keyPill');
  const tog = document.getElementById('keyToggle');
  if (pill && keys) pill.onclick = (e) => { e.preventDefault(); setKeysOpen(keys, true); };
  if (tog && keys) tog.onclick = (e) => { e.preventDefault(); setKeysOpen(keys, false); };
}

function setLogCollapsed(box, on) {
  if (!box) return;
  const pill = document.getElementById('logPill');
  const collapsed = box.classList.contains('collapsed') || document.body.classList.contains('log-collapsed');
  if (on === collapsed) return;
  const D = document.body.classList.contains('no-anim') ? 0 : 340;
  const EASE = 'cubic-bezier(.22,.61,.36,1)';
  const kids = box.querySelectorAll('.home-log-head, .home-log-body');
  box.getAnimations().forEach(a => a.cancel());
  kids.forEach(k => k.getAnimations().forEach(a => a.cancel()));
  const pw = (() => {
    if (!pill) return 108;
    const wasVis = pill.style.visibility, wasDisp = pill.style.display;
    pill.style.visibility = 'hidden'; pill.style.display = 'inline-flex';
    const w = Math.ceil(pill.offsetWidth) || 108;
    pill.style.display = wasDisp; pill.style.visibility = wasVis;
    return w;
  })();

  if (!on) {
    document.body.classList.remove('log-collapsed');
    box.classList.remove('collapsed', 'log-collapsing');
    Object.assign(box.style, { display: 'block', position: 'fixed', right: '24px', bottom: '24px', overflow: 'hidden' });
    box.style.width = ''; box.style.height = '';
    void box.offsetHeight;
    const tw = Math.ceil(box.offsetWidth), th = box.offsetHeight;
    const ph0 = pill ? Math.ceil(pill.offsetHeight) || 34 : 34;
    const a = box.animate(
      [{ width: pw + 'px', height: ph0 + 'px' }, { width: tw + 'px', height: th + 'px' }],
      { duration: D, easing: EASE, fill: 'both' }
    );
    kids.forEach(k => k.animate([{ opacity: 0 }, { opacity: 1 }],
      { duration: D, easing: 'ease', fill: 'both', delay: D * 0.25 }));
    a.onfinish = () => {
      box.getAnimations().forEach(x => x.cancel());
      kids.forEach(k => k.getAnimations().forEach(x => x.cancel()));
      box.style.width = ''; box.style.height = ''; box.style.overflow = '';
    };
  } else {
    const tw = Math.ceil(box.offsetWidth), th = box.offsetHeight;
    box.style.overflow = 'hidden';
    box.classList.add('log-collapsing');
    const ph = pill ? Math.ceil(pill.offsetHeight) || 34 : 34;
    const a = box.animate(
      [{ width: tw + 'px', height: th + 'px' }, { width: pw + 'px', height: ph + 'px' }],
      { duration: D, easing: EASE, fill: 'both' }
    );
    kids.forEach(k => k.animate([{ opacity: 1 }, { opacity: 0 }],
      { duration: D * 0.72, easing: 'ease', fill: 'both' }));
    setTimeout(() => {
      document.body.classList.add('log-collapsed');
    }, Math.round(D * 0.7));
    a.onfinish = () => {
      box.getAnimations().forEach(x => x.cancel());
      kids.forEach(k => k.getAnimations().forEach(x => x.cancel()));
      box.classList.remove('log-collapsing');
      box.classList.add('collapsed');
      box.style.width = ''; box.style.height = ''; box.style.overflow = '';
      document.body.classList.add('log-collapsed');
    };
  }
}

function bindHomeLog() {
  const pill = document.getElementById('logPill');
  const box0 = document.getElementById('homeLogBox');
  if (pill && box0) pill.onclick = () => { setLogCollapsed(box0, false); };
  const box = document.getElementById('homeLogBox');
  if (box0 && box0.classList.contains('collapsed')) document.body.classList.add('log-collapsed');
  const tab = document.getElementById('homeLogToggle');
  const close = document.getElementById('homeLogClose');
  if (box && tab) tab.onclick = () => setLogCollapsed(box, false);
  if (box && close) close.onclick = () => setLogCollapsed(box, true);
}

/* ==== ROUND 17: CHANGELOG CARD WITH PLAN TAB ==== */
(function () {
  var ROAD_EN = [
    'Update plan (in priority order)',
    '',
    '1. Keyboard shortcuts',
    '   Global hotkeys for the common actions: scan keys, unpack, export locres, start packing;',
    '   every hotkey is rebindable in Settings, conflicts are reported.',
    '',
    '2. Built-in AI localization',
    '   A translation channel inside the toolbox, no plugins: pick the strings you want',
    '   (locres / uasset), send glossary and context together, write results back and repack.',
    '   (A toolbox feature, not a wrapper around another tool.)'
  ].join('\n');
  var ROAD = [
    '更新计划（按优先级推进）',
    '',
    '1. 快捷键功能',
    '   给常用动作配全局热键：扫描密钥、解包、导出 locres、开始打包都能一键触发；',
    '   热键在设置里可自定义，冲突时给出提示。',
    '',
    '2. 接入 AI 进行汉化功能',
    '   工具箱内置翻译通道，不再靠外装插件：选中要翻的文本（locres / uasset 串）后',
    '   直接调用模型批量翻译，术语表与上下文一起送进去，回来就能写回并打包。',
    '   （是工具箱自己的功能，不是在装别的工具。）'
  ].join('\n');

  function init() {
    var box = document.getElementById('homeLogBox');
    var body = document.getElementById('homeLog');
    if (!box || !body) return;
    var tabs = Array.prototype.slice.call(box.querySelectorAll('.log-tab'));
    var refresh = document.getElementById('logRefresh');
    var pill = document.getElementById('logPill');
    var logText = null;
    var current = 'log';

    function isEn() {
      return !!(window.I18N && I18N.lang && I18N.lang() === 'en');
    }
    function paintTabs() {
      tabs.forEach(function (t) { t.classList.toggle('on', t.dataset.view === current); });
    }
    function renderPlan() {
      body.textContent = isEn() ? ROAD_EN : ROAD;
    }
    /* ROUND 18: LOG CARD ANIMATION
       ① 首次打开前先把日志正文取回来，否则按“加载中…”的高度做展开动画，正文到达后卡片会猛地长高；
       ② 切 tab 时给卡片做高度过渡 + 内容淡入上移，不再硬切。 */
    var logPromise = null;
    var EASE = 'cubic-bezier(.22,.61,.36,1)';
    function isAnimated() {
      return !document.body.classList.contains('no-anim');
    }
    function ensureLog() {
      if (logText !== null) return Promise.resolve();
      if (!logPromise) {
        logPromise = Promise.resolve(typeof loadChangelog === 'function' ? loadChangelog() : null)
          .then(function () { logText = body.textContent; })
          .catch(function () { logText = body.textContent; });
      }
      return logPromise;
    }
    function swapTo(which) {
      if (which === 'road') {
        if (logText === null) logText = body.textContent;
        renderPlan();
        return Promise.resolve();
      }
      if (logText !== null) {
        body.textContent = logText;
        return Promise.resolve();
      }
      return ensureLog();
    }
    function playSwap(prev, oldH) {
      if (!isAnimated() || prev === current) return;
      var newH = box.offsetHeight;
      if (Math.abs(newH - oldH) > 1) {
        box.style.overflow = 'hidden';
        var a = box.animate(
          [{ height: oldH + 'px' }, { height: newH + 'px' }],
          { duration: 220, easing: EASE, fill: 'both' }
        );
        a.onfinish = function () {
          try { a.cancel(); } catch (e) {}
          box.style.overflow = '';
        };
        a.oncancel = function () { box.style.overflow = ''; };
      }
      var b = body.animate(
        [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'translateY(0)' }],
        { duration: 220, easing: 'ease-out' }
      );
      b.onfinish = function () { try { b.cancel(); } catch (e) {} };
    }
    function show(which) {
      if (which !== 'log' && which !== 'road') which = 'log';
      var prev = current;
      var oldH = box.offsetHeight;
      current = which;
      paintTabs();
      if (refresh) refresh.style.display = (which === 'road') ? 'none' : '';
      return swapTo(which).then(function () {
        setLogCollapsed(box, false);
        playSwap(prev, oldH);
      });
    }

    tabs.forEach(function (t) {
      t.onclick = function (e) { e.preventDefault(); show(t.dataset.view); };
    });
    if (pill) pill.onclick = function (e) { e.preventDefault(); show(current); };
    var toggle = document.getElementById('homeLogToggle');
    if (toggle) toggle.onclick = function (e) { e.preventDefault(); show(current); };
    paintTabs();

    // 语言切换：若正停在更新计划，正文按新语言重出一次
    if (window.I18N && I18N.apply) {
      var _apply = I18N.apply;
      I18N.apply = function (l) {
        _apply.call(I18N, l);
        if (current === 'road') renderPlan();
      };
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { setTimeout(init, 260); });
  } else {
    setTimeout(init, 260);
  }
})();


/* 支持我：用系统浏览器打开爱发电，避免 WebView2 内嵌打开 */
(function () {
  var a = document.getElementById('supportMe');
  if (!a) return;
  a.addEventListener('click', function (e) {
    e.preventDefault();
    fetch('/api/link', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: a.getAttribute('href') }),
    }).catch(function () { window.open(a.getAttribute('href'), '_blank'); });
  });
})();
