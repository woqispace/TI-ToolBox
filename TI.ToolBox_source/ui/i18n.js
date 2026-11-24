/* TI Toolbox — 界面文案中英切换（V1.1.2）
   做法：以「中文原文 → 英文」字典替换文本节点与 placeholder/title，
   切换回中文时用记忆的原文还原；英文模式下用 MutationObserver 跟随动态渲染。 */
(function () {
  var LANG = 'zh';
  var EN = {
    /* 菜单骨架 */
    '菜单': 'Menu', '关闭': 'Close', '个性化': 'Appearance', '设置': 'Settings',
    '版本': 'Version', '关于': 'About', '保存': 'Save', '保存仓库': 'Save repository',
    '检查更新': 'Check for updates', '刷新': 'Refresh', '更新日志': 'Changelog',

    /* 个性化 */
    '界面主题': 'Theme', '界面语言': 'Language', '黑': 'Dark', '白': 'Light', '粉': 'Pink',
    '点一下立刻生效，写进 exe 同目录的 settings.json，下次打开还是这套。':
      'Applies immediately, saved to settings.json beside the exe.',
    '切换语言后，工具面板的说明文字同样跟随变化。':
      'Switching the language also updates the tool panels.',

    /* 设置 */
    '工具箱路径': 'Toolbox path', '性能': 'Performance', '关闭动画': 'Disable animations',
    '使用 GPU 加速': 'Use GPU acceleration', '默认输出目录': 'Default output folder',
    'Mappings 文件夹': 'Mappings folder', '选择文件夹': 'Choose folder',
    '清理缓存': 'Clear cache', '打开工具箱目录': 'Open toolbox folder',
    '工具箱根目录。全部内置工具与运行依赖位于其下的 ': 'Toolbox root. Bundled tools and runtime dependencies live in ',
    ' 子目录，后续通过仓库安装的工具同样安装至此。': ' under it; tools installed from the repository land there too.',
    '关闭后立即停用全部过渡与折叠动画，不影响功能执行。GPU 加速切换后需重启程序方可生效。':
      'Turns off every transition and collapse animation immediately. GPU acceleration applies after restart.',
    '输出型任务的输出路径留空时，默认写入该目录。':
      'When a task output path is left empty, results go to this folder.',
    '留空 = 工具箱目录下的 output': 'Empty = output folder inside the toolbox',
    'UAssetGUI / FModel / DUMP 面板会从这个目录列出 .usmap，方便快速切换。':
      'The UAssetGUI / FModel / DUMP panels list .usmap files from this folder.',

    /* 版本 */
    '当前版本': 'Current version', 'GitHub 仓库': 'GitHub repository',
    'GitHub Token（可选）': 'GitHub token (optional)',
    '版本号取自 catalog.json 的 app.version；后续更新以 GitHub 仓库的 Release 为准。':
      'Version comes from app.version in catalog.json; updates follow the latest GitHub Release.',
    '填写仓库后可用于检查更新与下载新版本；留空则只做本地版本展示。 支持 owner/repo 或完整地址。':
      'Fill in the repository to check for updates. owner/repo or a full URL both work.',
    '留空则使用匿名请求（每小时 60 次）；填写后配额提升至 5000 次并支持私有仓库。':
      'Empty uses anonymous requests (60/hour); a token raises the limit to 5000/hour and supports private repos.',

    /* 关于 */
    'TI 工具箱 · UE4/5 工具箱': 'TI Toolbox · UE4/5 Toolkit',
    '功能': 'Features', '优点': 'Highlights', '新增': 'What is new', '免责声明': 'Disclaimer',
    '统一入口：密钥、解包、文本、打包、验签在同一进程内完成，免去跨工具链切换':
      'One entry point: key extraction, unpacking, text work, packing and signature bypass in a single process.',
    '参数可复用：目标目录与密钥按模块独立持久化，exe / pak 路径自动探测':
      'Reusable parameters: per-module target folders and keys persist; exe / pak paths are auto-detected.',
    '过程可追溯：调用的命令、参数与输出完整落日志，支持复现与审计':
      'Traceable: every command, parameter and output is logged for reproduction and audit.',
    '可扩展：工具定义与调用命令由 catalog.json 声明，新增工具无需改动主程序':
      'Extensible: tools and their commands are declared in catalog.json; adding one needs no code change.',

    /* 侧栏与模块 */
    '工具': 'Tools', '主页': 'Home', 'AES 提取': 'AES Keys', '文本': 'Text',
    '绕签名': 'Signature', '解包': 'Unpack', '打包': 'Pack', '资产查看': 'Assets',
    '仓库': 'Repository', '开发中': 'WIP',
    '欢迎使用TI工具箱': 'Welcome to TI Toolbox',

    /* 通用按钮与状态 */
    '开始': 'Start', '停止': 'Stop', '就绪': 'Ready', '清空': 'Clear', '复制': 'Copy',
    '选择': 'Browse', '查找目录': 'Browse', '打开程序目录': 'Open folder',
    '启动': 'Launch', '已安装': 'Installed', '未安装': 'Missing', '默认': 'Default',
    '已收录': 'Collected', '展开': 'Expand', '收起': 'Collapse',
    '目标已保存': 'Target saved', '设置已保存': 'Settings saved', '保存失败': 'Save failed',
    '还没有收录，跑一次扫描试试': 'Nothing collected yet — run a scan first',

    /* 常用参数与任务标题 */
    'PAK 文件': 'PAK file', 'AES KEY（可选）': 'AES key (optional)', '解包目录': 'Output folder',
    '输入目录': 'Input folder', '输出 PAK': 'Output PAK', '挂载点': 'Mount point',
    'PAK 版本': 'PAK version', '压缩（可选）': 'Compression (optional)',
    'LOCRES 文件': 'LOCRES file', '输出 CSV': 'Output CSV', '输出目录': 'Output folder',
    '资产目录（解包后的 CONTENT）': 'Asset folder (unpacked CONTENT)',
    '资产路径（解包后的 CONTENT）': 'Asset folder (unpacked CONTENT)',
    '起始偏移（可空）': 'Start offset (optional)', '结束偏移（可空）': 'End offset (optional)',
    '覆盖已有文件（--force）': 'Overwrite existing files (--force)',
    '工具设置路径': 'Tool paths', '工具路径': 'Tool paths',
    '扫可执行文件': 'Scan executable', '扫代码立即数': 'Scan code immediates',
    '扫内存': 'Scan memory', '扫文本': 'Scan text', '解 DPAPI': 'Decrypt DPAPI',
    '校验 key': 'Verify key', '列出 pak 里的文件': 'List files in pak',
    'pak 头信息': 'pak header', '解包': 'Unpack', '普通 pak': 'Plain pak'
  };

  var TEXTS = new WeakMap();
  var ATTRS = new WeakMap();
  var MO = null, busy = false, pend = false;

  function key(t) { return (t || '').replace(/\s+/g, ' ').trim(); }

  function inLangBtn(node) {
    var p = node.parentElement;
    return !!(p && p.closest && p.closest('.theme-opt[data-lang]'));
  }

  function allText() {
    var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    var arr = [], n;
    while ((n = w.nextNode())) arr.push(n);
    return arr;
  }

  function applyText() {
    var arr = allText();
    for (var i = 0; i < arr.length; i++) {
      var node = arr[i];
      if (inLangBtn(node)) continue;
      var raw = node.nodeValue, k = key(raw);
      if (!k) continue;
      if (LANG === 'en') {
        var hit = EN[k];
        if (!hit) continue;
        if (!TEXTS.has(node)) TEXTS.set(node, raw);
        var lead = raw.match(/^\s*/)[0], trail = raw.match(/\s*$/)[0];
        node.nodeValue = lead + hit + trail;
      } else if (TEXTS.has(node)) {
        node.nodeValue = TEXTS.get(node);
      }
    }
  }

  function applyAttrs() {
    ['placeholder', 'title'].forEach(function (name) {
      document.querySelectorAll('[' + name + ']').forEach(function (el) {
        var k = key(el.getAttribute(name));
        var hit = EN[k];
        if (LANG === 'en') {
          if (!hit) return;
          if (!ATTRS.has(el)) ATTRS.set(el, {});
          var rec = ATTRS.get(el);
          if (rec[name] === undefined) rec[name] = el.getAttribute(name);
          el.setAttribute(name, hit);
        } else {
          var r = ATTRS.get(el);
          if (r && r[name] !== undefined) el.setAttribute(name, r[name]);
        }
      });
    });
  }

  function langButtons() {
    // 只认菜单里的语言按钮；绝不能用 document.querySelector('[data-lang]')，
    // 否则会命中 <html data-lang="zh"> 并把整页文本抹成「简体中文」。
    var btns = document.querySelectorAll('.theme-opt[data-lang]');
    for (var i = 0; i < btns.length; i++) {
      var b = btns[i];
      var code = b.getAttribute('data-lang');
      if (code === 'zh') b.textContent = (LANG === 'en') ? 'Chinese' : '简体中文';
      else if (code === 'en') b.textContent = 'English';
    }
  }

  function paint() {
    if (busy) { pend = true; return; }
    busy = true;
    if (MO) MO.disconnect();
    try {
      applyText();
      applyAttrs();
      langButtons();
    } finally {
      busy = false;
      if (LANG === 'en' && MO) MO.observe(document.body, { childList: true, subtree: true });
      if (pend) { pend = false; setTimeout(paint, 0); }
    }
  }

  function watch() {
    if (MO) { MO.observe(document.body, { childList: true, subtree: true }); return; }
    MO = new MutationObserver(function (recs) {
      for (var i = 0; i < recs.length; i++) {
        if (recs[i].type === 'childList' || recs[i].type === 'characterData') { paint(); return; }
      }
    });
    MO.observe(document.body, { childList: true, subtree: true });
  }

  window.I18N = {
    // 供 i18n.catalog.js 之类的外部字典追加条目
    extend: function (extra) {
      if (!extra) return;
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) EN[k] = extra[k];
      }
      paint();
    },
    apply: function (l) {
      LANG = (l === 'en') ? 'en' : 'zh';
      // 只把语言记在 <html data-i18n>；不要用 data-lang，否则任何
      // closest('[data-lang]') 都会命中根节点，把整页文本判成“语言按钮”。
      try { document.documentElement.setAttribute('data-i18n', LANG); } catch (e) {}
      if (LANG === 'en') watch(); else if (MO) MO.disconnect();
      paint();
    },
    retranslate: paint,
    lang: function () { return LANG; }
  };
})();
