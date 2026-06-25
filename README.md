# EcoData Extraction

面向生态环境领域的文献数据发现、抽取、质检和证据链管理项目。

> 当前为早期开发版本，尚未发布稳定 API。

目标是构建一条可运行、可测试、可追溯的 Literature-to-Data Pipeline：

```text
数据需求
  -> 文献发现
  -> 文献筛选
  -> 开放 PDF
  -> 图表索引
  -> 数据抽取
  -> 自动质检
  -> 人工复核
  -> 可追溯数据清单
```

## 当前功能

当前正在实现文献发现模块：

```text
关键词 -> OpenAlex API -> 规范化元数据 -> 候选文献清单
```

已实现 OpenAlex 搜索参数的清理和验证。

## 项目结构

```text
src/ecodata_extraction/  产品代码
tests/                   自动测试
.env.example             环境变量示例
pyproject.toml           Python 包配置
```

## 测试

运行全部测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 配置与安全

复制 `.env.example` 为本地 `.env`，并填写自己的配置。不要把真实 API Key、
Token 或下载的论文 PDF 提交到 Git。
