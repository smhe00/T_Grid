# TGrid — 会话交接摘要（HANDOFF TO NEW SESSION）

> 生成：2026-08-15。用途：本会话上下文接近上限时，新会话从此文件 + git + work/ 无缝续跑。
> 本项目所有状态都固化在 git 与 work/ 目录，不依赖对话记忆。

---

## 1. 项目是什么

**TGrid** — QMT 低频做T交易引擎（A 股/港股做T增强，`ACCUMULATE` 模式，先买后卖）。
设计文档：`TGrid_QMT_低频做T交易引擎开发设计文档_V1.1.md`（设计 §1–§53 全量要求）。

目标：长期核心持仓收益 + 低频波动交易增厚（1%~3%/年），安全边界：Core Floor / T Capacity /
Target Ceiling / 无自动止损 / 无裸卖 / `live_trading_allowed=false`。

---

## 2. 仓库布局（重要）

```
D:\gitee\miniQMT\            <- git 仓库根（gitee 大仓库，含 reverse_repo 等无关项目）
├── T_Grid\                  <- TGrid 的 gitee 侧提交目录（本地 main 跟踪）
├── T_Grid_dsh\              <- 本会话工作区（权威工作目录，测试/开发都在这里）
└── .venv\                   <- 含 xtquant + yaml 的 Python 环境（跑 QMT 用这个）
```

- **git 远端有两个**：
  - `origin` = gitee.com/smhe00/miniqmt.git（大仓库，T_Grid 是子目录）
  - `tgrid-github` = github.com/smhe00/T_Grid.git（**独立 TGrid 仓库，审计用的主仓**）
- 双 Agent 协作协议（GitHub 半自动循环）已废弃为**单 Agent（DSH）+ 独立审计**模式。

---

## 3. 当前 Gate 状态

| Gate | 状态 | 说明 |
|------|------|------|
| G0 项目骨架 | PASS | 配置/模型/异常/日志/CLI/Event Queue/SQLite |
| G1 QMT 只读 | PASS | ReadOnly Adapter + 探针 + Runtime Bridge |
| G2 Position+Ledger+Reconcile | PROVISIONAL/SELF_CERTIFIED | CorePositionGuard、t_lots、audit、writer、对账 |
| G3 策略离线模拟 | PROVISIONAL/SELF_CERTIFIED | VWAP20/EMA20/ATR14、网格、ACCUMULATE、场景 A-D |
| G4 Execution Dry Run | PROVISIONAL/SELF_CERTIFIED | OrderIntent/Reservation、SimBroker、恢复、PnL |
| G5 Shadow 模式 | **AUDIT_READY**（NODE A Iteration 4 修复后，等待复审） | WOULD_BUY/WOULD_SELL、对账分离、复权口径、T+1 |
| G5.5 Real Broker Adapter | **NOT AUTHORIZED / BLOCKED** | 需 Node A 独立 PASS 后才授权 |
| G6 极小真实资金 | **BLOCKED** | Node B 独立 PASS + 用户显式授权 |
| G7 V1 正式运行 | **BLOCKED** | Gate 6 完成并独立通过 |

**当前任务**：`work/control/CURRENT_TASK.md` = Audit Node A Iteration 4 Fixes（已完成，SELF_CERTIFIED）。
**权威状态**：`work/control/WORKFLOW_STATE.yaml`（state=AUDIT_READY, git_head_commit=4e7d04a）。

---

## 4. 审计历程（为什么走到这里）

独立审计（ChatGPT 侧）逐轮验收 Gate 5：

1. `1e1457f` AUD-R1-001..007（复权口径、T+1、对账分离、证据分类、卫生、控制面、exact-type）
   → 修复：`ca68110` → AUDIT_READY
2. `3e40aab` NODEA-001..006（基准确转换、settlement 结转、显式配置、不推断、_tmp 清理、一致性）
   → 修复：`03d3923` → AUDIT_READY
3. `3f7c207` NODEA-R3-001..004（逐日因子、可信策略配置、可信对账分解、控制面）
   → 修复：`4e7d04a` + `e6091ee`（SHA 回填）→ **AUDIT_READY，等待下一轮复审**

**已独立接受的项**（不要再动）：NODEA-002 结转、NODEA-005 _tmp 清理、BasisBinding 一致性、
对账/影子结构分离、无真实下单能力、`live_trading_allowed=false`。

---

## 5. 核心代码模块（全部在 `src/tgrid/`）

