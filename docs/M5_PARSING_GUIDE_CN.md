# M5 PDF 解析与分块持续事实指南

最后更新：2026-08-15

## 使用规则

这是面向仓库所有者的中文持续事实记录。后续更新只能按 `M5-Fxxx` 顺序
追加，不覆盖、不复用旧编号；如果旧结论后来被推翻，新增一条更正记录并
引用原编号。记录中的“已实现”必须同时有代码路径和测试或本地运行证据。

## 当前阶段

- 活跃里程碑：M5 第一阶段，文本层 parsing、parent-child chunking 与图表
  存在性概况。
- 分支：`feature/pdf-parsing`，从合并 M2 PR #4 后的最新 `main` 创建。
- 当前不做：扫描件 OCR、表格单元格最终结构化、图中曲线/柱形数字化、
  LLM 图像理解、Docling 模型下载。
- 为什么先解析后 Gold：parser 或 chunk 边界变化会改变 block ID。先冻结
  parser 版本再人工标注，可以避免无意义的 Gold 迁移。

## 顺序事实记录

### M5-F001 — 找回 15 篇本地语料且隔离 Gold

- 15 篇 PDF 原件仍位于本机 `proj_rsdata` 的不同目录，没有被删除。
- 本轮只在 `/private/tmp/ecoevidence-corpus15-20260815` 创建 15 个只读符号
  链接，不复制或提交论文。
- 新实验库是被 Git 忽略的 `data/ecoevidence-corpus15.sqlite3`，开始解析前
  Gold 数为 0；旧归档库的 11 条 Gold 保持原样。
- 如何理解：PDF 目录决定“本次扫描哪些文件”，SQLite 决定“这些文件的
  解析、检索和人工状态写到哪里”。工作台只出现一篇，是运行配置指向公开
  Demo，不代表其他论文被删除。

### M5-F002 — parser v1 的真实失败原因

- 旧版以 `extract_text_lines(layout=True)` 的返回顺序为主，再按垂直间距、
  栏跳转和字符数合并。
- 在真实中文双栏论文中，同一视觉行的左右栏可能被合成一条文本，形成
  “左栏半句 + 右栏半句”的交错证据；科学下标也会成为单独的 `10` 或 `2`
  block。
- 旧 15 篇当前运行产生 3,638 个扁平 block；其中一篇无可靠 text layer。
- 如何深入：先查看 PDF 中一个目标段落的 bbox 和行坐标，再比较数据库按
  `ordinal` 排列的文本。仅查看最终全文字符串很难区分是 PDF 字符映射错误、
  行重建错误还是栏排序错误。

### M5-F003 — `pdfplumber-reading-order-v2`

- 新 parser 从定位单词重建行，使用更宽的垂直容差吸收 `CO2`、`Q10` 等
  上下标，再按页面中缝的真实间隙分离双栏。
- 阅读顺序为栏内从上到下、左栏后右栏；全宽标题、摘要标题和 caption
  作为锚点。跨页重复的顶部/底部文本在构造证据前移除。
- 规范化文本会处理 Unicode 兼容字符、不可见控制符、英文跨行断词、中文
  跨行和常见科学下标空格；`raw_text` 仍保留原始行，避免规范化覆盖来源。
- 合成双栏 PDF 的端到端测试断言经纬度 `23.50 N, 101.25 E` 保持在同一
  连贯证据中，并且左栏 Methods 先于右栏 Results。
- 如何改动：栏判断和行合并是两层独立逻辑。误跨栏应调 `_line_records()` /
  `_order_lines()`；同一栏过碎或误合并应调 `_merge_lines()`，不要用一个
  更大的最大字符数掩盖栏排序问题。

### M5-F004 — parent-child retrieval 的实际语义

- parser 先保存完整父段，再将超过 680 字符的父段拆成目标约 480 字符的
  child，并保留最多一个短句的重叠。
