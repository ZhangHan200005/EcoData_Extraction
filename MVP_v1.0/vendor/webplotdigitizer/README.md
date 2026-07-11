# 本地 WebPlotDigitizer 运行组件

这里保存从 Automeris WebPlotDigitizer 精简出的离线浏览器运行文件。审核页通过同源 iframe 将论文裁剪图载入 WPD，图像和数据不需要上传到在线网站。

- 上游项目：https://github.com/automeris-io/WebPlotDigitizer
- 上游许可证：AGPL-3.0，见本目录 `LICENSE`
- 本地入口：`offline.zh_CN.html`
- 本项目负责论文、图号、页码、裁剪图和审核任务之间的关联；坐标标定、自动选点和数据导出由 WPD 完成。

精简目录只保留离线页面需要的 CSS、图标、PDF.js、tarball.js 和 `wpd.min.js`，不包含上游开发环境。