```
config.py / models.py         配置（不可变 dataclass，strict fail-closed）
risk/exceptions.py            显式异常层级（TGridError 根）
persistence/                  SQLite：migrations 1-5（bootstrap/t_lots/audit/order_intents/reservations）
  ├── t_lot_writer.py         原子 CAS status+audit writer
  ├── t_lot_transition_policy.py  五边闭集转换策略
position/                     PositionSnapshot / CorePositionGuard / reconcile_position
strategy/                     Gate 3：indicators / grid / corporate_action / quality / halts / engine
  ├── basis_transform.py      ADJUSTED→RAW 基准确转换（NODEA-001/R3-001）
execution/                    Gate 4：store / simbroker / executor / recovery / dryrun
shadow/                       Gate 5：engine / marketdata / settlement / daily_factor
  ├── daily_factor.py        逐日可信因子注册表（NODEA-R3-001）
integrations/qmt_gate1_runtime.py  唯一授权延迟 import XtQuant 的只读桥
```

---

## 6. 测试基线

```bash
python -m unittest discover -s tests -p "test_*.py"   # 840 tests OK
python -m compileall -q src tests                      # exit 0
# AST 能力扫描（src 48 文件）：assert / order_stock / cancel_order_stock / xtquant import = 0 命中
```

新增测试文件（后续轮次）：
- `tests/unit/test_gate5_remediation.py`（AUD-R1）
- `tests/unit/test_node_a_fixes.py`（NODEA-001..006）
- `tests/unit/test_node_a_iter4.py`（NODEA-R3，含策略级 2:1 拆股不变量）

---

## 7. 实机 QMT 情况

- QMT 模拟端已运行（XtMiniQmt 进程，xtdata 连接 127.0.0.1:58610）。
- 用 `.venv` 的 python（含 xtquant）：`D:\gitee\miniQMT\.venv\Scripts\python.exe`。
- Gate 1 只读探针已实机通过（trader 桥 + 账户订阅）。
- Gate 5 shadow 实机回放已验证（510300.SH 10 日：4 条 WOULD 订单、PnL +13.3、对账一致；
  511010.SH 非零持仓 5 日）。
- 已知客户端限制：该 QMT build 不实现 `get_trading_calendar`（用 get_trading_dates 替代）。

实机运行器（重构后，需显式参数）：
```bash
& ".venv\Scripts\python.exe" scripts\gate5_shadow_live.py `
  --config config\gate1_qmt.local.json `
  --strategy-config <可信策略yaml> --factor-map <逐日因子json> `
  --reconciliation-state <Core/Strategic/OpenT json> `
  --out work\reports\shadow\<date> --date <YYYY-MM-DD> --code 510300.SH --run-days 10
```

---

## 8. 安全边界（任何续跑必须保持）

- `live_trading_allowed=false` 全程强制；无真实 order_stock / cancel_order_stock 路径。
- Gate 5.5 / Gate 6 / Gate 7 BLOCKED：**不得实现或引入真实下单/撤单能力**，直到
  NODE A 独立 PASS（G5.5 前）与 NODE B 独立 PASS + 用户授权（真实资金前）。
- 禁止 force push / 历史重写；审计证据不删除。
- 不提交账户 ID/资金/持仓/路径/端口/密钥；`.gitignore` 已全局排除 `*.local.json`、`_tmp/`。

---

## 9. 续跑指引（新会话怎么做）

```bash
# 1. 同步状态
git fetch tgrid-github
git log --oneline tgrid-github/main -5

# 2. 读权威状态
cat work/control/WORKFLOW_STATE.yaml      # state / task / git_head_commit
cat work/control/CURRENT_TASK.md          # 当前任务与完成记录
cat work/gates/GATE_5/NODE_A_REVIEW_ITER3_20260815.md   # 最近一轮审计要求

# 3. 若远端有新审计提交（fetch 后 main 前进）→ 读新 NODE_* 文件，按 CURRENT_TASK 修复
# 4. 否则等待审计；不要自行进入 Gate 5.5
```

**下一步预期**：ChatGPT 对 `e6091ee`（AUDIT_READY）做 NODE A 复审。若 PASS → 授权 Gate 5.5
（真实 Broker Adapter，实现后仍需 NODE B 审计才能碰真实订单）。若 CHANGES_REQUIRED → 读新
审计文件继续修复。

---

## 10. 关键 git 提交速查

```
e6091ee  metadata: record SHA 4e7d04a (NODEA-R3-004)
4e7d04a  NODEA-R3-001..004 fixes (AUDIT_READY)        <- 当前实现 HEAD
3f7c207  audit(nodeA): request gate5 iteration 4 fixes
03d3923  NODEA-001..006 fixes (AUDIT_READY)
3e40aab  audit(node-a): request gate5 remediation iteration 3
910a727  remediation follow-up: live evidence + timestamp fix
ca68110  AUD-R1-001..007 fixes (AUDIT_READY)
1e1457f  audit: gate5 remediation requirements
2f4957b  gates2-5 offline + shadow live-verified
```

本地 gitee main 与远端内容一致（本地 SHA 不同，因历史线不同；内容以
`T_Grid/` 目录为准，工作以 `T_Grid_dsh/` 为准，二者通过复制保持同步）。
