# 拾光投资

一个面向个人的中文基金持仓管理 MVP，重点演示“支付宝持仓截图 → 视觉识别 → 差异对账 → 人工确认入账”。

## 安全设计

- 不读取支付宝账号、Cookie、密码或支付信息。
- 视觉模型只做转写，不直接修改数据库。
- 识别后展示新增、更新、未识别三类差异；“未识别”默认不删除。
- 确认入账后可自动删除原截图。
- 数据库和截图目录已加入 `.gitignore`。

## 本地运行

只需 Python 3.8+，无第三方依赖：

```bash
python3 server.py
```

浏览器打开 <http://127.0.0.1:8787>。

## 启用真实截图识别

默认是透明的演示模式：它不会读图，只返回两条演示持仓。要接入通义千问 VL：

```bash
export VISION_API_KEY="你的百炼 API Key"
export VISION_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export VISION_MODEL="qwen-vl-max"
python3 server.py
```

请先在支付宝截图中遮挡姓名、账号、会员信息等与持仓无关的内容。第三方模型的数据处理规则以对方最新条款为准。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

## 与参考项目的关系

产品流程参考了 [LuoDi-Nate/financial-management](https://github.com/LuoDi-Nate/financial-management) 的持仓截图导入理念，但本项目的名称、界面、代码和数据模型均为独立实现。

## 免责声明

本项目用于个人数据管理和学习，不构成投资建议、基金销售或收益承诺。
