# EcoEvidence MVP 1.1

一个本地运行的“研究需求 → PDF 全文解析 → 文献筛选 → 证据召回 → 可量化评估”工作台。

本版本刻意停在证据召回评估：还没有进入图表裁剪、PaddleOCR、数据表抽取或 WPD 数字化。这样可以先用人工 Gold evidence 回答一个更基础的问题：系统能否把正确证据找回来？

## 当前成果

- 允许用户用自然语言自由描述需求，后台拆成可核对的目标变量、必须字段、关注字段、来源和排除项。
- 对 PDF 全文解析，而非只读摘要或关键词页。
- 只在 SQLite 中保存规范化证据块，不额外保存重复的 `fulltext.jsonl`。
- 每个证据块保留论文、页码、章节、类型和 PDF 坐标。
- 文献只分为 `usable`、`relative`、`nodata`、`failed` 四类。
- 混合召回同时显示 BM25、字符语义、术语覆盖和章节先验分数。
- 审核员可以从 Top-K 或全文补漏结果中标记 verified Gold evidence。
- 自动计算 Hit@K、Recall@K、Precision@K、MRR 和按字段表现。

当前 15 篇样本文献的首轮结果是：14 篇成功解析、1 篇无文本层而失败；共保存 3,615 个证据块。首轮规则筛选得到 6 篇 `usable`、8 篇 `relative`、1 篇 `failed`。这些分类是基线结果，需要后续人工审核，而不是最终真值。

## 快速启动

环境要求：

- Node.js 22.13 或更高
- Python 3.9 或更高

首次安装：

```bash
cd /Users/zhanghan/Documents/dataFetching/mvp_v1.1
python3 -m venv .venv
.venv/bin/pip install -e .
npm install
```

启动后端：

```bash
npm run dev:backend
```

另开一个终端启动前端：

```bash
npm run dev
```

浏览器访问 [http://localhost:3000](http://localhost:3000)。默认 PDF 目录是：

```text
/Users/zhanghan/Documents/dataFetching/MVP_v1/example
```

要使用其他 PDF 目录，可在启动后端时指定：

```bash
ECODATA_SOURCE_DIR=/你的/PDF/目录 npm run dev:backend
```

如果 `3000` 已被占用，前端会自动使用 `3001` 或后续端口；后端只允许
`localhost` 和 `127.0.0.1`，但接受任意本地开发端口。终端输出的
`Local URL` 才是当前应打开的页面地址。

## 验证

```bash
npm run lint
npm run test:backend
npm test
```

`npm test` 会先执行生产构建，再验证服务端渲染页面。后端测试固定了需求拆解、四级筛选、排序分数组成和评估公式。

## 从哪里开始读

建议先看 [中文学习与调试指南](docs/LEARNING_GUIDE.md)，再看 [系统架构与数据流](docs/ARCHITECTURE.md)。

核心入口：

- [前端交互](app/page.tsx)
- [API 路由](backend/api.py)
- [业务流程](backend/services.py)
- [PDF 全文解析](backend/pdf_parser.py)
- [需求拆解](backend/requirement_interpreter.py)
- [四级筛选](backend/screening.py)
- [混合召回](backend/retrieval.py)
- [召回评估](backend/evaluation.py)
- [SQLite 数据层](backend/database.py)
- [共享数据结构](backend/schemas.py)

## 数据与隐私

PDF 内容、人工 Gold 和评估结果只保存在本地
`data/ecoevidence.sqlite3`。数据库文件已被 Git 忽略。PDF 原件不会被复制到本项目中；数据库只记录原始路径和哈希。

如果想创建一套不影响当前结果的实验数据库，推荐指定新路径，而不是删除现有数据库：

```bash
ECODATA_DB_PATH=/tmp/ecoevidence-experiment.sqlite3 npm run dev:backend
```

## 范围边界

本版本暂不实现：

- 扫描 PDF 的 OCR 补救
- 图表对象检测和可调裁剪框
- 表格结构识别与单元格审核
- PaddleOCR 图中数据提取
- WPD 预填和数字化
- 最终数据质检

这些能力可以在证据召回基线通过人工评估后继续增加，避免把“没有找到证据”和“找到了但抽错数据”混成同一个问题。
