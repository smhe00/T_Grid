# reverse_repo QMT 实盘调用方案研究报告

**研究对象**：`D:\gitee\miniQMT\reverse_repo`（已验证的 QMT 实盘/模拟交易代码）
**pinned commit**：`c9ecc701d9b1c47d6a8d03539b482368741204a3`
**研究日期**：2026-08-15

> 本报告是 Node B 审计指定的 QMT 行为基线的完整梳理。重点：**这些代码如何调用
> XtQuant 交易接口**，以及 TGrid 当前实现与其的差距（可吸收项）。

---

## 1. QMT 连接与启动序列

```python
# gc001_live_daily_90pct_093042.py:610-620
xtdata.enable_hello = False                                    # 关心跳问候
trader = XtQuantTrader(
    str(qmt_path),                                             # QMT userdata 目录
    random.randint(100_000_000, 999_999_999),                  # session id: 9 位随机 int
    MorningPushCallback(),                                     # 回调类作第 3 位置参
)
trader.start()
connect_result = int(trader.connect())
if connect_result != 0:
    raise ExecutionSafetyError(f"QMT connection failed: {connect_result}")
```

- 路径必须是已存在的目录；session id 用 9 位随机整数（bootstrap、压力测试一致）。
- **connect 返回值必须 `== 0`**（精确 int），否则 fail-closed。
- 连接时机：目标执行时刻（09:30:42）**提前 60 秒**连接（`CONNECT_LEAD_SECONDS=60`）。

### 账号选择（select_bound_account，core:831-912）

```python
normal_ids = {
    id for s in query_account_status()
    if int(s.account_type) == int(xtconstant.SECURITY_ACCOUNT)
    and int(s.status) == int(xtconstant.ACCOUNT_STATUS_OK)
}
selected = [
    i for i in query_account_infos()
    if int(i.account_type) == int(xtconstant.SECURITY_ACCOUNT)
    and i.account_id in normal_ids
    and account_id_fingerprint(i.account_id) == binding.account_id_fingerprint
]
if len(selected) == 1:
    return xttype.StockAccount(account_id, "STOCK"), binding
```

- 三重过滤：`SECURITY_ACCOUNT` 类型 + `ACCOUNT_STATUS_OK` 状态 + **SHA-256 指纹匹配**。
- 恰好 1 个才返回；否则重试 3 次（间隔 3s）后抛 `AccountBindingError`。
- 返回 `xttype.StockAccount(account_id, "STOCK")`。

### 订阅

```python
subscribe_result = int(trader.subscribe(account))
if subscribe_result != 0: raise ExecutionSafetyError(...)     # 0 = 成功
quote_sequence = int(xtdata.subscribe_quote(GC001, period="tick", count=0) or 0)
if quote_sequence <= 0: raise ExecutionSafetyError(...)       # 序号 >0 才成功
```

---

## 2. 下单调用链（order_stock）

### 精确参数映射（8 位置参数）

```python
# gc001_live_daily_90pct_093042.py:1234-1244
order_id = int(trader.order_stock(
    account,                                # xttype.StockAccount
    GC001,                                  # "204001.SH"
    xtconstant.STOCK_SELL,                  # order_type (23买/24卖)
    int(intent["qmt_volume"]),              # 手数 = 本金 // 100
    xtconstant.FIX_PRICE,                   # price_type: 11 限价
    float(intent["limit_rate_percent"]),    # 限价
    STRATEGY_NAME,                          # ≤23 字符 ASCII
    remark,                                 # f"{prefix}{attempt:04d}"
))
```

### 返回值处理（核心安全模式）

```python
if order_id <= 0:                          # QMT 约定 ≤0 = 提交被拒
    orders = query_all_orders_strict(trader, account)     # ⚠ 不直接放弃
    recovered = find_unique_order_by_remark(orders, remark)
    if recovered is None:
        halt(SUBMIT_REJECTED, ...)         # 确认真没受理 → 停机
    # 否则：券商实际已受理 → 用查询到的 order id 恢复
    order_id = recovered.order_id
# 受理成功后立即单笔回查，核验 symbol/strategy/remark/order_type 四要素
accepted = query_order_strict(trader, account, order_id)
```

**关键差异（TGrid 可吸收 #1）**：`order_stock` 返回 ≤0 时**不能直接判定失败**——先全量
查询按 remark 唯一匹配，若券商实际已受理则以查询到的 id 恢复；只有确认无匹配才停机。

### 提交异常 → 禁止自动重试

```python
except Exception as exc:
    apply(SUBMIT_EXCEPTION, ...)
    return _recover_unknown_submission(...)   # 只做查询恢复(5次attempts)
```

`_recover_unknown_submission`（:1309-1372）：严格查全部订单按 remark 找唯一订单，按其
状态分类推进（ACTIVE/CANCEL_PENDING/TERMINAL）；**找不到匹配也停机（RECOVERED_NO_MATCH），
绝不自动重发**——因为 durable intent 已落盘，订单可能迟到。

---

## 3. 撤单调用链（cancel_order_stock）

