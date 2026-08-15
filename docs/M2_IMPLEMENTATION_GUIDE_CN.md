# M2 中文实施与学习指南（持续更新）

最后更新：2026-08-15

记录规则：从 `M2-F001` 开始，事实账本只在末尾追加新的连续编号，已写入条目不覆盖、不重排。若旧条目后来发现错误，新增“更正”条目并引用原编号，而不是改写历史。前面的教程章节可以随代码演进修正，但实施轨迹以第 8 节账本为准。

## 1. 这份文档的用途

这是一份随 M2 实施持续更新的本地说明文档。它回答四个问题：

1. 这轮具体改了什么；
2. 为什么使用这些技术方法；
3. 你可以从哪里开始阅读、调试和修改；
4. M2 距离整体完成还有多远。

公开能力状态以 [ROADMAP.md](ROADMAP.md) 为准。本文件更偏向实现过程、学习路径和设计推理，不把计划中的功能描述成已经完成。

## 2. M2 建档时进度快照（保留，不覆盖）

下表是本文件建立时的快照，刻意保留当时状态。当前进度请读取第 8 节编号最大的事实条目。

| 子任务 | 状态 | 可验证证据 |
| --- | --- | --- |
| 可替换的 Embedding backend 契约 | 已完成 | `backend/retrieval.py` 中的 `EmbeddingBackend` |
| hashing baseline 保留为默认对照 | 已完成 | `HashingEmbeddingBackend` 及原有 0.45/0.35/0.15/0.05 权重 |
| backend/model/version/参数/耗时审计 | 已完成 | API response、`retrieval_runs`、evaluation report |
| 多字段离线比较 fixture | 已完成 | `synthetic-retrieval-comparison-v1` |
| stale-safe SQLite 向量缓存 | 已完成 | `embedding_vectors`、批量 cache 协议和专项测试 |
| 真实神经 Embedding backend | 等待模型依赖决策 | 尚未选择或下载模型 |
| baseline 与真实神经模型比较 | 未开始 | 必须复用冻结 Gold 查询集 |

整体判断：M2 处于 **In progress**。当前已经有“可比较的接口和实验仪表”以及“可安全复用的向量存储”，下一步是确认真实模型和运行时依赖，然后进行 baseline 对比实测。

## 3. 变更日志

### 2026-08-15：第二切片开始——持久化向量缓存

已完成：

- 用文档哈希、block ID、规范化文本哈希、backend/model/version 共同标识一个向量；
- 在 SQLite 中缓存证据块向量，查询向量仍按请求实时生成；
- 文本、模型版本或维度变化时自动 cache miss，不静默复用旧向量；
- 在 retrieval/evaluation/API/UI 中显示 cache hit、miss 和写入数量；
- 使用完全离线测试证明冷缓存、热缓存和失效行为。

实施中发现逐 block 打开 SQLite 连接会让微型 fixture 也产生明显连接开销，因此最终协议改为批量读取和 `executemany` 写入。测试不使用脆弱的“必须快于多少毫秒”断言，而是验证 encode 次数、hit/miss/write 和排名一致性。

### 2026-08-15：第一切片——版本化 backend 契约

已完成：

- 把原来写死在 `EvidenceRetriever` 中的 hashing 编码器改成可注入接口；
- 显式记录 backend、backend version、model、model version、维度和是否为神经模型；
- 保存 retrieval 参数、查询数、语料规模和耗时；
- 增加三字段、四证据块的合成比较 fixture；
- 增加可复现报告命令：

```bash
.venv/bin/python -m backend_tests.run_retrieval_fixture
```

## 4. 本轮使用的新知识与方法

### 4.1 Cache key 不是“模型名”这么简单

如果只用 `block_id + model` 作为缓存键，下面任一变化都可能错误复用旧向量：

- 同一 block 的规范化文本发生变化；
- backend 实现修复了分词或 pooling；
- 模型名称相同但 revision/version 不同；
- 输出维度或归一化方式变化。

因此本轮采用组合身份：

```text
document_sha256
+ block_id
+ normalized_text_sha256
+ backend + backend_version
+ model + model_version
+ dimensions
+ embedding_parameters_sha256
+ cache_key_version
```

