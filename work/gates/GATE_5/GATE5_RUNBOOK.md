# GATE 5 影子运行手册（用户人工执行）

> 本手册用于在**真实 MiniQMT 环境**执行设计 §40 的 5 交易日 Shadow 运行。
> Shadow 模式绝不产生真实订单；任何时刻 `live_trading_allowed=false`。
> 本手册反映 NODEA-R4 后的当前 CLI（NODEA-R3-002/R4-003）：显式可信配置、
> 逐日因子、可信对账状态；**不使用** `config.example.yaml` 作为运行时配置。

## 前置条件

1. 已安装并登录 MiniQMT（XtQuant 可用），账户为模拟/只读授权状态。
2. 本仓库代码就绪（`pip install -e .`），准备以下**可信本地文件**（不入库）：
   - `--strategy-config`：可信策略 YAML（含目标 symbol 的完整 `SymbolConfig`）；
   - `--factor-map`：逐日 ADJUSTED→RAW 因子 JSON（键 `"SYMBOL|YYYY-MM-DD"` →
     因子值；每个回放日必须有条目，无默认 1.0）；
   - `--reconciliation-state`：可信本地分解 JSON（`{ "<symbol>": {
     "strategic_extra": int, "open_t_position": int } }`；Core 来自
     `SymbolConfig.core_qty`，state 不得再作 Core 权威）。
3. 确认 `--config`（gate1_qmt.local.json）指向真实 runtime 配置（Gate 1 已验收的
   version-2 hashed binding）。

## 运行命令（当前 CLI，NODEA-R4 后）

```powershell
# 使用带 xtquant 的 venv；路径仅作示例，请按本机环境替换占位符
$env:PYTHONPATH = "<repo>/src"
& "<venv>/Scripts/python.exe" scripts\gate5_shadow_live.py `
    --config config\gate1_qmt.local.json `
    --strategy-config <trusted-strategy.yaml> `
    --factor-map <trusted-factors.json> `
    --reconciliation-state <trusted-recon.json> `
    --out work\reports\shadow\<date> `
    --date <YYYY-MM-DD> --code <SYMBOL> --run-days 10 `
    --settlement T1            # 或在策略配置中显式 settlement_rule
```

### 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `--config` | ✓ | Gate 1 runtime/binding 配置 |
| `--strategy-config` | ✓ | 可信策略配置；symbol 必须存在（NODEA-R3-002/R4-002） |
| `--factor-map` | ✓ | 逐日因子 JSON；缺日 fail-closed（NODEA-R3-001） |
| `--reconciliation-state` | ✓ | 可信 Core?/Strategic/OpenT 状态（Core 校验见下） |
| `--settlement` | 条件 | 未在策略配置中显式时必填 T0/T1（NODEA-R3-002） |
| `--out` / `--date` / `--code` / `--run-days` | ✓ | 输出目录 / 末日 / 标的 / 回放天数 |

> 注：本运行器仅支持 SH/SZ 市场（`SUPPORTED_MARKETS`）。HK 会话策略未实现，
> 传入非 SH/SZ symbol 会 fail-closed（NODEA-R3-002）。

## 手工接入（ShadowEngine）

```python
from tgrid.shadow import ShadowEngine, build_shadow_reports
from tgrid.strategy.engine import AccumulateStrategy
from tgrid.strategy.bars import SessionWindow

engine = ShadowEngine(
    AccumulateStrategy(cfg.symbols["510300.SH"], cfg.global_config,
                       session_window=SessionWindow(570, 900,
                                                    lunch_start=690,
                                                    lunch_end=780)),
    symbol="510300.SH", core_qty=cfg.symbols["510300.SH"].core_qty,
)
# 每个交易日：仅用 STRICTLY-PRIOR 日线 + 显式逐日因子（NODEA-R4-001）
engine.begin_day(prior_daily_bars, trade_date="2026-08-13",
                 adjusted_to_raw_factor=0.5, daily_price_basis="ADJUSTED")
# 逐 5m bar：
decision = engine.on_bar(bar, broker_position=..., can_use_qty=...,
                         strategic_extra=..., available_cash=...,
                         assume_fill_price=bar.close)
# 收盘后：
reports = build_shadow_reports(engine, trade_date="2026-08-13",
                               broker_positions={"510300.SH": ...},
                               strategic_extras={"510300.SH": ...},
                               open_t_positions={"510300.SH": ...})
```

## 数据/复权/结算纪律（NODEA-R4）

- **无 look-ahead**：日 D 的 basis 只用 `bar_date < D` 的日线；日 D 的 15:00 日线是
  未来信息，绝不参与当日 basis（设计 §9）。
- **显式复权**：日线 `front`（ADJUSTED）、5m `none`（RAW）；因子逐日显式绑定，
  缺日 fail-closed（NODEA-R3-001）。
- **单一 Core 权威**：Core 只来自 `SymbolConfig.core_qty`；reconciliation-state
  若带 `core_qty` 必须与配置精确相等，否则 fail-closed（NODEA-R4-002）。
- **不推断**：Strategic/OpenT 必须来自可信本地状态；未知组件 → UNKNOWN/SAFE_MODE
  输入，绝不静默当 0（INV-006）。

## 5 交易日运行要求（§40）

- 连续 **≥ 5 个完整交易日**（`--run-days 5` 或更大）；
- 每交易日输出四份交付物 + `shadow_delta` + `evidence`（含 factor 注册表摘要、
  settlement、basis、reconciliation_source、run_days）；
- 每日检查 **Reconciliation Report**：`delta != 0` 时必须人工确认原因，不得静默修复；
- 运行结束后汇总：Shadow Orders 与 Signal Log 一致、无未解释对账差异、无 risk 型
  violations，才允许进入 Gate 6。

## 已知客户端限制

- 该 QMT 客户端（sp3 build）不实现 `xtdata.get_trading_calendar`（"function not
  realize"，ErrorID 300000）：交易日历请使用 `get_trading_dates`。
- 5m 历史默认未下载：运行器会先 `download_history_data`（只读数据获取，非交易）。

## 旧证据状态（NODEA-R4-003）

- `LIVE_VERIFICATION.md` 中 `LIVE VERIFIED` 与 +13.3 结果是 **NODEA-R4-001 修复前**
  的历史回放，已标记 `SUPERSEDED`；不作为当前 Gate-5 验收证据。
- 当前可接受证据类别：`REAL_QMT_REPLAY_VERIFIED`（历史回放 + 真实券商快照）；
  `LIVE_SOAK_VERIFIED`（连续 wall-clock live-soak）为未来独立里程碑。

## 退出条件

- 全部 5 日对账一致 → 将证据归档并申请 Gate 6。
- 任一日出现无法解释的 delta / risk violations / 异常 → 停止 Shadow 运行，修复后重新累计 5 日。