```python
# gc001_live_daily_90pct_093042.py:1529-1586
controller.apply(CANCEL_REQUESTED, ...)                    # ① durable intent 先落盘
try:
    cancel_result = int(trader.cancel_order_stock(account, order.order_id))
except Exception: halt(CANCEL_REJECTED, ...)
journal.update_data(cancel_result=cancel_result)
if cancel_result != 0:                                    # ② 撤单被拒
    latest = query_order_strict(trader, account, order.order_id)   # ③ 重查
    if latest.classification in {FILLED, TERMINAL_PARTIAL, CANCELED_ZERO, REJECTED}:
        apply(CANCEL_TERMINAL, ...)                       # 实际已终态 → 接受
        return latest
    halt(CANCEL_REJECTED, ...)                            # 否则停机
return _wait_cancel_terminal(...)                         # ④ 受理后轮询终态
```

- 参数 `(account, order_id)`；返回 **0 = 受理**，**非 0 = 被拒**（不硬编码 -1，判 `!= 0`）。
- 被拒时**先重查**：若实际已到终态（成交/已撤/废单）按终态接受，绝不假设撤单成功即零成交。
- **撤单意图先持久化（CANCEL_REQUESTED）再执行外部副作用**。
- `_wait_cancel_terminal`：15 秒内单笔查询 + 推送信号双通道等终态；超时 `CANCEL_TIMEOUT` 停机。

---

## 4. 查询调用链

| QMT 接口 | 封装 | 用法 |
|---|---|---|
| `query_stock_orders(account, cancelable_only)` | `query_all_orders_strict` | `cancelable_only=False` 全量，strict_query 3 次 |
| `query_stock_order(account, order_id)` | `query_order_strict` | 单笔回查 |
| `query_stock_asset(account)` | `query_asset_strict` | 现金快照，保守 min |
| `query_account_infos()` / `query_account_status()` | strict_query 内联 | 账号绑定/选择 |
| `query_stock_positions(account)` / `query_stock_trades(account)` | 直接调用 | 持仓/成交 |

### strict_query 语义（core:659-683）——TGrid 已对齐

```python
for attempt in range(1, attempts + 1):
    try: result = operation()
    except Exception as exc: errors.append(...)
    else:
        if result is not None: return result
        errors.append("None")          # None 与异常同等对待
    if attempt < attempts: time.sleep(delay_seconds)
raise BrokerQueryAmbiguous(...)        # 3 次后抛模糊错误
```

- **None 永不等于空成功**；默认 3 次重试（0.15s）；空列表是合法结果。
- 查询失败 → `BrokerQueryAmbiguous` → 上层 halt，绝不猜结果。

### 订单状态码与分类（core:273-305, 451-469）

```python
48 未报 / 49 待报 / 50 已报 / 51 已报待撤 / 52 部成待撤 / 53 部撤 /
54 已撤 / 55 部成 / 56 已成 / 57 废单 / 255 未知
ACTIVE={48,49,50,55}  PENDING_CANCEL={51,52}  TERMINAL={53,54,56,57}
```

`classify_order` **先看成交量**（traded>=volume 即 FILLED）再看状态；53/54 终态按是否
有成交量分 `TERMINAL_PARTIAL`/`CANCELED_ZERO`；兜底 `UNKNOWN`。

### 保守现金

`read_cash_snapshot`：取 `cash/available_cash/total-market-frozen` 的**最小值**作为
`conservative_available_cash`——下单预算上限基准，宁可少下不可超支。

---

## 5. 账号绑定（bootstrap_repo_account_binding.py）

- 环境校验：**simulation 路径必须含"模拟"，live 路径必须不含**（双向硬校验，core:848-863）。
- 账号从 `query_account_infos` + `query_account_status` 交叉确认，恰好 1 个 `SECURITY_ACCOUNT` + OK。
- 指纹算法：
  - `account_id_fingerprint = sha256("miniqmt-account-v1:" + 账号ID)`（域名前缀防彩虹表）
  - `qmt_path_fingerprint = sha256(normcase(resolve(path)))`（Windows 大小写归一）
- 绑定文件 version=2，**含明文 `account_id` 字段直接拒绝**；指纹须 64 位小写 hex。
- 路径指纹不匹配即拒绝（防止用错误 QMT 实例跑生产）。
- 原子写：`.tmp` + fsync + `os.replace`（Windows PermissionError 重试 20 次）。

---

## 6. 交易时段与日期校验

```python
# core:1050-1065 — 交易日（注意用 get_trading_dates，非 get_trading_calendar）
def is_exchange_trading_day(xtdata, trade_date):
    result = xtdata.get_trading_dates("SH", stamp, stamp, count=-1)
    if result is None: raise BrokerQueryAmbiguous(...)   # None = 模糊，不是非交易日
    return bool(list(result))
```

- 主脚本在连接前检查：非交易日且 PREFLIGHT → `NON_TRADING_DAY` 正常退出（exit 0）；
  已有非终态 journal 却变非交易日 → 停机 `RECOVERY_AMBIGUOUS`。
- 执行时段：`is_first_execution_time` 09:30–11:28 / 13:00–15:28；deadline = 触发+5 分钟且不越收盘。
- 日期一致性：`trade_date` 必须等于本地日历日期（`gc001...:350-352`）。

