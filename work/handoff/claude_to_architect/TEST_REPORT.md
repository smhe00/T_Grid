# Test Report — G2-T001 / Iteration 2

## Task
G2-T001 — 离线不可变 Core Position Guard（Iteration 2 修复 REV-G2T001-001 至 -004）

## Environment
- 默认 Python 3.12.10；纯离线，无 XtQuant import。

## Commands Run（完整输出见 `work/reports/tests/G2-T001-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **523 项全部 OK**（514 + 9 净增） |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（23 文件） | PASS：无 assert / 字面 xtquant import / order-cancel / subscribe / download |
| `git diff --check -- :/T_Grid` | exit 0 |
| HEAD 与基线 | `20e00c1...` == base |

## Iteration 2 新增/更新测试

### TestStrategicIsolation（REV-001，5 项）
- strategic-only（T=0）：`available_t_qty=0`，任何正卖出（1/100）→ `CoreFloorViolation`。
- mixed（strategic=100/open_t=100）：`available_t_qty=100`，sell=100 通过，sell=101/200 → `CoreFloorViolation`。
- reserved mixed（reserved=40/can_use=800）：`available_t_qty=60`，sell=60 通过、sell=61 →
  `SellReservationConflict`、sell=101 → `CoreFloorViolation`。
- Strategic/Core 不被重分类或修改（失败后字段不变）。

### TestSymbolConfigBinding（REV-002，5 项）
- `snapshot_from_symbol_config`：core 精确取自 `SymbolConfig.core_qty`。
- 签名无 `core_position`/`core` 参数（inspect.signature）——调用者无法制造 core 漂移。
- wrong config 类型 → `PositionInvariantError`。
- 原配置保持 frozen；非 plain-int core（True）→ `PositionInvariantError`。

### REV-003 重命名
- `open_t_lots` → `open_t_lot_position`（字段/构造/测试/文档同步，无旧 alias）。

### REV-004 越权撤销
- `src/tgrid/risk/__init__.py` 的 G2-T001 改动已撤销；Git 范围仅 Allowed Files + 协议控制/报告。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 523 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（23 文件） |
| Strategic 隔离 / SymbolConfig 绑定 / 重命名 / 越权撤销 | PASS |
| 无真实 QMT/DB/账号访问 | 通过（纯合成数据） |

## 结论
REV-G2T001-001 至 -004 已修复并有离线回归证据。REVIEW_READY（iteration=2）。
