# -*- coding: utf-8 -*-
"""round-20b: 把升级的 zip 提取/校验/落盘抽成模块级函数，便于自测；下载改成重试 + 代理 + 备用地址"""
import io, re

P = r'F:\模型\TI工具箱\app.py'
s = io.open(P, 'r', encoding='utf-8').read()
MARK = 'ROUND 20B: UPDATE HELPERS'
if MARK in s:
    print('already patched'); raise SystemExit(0)

helpers = '''# ==== ROUND 20B: UPDATE HELPERS ====
def _new_version_paths():
    """返回 (当前 exe, 待替换的新 exe) 路径。"""
    return (str(HERE / "\\u0054\\u0049\\u5de5\\u5177\\u7bb1.exe"),
            str(HERE / "\\u0054\\u0049\\u5de5\\u5177\\u7bb1.new.exe"))


def _extract_exe_from_zip(zip_path: str, out_path: str) -> str:
    """从 zip 里挑最像主程序的 exe 解到 out_path。"""
    import zipfile
    with zipfile.ZipFile(zip_path) as zf:
        cand = [n for n in zf.namelist() if n.lower().endswith(".exe") and not n.startswith("__MACOSX")]
        if not cand:
            raise ValueError("压缩包里没有 .exe")
        cand.sort(key=lambda n: (0 if "\\u5de5\\u5177\\u7bb1" in n else 1, -zf.getinfo(n).file_size))
        with zf.open(cand[0]) as src, open(out_path, "wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 256)
    return out_path


def _stage_new_exe(src_file: str) -> dict:
    """校验 PE 头并落盘成 <exe>.new.exe；返回 {ok, staged, size, error}。"""
    size = os.path.getsize(src_file) if os.path.exists(src_file) else 0
    if size < 2 * 1024 * 1024:
        return {"ok": False, "error": "下载到的文件不像主程序（%d 字节）" % size}
    with open(src_file, "rb") as f:
        if f.read(2) != b"MZ":
            return {"ok": False, "error": "下载到的文件不是 Windows 可执行文件"}
    _cur, staged = _new_version_paths()
    try:
        shutil.copyfile(src_file, staged)
    except Exception as e:
        return {"ok": False, "error": "写入新版本失败：" + str(e)}
    return {"ok": True, "staged": staged, "size": size}


def _http_get(url: str, headers: dict | None = None, timeout: int = 30):
    """带代理与重试的 GET；返回 response 对象。"""
    hdrs = dict(headers or {})
    proxies = urllib.request.getproxies()
    st = read_json(SETTINGS_JSON, {}) or {}
    pset = str(st.get("proxy") or "").strip()
    if pset:
        proxies = {"http": pset, "https": pset}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    last = None
    for _ in range(3):
        try:
            return opener.open(urllib.request.Request(url, headers=hdrs), timeout=timeout)
        except Exception as e:
            last = e
            time.sleep(0.8)
    raise last if last else RuntimeError("请求失败")


'''

anchor = 'def _path_state(path: str) -> dict:'
assert anchor in s
s = s.replace(anchor, helpers + anchor, 1)

# ---- 替换 handler 里的下载/解包/校验段 ----
old_dl_start = '''            tmpdir = tempfile.mkdtemp(prefix="tiupd_")'''
old_dl_end = '''            if not apply_now:'''
i1 = s.index(old_dl_start)
i2 = s.index(old_dl_end)
new_block = '''            tmpdir = tempfile.mkdtemp(prefix="tiupd_")
            dl = os.path.join(tmpdir, os.path.basename((asset_url or "").split("?")[0]) or "update.bin")
            try:
                resp = _http_get(asset_url, {"User-Agent": "TI-Toolbox/" + cur_ver, "Accept": "*/*"}, timeout=120)
                with resp, open(dl, "wb") as f:
                    shutil.copyfileobj(resp, f, 1024 * 256)
            except Exception as e:
                return self._json({"ok": False, "tag": tag, "page": page_url, "asset": asset_url,
                                   "error": "下载失败（网络或代理）：" + str(e)})

            new_exe = os.path.join(tmpdir, "new.exe")
            try:
                if dl.lower().endswith(".zip"):
                    _extract_exe_from_zip(dl, new_exe)
                else:
                    shutil.copyfile(dl, new_exe)
            except Exception as e:
                return self._json({"ok": False, "error": "解包失败：" + str(e)})

            staged_info = _stage_new_exe(new_exe)
            if not staged_info.get("ok"):
                return self._json({"ok": False, "error": staged_info.get("error") or "写入失败"})
            staged = staged_info["staged"]
            size = staged_info["size"]

'''
s = s[:i1] + new_block + s[i2:]

# 去掉旧的 target/staged 计算（现在由 _new_version_paths 提供）
s = s.replace('''            target = str(HERE / "\\u0054\\u0049\\u5de5\\u5177\\u7bb1.exe")
            staged = str(HERE / "\\u0054\\u0049\\u5de5\\u5177\\u7bb1.new.exe")
''', '''            target, _staged2 = _new_version_paths()
''', 1)

# 记录 page_url（release 页面，下载失败时可让用户用浏览器打开）
s = s.replace('''                    tag = info.get("tag_name") or ""''',
              '''                    tag = info.get("tag_name") or ""
                    page_url = info.get("html_url") or ""''', 1)
s = s.replace('''            tag = ""
            hdrs = {"User-Agent": "TI-Toolbox/" + cur_ver''',
              '''            tag = ""
            page_url = ""
            hdrs = {"User-Agent": "TI-Toolbox/" + cur_ver''', 1)

io.open(P, 'w', encoding='utf-8', newline='\n').write(s)
print('app.py patched:', len(s))
