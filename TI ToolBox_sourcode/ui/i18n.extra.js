/* TI Toolbox — 补齐遗漏文案的英文字典（V1.1.2）
   与 i18n.catalog.js 同样的做法：键是完整中文原文，I18N.extend 合并后立即重译。
   覆盖：DUMP / 资产查看 / LOCRES / 侧栏副标题 / 语言按钮 等此前漏翻的界面文案。 */
(function () {
  if (!window.I18N || !window.I18N.extend) return;

  window.I18N.extend({
    /* ---- DUMP 面板 ---- */
    'Dumper-7.dll 路径': 'Dumper-7.dll path',
    'jmap_dumper 路径（备用）': 'jmap_dumper path (fallback)',
    '留空 = 工具自己的默认位置': 'Empty = the tool default location',
    '注入前等待（秒）': 'Wait before injecting (s)',
    '0 = 选完立刻注入': '0 = inject right after selection',
    '目标进程': 'Target process',
    '点「刷新」列出进程': 'Click Refresh to list processes',
    '注入 DLL': 'Inject DLL',
    '启动 Dumper': 'Launch Dumper',
    '快速换 mapping': 'Quick mapping',
    '（未选 .usmap）': '(no .usmap selected)',

    /* ---- 侧栏 / 模块副标题 ---- */
    ' · 开发中': ' · WIP',
    'v0.1 · 开发中': 'v0.1 · WIP',

    /* ---- 工具路径面板 ---- */
    'UAssetGUI 路径': 'UAssetGUI path',
    'FModel 路径': 'FModel path',
    'Mapping（.usmap）': 'Mapping (.usmap)',
    '例如 F:\\模型\\UAssetGUI.exe': 'e.g. F:\\Model\\UAssetGUI.exe',
    '例如 F:\\模型\\UEHanHua\\FModel\\FModel.exe': 'e.g. F:\\Model\\UEHanHua\\FModel\\FModel.exe',
    '例如 F:\\模型\\Dumper-7.dll': 'e.g. F:\\Model\\Dumper-7.dll',
    '例如 …\\jmap_dumper.exe': 'e.g. …\\jmap_dumper.exe',
    '选填；UAssetGUI 打开映射时要用': 'Optional; used when UAssetGUI opens the mapping',
    '手动指定 FModel 用的 .usmap': 'Pick the .usmap used by FModel',
    '开发中 · 先走 UE4 通道': 'WIP · UE4 channel only for now',
    '这个工具还在路上。': 'This tool is still on the way.',
    '状态': 'Status', '可用': 'Ready', '已设置': 'Set',
    '解析失败': 'Parse failed', '未标注': 'Unlabelled',

    /* ---- 资产查看 / LOCRES ---- */
    '可直接 Ctrl+V 粘贴路径': 'Paste a path with Ctrl+V',
    '在上方填写或选择「资产路径」（解包后的 Content 目录）。':
      'Fill in or pick the asset folder above (the unpacked Content directory).',
    '该路径下没有 .uasset / .umap / .uexp。':
      'No .uasset / .umap / .uexp under that path.',
    '正在读取…': 'Reading…', '正在解析…': 'Parsing…',
    '读取失败': 'Read failed', '读取失败：': 'Read failed: ',
    '该文件没有条目。': 'This file has no entries.',
    '选择一个 .locres 文件后点「查看」。': 'Pick a .locres file, then click View.',

    /* ---- 更新日志卡片 ---- */
    '（还没有更新日志，写 changelog.md 放在 exe 旁边即可）':
      '(No changelog yet — put changelog.md next to the exe.)',

    /* ---- 顶部与语言 ---- */
    '更新计划': 'Update plan',
    '简体中文': 'Chinese',
    '放一堆 .usmap 的目录，例如 E:\\model\\mapping':
      'A folder full of .usmap files, e.g. E:\\model\\mapping',
    '支持我': 'Support me',

    /* ---- catalog.json 里未覆盖的说明 ---- */
    'dump 目录（空 = <游戏目录>\\mem）': 'Dump folder (empty = <game>\\mem)',
    '例如 Content\\GameCode\\UI': 'e.g. Content\\GameCode\\UI',
    '后续从 GitHub 拉取工具清单，安装至 tools\\ 并自动生成入口。':
      'Will pull the tool list from GitHub later, install into tools\\ and create entries automatically.',
    '在进程内存转储中检索明文密钥；需先将转储放入工具目录的 mem\\。':
      'Searches a process memory dump for plaintext keys; put the dump into mem\\ of the tool folder first.'
  });
})();
