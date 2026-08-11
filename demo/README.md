# Demo 数据说明

`pdfs/synthetic_stem_respiration_study.pdf` 是为本仓库编写的合成论文，不对应真实研究，不含版权或隐私数据。它只用于验证解析、证据回链、筛选和召回流程。

## 建议使用的研究需求

```text
我希望提取树干呼吸速率数据，必须报告物种和样本量；关注站点、经纬度、胸径、测量温度和测量方法。接受正文、表格和数据图中的观测值或均值，不接受模型预测值。经纬度缺失时可以保留为 relative。
```

## 人工核对清单

同步 PDF 后，应能在页面中找到以下证据：

| 字段 | 合成值 | 预期位置 |
| --- | --- | --- |
| 物种 | *Pinus sylvestris* | Methods，第 1 页 |
| 样本量 | 12 trees | Methods，第 1 页 |
| 站点 | Demo Forest Research Station | Methods，第 1 页 |
| 经纬度 | 50.93 N, 13.57 E | Methods，第 1 页 |
| 胸径 | 24.6 cm | Methods，第 1 页 |
| 测量温度 | 18 degrees C | Methods / Results，第 1 页 |
| 测量方法 | closed chamber + IRGA | Methods，第 1 页 |
| 树干呼吸速率 | 2.40 micromol CO2 m-2 s-1 | Results，第 1 页 |

“正确结果”不是要求所有字段都排在 Top 1，而是：相关证据能被解析、返回时保留页码和坐标，并允许审核者把正确 block 标为 verified Gold evidence。
