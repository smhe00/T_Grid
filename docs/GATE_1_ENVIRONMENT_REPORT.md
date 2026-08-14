# Gate 1 环境与 API 边界调查报告

> 任务：`G1-T001 — QMT 只读环境与 API 边界调查`
> 状态：**调查完成，待架构师 Review**（本任务为只读调查，未建立任何 QMT 连接）
> 日期：2026-08-14
> 基线 commit：`34169aa9873af9ae7f94994ed7301956d491585d`
> 完整命令输出：`work/reports/tests/G1-T001-environment-probe.txt`

本报告是**离线环境/API 边界调查结论**，不是 Gate 1 接入通过声明。当前阶段未连接 QMT、
未读取账号/行情、未创建任何交易实例，所有能力结论均以**静态存在（AVAILABLE_UNVERIFIED）**
或**待显式输入（NEEDS_EXPLICIT_INPUT）**标注，不得把静态存在误报为真实可用。

---

## 1. 调查方法

1. 记录当前可执行解释器、Python 版本与 `sys.path` 来源摘要。
2. 用 `importlib.util.find_spec` 检查 `xtquant` / `xtquant.xtdata` / `xtquant.xttrader` / `xtquant.xttype`
   在候选解释器中的可用性（`find_spec` 只查询 import 系统，**不导入**模块）。
3. 对已安装的 XtQuant 包源文件做 **AST 离线反射**（`ast.parse` 枚举类/方法/签名），
   **从未执行 `import xtquant`**，不创建 `XtQuantTrader`，不调用 `connect/start/subscribe`，不查询任何数据。
4. 只检查 PATH / Python launcher 和仓库内已有文档/脚本引用的解释器与 API（父仓库
   `docs/etf_qmt_preflight.md`、`scripts/etf_qmt_readonly_health.py`），未递归扫描整盘。
5. 记录后续真实只读验证所需显式输入；报告不含真实账号 ID、凭据或私密配置值。

## 2. 解释器环境

| 项目 | 值 |
|---|---|
| TGrid 默认解释器（`python`） | `C:\Users\peter\AppData\Local\Python\pythoncore-3.12-64\python.exe` |
| 版本 | Python 3.12.10（64 位，win32） |
| `sys.prefix` / `base_prefix` | `C:\Users\peter\AppData\Local\Python\pythoncore-3.12-64` |
| `sys.path` 摘要 | 仅 pythoncore 自带目录 + 工作目录；`site-packages` 位于 pythoncore 之下 |
| Windows launcher | Python 3.12.10（默认）、3.11.9 可用 |
| 父仓库引用解释器 | `D:\gitee\miniQMT\.venv\Scripts\python.exe`（3.12.10）、`.venv-bigquant\Scripts\python.exe`（3.11.9） |

### 2.1 `find_spec` 结果（未导入）

| 解释器 | xtquant | 结论 |
|---|---|---|
| TGrid 默认 3.12.10（pythoncore） | MISSING（spec None） | 该解释器**不含** XtQuant |
| `.venv` 3.12.10（父仓库引用） | **FOUND**（`site-packages\xtquant`，含 xtdata/xttrader/xttype） | 兼容解释器已具备 XtQuant |
| `.venv-bigquant` 3.11.9 | MISSING | 不含 XtQuant |
| launcher 3.11.9 | MISSING | 不含 XtQuant |

> **关键结论**：TGrid 默认解释器没有 XtQuant；仓库引用且唯一具备 XtQuant 的解释器是
> `D:\gitee\miniQMT\.venv\Scripts\python.exe`（Python 3.12.10）。这只证明**静态存在**，
> 不证明连接或数据验收通过。

## 3. 只读 Capability Matrix

对安装的 XtQuant 包（`.venv` 3.12.10）做 AST 离线反射（未导入），确认下列候选只读 API
**静态存在**。状态统一标注 `AVAILABLE_UNVERIFIED`（静态存在，尚未真实验证）或
`NEEDS_EXPLICIT_INPUT`（依赖运行前必须提供的输入）。

| 能力 | 候选 API（静态存在） | 签名摘要 | 状态 |
|---|---|---|---|
| 连接 | `XtQuantTrader.connect` / `start` / `run_forever`；`xtdata.connect` | `connect(self)`；`xtdata.connect(ip, port, remember_if_success)` | AVAILABLE_UNVERIFIED（需本地 QMT 客户端运行 + userdata 路径） |
| 行情 | `xtdata.get_full_tick` / `get_market_data` / `get_market_data_ex` / `subscribe_quote` / `unsubscribe_quote` | `get_full_tick(code_list)`；`get_market_data(field_list, stock_list, period, ...)` | AVAILABLE_UNVERIFIED |
| 资产 | `XtQuantTrader.query_stock_asset` | `query_stock_asset(account)` | AVAILABLE_UNVERIFIED |
| 持仓 | `XtQuantTrader.query_stock_positions` | `query_stock_positions(account)` | AVAILABLE_UNVERIFIED |
| 委托 | `XtQuantTrader.query_stock_orders` | `query_stock_orders(account, cancelable_only)` | AVAILABLE_UNVERIFIED |
| 成交 | `XtQuantTrader.query_stock_trades` | `query_stock_trades(account)` | AVAILABLE_UNVERIFIED |
| 断线识别 | `XtQuantTraderCallback.on_disconnected` / `on_connected` / `on_account_status` | 回调签名静态存在 | AVAILABLE_UNVERIFIED |
| 企业行动/复权 | `xtdata.get_divid_factors` / `get_instrument_detail` | `get_divid_factors(stock_code, start_time, end_time)` | AVAILABLE_UNVERIFIED |
| 交易日历/交易时段 | `xtdata.get_trading_calendar` / `get_trading_dates` / `get_trading_period` | `get_trading_calendar(market, start_time, end_time)` 等 | AVAILABLE_UNVERIFIED |
| 行情新鲜度 | tick/market_data 时间字段（候选字段需实盘核验） | — | NEEDS_EXPLICIT_INPUT（需指定验证标的与口径） |
| 只读验证标的 | — | — | NEEDS_EXPLICIT_INPUT（需用户指定） |

