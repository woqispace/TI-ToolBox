# -*- coding: utf-8 -*-
"""round-20c: 下载失败时给出下载页兜底；/api/link 放行 github.com"""
import io

ROOT = r'F:\模型\TI工具箱'

# 1) app.py: /api/link 白名单加 github.com
p = ROOT + r'\app.py'
s = io.open(p, 'r', encoding='utf-8').read()
old = '''host.endswith("ifdian.net")'''
if 'objects.githubusercontent.com' in s:
    print('link whitelist already extended')
else:
    assert old in s, 'link whitelist anchor missing'
    s = s.replace(old, '''(host.endswith("ifdian.net") or host.endswith("github.com") or host.endswith("objects.githubusercontent.com"))''', 1)
    io.open(p, 'w', encoding='utf-8', newline='\n').write(s)
    print('app.py link whitelist extended')

# 2) app.js: 失败兜底打开下载页
p2 = ROOT + r'\ui\app.js'
js = io.open(p2, 'r', encoding='utf-8').read()
MARK = 'ROUND 20C: UPDATE FALLBACK'
if MARK in js:
    print('app.js already patched')
else:
    old_fail = """  if (!r || !r.ok) {
    if (btn) { btn.disabled = false; btn.textContent = '更新版本'; }
    const msg = (r && r.error) || '未知错误';
    if (st) st.textContent = '更新失败：' + msg;
    if (btn) btn.title = '更新失败：' + msg;
    return;
  }"""
    new_fail = """  if (!r || !r.ok) {
    if (btn) { btn.disabled = false; btn.textContent = '更新版本'; }
    const msg = (r && r.error) || '未知错误';
    if (r && r.page) {
      /* ROUND 20C: UPDATE FALLBACK —— 内置下载走不通时，用系统浏览器打开下载页 */
      api('/api/link', { url: r.page }).catch(() => {});
      if (st) st.textContent = '自动更新失败（' + msg + '），已打开下载页：' + r.page;
      if (btn) btn.title = '自动更新失败，已打开下载页';
    } else {
      if (st) st.textContent = '更新失败：' + msg;
      if (btn) btn.title = '更新失败：' + msg;
    }
    return;
  }"""
    assert old_fail in js, 'fail branch not found'
    js = js.replace(old_fail, new_fail, 1)
    io.open(p2, 'w', encoding='utf-8', newline='\n').write(js)
    print('app.js patched:', len(js))
print('DONE')
