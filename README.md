# VeyraQuant 量化交易助手

VeyraQuant 是一个面向美股波段交易的半自动量化交易助手。它会定时扫描股票池，结合行情、技术指标、市场环境、新闻情绪、期权数据和风控预算，生成每日简报、机会提醒和可复核的交易计划。

它不是自动交易机器人，也不会连接券商 API。VeyraQuant 的目标是帮助交易者更快回答三个问题：

- 现在市场环境是否适合进攻？
- 哪些标的最值得关注？
- 如果要交易，入场区、止损、目标位和仓位应该如何规划？

## 核心亮点

### 1. 股票池扫描

通过 `SYMBOLS` 配置多个美股或 ETF，例如：

```text
NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH
```

系统会为每个标的计算综合评分，并按优先级排序，避免只盯着单一股票做主观判断。

### 2. 市场环境过滤

VeyraQuant 不会只看个股信号。它会先读取市场背景：

- `SPY`: 美股大盘风险偏好
- `QQQ`: 科技股趋势
- `SMH`: 半导体板块强度
- `^VIX`: 市场波动压力

当市场处于风险规避状态时，系统会降低入场信号的进攻性，避免在大盘环境不利时盲目追涨。

### 3. 多维度分项评分

每个标的都会拆成多个可解释评分项：

- 趋势结构：MA5/MA10/MA20/MA50/MA200、20/55 日高低点
- 动量状态：RSI、MACD、ADX、DI
- 相对强弱：个股相对 `SPY` / `QQQ` 的表现
- 成交量确认：当前量能相对 20 日均量与 5 日均量
- 波动与期权：ATR、隐含波动率、Put/Call 比率
- 新闻与情绪：公开 RSS、Google News、社媒标题代理情绪
- 事件风险：基本面增长、分析师一致预期
- 市场环境：大盘、科技、半导体、VIX 背景
- 纪律过滤：乖离率不追高、利空消息一票否决、板块共振加分

这样你看到的不只是一个分数，而是知道分数从哪里来。

### 4. 明确交易计划

当信号达到条件时，VeyraQuant 会输出完整交易计划：

- 信号类型
- 综合评分
- 市场状态
- 入场区间
- 止损位置
- 第一/第二目标位
- 预期 R 倍数
- 建议仓位比例
- 最大亏损占账户比例
- 触发条件
- 取消条件
- 主要理由
- 主要风险

示例字段：

```text
symbol: NVDA
signal_type: 趋势回踩加仓
score: 72
market_regime: 风险偏好
entry_zone: $904.20 - $916.80
stop: $874.50
targets: $952.00 / $988.40
position_pct: 6.40%
max_loss_pct: 0.50%
```

只有最终 `actionable` 的结果才会保留完整买入型交易计划。`持有观察`、`禁止交易/等待`、`减仓/风险升高` 和被 validator 否决的结果不会再伪装成可执行买入计划。

### 4.1 当前策略框架

当前系统更接近“纪律化趋势波段策略助手”，核心逻辑是：

- 市场先过滤：先判断 `risk-on / neutral / risk-off`
- 个股再打分：优先多头排列、强趋势、量价配合
- 买点偏好：优先缩量回踩，不鼓励高位追涨
- 突破确认：要求放量、强势收盘、乖离率可控
- 风险排查：舆情明显偏空时，买入信号会被降级或否决

你现在实际采用的两类主交易机会是：

- `突破入场`：接近/突破 20 日高点，且 5 日量比足够强、收盘位置强势
- `趋势回踩加仓`：MA5 > MA10 > MA20，多头趋势中缩量回踩 MA5/MA10 附近

### 5. 风控优先

VeyraQuant 默认采用保守风险参数：

- 单笔风险：`0.5%`
- 单标的最大仓位：`10%`
- 组合总风险暴露上限：`3%`
- ATR 止损倍数：`2.0`
- 最低盈亏比：`1.5R`

仓位不是拍脑袋给出的。系统会根据入场价、止损距离、单笔风险预算和组合风险上限计算建议仓位。

在生成 actionable 交易计划后，系统还会做一层计划校验：

- RR 必须不低于 `MIN_RR`
- 仓位不得超过 `MAX_POSITION_PCT`
- 最大亏损占比不得超过 `RISK_PER_TRADE_PCT`
- 过宽的 entry zone 会先给 warning，再对明显异常区间做 reject

这层校验只用于阻止无效交易计划进入结果对象，不会新增交易策略或改写原有市场信号逻辑。

### 6. 自动邮件简报与提醒

系统支持两类输出：

- 每日简报：在设定的悉尼时间窗口发送股票池总览和重点交易计划
- 每日简报：到达阈值时间后，当天任意一次成功运行都会补发一次，避免因 GitHub Actions 延迟漏掉整天日报
- 机会提醒：在美股正常交易时段内，如果信号达到阈值，发送入场、加仓或风险提醒

每类提醒都有冷却机制，避免同一信号反复刷屏。

