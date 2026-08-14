# Gate 1 QMT 只读接入报告

状态：`PASS`（2026-08-14）

## 结论

Gate 1 的真实 MiniQMT 核心验收指标已经满足：simulation 连接、账号哈希绑定、行情、资产、持仓、委托、
成交及失败识别均有真实或独立离线证据。最终 integration runner 仅调用固定只读 Probe，不暴露交易能力。

## 已实现能力

- `ReadOnlyTraderAdapter`：start/connect/subscribe、资产/持仓/委托/成交查询、确定性 stop。
- `ReadOnlyMarketDataAdapter`：八个固定查询面，严格参数验证与安全异常。
- `run_gate1_readonly_probe`：固定 15 步、业务返回零观察、cleanup 至多一次。
- `run_gate1_readonly_acceptance`：simulation-only runtime、reverse_repo version-2 哈希绑定、单次配置
  snapshot、固定 Probe 调用与 data-free summary。

## 真实 simulation 证据

- 历史脱敏运行：固定流程 1–12 步 PASS，覆盖 Gate 1 核心连接和查询指标。
- 最终受控 runner：在真实 simulation 环境启动并以安全 `Gate1ProbeExecutionError` 停止，无业务数据
  泄漏；结果与已知 calendar 能力缺口一致。
- `get_trading_dates` 先前辅助检查可用。
- `get_trading_calendar` / `get_trading_period` 在当前客户端不支持，记录为非阻塞限制。

## 独立验证

```text
475 tests — OK
compileall — PASS
AST safety scan — PASS
git diff --check — PASS
```

Failure Injection 覆盖配置/绑定损坏、账号 0/2 匹配、返回类型欺骗、foreign token、构建失败、查询失败、
cleanup 普通异常与三类 BaseException、恶意 summary 及敏感数据泄漏。

## 安全与授权边界

- `live_trading_allowed=false`。
- 未执行任何下单或撤单；不存在 Gate 1 公开交易入口。
- 账号 ID、QMT 路径、fingerprint 与业务 payload 不写入证据或返回值。
- 复用 reverse_repo 的 runtime/哈希绑定与 QMT 调用模式，但不把复用视为交易执行授权。

## 已知限制

- Gate 2 不得依赖 unsupported calendar/period 方法作关键风控结论。
- 正式 CLI 前应统一 PyYAML 与 XtQuant 依赖环境；本次真实运行使用 TGrid Python 加 reverse_repo 已安装
  XtQuant 包路径完成。

完整裁决与证据索引见 `work/gates/GATE_1/RESULT.md`。