- BM25、hashing 和 E5 都只对 child 排序；API 的每个 hit 同时返回完整
  `parent_context` 和同父段 `context_block_ids`。
- Gold 仍标在命中的 child block 上。父段只是阅读上下文，不能替代精确
  证据引用。
- 检索参数记录 `parent-child-480char-v1`，parser 变化会形成新的 embedding
  cache key，不会复用旧 block 向量。
- 如何改动：目标长度越短，精确匹配通常越好但上下文不足、向量数更多；
  越长则语义更完整但主题混杂。应通过人工 Gold 的 Hit@K/MRR 与延迟共同
  决定，而不是只看 chunk 数量。

### M5-F005 — 图表概况不是图表数字化

- `visual_assets` 保存 `figure/table/image` 候选的页码、caption、bbox、检测
  方法、置信度、是否检测到表格结构、待数字化状态和 parser 版本。
- 当前信号来自 caption 文本、PDF 表格边界和嵌入图像对象。它能够回答
  “可能有没有、在哪一页、标题是什么”，不能回答图中曲线的精确数值。
- 无 caption 的矢量图可能漏检；复杂页面线框可能产生表格误报。因此网页
  使用“候选”“待核对”，不把计数写成经过人工验证的事实。
- 后续正确顺序是：人工确认资产存在 → 表格 cell/图例/坐标轴结构 → 数字
  提取 → 回链 bbox → 人工验证。

### M5-F006 — 15 篇本地回归结果

- 数据集：本机找回的固定 15 篇树干呼吸相关 PDF；不提交原件。
- 结果：14 篇 text-layer 解析成功，`51Ryan_1989.pdf` 仍因无可靠文字层
  失败并明确需要 OCR。
- parser v2 调整后得到 2,974 个 child block、2,408 个父段和 162 个图表/
  图像候选；15 篇累计解析耗时约 24.8 秒。本数字只描述这台机器和该私有
  语料，不是公开性能基准。
- 实例：旧输出把江西论文第 2 页的站点坐标和右栏数据分析交错；新输出把
  `115°04'E, 26°44'N` 保留在独立、连贯的“试验地概况”父段中。英文摘要
  的 `valuesofstemrespiration` 被恢复为有空格的词序。
- 仍存在的失败：部分旧中文 PDF 自带异常字符映射和词内空格；这些不是仅
  靠几何排序就能完全修复，需要对比 Docling 或 OCR。

### M5-F007 — Gold 与数据安全保护

- 旧数据库保存文档时会先删除全部 block；SQLite 外键可能连带删除 Gold。
- 新实现先比较已有 Gold block ID 与新 parser 输出。如果任何人工引用无法
  保留，整个事务拒绝覆盖，并提示需要显式迁移。
- 无 Gold 的新实验库可以正常升级；已有 Gold 的库不会被静默重建。
- 如何理解：parser 输出是机器派生数据，Gold 是人工事实。机器派生数据的
  更新不能自动消灭人工事实，即使数据库外键允许级联删除。

### M5-F008 — Docling 的依赖边界

- 本轮没有把 Docling 加入默认依赖，也没有声称已经运行 Docling。
- 原因不是否定 Docling，而是其 PDF pipeline 需要模型 artifacts，不同模型
  还有许可、下载体积、CPU/MPS 支持和离线缓存差异。
- 下一实验应把相同页面分别交给 parser v2 和固定 Docling 版本，只比较
  阅读顺序、表格/图检测、解析成功率和耗时；确认增益后再加入可选 extra。
- 自动测试继续使用合成 PDF，不下载模型、不需要密钥或付费 API。

### M5-F009 — 参考文献 hard-negative 降权

- 真实浏览器验收发现：解析顺序改善后，首篇论文的 Top 3 仍有两条来自
  references，因为引用标题会高密度重复 `stem respiration`。
- 这类 block 是检索 hard negative：字面和 embedding 都可能很相似，但不
  是支持字段值的原始研究证据。
