# -*- coding: utf-8 -*-
"""round-20: V1.1.3 —— 更新功能修复（徽标移到侧栏右下 + 一键下载替换）"""
import io, json, sys

ROOT = r'F:\模型\TI工具箱'
MARK = 'ROUND 20: SELF UPDATE'

# ---------- 1) app.py: 新增 /api/update ----------
p_app = ROOT + r'\app.py'
app = io.open(p_app, 'r', encoding='utf-8').read()
if MARK in app:
    print('app.py already patched')
else:
    anchor = '''        if p == "/api/locres":'''
    assert anchor in app, 'locres anchor missing'
    handler = r'''        if p == "/api/update":
            # ROUND 20: SELF UPDATE —— 下载最新 Release 的可执行文件，交给外部脚本替换并重启
            repo = (data.get("repo") or "").strip()
            if not repo:
                repo = str((read_json(SETTINGS_JSON, {}) or {}).get("github_repo") or "")
            asset_url = (data.get("asset_url") or "").strip()
            force = bool(data.get("force"))
            apply_now = data.get("apply") is not False

            def _vtxt(v):
                return [int(x) for x in re.findall(r"\d+", str(v))[:4]]

            def _vgt(a, b):
                A, B = _vtxt(a), _vtxt(b)
                n = max(len(A), len(B))
                A += [0] * (n - len(A))
                B += [0] * (n - len(B))
                return A > B

            cur_ver = str((catalog().get("app") or {}).get("version") or "0.0.0")
            tag = ""
            hdrs = {"User-Agent": "TI-Toolbox/" + cur_ver, "Accept": "application/vnd.github+json"}
            tok = (read_json(SETTINGS_JSON, {}) or {}).get("github_token") or ""
            if tok:
                hdrs["Authorization"] = "Bearer " + tok
            try:
                if not asset_url:
                    m = re.search(r"github\.com[/:]([^/\s]+)/([^/\s]+)", repo)
                    if not m:
                        m = re.search(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", repo)
                    if not m:
                        return self._json({"ok": False, "error": "仓库地址无法识别"})
                    owner, name = m.group(1), m.group(2)
                    if name.endswith(".git"):
                        name = name[:-4]
                    url = "https://api.github.com/repos/%s/%s/releases/latest" % (owner, name)
                    req = urllib.request.Request(url, headers=hdrs)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        info = json.loads(resp.read().decode("utf-8"))
                    tag = info.get("tag_name") or ""
                    if tag and not force and not _vgt(tag, cur_ver):
                        return self._json({"ok": False, "error": "已是最新版本（%s）" % tag, "tag": tag,
                                           "current": cur_ver})
                    assets = info.get("assets") or []
                    pick = None
                    for a in assets:
                        if str(a.get("name", "")).lower().endswith(".exe"):
                            pick = a
                            break
                    if pick is None:
                        for a in assets:
                            if str(a.get("name", "")).lower().endswith(".zip"):
                                pick = a
                                break
                    if pick is None:
                        return self._json({"ok": False, "error": "该 Release 没有 .exe 或 .zip 附件", "tag": tag})
                    asset_url = pick.get("browser_download_url") or ""
                    if not asset_url:
                        return self._json({"ok": False, "error": "附件没有下载地址", "tag": tag})
            except urllib.error.HTTPError as e:
                return self._json({"ok": False, "error": "请求 GitHub 失败：HTTP %d" % e.code})
            except Exception as e:
                return self._json({"ok": False, "error": "请求 GitHub 失败：" + str(e)})

            tmpdir = tempfile.mkdtemp(prefix="tiupd_")
            dl = os.path.join(tmpdir, os.path.basename(asset_url.split("?")[0]) or "update.bin")
            try:
                req = urllib.request.Request(asset_url, headers={"User-Agent": "TI-Toolbox/" + cur_ver})
                with urllib.request.urlopen(req, timeout=90) as resp, open(dl, "wb") as f:
                    shutil.copyfileobj(resp, f, 1024 * 256)
            except Exception as e:
                return self._json({"ok": False, "error": "下载失败：" + str(e)})

            new_exe = os.path.join(tmpdir, "new.exe")
            try:
                if dl.lower().endswith(".zip"):
                    import zipfile
                    with zipfile.ZipFile(dl) as zf:
                        cand = [n for n in zf.namelist()
                                if n.lower().endswith(".exe") and not n.startswith("__MACOSX")]
                        cand.sort(key=lambda n: (0 if "\u5de5\u5177\u7bb1" in n else 1, -zf.getinfo(n).file_size))
                        if not cand:
                            return self._json({"ok": False, "error": "压缩包里没有 .exe"})
                        with zf.open(cand[0]) as src, open(new_exe, "wb") as dst:
                            shutil.copyfileobj(src, dst, 1024 * 256)
                else:
                    shutil.copyfile(dl, new_exe)
            except Exception as e:
                return self._json({"ok": False, "error": "解包失败：" + str(e)})

            size = os.path.getsize(new_exe) if os.path.exists(new_exe) else 0
            if size < 2 * 1024 * 1024:
                return self._json({"ok": False, "error": "下载到的文件不像主程序（%d 字节）" % size})
            with open(new_exe, "rb") as f:
                if f.read(2) != b"MZ":
                    return self._json({"ok": False, "error": "下载到的文件不是 Windows 可执行文件"})

            target = str(HERE / "\u0054\u0049\u5de5\u5177\u7bb1.exe")
            staged = str(HERE / "\u0054\u0049\u5de5\u5177\u7bb1.new.exe")
            try:
                shutil.copyfile(new_exe, staged)
            except Exception as e:
                return self._json({"ok": False, "error": "写入新版本失败：" + str(e)})

            if not apply_now:
                return self._json({"ok": True, "staged": staged, "size": size, "tag": tag, "restarting": False})

            # 外部 PowerShell：等本进程退出 → 覆盖 → 重新启动
            ps = (
                "$ErrorActionPreference='SilentlyContinue';"
                "for($i=0;$i -lt 60;$i++){ if(-not (Get-Process -Id %d -ErrorAction SilentlyContinue)){ break }; Start-Sleep -Milliseconds 400 };"
                "Start-Sleep -Milliseconds 600;"
                "for($i=0;$i -lt 30;$i++){ try{ Move-Item -LiteralPath '%s' -Destination '%s' -Force -ErrorAction Stop; break }catch{ Start-Sleep -Milliseconds 400 } };"
                "Start-Process -FilePath '%s'"
            ) % (os.getpid(), staged, target, target)
            try:
                subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) |
                                 getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                                 close_fds=True)
            except Exception as e:
                return self._json({"ok": False, "error": "启动替换脚本失败：" + str(e)})

            threading.Timer(1.2, lambda: os._exit(0)).start()
            return self._json({"ok": True, "staged": staged, "size": size, "tag": tag, "restarting": True})
'''
    app = app.replace(anchor, handler + anchor, 1)
    io.open(p_app, 'w', encoding='utf-8', newline='\n').write(app)
    print('app.py patched:', len(app))