**能力结论**：全部候选只读能力在 `.venv` 3.12.10 中**静态存在**，但均未真实验证。
仓库引用的只读健康检查（`scripts/etf_qmt_readonly_health.py`）已实践其中部分能力
（`xtdata` 连接、交易日历/日线、账户数量/类型/状态），可作为后续真实只读接入的机制参考。

## 4. 后续只读验证所需显式输入（不填写/不猜测真实值）

1. **兼容 XtQuant 的 Python/启动方式**：使用 `D:\gitee\miniQMT\.venv\Scripts\python.exe`
   （Python 3.12.10，已含 XtQuant）；或为 TGrid 默认解释器补充 XtQuant（安装行为不在本任务范围内）。
2. **QMT userdata 路径**：仓库预检以 `--qmt-path <QMT_SIM_USERDATA_MINI>` 传入模拟目录的
   `userdata_mini` 路径；TGrid 需在验证时提供该路径真实值。
3. **账号类型与经脱敏的账号选择**：账号类型（证券/信用/期权等）及经脱敏的账号选择，
   通过本地 SHA-256 账户指纹白名单配置文件（`config/*.local.json`）匹配，不保存/输出账号明文。
4. **只读验证标的**：指定用于只读行情/复权核验的标的清单（如冻结 ETF 清单或特定证券代码）。
5. **客户端运行前提**：本地 QMT 客户端必须已启动，行情服务来自本机 QMT 安装目录；
   未运行时连接/数据读取无法成功。

以上均为**待填项**，本报告未填写任何真实值。

## 5. 最小只读 allowlist（下一任务候选）

```text
# 连接
XtQuantTrader.start
XtQuantTrader.connect
XtQuantTrader.run_forever
xtdata.connect

# 只读查询（不产生任何订单副作用）
XtQuantTrader.query_stock_asset
XtQuantTrader.query_stock_positions
XtQuantTrader.query_stock_orders      # 只读查询，不得因名称含 order 误判为报单
XtQuantTrader.query_stock_trades
xtdata.get_full_tick
xtdata.get_market_data / get_market_data_ex
xtdata.subscribe_quote / unsubscribe_quote
xtdata.get_divid_factors
xtdata.get_instrument_detail
xtdata.get_trading_calendar / get_trading_dates / get_trading_period
xtdata.get_stock_list_in_sector

# 生命周期
XtQuantTrader.stop
```

## 6. 无条件 forbidden list

```text
order_stock
order_stock_async
cancel_order_stock
cancel_order_stock_async
cancel_order_stock_sysid
cancel_order_stock_sysid_async
cancel_order
任何名称或语义等价的报单、撤单、改单方法
```

上述方法在安装的 XtQuant 中**静态存在**（见 probe 输出第 69–75 行），本调查只确认其存在
并列入 forbidden，**绝不允许调用**。静态 API 检查未实例化 trader，未发生 connect/query/subscribe。

## 7. 安全与范围验证

| 检查 | 结果 |
|---|---|
| 未连接 QMT / 未启动进程 | 通过（全程 AST/`find_spec`，未执行任何 XtQuant 代码） |
| 未 `import xtquant` / 未实例化 trader | 通过 |
| 未读取账号、行情或私密配置；报告无敏感值 | 通过 |
| 未安装/下载依赖（无 pip/conda） | 通过 |
| 未修改生产代码/测试；Git diff 仅含 Allowed Files | 通过 |
| `git diff --check -- T_Grid` | exit 0 |
| AST 扫描 `src/tgrid/**/*.py`（13 文件）：无 `ast.Assert`、无 `xtquant` import、无 order/cancel 调用 | PASS，exit 0 |
| 完整 Gate 0 回归（AC8 声明无需重跑，本轮为完整性补跑） | `Ran 223 tests ... OK`；`compileall -q src tests` exit 0 |
| HEAD 与基线 | `34169aa...` == base，一致 |
| `live_trading_allowed` | 保持 `false` |

完整命令与输出见 `work/reports/tests/G1-T001-environment-probe.txt`（112 行）。

## 8. 环境就绪结论

- **TGrid 默认解释器**未安装 XtQuant → 按 Acceptance Criteria 5，**该解释器环境未就绪**，
  不声称 Gate 1 接入成功。
- **父仓库 `.venv`（3.12.10）**已安装 XtQuant，是唯一兼容解释器；其候选只读 API 静态存在
  （AVAILABLE_UNVERIFIED），真实只读连接与数据验收仍需本地 QMT 客户端运行并提供第 4 节输入。
- 本任务未建立任何连接，未产生真实交易风险；Gate 1 真实只读接入留给后续任务。

## 9. Recommendations

1. 下一只读接入任务应以 `.venv`（3.12.10）为运行解释器，先做连接 smoke（`xtdata.connect` +
   `XtQuantTrader.start/connect`），确认断线识别与行情新鲜度字段，再扩展查询矩阵。
2. 所有账号匹配沿用父仓库的 SHA-256 指纹白名单机制，不落明文账号。
3. 保持 `live_trading_allowed=false`，禁止清单（第 6 节）不可弱化。
