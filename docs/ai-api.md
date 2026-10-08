# AI 只读持仓接口（v1）

拾光投资提供稳定的 JSON 视图，供本机 AI 工具读取。接口只读取本地数据库，不执行刷新行情、交易、转账或写入。所有金额是人民币十进制**字符串**，避免浮点精度问题；时间是本机记录时间，不代表基金最新净值时间。

## 不启动 App 时读取

在源码目录执行：

```bash
python3 tools/read_portfolio.py
python3 tools/read_portfolio.py --day 2026-08-12
```

脚本默认读取桌面 App 数据目录中的 `portfolio.db`，也接受 `SHIGUANG_DATA_DIR` 或 `--db /path/to/portfolio.db`。第一条命令输出当前基金/ETF 与资产账户；第二条只输出指定日期的基金/ETF 快照。命令不修改数据库。

## App 运行时读取

```bash
curl --fail http://127.0.0.1:8787/api/ai/v1/portfolio
curl --fail 'http://127.0.0.1:8787/api/ai/v1/holdings?day=2026-08-12'
```

端口由 `PORT` 环境变量决定，默认 `8787`。服务仅绑定 `127.0.0.1`，现有同源和本机 Host 检查也适用于新接口；JSON 响应使用 `Cache-Control: no-store`。不要把端口公开转发到互联网。

### `GET /api/ai/v1/portfolio`

顶层 `schema_version` 固定为 `1`，`scope` 为 `current_portfolio`。`generated_at` 是读取时间；`last_recorded_at` 是当前持仓和账户中最近一次保存时间。`totals` 包括 `assets`、`holdings_market_value`、`cash_accounts`、`reported_current_holding_profit`、`current_holding_return_rate_pct`。最后一项只按**当前未清仓持仓**的用户上报收益计算；基数无效或没有持仓时为 `null`，不包含现金和已清仓收益，也不是整个投资组合的历史收益率。

`holdings[]` 只有当前未归档持仓，包含代码、名称、类别、当前金额、平台填报的持有收益/收益率、保存时间、最近快照日期和快照来源。`cash_accounts[]` 包含账户名称、类型、平台、余额、保存时间。`purchase_channel` 恒为 `null`，因为现有持仓模型没有记录每只基金是在支付宝还是券商购买；不得从现金账户平台或基金名称推断。

`data_basis` 明示这些是 App 保存的记录，不是支付宝或券商的实时同步结果。历史 `cost` 字段不会输出，也不会据此重算本金。

### `GET /api/ai/v1/holdings?day=YYYY-MM-DD`

顶层 `scope` 为 `dated_holdings`。`positions[]` 包含截至指定日期每只基金/ETF 的最近快照，以及 `snapshot_day`、`snapshot_source`、`snapshot_recorded_at`、`closed`、`closed_on`。已清仓持仓仍在结果中，但 `market_value` 为 `0.00`，不计入 `holdings_market_value`。

指定日没有快照时，`valuation_method` 为 `latest_recorded_snapshot_on_or_before_day`：沿用该日之前最近一次**手动记录的金额**，不会按当日行情重新估值。`snapshot_days` 列出有记录的日期。资产账户没有按日余额，故 `historical_cash_available` 为 `false`，此接口不返回历史总资产；卖出款也不会自动计入现金。

日期无效、重复或晚于今天时返回 HTTP 400。数据库暂时不可读取时返回 HTTP 503。跨站来源被现有同源检查拒绝，返回 HTTP 403。
