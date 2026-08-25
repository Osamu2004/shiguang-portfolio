# 拾光 · Scholar 快照扩展

1. 解压下载的 ZIP。
2. 在 Chrome/Edge 扩展管理页开启开发者模式。
3. 选择“加载已解压的扩展程序”，指向 `scholar-extension` 文件夹。
4. 打开自己的 Google Scholar 主页，按需登录并手动完成人机验证。
5. 点击右下角“导出到拾光”，再把 JSON 导入拾光的“科研档案”。

扩展只读取当前页面 DOM，不读取密码和 Cookie，不绕过验证码，也不向第三方服务器发送数据。

架构参考 MIT 许可的 [MyPaperTrend](https://github.com/marsggbo/MyPaperTrend) 的本地优先、页面内采集和日期快照思路；本实现为独立的精简导出器。