# ---------- 2) catalog.json: 版本 1.1.3 ----------
p_cat = ROOT + r'\catalog.json'
raw = io.open(p_cat, 'r', encoding='utf-8').read()
cat = json.loads(raw)
cat['app']['version'] = '1.1.3'
io.open(p_cat, 'w', encoding='utf-8', newline='\n').write(json.dumps(cat, ensure_ascii=False, indent=2) + '\n')
print('catalog version ->', cat['app']['version'])

# ---------- 3) index.html: 更新按钮放到侧栏右下角 ----------
p_html = ROOT + r'\ui\index.html'
html = io.open(p_html, 'r', encoding='utf-8').read()
old_btn = '<button id="newVer" class="newver" hidden>\u65b0\u7248\u672c\u53ef\u7528</button>'
new_btn = '<button id="newVer" class="newver" hidden>\u66f4\u65b0\u7248\u672c</button>'
assert old_btn in html, 'newVer button text not found'
html = html.replace(old_btn, new_btn, 1)
io.open(p_html, 'w', encoding='utf-8', newline='\n').write(html)
print('index.html patched:', len(html))

# ---------- 4) app.js: 徽标就是更新按钮 ----------
p_js = ROOT + r'\ui\app.js'
js = io.open(p_js, 'r', encoding='utf-8').read()
if MARK in js:
    print('app.js already patched')