- `hybrid-parent-context-v6` 对 `references` 最终得分乘以 0.25，并在
  `score_components.reference_multiplier` 和 retrieval parameters 中公开，
  不做不可见过滤。Methods/Results 中的证据仍可正常竞争排名。
- 如何改动：降权值应由 Gold 失败案例校准。完全删除 references 会掩盖
  parser 分节错误，而保留可审计乘数能让误分类在 UI 中被发现。

### M5-F010 — 最终本地重建修正 M5-F006

- M5-F006 记录的是第一次通过阅读顺序回归后的中间结果；随后科学表达
  规范化增加了控制字符替换、`Q10` / `CO2` / `n=12` 复原，并修复同页多个
  图像只关联到第一个 caption 的问题。
- 最终冻结结果仍为 2,974 个 child block，但父段是 2,407 个，图表/图像
  候选是 175 个，累计约 24.9 秒；状态为 8 usable、6 relative、1 failed。
- 候选从 162 增至 175 不代表召回率提高，只表示同页多个 PDF 图像对象不再
  被相互覆盖。准确率仍需后续人工确认。
- 后续引用本地回归数量时应使用本条，不再使用 M5-F006 的中间父段和资产
  数量。

### M5-F011 — 整页扫描图像也属于视觉概况

- `51Ryan_1989.pdf` 的 10 页各包含一个覆盖整页的 PDF 图像对象，但没有
  可靠 text layer。此前大图过滤会让 UI 错误显示“0 图像”。
- parser 现在只在该页无文本父段时，将覆盖超过 90% 页面面积的对象记录为
  `full-page-image-scan-candidate`，摘要明确标记“需要 OCR”。
- 这 10 项加入后，最终本地视觉候选总数为 185；M5-F010 的 175 是加入扫描
  页识别前的中间值，其余最终数字不变。
- 该状态只证明“页面是图像”，不证明页面里有数据图，也不会让扫描件进入
  text retrieval。

### M5-F012 — 深入理解 Docling 的官方材料

- 包与许可入口：<https://pypi.org/project/docling/>。代码许可和模型许可要
  分开核对，不能只看到 Python 包是 MIT 就推断全部模型相同。
- 离线 artifacts：<https://github.com/docling-project/docling/blob/main/docs/faq/index.md>。
  重点理解模型权重如何预下载，以及 `artifacts_path` 如何阻止运行时联网。
- 模型目录：<https://github.com/docling-project/docling/blob/main/docs/usage/model_catalog.md>。
  对比 layout、TableFormer、图片分类和 OCR 分别解决什么问题，以及 CPU、
  MPS、CUDA 支持差异。
- 建议阅读方法：先把 Docling 看成“多个可组合模型的解析 pipeline”，而非
  单一 PDF 文本库；每启用一个模块都应记录版本、artifact、许可、耗时和
  失败降级。

### M5-F013 — 最终真实浏览器验收

- 本地工作台第 02 步实际显示 15 篇论文，状态为 8 usable、6 relative、
  0 nodata、1 failed；每篇已解析论文都显示 parser 身份、耗时、child 数、
  父段数以及可展开的图表候选。
- `51Ryan_1989.pdf` 现在显示 10 个图/图像候选，对应 10 个无可靠文字层的
  整页扫描页；它仍明确标记为解析失败和需要 OCR，不会混入文本检索。
- 第 03 步的论文选择器包含全部 15 篇，Gold 标注入口可用；本次验收前新
  实验库仍为 0 条 Gold，等待人工判断，不沿用旧 parser 下的标签。
- 浏览器控制台没有 warning 或 error。工作台最终停留在“03 · 证据召回
  审计”，便于下一步直接运行 BM25/hashing/E5 对比并标注 Gold。

### M5-F014 — 远端发布状态

- 实现提交为 `10c645e feat: improve PDF parsing and hierarchical chunks`，
  已推送到 `feature/pdf-parsing`，没有直接修改 `main`。
