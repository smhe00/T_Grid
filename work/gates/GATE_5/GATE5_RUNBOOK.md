# GATE 5 影子运行手册（用户人工执行）

> 本手册用于在**真实 MiniQMT 环境**执行设计 §40 的 5 交易日 Shadow 运行。
> Shadow 模式绝不产生真实订单；任何时刻 `live_trading_allowed=false`。

## 已验证命令（2026-08-15 实机通过）

```powershell
# 使用带 xtquant 的 venv
$env:PYTHONPATH = "D:\gitee\miniQMT\T_Grid_dsh\src"
& "D:\gitee\miniQMT\.venv\Scripts\python.exe" scripts\gate5_shadow_live.py `
    --config config\gate1_qmt.local.json `
    --out work\reports\shadow\10day-<date> `
    --date <YYYY-MM-DD> --code 510300.SH --run-days 10
```

实机证据见 `work/gates/GATE_5/LIVE_VERIFICATION.md`（10 交易日，4 条 WOULD 订单，
Realized T PnL +13.3，对账一致）。

## 前置条件

1. 已安装并登录 MiniQMT（XtQuant 可用），账户为模拟/只读授权状态。
2. 本仓库代码就绪（`pip install -e .`），`config/config.local.yaml` 已按需配置
   （`0700.HK` / `000333.SZ` 或自选标的，数量仅为示例）。
3. 确认 `config/gate1_qmt.local.json` 指向真实 runtime 配置（Gate 1 已验收的
   version-2 hashed binding）。

## 接入方式（推荐）

`ShadowEngine` 是纯离线核心；真实接入只需把 Gate 1 只读 Adapter 的输出转换成
`Bar` 序列喂给引擎。生产环境建议直接使用仓库脚本：

```powershell
python scripts\gate5_shadow_live.py --config config\gate1_qmt.local.json `
    --out work\reports\shadow\<date> --date <YYYY-MM-DD> --code <SYMBOL> --run-days 5
```

脚本内部：读取 Gate 1 runtime/binding → 真实下载日线+5m 历史（只读数据获取）→
逐交易日 `begin_day`（每日冻结 anchor/ATR/G，设计 §9）→ 逐 5m bar 决策（影子持仓按
"真实持仓 + 影子成交"的有效模型，INV-005）→ 生成四份交付物。

或手工接入：

```python
from tgrid.shadow import ShadowEngine
from tgrid.strategy.engine import AccumulateStrategy
from tgrid.strategy.bars import Bar, SessionWindow

engine = ShadowEngine(
    AccumulateStrategy(cfg.symbols["0700.HK"], cfg.global_config,
                       session_window=SessionWindow(570, 900)),
    symbol="0700.HK",
)
engine.begin_day(daily_adjusted_bars, trade_date="2026-08-13")

# 每个 5m bar：
decision = engine.on_bar(
    bar,                                  # 来自 ReadOnlyMarketDataAdapter 的 5m bar
    broker_position=700, can_use_qty=700, strategic_extra=0,
    available_cash=broker_cash,
    assume_fill_price=bar.close,          # 影子成交假设：按收盘价
)

# 收盘后：
reports = build_shadow_reports(engine, trade_date="2026-08-13",
                               broker_positions={"0700.HK": 700})
```

> 注意：影子持仓必须按"真实券商持仓 + 影子成交"的有效持仓喂给策略（保持
> Broker=Core+Strategic+OpenT 分解，INV-005）；对账报告仍与真实券商持仓比较。

## 5 交易日运行要求（§40）

- 连续 **≥ 5 个完整交易日**（`--run-days 5` 或更大）；
- 每交易日输出四份交付物（Shadow Orders / Signal Log / Reconciliation Report /
  Daily Report），建议落盘 `work/reports/shadow/<date>/`；
- 每日检查 **Reconciliation Report**：`delta != 0` 时必须人工确认原因，不得静默修复；
- 运行结束后汇总：Shadow Orders 与 Signal Log 一致、无未解释对账差异、无 risk 型
  violations，才允许进入 Gate 6。

## 已知客户端限制

- 该 QMT 客户端（sp3 build）不实现 `xtdata.get_trading_calendar`（"function not
  realize"，ErrorID 300000）：交易日历请使用 `get_trading_dates`。
- 5m 历史默认未下载：运行器会先 `download_history_data`（只读数据获取，非交易）。

## 退出条件

- 全部 5 日对账一致 → 将证据归档并申请 Gate 6。
- 任一日出现无法解释的 delta / risk violations / 异常 → 停止 Shadow 运行，修复后重新累计 5 日。
