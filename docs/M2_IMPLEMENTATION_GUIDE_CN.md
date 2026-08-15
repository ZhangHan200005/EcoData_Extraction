# M2 中文实施与学习指南（持续更新）

最后更新：2026-08-15

## 1. 这份文档的用途

这是一份随 M2 实施持续更新的本地说明文档。它回答四个问题：

1. 这轮具体改了什么；
2. 为什么使用这些技术方法；
3. 你可以从哪里开始阅读、调试和修改；
4. M2 距离整体完成还有多远。

公开能力状态以 [ROADMAP.md](ROADMAP.md) 为准。本文件更偏向实现过程、学习路径和设计推理，不把计划中的功能描述成已经完成。

## 2. M2 当前进度

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
encode(text: str) -> list[float]
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

## 7. 下一决策点

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
