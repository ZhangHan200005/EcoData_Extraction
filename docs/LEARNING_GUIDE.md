# 中文学习与调试指南

这份指南的目标不是让你一次看懂所有框架，而是让你能回答三类实际问题：

1. 一次点击经过了哪些代码？
2. 某个规则或页面要改，应该去哪里？
3. 结果不对时，先在哪一层 debug？

## 一、15 分钟读懂一次完整请求

以页面上的“运行证据召回”为例。

### 第 1 步：前端收集参数

打开 [app/page.tsx](../app/page.tsx)，搜索 `runRetrieval`。

它读取三个界面状态：

- `selectedDocumentId`：哪篇论文
- `selectedField`：要找哪个字段
- `topK`：返回多少条

随后通过公共 `api()` 函数向 `/api/retrieve` 发送 JSON。遇到 400/404/500 时，`api()` 会把后端的 `detail` 转成页面错误提示。

你最容易修改的内容：

- 默认研究需求：搜索 `DEFAULT_BRIEF`
- 工作流阶段名称：搜索 `STAGES`
- 默认 Top-K：搜索 `useState(8)`
- 后端地址：搜索 `NEXT_PUBLIC_API_BASE`
- 每一页的文字和布局：在 `return (` 之后按 `stage ===` 找四个页面

### 第 2 步：API 只做入口工作

打开 [backend/api.py](../backend/api.py)，搜索 `def retrieve`。

API 层校验请求类型，调用 service，并把 `KeyError` 或 `ValueError` 转成用户能理解的 HTTP 状态。它不应该包含检索公式，否则以后 CLI、批处理和页面会出现三套不同逻辑。

要新增接口时，先在 [schemas.py](../backend/schemas.py) 定义输入输出，再在 `api.py` 增加路由。

### 第 3 步：Service 串联业务

打开 [backend/services.py](../backend/services.py)，搜索 `def retrieve`。

这里依次：

1. 读取当前 `ProjectSpec`
2. 验证论文存在
3. 读取该论文全部证据块
4. 读取已有 Gold
5. 调用 ranker
6. 截取 Top-K
7. 保存带版本号的 retrieval run

Service 是理解“系统做事顺序”的最佳入口。

### 第 4 步：Ranker 计算每个块的分数

打开 [backend/retrieval.py](../backend/retrieval.py)，搜索 `def rank`。

每个证据块获得四个分量：

- `bm25`：查询词在本块中是否有区分度
- `semantic`：字符 n-gram hashing 向量的余弦相似度
- `term_coverage`：同义词实际覆盖比例
- `section_prior`：字段是否出现在更合理的章节

搜索 `score = (` 就能看到权重。修改权重后不需要重新解析 PDF，但要提升
[settings.py](../backend/settings.py) 中的 `retrieval_version`，重新运行召回和评估。

### 第 5 步：评估只相信人工 Gold

打开 [backend/evaluation.py](../backend/evaluation.py)，搜索 `for k in k_values`。

评估器先按 `(document_id, field_name)` 对 verified Gold 分组，然后对每组重新排序。指标不是模型自己给出的 confidence，而是排序结果与人工答案的集合运算。

这一区别很重要：

```text
score = 模型内部排序依据
Recall/Precision/MRR = 与人工真值比较后的外部效果
```

## 二、PDF 是如何进入数据库的

入口仍在 [services.py](../backend/services.py) 的 `sync_documents`。

### 哈希复用

[pdf_parser.py](../backend/pdf_parser.py) 中的 `sha256_file()` 计算 PDF 内容哈希。数据库里已经有相同哈希，并且 `parser_version` 相同时，文件直接复用。

因此重复点击“同步并解析语料”不会重复保存全文。

### 全文分块

在 [pdf_parser.py](../backend/pdf_parser.py) 中依次阅读：

1. `_line_records()`：从单页读取文本行和坐标。
2. `_merge_lines()`：把行合成适合检索的证据块。
3. `_section_name()`：识别 Methods、Results 等章节。
4. `CAPTION_RE`：识别 Figure/Table/图/表标题。
5. `FullDocumentParser.parse()`：遍历所有页并生成稳定 ID。