- GitHub Draft PR 为
  <https://github.com/ZhangHan200005/EcoData_Extraction/pull/5>，目标分支是
  `main`，创建时 GitHub 报告可合并；仍需 CI 通过和人工审查后才应合并。
- PR 保持 Draft，不删除功能分支。本条仅记录发布状态，不把 M5 标记为
  Completed；OCR、表格 cell 结构和可选 Docling 对照仍是后续范围。

### M5-F015 — 首轮远端 CI 结果

- Draft PR #5 的 GitHub Actions `CI` run #28 已在提交 `bf121b7` 上完成，
  结论为 success。
- 发布前本地验证也保持通过：ESLint、30 个后端测试、前端生产构建、2 个
  rendered-page tests 和 `git diff --check`。
- 这证明当前垂直切片满足仓库自动化验收；它不证明视觉候选准确率或检索
  效果已经达到目标，这两项仍需人工 Gold 与后续量化评估。

### M5-F016 — 为什么 E5 对比列显示不可用

- 三路对比中的 E5 列不是 hashing 的别名；选择 E5 后系统必须找到固定版本
  的 `sentence-transformers`、`transformers` 和 `torch`，否则明确返回
  unavailable，不允许静默退回 hashing。
- 当前 `.venv` 是默认轻量安装，只包含 BM25/hashing 所需依赖，所以网页
  正确显示 neural extra 未安装。M2 的“已实现”表示代码路径、固定版本、
  离线测试和可选安装方式存在，不表示每台开发机已下载约 470 MB 模型。
- 启用方式仍是 `.venv/bin/python -m pip install -e ".[neural]"`，随后首次
  加载固定 E5 revision。该动作涉及大型模型下载，本轮没有擅自执行。
- BM25 和 hashing 的结果仍是真实运行结果；E5 unavailable 是一项运行时
  状态，不是第三个伪造分数。

### M5-F017 — 文本 Gold 与视觉 Gold 必须分开

- 文本 Gold 引用 `block_id`，用于评价文本 child retrieval 的 Hit@K、
  Recall@K、Precision@K 和 MRR。
- 视觉标注引用 `asset_id`，按 `(document_id, field_name, asset_id)` 保存，
  可取 `relevant`、`not_relevant` 或 `uncertain`；只有 verified relevant
  才称为视觉相关 Gold。
- 当前文本检索器不排序 visual asset，因此视觉 Gold 不进入文本 Recall
  分母。把两种 Gold 合并会错误惩罚一个根本没有机会返回图表资产的检索器。
- 重解析现在增量 upsert visual asset；如果新 parser 会让已标注 asset ID
  消失，整个事务拒绝覆盖，与文本 Gold 采用相同的数据安全原则。

### M5-F018 — 视觉 Gold 网页操作与验收

- 第 03 步新增“图表证据独立标注”，可按图、表格、图像/扫描页过滤当前
  论文的视觉候选，并针对当前字段选择相关 Gold、无关或待定，也可清除。
- 每张卡展示页码、候选置信度、caption/summary、检测方法、bbox 和 parser
  版本；“查看 PDF 第 N 页”打开数据库已登记的源 PDF 对应页，避免只根据
  caption 猜测内容。
- 真实 15 篇工作台完成一次“相关 Gold → 保存 → 清除”往返；计数从 0 变 1
  再回到 0，PDF 第 3 页链接实际打开，浏览器控制台无 warning/error。
- 验收结束后本地实验库仍是 0 条文本 Gold、0 条视觉标注，不留下机器测试
  标签干扰后续人工判断。

### M5-F019 — 视觉 Gold 远端发布状态

- 功能提交为 `7ca2373 feat: add visual evidence Gold annotations`，已推送到
  `feature/pdf-parsing`，没有直接修改 `main`。
- Draft PR #5 已更新为“improve PDF parsing and visual evidence review”，
  仍以 `main` 为目标并保持 Draft：
  <https://github.com/ZhangHan200005/EcoData_Extraction/pull/5>。