**TGrid 可吸收 #2**：`get_trading_calendar` 未实现时应像 reverse_repo 一样用
`get_trading_dates`（TGrid 已有该替代）。

---

## 7. 状态机（repo_execution_state_machine.py）

- Morning 17 态 / 33 事件；Afternoon 17 态 / 34 事件。
- `RECOVERY → (CLEAR|ACTIVE|CANCEL_PENDING|TERMINAL|AMBIGUOUS→HALTED)`。
- **`SUBMIT_UNKNOWN` 状态**专门处理"提交结果未知"（对应 order_stock 异常/负返回歧义）。
- **`RESTART` 事件从任何状态回到 RECOVERY**，由 journal 恢复。
- 进入 `HALTED`（safe_halt）的事件：FAULT/DEADLINE/NO_FUNDS/ORDER_QUERY_AMBIGUOUS/
  CANCEL_TIMEOUT 等；`SUBMIT_EXCEPTION` 进 SUBMIT_UNKNOWN（恢复查不到匹配→HALTED）。
- `verify_state_machines` 显式穷举到不动点，产出转移/源码双 sha256；journal 校验代码
  变更后不再被信任。

**TGrid 可吸收 #3**：TGrid 的 SAFE_MODE 是二元布尔；reverse_repo 用完整状态机 +
`SUBMIT_UNKNOWN` + journal 驱动的 `RESTART→RECOVERY`，更完整地表达"提交结果未知"。

---

## 8. 模拟 vs 实盘 + 实盘 canary（对应 TGrid Gate 6）

```python
# gc001_live_daily_90pct_093042.py:356-386 — live channel certification
if args.live_channel_certification:
    if args.environment != "live": raise ValueError(...)
    if args.remark_root != "repo_live_cert": raise ValueError(...)
    certification_prefix = f"{remark_root}_{trade_date:%Y%m%d}_"
    # 每次认证尝试唯一命名空间 repo_live_cert_YYYYMMDD_HHMMSS_
    if int(args.maximum_principal_yuan) != 1000: raise ValueError("hard-capped at CNY 1,000")
    if float(args.cash_usage_ratio) != 1.0: raise ValueError(...)
```

- **实盘极小验证 = 1000 元硬顶 + ratio 1.0 + 每次唯一 remark 命名空间**——这是 TGrid
  Gate 6 极小真实资金验证的直接参照。
- 常规实盘默认 `--cash-usage-ratio 0.90`；模拟/canary 有 `--maximum-principal-yuan` 上限。
- 模拟/实盘通过：路径"模拟"字样 + binding environment + 三重复合隔离。

---

## 9. 与 TGrid 当前实现的差距（可吸收清单）

| # | reverse_repo 模式 | TGrid 现状 | 建议 |
|---|---|---|---|
| 1 | `order_stock` 返回 ≤0 → 反查 remark 恢复，不直接判失败 | TGrid 桥 `place_order` 对 ≤0 直接 `raise BrokerOrderRejectedError` | **高优先级**：负返回歧义恢复 |
| 2 | `get_trading_dates` 判交易日（None→模糊） | TGrid 已知用 `get_trading_dates` 替代 | 已在 Shadow 层实现 |
| 3 | 完整状态机 + `SUBMIT_UNKNOWN` + journal 驱动 `RESTART→RECOVERY` | TGrid 二元 SAFE_MODE | 中优先级：Gate 6 前补提交未知状态 |
| 4 | 撤单意图先落盘（CANCEL_REQUESTED）再执行 | TGrid cancel→re-query 已具备，但无持久化意图 | 中优先级 |
| 5 | `_owned_order_identity_error` 逐单身份校验（symbol/strategy/side） | TGrid recovery 校验 remark/UNKNOWN，无 side/strategy 校验 | 低优先级增强 |
| 6 | 实盘 canary 1000 元硬顶 + 唯一 remark 命名空间 | TGrid Gate 6 尚在模拟验证阶段 | **Gate 6 参照** |
| 7 | `classify_order` 先看成交量再状态 | TGrid 用状态码映射 | 已基本一致 |
| 8 | 保守现金 = min(cash, available, total-market-frozen) | TGrid 用 available_cash | 可借鉴 |

---

## 10. 结论

reverse_repo 的 QMT 调用方案核心是：**连接三件套（构造+start+connect==0）、订阅两件套
（subscribe==0、subscribe_quote 序号>0）、下单 8 参数限价、撤单 2 参数、查询一律
strict_query 三连并拒绝 None；所有副作用前先落盘 durable intent；所有非零/非正返回
按 fail-closed 处理；实盘与模拟通过路径"模拟"字样 + binding 指纹 + environment
三重复合隔离**。

TGrid 已对齐其中大部分（BrokerPort、strict query、指纹绑定、UNKNOWN fail-closed、
cancel→re-query、EventQueue 健康）。**最值得在 Gate 6 前吸收的是 #1（负返回歧义恢复）
与 #3（提交结果未知状态）**——这两项直接关系首次真实下单的安全性。
