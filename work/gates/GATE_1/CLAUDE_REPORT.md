# Gate 1 / Claude Report — G1-T002

## Status
G1-T002 **Iteration 2 修复完成**（REV-G1T002-001 / -002 均 FIXED），交付 `REVIEW_READY / iteration=2`，等待架构师 Review。

## Iteration 2 修复内容

### REV-G1T002-001（P0）— `from None` 未清除 `__context__`
- 重构所有外部调用为 `_run_client_op(method, *args)`：普通 `Exception` 只返回 `(None, 类型名)` 并标记
  FAILED，**离开 active exception context 之后**才由调用方抛项目异常（`from None`）。
- 因此项目异常在创建时 `sys.exc_info()` 为空，`__cause__ is None` 且 `__context__ is None`，
  原异常 object / message / repr / traceback 从公共异常图中彻底消失。
- `KeyboardInterrupt`/`SystemExit`/`GeneratorExit` 仍先 FAILED 后原样传播，不转成项目异常。
- 覆盖 start/connect/subscribe/query/stop 五条路径，注入唯一 secret 全部断言 cause/context 递归安全。

### REV-G1T002-002（P1）— constructor descriptor 泄漏 + bound methods 未冻结
- constructor 对 8 个固定只读方法改用**字面量属性读取**（无 `getattr`、无运行时派生方法名），每个属性
  读取独立 try/except：普通 `Exception`（含抛异常 descriptor）转安全 `QmtAdapterConfigError`（异常图
  干净），BaseException 不吞。
- 校验通过后把 8 个 bound callable **冻结**进私有 `self._methods`，后续 connect/subscribe/query/stop
  只调用这些固定 callable，**不再重新解析 client 属性**；同时移除 `self._client`，注入 client 彻底
  不出现在实例状态中。
- 新增测试证明：构造后替换 client 目标属性为危险 callable / 指向 order 的转发，Adapter 仍用冻结的
  原方法，危险计数为 0。

## 证据
- 完整输出：`work/reports/tests/G1-T002-test-output.txt`（**287 项全部通过** + compileall exit 0 +
  AST 扫描 PASS + 异常图 probe 全 `cause=None context=None`）。
- `git diff --check -- :/T_Grid` exit 0；HEAD == 基线 `73cbe3b`。

## 范围遵守
未 import xtquant、未连接 QMT、未读行情/账号、未安装依赖、未修改 Gate 0 已验收代码、
未触碰父目录文件、未 commit/push、`live_trading_allowed` 保持 `false`。

## Recommendation
REVIEW_READY（等待 Desktop ChatGPT 独立 Review）。