数据库没有独立 `fulltext` 字段。全文就是按 `ordinal` 排序的所有 block。这样页码和坐标不会丢，也不会重复存两遍正文。

### 你可以安全修改什么

- 新增章节标题写法：修改 `SECTION_PATTERNS`
- 新增 caption 写法：修改 `CAPTION_RE`
- 调整块长度：修改 `_merge_lines()` 中的 `char_count > 850`
- 调整段落断开距离：修改 `vertical_gap` 判断

只要改变分块结果，就应在 [settings.py](../backend/settings.py) 提升
`parser_version`。否则哈希缓存会复用旧块，看起来像“代码没有生效”。

## 三、自然语言需求是如何拆解的

[requirement_interpreter.py](../backend/requirement_interpreter.py) 是一个故意透明的规则基线。

- `TARGET_FIELDS`：可提取变量及中英文同义词和单位
- `CONTEXT_FIELDS`：物种、样本量、站点等上下文
- `REQUIRED_MARKERS`：识别“必须、一定要”等强约束
- `source_terms`：正文、表格、图等允许来源
- `exclusion_terms`：模型值、综述、引用数据等排除项

用户仍可自由输入；规则只负责把文本拆成可供用户核对的 `ProjectSpec`。如果找不到内置变量，系统保留 `custom_target` 并显示警告，不会默默丢弃用户需求。

以后接入 LLM 时，建议新增一个实现相同输入输出的 interpreter，而不是改动后续所有模块。LLM 输出仍要经过 Pydantic 校验，并让用户确认。

## 四、四级筛选在哪里调整

打开 [screening.py](../backend/screening.py)。

常改位置：

- `NUMBER_RE`：什么算数值
- `UNIT_RE`：接受哪些单位
- `evidence_window`：目标术语前后看几个块
- `missing_required`：怎样判断必须字段覆盖
- 最后的 `if / elif / else`：四级分类逻辑

当前筛选只负责粗筛。比如一篇论文在参考文献中出现 `sample size`，规则也可能认为该字段存在。这类假阳性应该先通过人工审核形成标注，再决定是增加章节限制、引用区排除，还是引入分类模型。

不要直接根据 15 篇样本把规则写得非常具体，否则容易过拟合。每次修改后对同一 Gold 集比较，而不是只看几个页面例子。

## 五、数据库能修改和重建什么

数据库表定义在 [database.py](../backend/database.py) 顶部的 `SCHEMA`。

重要关系：

```text
documents 1 ── N blocks
documents + field_name + blocks ── gold_evidence
retrieval_runs 保存一次排序实验
evaluations 保存一次汇总指标
project_specs 保存需求解释版本
```

本地数据文件是 `data/ecoevidence.sqlite3`，Git 不会提交它。

推荐的实验方式是使用另一个数据库路径：

```bash
ECODATA_DB_PATH=/tmp/ecoevidence-experiment.sqlite3 npm run dev:backend
```

这样不会破坏现有人工 Gold。只有确认不需要旧标注时，才应重建原数据库。

### 哪些改动不需要重建数据库

- 页面和 CSS
- 召回权重、查询扩展、Top-K
- 需求文本和文献筛选
- 评估 K 值

### 哪些改动通常要重新解析

- PDF 行合并
- 两栏阅读顺序
- caption 与章节识别
- block ID 算法

提升 `parser_version` 后点击同步即可触发重新解析。

## 六、最实用的 debug 地图