这叫做 **content-addressed / version-addressed caching**：缓存是否可用由输入内容和处理版本共同决定，而不是依赖人工记得清缓存。

### 4.2 依赖倒置：检索算法不应该知道 SQLite 细节

`EvidenceRetriever` 只依赖一个很小的批量向量缓存协议，例如“按一组键读取”和“保存一组向量”。SQLite 的 SQL 细节仍留在 `database.py`。这样做的好处是：

- 单元测试可以换成内存 fake；
- 后续可以替换为专用向量库而不重写排序逻辑；
- 没有缓存时仍可运行，baseline 不被破坏。

### 4.3 冷缓存和热缓存必须分别测量

- 冷缓存：第一次运行，需要为全部 block 编码并写入；
- 热缓存：第二次运行，block 向量全部复用；
- 查询向量：每次查询不同，仍实时编码；
- 失效测试：修改文本或模型版本后，应再次编码而不是命中旧值。

只测试“结果排名正确”不足以证明缓存安全；还要断言 encode 次数和 hit/miss 计数。

### 4.4 向量缓存不等于 ANN 向量数据库

当前 SQLite 表解决的是“避免重复生成 block 向量”，排序时仍对当前文档的全部 block 做精确余弦计算。它不是 FAISS、HNSW 或托管向量数据库。对当前单文档审核流程，这让实现可解释、依赖小、测试稳定；只有在语料规模和延迟测量证明精确扫描成为瓶颈后，才应引入近似最近邻索引。SQLite 中的向量暂以 JSON 保存，也应在代表性规模下测量体积后再决定是否改成 BLOB。

## 5. 如何深入理解现有代码

建议按调用链阅读：

```text
app/page.tsx
  -> backend/api.py
  -> backend/services.py
  -> backend/retrieval.py
  -> backend/database.py
  -> backend/evaluation.py
```

重点入口：

- `backend/retrieval.py`
  - `EmbeddingBackend`：向量 backend 必须满足的接口；
  - `HashingEmbeddingBackend`：当前离线 baseline；
  - `EvidenceRetriever.rank()`：BM25、向量相似度和规则特征的组合排序。
- `backend/embedding_backends.py`
  - `MultilingualE5SmallEmbeddingBackend`：固定模型、运行时版本、前缀和批量推理；
  - `build_embedding_backend()`：把配置名称转换为明确 backend，不做静默回退。
- `backend/database.py`
  - `SCHEMA`：SQLite 表结构；
  - `initialize_database()`：只增列/增表迁移；
  - `get_embedding_vectors()` / `save_embedding_vectors()`：批量读取和写入缓存；
  - `save_retrieval_run()`：检索审计记录。
- `backend/evaluation.py`
  - `RetrievalEvaluator.evaluate()`：按 `(document_id, field_name)` 聚合 Gold 并计算指标。
- `backend_tests/test_retrieval_evaluation.py`
  - 排序、持久化、迁移、冷/热缓存失效和比较 fixture 的主要回归测试。

## 6. 你可以怎样修改和实验

### 修改混合权重

在 `RetrievalWeights` 中修改四个权重，保持非负且总和为 1，然后提升 `settings.retrieval_version`：

```text
bm25 + vector_similarity + term_coverage + section_prior = 1.0
```

### 实现新的 Embedding backend

新 backend 至少要实现：

```python
metadata -> RetrievalBackendMetadata
parameters -> dict[str, Any]
runtime_status -> dict[str, Any]
encode_query(text: str) -> list[float]
encode_passages(texts: list[str]) -> list[list[float]]
```

输出长度必须与 `metadata.dimensions` 一致。模型或预处理行为变化时必须提升对应版本，不能只改代码不改版本。

### 查看本地缓存

运行过至少一次检索后，可以只读检查缓存身份和数量：

```bash
sqlite3 data/ecoevidence.sqlite3 \
  "SELECT retrieval_backend, embedding_model, model_version, dimensions, COUNT(*) FROM embedding_vectors GROUP BY 1,2,3,4;"
```

旧版本产生但已经不可达的向量不会自动删除。这是刻意的安全边界：增加垃圾回收前必须先定义精确范围、预览和恢复方式，不能把缓存清理扩展成用户数据删除。