- GitHub Actions CI run #32 已在该功能提交上完成，结论为 success；本地
  对应验证为 34 个后端测试、前端生产构建、2 个页面测试和 lint 全部通过。
- E5 neural extra 本轮没有安装或下载；视觉标注功能及自动测试不依赖模型、
  付费 API 或密钥。

### M5-F020 — neural 安装失败的真实原因与安全恢复

- 用户运行 `.venv/bin/python -m pip install -e ".[neural]"` 时，项目元数据
  报告 Python `3.9.6 not in '>=3.10'`。原因是 `.venv` 由 Python 3.9.6
  创建；虚拟环境绑定创建时的解释器，后来安装新 Python 不会原地升级它。
- 本机 `/usr/bin/python3` 也是 3.9.6；Homebrew 已有 Python 3.13.13。直接
  对 Homebrew Python 安装被 PEP 668 正确阻止，因此没有使用会污染受管理
  解释器的 `--break-system-packages`。
- 先在临时 Python 3.13 venv 中执行 neural extra 的 dependency dry-run，
  确认固定 `torch 2.13.0` 存在原生 macOS arm64 / CPython 3.13 wheel 后，
  才迁移正式环境。
- 旧环境没有删除，而是移动为 `.venv-py39-backup-20260816`；新 `.venv`
  使用 Python 3.13.13 重建。`.gitignore` 和 ESLint 均忽略 `.venv*`，避免
  恢复备份被误提交，也避免 lint 扫描 Torch 等依赖自带的 JavaScript。
  该操作没有修改论文、SQLite 数据库、Gold 或 Git 分支历史。

### M5-F021 — E5 本机运行时与真实三路对比

- 新 `.venv` 已安装并核对固定版本：`sentence-transformers 5.5.1`、
  `transformers 5.15.0`、`torch 2.13.0`；固定模型是
  `intfloat/multilingual-e5-small` revision
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`。运行时使用
  `ECODATA_MODEL_LOCAL_FILES_ONLY=1`，复用已存在的约 470 MB 本地缓存，
  没有付费 API 或密钥。
- 对 15 篇语料中的江西湿地松论文、字段 `stem_respiration_rate`、Top 5
  执行真实三路比较。首次 E5 对 88 个 child block 编码并写入 88 个缓存，
  记录 35,284.5 ms；同一查询第二次 88/88 缓存命中，记录 67.5 ms。
  这些是本机单次观测，不是跨机器性能基准。
- 工作台第 03 步再次实测 Top 8：BM25-only、hashing hybrid、E5 hybrid
  均显示“可运行”；该次热缓存页面分别记录约 9.1 ms、28.3 ms、45.4 ms，
  E5 卡片显示完整 backend/model/version。15 篇论文选择器和独立视觉 Gold
  区域均保持可用。
- 当前没有人工文本 Gold，因此页面的 Hit@K、Recall@K 和 Gold 首位仍显示
  未标注；耗时和排名是真实结果，但不能据此宣称 E5 的检索质量优于基线。
  质量结论必须等待同一批人工 Gold 后再比较。

### M5-F022 — 如何理解和调整 neural 本地环境

- `.venv` 约 1.0 GB，旧 Python 3.9 备份约 70 MB，模型缓存约 470 MB；三者
  角色不同：venv 放运行依赖，备份用于可恢复迁移，`data/models` 放固定
  权重。不要把任一目录提交到 Git。
- 遇到 neural 不可用时按顺序检查：`.venv/bin/python --version`，三个包的
  精确版本，`/api/health` 中 `retrieval_backend_runtime.ready`，最后才运行
  页面比较。这样能区分“解释器不兼容”“依赖未安装”“模型未缓存”和
  “检索请求失败”。
- 需要改模型或依赖版本时，应同时更新 `pyproject.toml` 的固定依赖、backend
  的 model/revision 元数据、运行时兼容检查、缓存身份、测试和本指南；只换
  模型名会让旧向量与新向量的来源不可审计。