| 现象 | 先看哪里 | 快速检查 |
|---|---|---|
| 页面显示“后端尚未连接” | [page.tsx](../app/page.tsx)、[api.py](../backend/api.py) | 打开 `http://127.0.0.1:8771/api/health` |
| 找不到 PDF | [settings.py](../backend/settings.py) | 看 health 返回的 `source_directory` |
| 某 PDF 是 failed | [pdf_parser.py](../backend/pdf_parser.py) | 看 `parser_warnings`；很可能没有文本层 |
| 标题识别奇怪 | `_metadata()` | PDF 元数据差时会从第一页候选行兜底 |
| Methods 后面全部章节都错 | `SECTION_PATTERNS` | 查看数据库块的 `section` 与标题原文 |
| 明明有数据却是 nodata | [screening.py](../backend/screening.py) | 检查术语、数字、单位和相邻块窗口 |
| Top-K 都是参考文献 | `_expected_sections()` 和章节识别 | 提高 References 惩罚或修复章节标题 |
| 中文同义词召回差 | `FIELD_HINTS`、变量 `synonyms` | 增加真实语料中的表达，不要只加翻译词 |
| Recall 很高但结果不好 | [evaluation.py](../backend/evaluation.py) | 检查 Gold 覆盖数及是否做过全文补漏 |
| 修改 parser 后结果没变 | [settings.py](../backend/settings.py) | 是否提升了 `parser_version` |
| Gold 突然消失 | [database.py](../backend/database.py) | 重新分块会改变 block，旧 Gold 应失效 |

### 三个最有用的本地接口

- `GET /api/health`：端口、PDF 路径、数据库路径和算法版本
- `GET /api/state`：当前需求、论文、Gold 和最近评估
- `GET /api/documents/{document_id}/blocks?query=sample`：直接检查全文块

FastAPI 还会提供交互式接口文档：
[http://127.0.0.1:8771/docs](http://127.0.0.1:8771/docs)。

## 七、怎样正确建立召回评估集

只有在 Gold 比较完整时，Recall 才可信。推荐流程：

1. 选取覆盖中英文、短文/长文、表格多/少、扫描失败的论文。
2. 对每个关注字段先审核 Top-K。
3. 再用“全文补漏”搜索同义词、单位和具体值。
4. 把 Top-K 外的正确块也标为 verified Gold。
5. 确认一条事实跨两个相邻块时，两个块是否都需要标注，并保持统一规则。
6. 观察页面上的评估覆盖，不只看百分比。
7. 冻结这批 Gold，再比较不同权重或 embedding 版本。

如果只把 Top-K 中看到的结果标成 Gold，系统永远很难发现自己的漏召回，这叫 verification bias。

## 八、建议的学习练习

### 练习 1：增加一个同义词

在 [requirement_interpreter.py](../backend/requirement_interpreter.py) 给树干呼吸加入一个真实语料表达，在 [test_requirements.py](../backend_tests/test_requirements.py) 添加断言，运行：

```bash
npm run test:backend
```

### 练习 2：调整一个召回权重

在 [retrieval.py](../backend/retrieval.py) 修改四个权重，但保持总和为 1。提升 `retrieval_version`，在同一 Gold 上重新评估，记录 Recall@5 和 MRR 的变化。

### 练习 3：修复一个标题或章节

找一篇页面标题不理想的 PDF，用全文块定位第一页内容，在 `_metadata()` 或 `SECTION_PATTERNS` 增加通用规则。提升 parser version 后，用实验数据库重新解析，不要先覆盖正式 Gold。

### 练习 4：替换真正的 embedding

保留 `EvidenceRetriever.rank()` 的输出结构，只替换 `HashingEmbedder`。比较：

- 同一 Gold 集
- 同一 K
- 同一 BM25 权重
- 运行时间和模型体积
- 中文与英文分字段指标

只有这样才能判断“高级模型”是否真的改善了这个项目，而不是仅仅让系统更复杂。

## 九、测试文件怎么读

- [test_requirements.py](../backend_tests/test_requirements.py)：自然语言拆解
- [test_screening.py](../backend_tests/test_screening.py)：四种筛选状态
- [test_retrieval_evaluation.py](../backend_tests/test_retrieval_evaluation.py)：排序分量和指标公式
- [rendered-html.test.mjs](../tests/rendered-html.test.mjs)：生产构建后的页面是否还能渲染

测试使用合成文本和临时数据库，不会修改 15 篇文献对应的正式 SQLite。