当前日报已经重组为更接近交易台晨会的结构：

- `Today Conclusion`
- `Market Filter`
- `Action List`
- `Hold / Watch`
- `Avoid Chase / Risk Reduce`
- `Rejected Plans`
- `System Notes`

其中只有 `BUY_TRIGGER` / `ADD_TRIGGER` 且 `is_actionable=True` 的结果会进入 `Action List`。其余结果只按观察、回避、拒绝或风控状态展示，不展示成可执行买入计划。

### 7. 免费数据优先，支持降级

当前数据源以免费来源为主：

- Yahoo Finance: 行情、基本面、期权链
- NVIDIA RSS / Google News RSS: 新闻和公开标题情绪
- 本地缓存: 当实时数据失败时尝试降级使用缓存

如果 Yahoo、RSS 或期权数据临时不可用，系统会尽量生成带有数据降级提示的报告，而不是直接中断。

### 8. 可测试、可维护、可扩展

项目已从单文件脚本升级为模块化结构：

```text
veyraquant/
  config.py       # 环境变量与配置
  data.py         # 数据获取、缓存、降级
  indicators.py   # RSI、MACD、ATR、ADX 等指标
  market.py       # 市场环境过滤
  signals.py      # 信号评分与交易计划
  risk.py         # 仓位与组合风险控制
  validator.py    # actionable 交易计划有效性校验
  reporting.py    # 日报与提醒内容
  state.py        # 状态记录与迁移
  backtest.py     # 简易回测框架
  runner.py       # 主运行流程
```

并包含测试覆盖：

- 技术指标测试
- 风控计算测试
- 状态迁移测试
- 数据降级测试
- 报告字段测试
- 信号评分测试
- 简易回测测试

## 信号类型

VeyraQuant 当前支持以下信号：

- `突破入场`: 趋势、动量、量能和市场背景共同支持突破
- `趋势回踩加仓`: 强趋势中回踩关键均线附近，适合分批加仓
- `持有观察`: 分数尚可，但不适合新增仓位
- `减仓/风险升高`: 过热、转弱或风险条件恶化
- `禁止交易/等待`: 数据不足、市场不利或信号不清晰

## 环境变量

### 邮件配置

```text
SMTP_USER
SMTP_APP_PASSWORD
FROM_EMAIL
TO_EMAIL
```

### 股票池与调度

```text
SYMBOLS=NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH
MARKET_SYMBOLS=SPY,QQQ,SMH,^VIX
SEND_HOUR=7
SEND_MINUTE=30
SEND_WINDOW_MINUTES=30
ENABLE_ENTRY_ALERTS=true
ALERT_COOLDOWN_HOURS=12
ALERT_SCORE_THRESHOLD=65
INTRADAY_INTERVAL=30m
SUBJECT_PREFIX=VeyraQuant 量化简报
DRY_RUN=false
FORCE_DAILY_REPORT=false
```

### 风控参数

```text
ACCOUNT_EQUITY=
RISK_PER_TRADE_PCT=0.5
MAX_POSITION_PCT=10
PORTFOLIO_HEAT_MAX_PCT=3
ATR_STOP_MULTIPLIER=2.0
MIN_RR=1.5
MAX_ENTRY_ZONE_WIDTH_WARN_PCT=3.0
MAX_ENTRY_ZONE_WIDTH_REJECT_PCT=6.0
```

`ACCOUNT_EQUITY` 是可选项。如果不设置，系统只输出百分比仓位，不输出具体金额。

## 本地运行

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

干跑模式：

```powershell
$env:DRY_RUN="true"
python report.py
```

运行测试：

```powershell
python -m compileall report.py veyraquant tests
pytest
```

## GitHub Actions

项目内置 GitHub Actions workflow：

- 每 20 分钟自动运行
- 到达发送阈值后，当天任意一次成功运行都会补发每日简报
- 只在美股正常交易时段发送机会提醒
- 支持手动 `workflow_dispatch`
- 支持 dry-run
- 支持 `force_send=true` 的手动强制日报测试，不受时间窗口限制，且不会覆盖当天正式日报状态
- 只在状态文件变化时提交 `state/last_sent.json`

## 适合谁使用

VeyraQuant 适合：

- 想系统化跟踪美股波段机会的交易者
- 想把主观看盘流程变成可重复检查清单的人
- 想在入场前明确止损、目标位和仓位的人
- 想用免费数据源搭建轻量量化助手的人
- 想学习如何把交易逻辑拆成数据、信号、风控和报告模块的人

## 不适合谁使用

VeyraQuant 不适合：

- 想要自动下单机器人的用户
- 想要高频交易或毫秒级行情系统的用户
- 想要保证收益或确定性买卖点的用户
- 不愿意人工复核交易计划的用户

## 免责声明

VeyraQuant 仅用于信息分析和交易辅助，不构成投资建议，不代表任何自动交易指令。所有交易计划都需要人工复核，任何投资决策和交易风险均由使用者自行承担。