else:
    old_mark = """function markUpdate(tag) {
  const btn = $('#newVer');
  if (!btn) return;
  const cur = (CATALOG.app && CATALOG.app.version) || '1.0.0';
  const ok = /^\\s*v?\\d+(?:\\.\\d+){1,3}\\s*$/i.test(String(tag || ''));
  const yes = ok && verGt(tag, cur);
  btn.hidden = !yes;
  if (yes) {
    btn.title = '有新版本可用：' + tag + '（当前 V' + cur + '）';
    localStorage.setItem('ti-upd-tag', tag);
  } else {
    btn.removeAttribute('title');
    localStorage.removeItem('ti-upd-tag');
  }
}"""
    new_mark = """/* ROUND 20: SELF UPDATE —— 徽标即更新按钮 */
function markUpdate(tag) {
  const btn = $('#newVer');
  if (!btn) return;
  const cur = (CATALOG.app && CATALOG.app.version) || '1.0.0';
  const ok = /^\\s*v?\\d+(?:\\.\\d+){1,3}\\s*$/i.test(String(tag || ''));
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
  const repo = (($('#s_ghrepo') && $('#s_ghrepo').value.trim()) ||
    (CATALOG.settings && CATALOG.settings.github_repo) || '');
  if (btn) { btn.disabled = true; btn.textContent = '正在下载…'; }
  if (st) st.textContent = '正在下载新版本…';
  let r = null;
  try { r = await api('/api/update', { repo }); } catch (e) { r = { ok: false, error: e.message }; }
  if (!r || !r.ok) {
    if (btn) { btn.disabled = false; btn.textContent = '更新版本'; }
    const msg = (r && r.error) || '未知错误';
    if (st) st.textContent = '更新失败：' + msg;
    if (btn) btn.title = '更新失败：' + msg;
    return;
  }
  if (btn) btn.textContent = '正在重启…';
  if (st) st.textContent = '已下载 ' + Math.round((r.size || 0) / 1024 / 1024) + ' MB，正在替换并重启…';
}"""
    assert old_mark in js, 'markUpdate block not found'
    js = js.replace(old_mark, new_mark, 1)

    old_bind = """  const nv = $('#newVer');
  if (nv) nv.onclick = () => openMenu('version');"""
    new_bind = """  const nv = $('#newVer');
  if (nv) nv.onclick = () => {
    if (nv.dataset && nv.dataset.tag) runUpdate();
    else openMenu('version');
  };"""
    assert old_bind in js, 'newVer binding not found'
    js = js.replace(old_bind, new_bind, 1)
    io.open(p_js, 'w', encoding='utf-8', newline='\n').write(js)
    print('app.js patched:', len(js))

# ---------- 5) style.css: 徽标推到侧栏右下角 ----------
p_css = ROOT + r'\ui\style.css'
css = io.open(p_css, 'r', encoding='utf-8').read()
if MARK in css:
    print('style.css already patched')
else:
    css += """
/* ==== ROUND 20: SELF UPDATE ==== */
/* 徽标移到侧栏底部右侧（原来齿轮的位置在左，右侧空着） */
.side-foot #gear { order: 1; }
.side-foot .support { order: 2; }
#newVer.newver { order: 3; margin-left: auto; margin-right: 0; }
#newVer.newver:disabled { cursor: default; opacity: .75; }
html[data-theme="light"] #newVer.newver:disabled,
html[data-theme="pink"] #newVer.newver:disabled { opacity: .7; }
#newVer.newver[data-tag] { border-color: #3ad07b; }
html[data-theme="pink"] #newVer.newver[data-tag] { border-color: #d6336c; }
"""
    io.open(p_css, 'w', encoding='utf-8', newline='\n').write(css)
    print('style.css patched:', len(css))

# ---------- 6) changelog ----------
p_log = ROOT + r'\changelog.md'
log = io.open(p_log, 'r', encoding='utf-8').read()
if '## V1.1.3' in log:
    print('changelog already has V1.1.3')
else:
    head = '~~~~~!!! V1.1.2 \u6b63\u5f0f\u7248 !!!~~~~~~\n'
    new_head = '~~~~~!!! V1.1.3 \u4fee\u590d\u7248 !!!~~~~~~\n'
    assert head in log, 'changelog header not found'
    log = log.replace(head, new_head, 1)
    entry = (
        '## V1.1.3 \u00b7 2026-11-24\n'
        '- \u4fee\u590d\u4e86\u66f4\u65b0\u529f\u80fd\uff1a\u53d1\u73b0\u65b0\u7248\u672c\u540e\u53ef\u76f4\u63a5\u4e0b\u8f7d\u5e76\u66ff\u6362\u65e7\u7248\uff0c\u4e0d\u518d\u53ea\u662f\u5f39\u4e2a\u6807\u7b7e\n'
        '- \u300c\u66f4\u65b0\u7248\u672c\u300d\u6309\u94ae\u79fb\u5230\u4fa7\u680f\u53f3\u4e0b\u89d2\uff0c\u4e0e\u8bbe\u7f6e\u540c\u6392\uff1b\u70b9\u51fb\u5373\u4e0b\u8f7d\u3001\u66ff\u6362\u3001\u81ea\u52a8\u91cd\u542f\n'
        '- \u4e0b\u8f7d\u524d\u4f1a\u6821\u9a8c\u9644\u4ef6\uff08exe \u6216 zip\uff09\u4e0e PE \u5934\uff0c\u7248\u672c\u672a\u53d8\u65f6\u76f4\u63a5\u62d2\u7edd\n'
        '\n'
    )
    idx = log.index('## V1.1.2')
    log = log[:idx] + entry + log[idx:]
    io.open(p_log, 'w', encoding='utf-8', newline='\n').write(log)
    print('changelog patched')

print('DONE')
