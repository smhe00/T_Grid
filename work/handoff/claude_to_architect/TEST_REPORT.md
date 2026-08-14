# Test Report — G1-T006 / Iteration 6

## Task
G1-T006 — 真实 MiniQMT 只读验收（Iteration 6 最小离线修复；无任何 QMT 访问）

## Environment
- 默认 Python 3.12.10；`src/tgrid` 可无 XtQuant 离线导入。
- 全部测试使用 fake trader/xtdata/xtconstant/xttype 与临时文件，直接运行既有固定 Probe。

## Commands Run（完整输出见 `work/reports/tests/G1-T006-test-output.txt`）

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -p "test_*.py" -v` | **475 项全部 OK** |
| `python -m compileall -q src tests` | 退出 0 |
| AST 扫描 `src/tgrid/**/*.py`（21 文件） | PASS：无 assert / 字面 xtquant import / order-cancel / subscribe / download |
| 敏感值扫描（G1-T006 交付物） | CLEAN |
| `git diff --check -- :/T_Grid` | exit 0 |
| HEAD 与基线 | `237d312...` == base |

## Iteration 6 变更与验证（REV-019）

### runner 无 probe 注入
- `inspect.signature(run_gate1_readonly_acceptance)` 无 `probe` 参数；调用者无法替换 Probe 伪造成功。

### 固定 Probe 直接运行（fake trader/xtdata）
- 成功路径：固定 15 步，底层 stop=1。
- cleanup RuntimeError → 安全 data-free 失败（无 false PASS、secret 零泄漏）。
- cleanup KeyboardInterrupt → 原样传播（无 false PASS）。
- 固定 Probe asset 查询失败 / calendar 失败 → 安全 data-free 错误，secret 零泄漏。

### 复用验证
- 完整生命周期（15 步 + at-most-once cleanup + 异常净化 + BaseException 传播）直接来自既有
  `run_gate1_readonly_probe`（G1-T005 合同）；runner 无重复生命周期。未新增平行 abstraction；
  仅为代码/模式复用，非交易执行授权。

## 历史真实结果（脱敏）
见 `G1-T006-test-output.txt` 末尾：1–12 步 PASS；calendar/period UNSUPPORTED；dates PASS（prior
auxiliary）。Iteration 6 未做任何真实 QMT 调用。

## 结果汇总
| 检查项 | 结果 |
|---|---|
| 475 项 unittest | OK |
| compileall | exit 0 |
| AST 安全扫描 | PASS（21 文件） |
| REV-019 Failure Injection | PASS（无 false PASS、无 secret 泄漏） |
| 敏感数据零泄漏 | PASS |

## 结论
REV-G1T006-019 已修复并有离线回归证据。REVIEW_READY（iteration=6）。