### 运行验证

```bash
npm run lint
npm run test:backend
npm test
git diff --check
```

## 7. 历史决策点（已在 `M2-F003` 确认）

真实神经模型会带来模型下载、运行时依赖、许可证、隐私和资源占用问题。接入前需要至少比较：

- 中英文与生态学术语覆盖；
- 模型许可证和模型卡完整性；
- 下载体积、内存、CPU 延迟；
- 是否完全本地运行、是否产生外部数据传输；
- Python 3.9 与当前 CI 环境兼容性。

在这些信息被记录并由用户确认前，M2 不会把测试 fake 伪装成真实神经模型，也不会声称神经检索带来质量提升。

### 2026-08-15 候选模型调研

以下信息来自模型作者和运行库的官方页面，记录的是决策输入，不代表已经安装：

| 候选 | 许可证/语言 | 向量与权重 | 适配判断 |
| --- | --- | --- | --- |
| [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) | MIT；模型页标注 94 languages | hidden size 384；safetensors 约 471 MB | 面向检索，适合中英文 query/passage 对比，优先候选 |
| [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) | Apache-2.0；50 languages | 384 维；safetensors 约 471 MB；max sequence length 128 | 通用语义相似度，接入简单，但不是专门检索目标 |
| [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT；multilingual | 1024 维、8192 tokens；safetensors 约 2.27 GB | 能力更广，但对本地 Demo 和 CI 明显偏重 |

当前建议先实验 `multilingual-e5-small`，固定具体模型 revision，分别对 query 和 passage 执行模型要求的预处理，并保持 hashing baseline。重大代价是约 471 MB 模型权重，以及 Sentence Transformers/PyTorch 运行时。[Sentence Transformers 官方安装说明](https://sbert.net/docs/installation.html)当前推荐 Python 3.10+，而本仓库本地验证环境仍是 Python 3.9.6，因此还需要决定：

1. 将项目最低 Python 版本提升到 3.10，并使用标准 Sentence Transformers/PyTorch；或
2. 保留 Python 3.9 公开基线，另行验证一个固定旧版依赖或 ONNX CPU 路径。

未确认前不会修改 Python 版本、下载模型或加入大型依赖。

## 8. 追加式事实账本

### M2-F001 — 版本化 backend 契约

- 时间：2026-08-15
- 状态：已完成并提交，commit `70b03fe`
- 事实：hashing 编码器从排序器内部实现变成可替换 backend；检索响应和评估开始记录 backend、model、version、参数与耗时。
- 验证：离线 deterministic fixture 与 hashing 使用相同 Gold 查询和混合权重。
- 深入理解：先固定比较接口和测量口径，再引入大型模型，才能区分“模型收益”和“实验管线变化”。

### M2-F002 — stale-safe 持久化向量缓存

- 时间：2026-08-15
- 状态：已完成并提交，commit `fcc2ed5`
- 事实：SQLite 按文档、文本、backend/model 版本、维度和参数哈希缓存 block 向量；冷/热缓存和多种失效条件均有离线测试。
- 验证：Draft PR #4 的 CI #15 通过；缓存测试覆盖文档、文本、模型版本和参数变化。
- 深入理解：缓存正确性不是“能读回来”，而是任何会改变向量的输入或处理版本都不能误命中旧结果。

### M2-F003 — 模型和 Python 方案获确认

- 时间：2026-08-15
- 状态：用户已确认
- 事实：选择将最低 Python 提升到 3.10，使用标准 Sentence Transformers/PyTorch，并以 `multilingual-e5-small` 作为首个真实本地模型。
- 安全边界：自动测试不下载模型；hashing 保持默认；模型权重不提交 Git；没有付费 API 或密钥要求。
- 深入理解：这是依赖、许可证、磁盘和运行时都会变化的决策，所以必须先确认再实施。

### M2-F004 — pinned E5 backend 与批量编码

- 时间：2026-08-15
- 状态：已实现，等待本轮最终提交
- 事实：模型固定为 `intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3`；运行时固定为 Sentence Transformers 5.5.1、Transformers 5.15.0、PyTorch 2.13.0。
- 事实：query 使用 `query: `，证据块使用 `passage: `；冷 block 一次批量编码，输出 L2 归一化；模型延迟加载。
- 配置：`ECODATA_RETRIEVAL_BACKEND=multilingual-e5-small` 显式启用；`ECODATA_MODEL_LOCAL_FILES_ONLY=1` 禁止后续模型网络访问。
- 修改入口：模型身份和加载行为在 `backend/embedding_backends.py`；backend 选择、batch、device 和缓存目录在 `backend/settings.py`。
- 深入理解：E5 是非对称检索模型，query/passage 前缀属于模型契约；遗漏前缀不是小参数差异，而是会改变 embedding 语义的版本变化。

### M2-F005 — 首次真实模型冻结 fixture 结果

- 时间：2026-08-15T16:53:01Z
- 状态：本地运行完成，结果已写入 `docs/M2_RETRIEVAL_EVALUATION.md`
- 环境：Python 3.13.13、Apple Silicon CPU、本地缓存模式；模型缓存 470 MB、28 个文件，位于 Git 忽略的 `data/models/`。
- 数据：`synthetic-retrieval-comparison-v1`，1 个合成文档、4 个 block、3 个查询、每查询 1 个 verified Gold。
- 结果：hashing 和真实 E5 的 Hit@1、Recall@1、MRR 都是 1.0；没有观察到可声称的神经质量提升。
- E5 耗时：总检索 5160.129207 ms；首个冷查询含模型初始化和 4 个 passage 编码，为 5132.370791 ms；后两个 query 在 block 向量热缓存下分别为 13.743916 ms 和 14.0145 ms。
- 缓存：首查询 4 miss/4 write，后两查询合计 8 hit；缓存身份记录完整模型和运行时参数。
- 深入理解：微型 fixture 的满分主要证明“路径和指标工作正常”。要判断模型是否更好，下一数据任务必须加入跨论文、中英文改写、术语同义表达和 hard negatives。
- 整体位置：M2 核心真实路径已具备；本轮还需完成全套测试、diff 审查、提交、PR 更新和远端 CI。

### M2-F006 — 双运行时本地验收与 SQLite 资源修复

- 时间：2026-08-15
- 状态：本地验收完成，等待提交和远端 CI
- 事实：现有轻量 `.venv` 在不安装 neural extra、不下载模型的情况下通过 19 项后端测试；独立 Python 3.13.13 神经运行时也通过相同 19 项测试。
- 发现：Python 3.13 对未关闭 SQLite connection 发出 `ResourceWarning`；旧 `initialize_database()` 的事务上下文只提交/回滚，不负责关闭连接，legacy migration 测试也有同类问题。
- 修复：生产初始化和 legacy 测试显式使用 `contextlib.closing`；Python 3.13 测试以 `-W error::ResourceWarning` 运行后无警告通过。
- 全套验证：`npm run lint`、`npm run test:backend`、`npm test`、`git diff --check` 全部通过；前端包含生产构建和 2 项 rendered-page 测试。
- Python 3.10：项目元数据最低版本已提升到 3.10，并新增独立 core/offline CI job；本地没有覆盖或删除原 `.venv`。
- 深入理解：升级解释器不仅是修改 `requires-python`，还要在新运行时用更严格警告发现资源生命周期变化，并让最低支持版本进入 CI。
- 整体位置：本地实现与验收完成；下一步是 diff/敏感文件审查、语义化提交、推送 Draft PR #4 和监控 CI。

### M2-F007 — 真实神经切片发布与远端验收

- 时间：2026-08-15
- 状态：实现提交和首轮远端验收完成
- 提交：`5e682f8 feat: add pinned multilingual embedding backend`
- PR：Draft PR #4 已更新为 `feat: add versioned neural embedding retrieval`，仍以 `main` 为 base。
- CI：GitHub Actions CI #17 成功；`Backend compatibility (Python 3.10)` 和 `Lint, build, and test` 两个 job 均通过。
- 远端覆盖：Python 3.10 core/offline 安装与 19 项后端测试；Python 3.11 综合 lint、19 项后端测试、前端生产构建和 rendered-page 测试。
- 发布边界：没有提交 470 MB 模型、SQLite 数据、缓存、密钥或临时虚拟环境；远端 CI 没有下载模型。
- 整体位置：M2 的版本化真实神经检索垂直切片已可运行、可比较、可审计；Roadmap 仍标记 **In progress**，下一证据任务是扩展跨论文、中英文改写和 hard-negative Gold 集，不能用当前 3-query 满分宣称质量提升。

### M2-F008 — 三路交互对比与全文 Gold 补漏

- 时间：2026-08-15
- 状态：本地实现和交互验收完成，等待提交与远端 CI
- 事实：新增 `POST /api/retrieve/compare`，对同一论文、字段查询、Top K 和 verified Gold 运行 BM25-only、hashing hybrid、E5 hybrid；每一路仍写入普通 retrieval run，并记录 `comparison_strategy`、权重、backend/model/version、缓存和耗时。
- BM25 边界：BM25-only 使用 `1/0/0/0` 权重，检索器检测到 vector 权重为零后完全跳过 query/passage embedding 和向量缓存；它不是“算完 embedding 再忽略”。
- 容错：E5 依赖或本地固定模型不可用时，该列显示 unavailable 和安装提示；BM25-only 与 hashing hybrid 继续返回，不发生静默模型回退。
- 前端：三列展示 Top-K、相对 BM25 的排名变化、BM25/semantic 分数、Gold 首位、Hit@K、Recall@K、模型身份和耗时；可从任意列直接增删 Gold。Gold 更新后，三列使用同一 Gold 集自动重算。
- 全文审核：原有关键词补漏之外新增“浏览全部”，当前 API 最多载入 300 个 block，允许人工逐条补充 Top-K 外 Gold。网页可以完成标注操作，但“某段是否真正相关”以及是否已审遍全文仍由人工负责。
- 真实交互验证：公开合成 PDF 共 12 个 block；三路比较均成功，本机首次 E5 冷启动约 6.25 秒，模型和 block 向量热缓存后约 42 毫秒；Gold 标注后三列均显示首位 `#1`、Hit@8/Recall@8 为 100%。这些数字只描述本机单篇合成 Demo，不是质量或生产延迟结论。
- 自动验证：本轮新增三策略持久化、BM25 跳过向量、Gold 指标和 E5 unavailable 降级测试；截至本条记录，21 项后端测试、lint、生产构建和 2 项 rendered-page 测试通过；浏览器控制台无 warning/error，700px 视口下三列折为单列且无横向溢出。
- 深入理解：`backend` 回答“向量由谁生成”，`comparison_strategy` 回答“检索分支如何组合”。BM25 是共享的词法分支，不应被错误描述成 hashing 或 E5 的另一个名字。
- 整体位置：M2 已从命令行比较推进到可人工审计的交互比较；仍为 **In progress**，下一数据任务是扩大经过人工确认的跨论文、中英文改写和 hard-negative Gold 集。

### M2-F009 — 三路交互增强发布与远端验收

- 时间：2026-08-15
- 状态：实现已推送，远端 CI 成功
- 实现提交：`47a83cc feat: add interactive retrieval comparison`
- 分支与 PR：`feature/embedding-retrieval` 已推送；Draft PR #4 保持以 `main` 为 base，并已更新变更说明、用户影响、验证证据和限制。
- 远端验证：GitHub Actions CI #21 成功；`Backend compatibility (Python 3.10)` 与 `Lint, build, and test` 两个 job 均通过，覆盖离线 core 安装、21 项后端测试、公开 PDF Demo、前端 lint、生产构建和 2 项 rendered-page 测试。
- 审计修正：发布前把 BM25-only 的向量身份从借用 hashing 改为明确的 `disabled/none@none`；因此 hashing 和 E5 是两种真实向量 backend，而 BM25-only 清楚表示没有启用向量分支。
- 发布边界：没有提交本地 SQLite、470 MB 模型、虚拟环境、缓存、构建产物、密钥或私人论文；没有修改 `main`、删除数据或重写历史。
- 整体位置：M2 的实现、三路交互、Gold 联动、版本审计和远端验收已形成可运行闭环；代表性跨论文 Gold 证据仍未完成，因此 Roadmap 继续标记 **In progress**。
