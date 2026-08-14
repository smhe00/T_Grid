# Closed Fix Request — G1-T002 / Iteration 2

> REV-G1T002-001/-002 已关闭；G1-T002 裁决为 PASS。

只修复异常链 secret 泄漏与注入 client 方法捕获边界；保持现有固定只读 API、状态机和测试。

## P0 — REV-G1T002-001：`from None` 未清除 `__context__`，原始 secret 仍可读取

### Evidence

独立在 start/connect/subscribe/query/stop 注入 `RuntimeError(UNIQUE_SECRET)`。公共文本和 traceback
展示虽已净化，但 Python exception object 仍保留原异常：

```text
start:     cause=None, context=RuntimeError(secret), suppress_context=True
connect:   cause=None, context=RuntimeError(secret), suppress_context=True
subscribe: cause=None, context=RuntimeError(secret), suppress_context=True
query:     cause=None, context=RuntimeError(secret), suppress_context=True
stop:      cause=None, context=RuntimeError(secret), suppress_context=True
```

`raise ... from None` 只抑制 traceback 展示，不会把 `__context__` 置空。调用方仍可通过
`exc.__context__` 读到原 message，违反 Acceptance Criteria 5 和 Required Tests 的 cause/context 安全要求。

### Required Fix / Tests

- 普通 `Exception` 路径在 `except` 中只捕获安全的类型名/状态，离开 active exception context 后再抛
  项目异常；不得保留原 exception object、traceback、repr 或 message。
- start/connect/subscribe/query/stop 各至少覆盖一个 unique secret 注入，断言公共异常图递归安全：
  `__cause__ is None`、`__context__ is None`，文本/输出无 secret。
- KeyboardInterrupt/SystemExit/GeneratorExit 仍须先 FAILED 后原样传播，不得转成项目异常。

## P1 — REV-G1T002-002：constructor descriptor 可泄漏裸异常，验证后的 bound methods 未被冻结

### Evidence

注入 client 的 `connect` 使用会抛 `RuntimeError(UNIQUE_SECRET)` 的 property。constructor 的
`getattr(client, "connect")` 直接执行 descriptor，结果：

```text
type=RuntimeError
secret_in_text=True
```

此外 constructor 已取得并验证 8 个 bound method，却丢弃结果；query 每次重新做属性解析，固定 mapping
仍可被动态 descriptor/后续 mutation 改写，并且 query 的属性解析发生在现有 try/except 之外。

### Required Fix / Tests

- constructor 对 8 个固定字面量属性的读取若抛普通 Exception，转换为安全
  `QmtAdapterConfigError`，exception context/cause 均不携带原异常；BaseException 不得吞掉。
- 成功验证后冻结/保存 8 个 private bound callable，后续只调用这些固定 callable；不得保留或公开通用
  client 转发入口，不得在 query 时重新解析属性。
- 增加 descriptor secret failure 与“构造后目标属性被替换/变成危险 descriptor”测试，证明只使用构造时
  固定映射、无裸异常/secret、无动态逃逸。
- 保持 Adapter 不含交易方法、无 `__getattr__`/generic call/raw client property，危险方法调用计数为 0。

## Iteration 2 Completion

1. 只修 REV-G1T002-001/-002；不新增 QMT/行情/账号真实能力。
2. 完整回归、compileall、AST、异常图和并发清理测试通过，更新完整证据。
3. 不提交 commit；释放 Lease，设置 `REVIEW_READY / owner=architect / iteration=2` 并停止。

---

# Closed Fix Request — G0-T006 / Iteration 2

> REV-G0T006-001 已关闭；G0-T006 与 Gate 0 最终裁决为 PASS。

只修复 Gate 0 认证输出被截断这一项；不得修改任何生产代码、测试或业务报告结论。

## P1 — REV-G0T006-001：声称“完整输出”的证据文件只保存了测试尾部

### Evidence

`work/reports/tests/G0-T006-gate0-certification.txt` 当前统计：

```text
total lines: 79
individual unittest result lines: 26
literal placeholder line: ... ok
summary: Ran 223 tests ... OK
```

任务 Acceptance Criteria 9 和 Required Tests 明确要求保存完整命令输出。当前 artifact 只保留最后
26 条用例并用 `... ok` 代替前 197 条，因此无法从交付证据逐项审计 223 个测试；Test Report 中
“完整输出”“共 79 行”的表述彼此冲突。

架构师已独立运行 223 项测试、compileall、AST、隔离 CLI 和 Event Queue 正常/失败 smoke，功能检查
全部通过。本轮不要求也不允许修改代码，仅修证据完整性。

### Required Fix / Verification

1. 重新运行完整 unittest，并把 stdout/stderr 原样写入认证 artifact；不得 tail、截断、折叠或插入
   `... ok` 占位。
2. artifact 必须逐条包含全部 223 个 `test_... ... ok` 结果及 `Ran 223 tests ... OK` 摘要。
3. 重新保存 compileall、AST、CLI、Event Queue smoke 的真实输出；保持现有通过证据。
4. 更新 Test/Implementation/Claude Gate 报告，准确说明 artifact 是逐条完整输出，并记录实际行数。
5. 不得修改 `src/**`、`tests/**`、`docs/GATE_0_REPORT.md` 或其他非 Allowed Files；不提交 commit。
6. diff/HEAD/Lease 检查通过后设置 `REVIEW_READY / owner=architect / iteration=2` 并停止。

---

# Closed Fix Request — G0-T005 / Iteration 4

> REV-G0T005-005/-006 已由 Iteration 4 关闭；G0-T005 裁决为 PASS。

只修复 start failure 与并发 join 的 handshake 竞态，并移除测试自身的 daemon 线程泄漏。

## P0 — REV-G0T005-005：join 缓存未启动 worker，start failure 后仍调用 Thread.join

### Evidence

确定性交错：start phase 1 已发布 `_worker`/`_starting=True`，并发 join 捕获该对象后等待；随后
`Thread.start()` 抛 RuntimeError，start failure 路径清空 `_worker` 并通知。join 醒来后仍使用等待前
缓存的旧对象：

```text
start_fail_join_race.results={
  start_exc: (EventQueueLifecycleError, failed to start event queue worker: RuntimeError),
  join_exc: (RuntimeError, cannot join thread before it is started)
}
start_fail_join_race.state=FAILED failure_type=RuntimeError
```

start 调用方的安全边界正确，但并发 join 仍泄漏裸 threading exception。

### Required Behavior / Tests

- join 等待 `_starting` 结束后必须在同一 lock 内重新读取 `_worker`/start outcome；若 start 失败且 worker
  已清空，应安全返回 True（无实际线程可等待），FAILED 状态由 `state`/`raise_if_failed` 表达。
- 不得对未 OS-started 的 Thread 调用 `join()`；不得通过捕获其 RuntimeError 来掩盖状态机错误。
- 增加 Event 驱动的 start-pause-then-fail + concurrent join 测试：start 返回安全项目异常，join 无异常并
  返回 True，最终 FAILED/failure_type 正确，唯一 secret 不出现在 exception/stdout/stderr。
- 同时交错 stop + start failure + join，确保无死锁、无虚假 RUNNING、无活线程。

## P1 — REV-G0T005-006：测试故意遗留永不结束的 daemon 控制线程

当前 `test_bounded_join_returns_false_when_start_never_completes` 在 daemon controller 中执行无限循环，
测试断言结束后该线程仍活着：

```text
never_start.join_result=False
never_start.controller_alive_after_test_logic=True
never_start.worker_started=False
```

删除这种不可清理的测试形态。使用可释放 Event 暂停 start，先验证 bounded join 返回 False，再 stop、
release 并 join 所有控制/worker 线程；每个测试结束必须断言其 controller 与目标 thread_name 均无存活线程。

## Iteration 4 Completion

1. 只修 REV-G0T005-005/-006，保持前述修复。
2. 完整运行回归、compileall、AST；测试不得留下 daemon/non-daemon 线程。
3. 设置 `REVIEW_READY / owner=architect / iteration=4`，更新真实时间，释放 Lease并停止。

---

# Closed Fix Request — G0-T005 / Iteration 3

> REV-G0T005-004 的 stop 非阻塞与端到端 deadline 已关闭；start failure join outcome 由
> REV-G0T005-005 继续跟踪。

只修复启动期间 lifecycle lock 导致 `stop()` 与 bounded `join()` 失去时限这一项。

## P0 — REV-G0T005-004：Thread.start 持有 lifecycle lock，stop/join 可被无限阻塞

### Evidence

Iteration 2 将 `worker.start()` 移到 condition lock 内，避免了“RUNNING 但线程未启动”，但
`Thread.start()` 是外部/OS 边界，若其变慢，所有需要该 lock 的 lifecycle 调用都会被阻塞。

独立探针只暂停目标 worker 的 start，然后并发调用 `join(timeout=0.01)` 与 `stop()`：

```text
paused_start.join_done_after_100ms=False
paused_start.stop_done_after_100ms=False
paused_start.results={stop_elapsed: ~0.094, join_result: True, join_elapsed: ~0.094}
```

`join(0.01)` 超过期限近十倍，并且结果取决于 0.01 秒期限之后发生的 stop；`stop()` 也不能及时返回，
违反 stop 不得无限阻塞与 bounded join 契约。

现有 `test_concurrent_start_during_pause_no_second_worker` 在全局 patch `Thread.start` 后直接调用
`t1.start()`/`t2.start()`，控制线程自身也进入 `pausing_start`，依靠 `release.wait(timeout=5)` 超时推进，
测试耗时约 10 秒且没有确定性覆盖目标 worker 的 join/stop 交错。

### Required Behavior / Tests

- 不得在 lifecycle lock 内跨越可能阻塞的 `Thread.start()`；使用私有 starting flag + condition、显式
  handshake 或等价两阶段状态机，仍保证最多启动一个 worker，且不发布虚假 RUNNING。
- start 进行中调用 `stop()` 必须及时返回并记住 stop 请求；worker 真正启动后必须直接进入可清理的
  STOPPING/STOPPED 路径，不接受 stop 之后的 enqueue，不泄漏线程。
- `join(timeout)` 的 timeout 必须约束整个调用，包括等待 start handshake 与实际 thread join；使用单一
  `time.monotonic()` deadline 计算剩余时间。start 未完成而期限到达时返回 False，不能等待到 start 释放。
- 第二个并发 `start()` 不得创建第二 worker；start failure 仍保持 FAILED、type-only、安全 join。
- 重写错误的 pause 测试：patch 只暂停目标 worker（按 thread identity/name 或注入 factory），控制线程用
  未 patch 的原始 start；使用 Event/Barrier 完成交错，不使用 `time.sleep` 或 5 秒 timeout 推进逻辑。
- 至少断言：暂停期间 `join(0.01)` 在合理上界内返回 False；`stop()` 在合理上界内完成；release 后唯一
  worker 退出、最终 STOPPED、无同名存活线程、无裸 threading exception。
- 保持 REV-G0T005-002/-003 修复与全部既有行为，完整运行回归、compileall、AST 并更新报告。

## Iteration 3 Completion

1. 只修 REV-G0T005-004。
2. 设置 `REVIEW_READY / owner=architect / iteration=3`，更新真实时间，释放 Lease并停止。

---

# Closed Fix Request — G0-T005 / Iteration 2

> REV-G0T005-002 与 -003 已关闭；REV-G0T005-001 的裸异常/虚假 RUNNING 部分已修复，但持锁启动造成的
> bounded lifecycle 回归由 REV-G0T005-004 继续跟踪。

只修复以下线程启动原子性、timeout 与异常边界问题，不接入 QMT、CLI、数据库、策略或交易。

## P0 — REV-G0T005-001：RUNNING 在 worker 真正启动前发布，join/start failure 失控

### Evidence

确定性暂停 `Thread.start()`，让 `EventQueue.start()` 已写 RUNNING 但 worker 尚未启动：

```text
start_race.state_before_actual_start=RUNNING
start_race.join_exception=RuntimeError cannot join thread before it is started
```

直接注入 `Thread.start()` 抛含敏感 token 的 `RuntimeError`：

```text
start_failure.exception=RuntimeError THREAD_SECRET
start_failure.state=RUNNING
start_failure.join_exception=RuntimeError cannot join thread before it is started
```

状态发布与真实线程启动不原子，既泄漏标准库异常/原文，也留下无法恢复、无法 join 的虚假 RUNNING。

### Required Behavior / Tests

- 在 lifecycle lock 内完成 worker start 与 RUNNING 发布，或使用显式 STARTING 状态/condition；任何调用方
  不得观察到 RUNNING 但 thread 尚未启动。
- `Thread.start()` 失败必须 fail closed：不得保留 RUNNING，不得泄漏原始异常文本；使用项目异常和稳定
  类型摘要，后续 `join()` 不得泄漏 `RuntimeError` 或死锁。
- 用 Event/Barrier + patched start 确定性交错 start 与 join/stop/第二次 start，证明无裸异常、无第二 worker、
  无遗留测试线程。
- 注入唯一 secret 的 start failure，断言 exception/stdout/stderr 不含 token，状态和 failure_type 一致。

## P1 — REV-G0T005-002：join timeout 未拒绝 NaN / Infinity

任务要求 timeout 为 None 或非负有限实数。当前只检查 `< 0`：

```text
timeout nan accepted_result=True
timeout inf accepted_result=True
```

使用 `math.isfinite`（或等价）拒绝 `nan`、`inf`、`-inf`，统一抛 `EventQueueConfigError`；增加真实阻塞
handler 的 join timeout 测试，必须在 worker 存活时返回 `False`，随后可释放并正常清理。

## P1 — REV-G0T005-003：EventQueueFull 链接并暴露 queue.Full

```text
full.__cause__=Full
```

转换为项目异常时不得将 `queue.Full` 作为公开 cause/traceback 链；抛出稳定 `EventQueueFull`，其字符串、
cause 与打印 traceback 均不暴露 `queue.Full`。测试同时证明 enqueue 仍为非阻塞且队列可正常 drain。

## Iteration 2 Completion

1. 只修 REV-G0T005-001 至 -003。
2. 完整运行回归、compileall、AST 与上述确定性 Failure Injection。
3. 更新完整证据与报告，逐 Issue 标记 FIXED/NOT_FIXED/DISAGREE。
4. 设置 `REVIEW_READY / owner=architect / iteration=2`，更新真实时间，释放 Lease并停止。

---

# Closed Task Start — G0-T005 / Iteration 1

G0-T005 初始任务已实现并完成第 1 轮 Review；以下均为历史 fix request。

---

# Closed Fix Request — G0-T004 / Iteration 4

> REV-G0T004-006 已由架构师独立重放关闭；G0-T004 已 PASS。本文件以下内容均为验收历史。

只修复 logger shutdown 仍可被 cleanup/event 的 `BaseException` 跳过这一项，不新增功能。

## P0 — REV-G0T004-006：最外层 cleanup 不是嵌套 finally，logger 仍可泄漏

### Evidence

Iteration 3 已把 DB close 放入 `finally`，但 `_close_db()`、`shutdown_complete` emit 与
`shutdown_logger()` 仍顺序位于同一个 finally suite。前两者一旦抛出未捕获且不应吞掉的
`SystemExit`/`GeneratorExit`，Python 会直接离开该 suite，跳过 logger shutdown。

独立注入结果：

```text
db_close_system_exit.propagated=9
db_close_system_exit.shutdown_calls=[]
db_close_system_exit.registry_open=(True, True)

shutdown_event_generator_exit.propagated=True
shutdown_event_generator_exit.shutdown_calls=[]
shutdown_event_generator_exit.registry_open=(True, True)
```

### Required Behavior / Tests

- 将 DB close + 条件性 `shutdown_complete` emit 包在内层 `try`，把 `shutdown_logger()` 放在其
  对应的最外层 `finally`，使任何 `BaseException` 都不能跳过 logger shutdown 尝试。
- 不得吞掉或转换 `SystemExit`/`GeneratorExit`；原异常须在 cleanup 尝试完成后原样传播。
- 测试 DB close 抛 `SystemExit`，以及 `shutdown_complete` emit 抛 `GeneratorExit`（或对调）：
  断言异常传播、shutdown_logger 调用一次、registry 为空、真实 log 文件可移动。
- 保持上一轮 failure-event KeyboardInterrupt、startup SystemExit/GeneratorExit 的修复及全部既有行为。
- 完整运行回归、compileall、CLI smoke 与 AST 扫描并更新证据。

## Iteration 4 Completion

1. 只修 REV-G0T004-006。
2. 更新报告并设置 `REVIEW_READY / owner=architect / iteration=4`，释放 Lease 后停止。

---

# Closed Fix Request — G0-T004 / Iteration 3

> REV-G0T004-005 的三条指定入口已关闭；最外层 logger cleanup 缺口由 REV-G0T004-006 跟踪。

只修复一个仍未关闭的资源生命周期问题，不扩大到 Event Queue、QMT、策略或交易功能。

## P0 — REV-G0T004-005：DB cleanup 不在 finally，BaseException 可跳过 close

### Evidence

独立注入在 DB 已获取后让 `preflight_ok` 先抛普通异常，再让 `preflight_failed` emit 抛
`KeyboardInterrupt`：

```text
failure_event_keyboard_interrupt.rc=130
failure_event_keyboard_interrupt.db_close_called=False
failure_event_keyboard_interrupt.logger_registered=False
```

同样在 DB 已获取后由 `preflight_ok` 抛 `SystemExit(7)` / `GeneratorExit`：两者均按契约向外传播，
logger 也完成 shutdown，但 `db_close_called=False`。根因是 DB close 仍是正常控制流中的普通代码块，
只有 logger shutdown 位于 `finally`；任何未被捕获、且按契约不应吞掉的 `BaseException` 都可跳过 DB close。

### Required Behavior / Tests

- DB 成功获取后，close 必须位于覆盖后续 startup、failure-event 和 shutdown-complete emit 的
  `finally`（或等价的不可跳过 cleanup 结构）中；logger shutdown 仍必须是更外层 cleanup。
- `preflight_failed` emit 抛 `KeyboardInterrupt` 时返回 130，并且 DB close 已调用、logger registry
  为空；不得泄漏 primary exception 文本。
- `preflight_ok` 抛 `SystemExit` 或 `GeneratorExit` 时异常必须原样向外传播，不能转成 1/130；但 DB close
  与 logger shutdown 都必须已尝试。
- 增加以上三个回归测试，并对已打开的真实 DB/log 文件验证返回/传播后可移动。
- 完整运行 173 项既有回归、compileall、CLI smoke 与 AST 扫描；修正报告中“已覆盖 failure-event
  KeyboardInterrupt”的不准确陈述。

## Iteration 3 Completion

1. 只修 REV-G0T004-005，不新增功能。
2. 更新完整测试证据与报告，明确 `FIXED`/`NOT_FIXED`/`DISAGREE`。
3. 设置 `REVIEW_READY / owner=architect / iteration=3`，使用真实本机时间，释放 Lease并停止。

---

# Closed Fix Request — G0-T004 / Iteration 2

> REV-G0T004-001 至 -004 的直接问题已修复；本节保留为验收历史。第 2 轮遗漏的 DB cleanup
> BaseException 路径由 REV-G0T004-005 单独跟踪。

只修复以下 CLI 生命周期与输出边界问题，不扩大到 Event Queue、QMT、策略或交易功能。

## P0 — REV-G0T004-001：DB close 失败仍记录 shutdown_complete

### Evidence

注入已成功打开、但 `close()` 抛 `OSError` 的连接：

```text
db_close_failure rc 1
events ['startup_begin', 'preflight_ok', 'shutdown_complete']
```

代码只检查 `primary is None and not interrupted`，没有检查 cleanup failure，因此把未完成 shutdown
写成成功完成，违反成功事件真实性与失败不得伪报成功。

### Required Behavior / Tests

- 只有 DB 已成功关闭且没有 primary/interrupted/cleanup failure 时才允许写 `shutdown_complete`。
- DB close 失败必须返回 1，日志不得含 `shutdown_complete`；logger 仍须 shutdown。
- 可写稳定的 `preflight_failed` 或 `cleanup_failed`（只含异常类型），但不得包含原始异常文本。

## P0 — REV-G0T004-002：KeyboardInterrupt 在 cleanup 阶段会跳过剩余资源清理

### Evidence

注入 `db_conn.close()` 抛 `KeyboardInterrupt`：

```text
interrupt_during_db_close rc 130
logger_registered True
events ['startup_begin', 'preflight_ok']
```

当前 outer `main()` 捕获中断并返回 130，但 `_run_preflight()` 的后续 logger shutdown 没有位于能覆盖
cleanup 自身异常的 `finally`，导致 handler/文件句柄残留。

### Required Behavior / Tests

- logger 建立后，DB close、失败事件写入或其他 cleanup 步骤发生 KeyboardInterrupt/Exception 时，
  后续可独立执行的清理仍必须尝试；不得捕获 `SystemExit`/`GeneratorExit`。
- 使用嵌套 `try/finally` 或等价状态机，保证 DB cleanup 不能跳过 logger shutdown。
- 至少测试 KeyboardInterrupt 发生在 `preflight_ok`（DB 已打开）、failure-event emit、DB close 三个位置；
  返回 130，DB close 与 logger shutdown 调用符合可达顺序，registry 最终为空，文件可移动。

## P1 — REV-G0T004-003：logger 建立前未知异常逃出 main

### Evidence

注入 `configure_jsonl_logger` 抛 `RuntimeError`：

```text
configure_unknown ESCAPED RuntimeError SECRET_CONFIGURE_XYZ
```

`main()` 最外层只捕获 `TGridError` 与 `OSError`，违反未知异常 fail closed 和“受控失败无 traceback”。

### Required Behavior / Tests

- `main()` 在不捕获 `SystemExit`/`GeneratorExit` 的前提下，将其他未知 `Exception` 转为退出 1；
  `KeyboardInterrupt` 仍为 130。
- logger 配置前的 `load_config`/path/configure 未知异常均不得逃出或打印 traceback。
- 正常 argparse `SystemExit(0/2)` 行为保持不变。

## P1 — REV-G0T004-004：未知异常原文泄露到用户输出

### Evidence

注入 DB 初始化异常：

```text
sensitive_error rc 1
secret_in_stderr True
stderr 'tgrid: error: ACCOUNT_SECRET_XYZ\n'
```

### Required Behavior / Tests

- 对内部未知异常，stderr 只报告稳定、非敏感摘要（至少异常类型），不得输出异常原文、repr、
  traceback、完整配置或注入 secret。
- 已定义的 `TGridError` 可保留经过模块控制的安全消息与字段路径；内部 `RuntimeError`/未知异常必须
  采用安全格式。
- cleanup error 同样适用；测试以唯一 secret token 注入 primary 与 cleanup，断言 stdout/stderr/JSONL
  均不含 token，且退出非零。

## Iteration 2 Completion

1. 只修 REV-G0T004-001 至 -004。
2. 完整运行回归、compileall、CLI smoke、AST 与上述 Failure Injection。
3. 更新完整输出和报告，逐 Issue 标记 `FIXED`/`NOT_FIXED`/`DISAGREE`。
4. 设置 `REVIEW_READY / owner=architect / iteration=2`，使用真实本机时间，释放 Lease并停止。

---

# Closed Fix Request — G0-T003 / Iteration 3

> REV-G0T003-006 与 -007 已由架构师独立验证并关闭；本节仅保留为验收历史。

Iteration 2 已关闭 REV-G0T003-001 至 -005。当前只修下面两项并发生命周期问题。

## P0 — REV-G0T003-006：emit 与 shutdown 竞态可在 shutdown 返回后重开文件并写入

### Evidence

独立探针让 `emit()` 通过 `_resolve_configured_handler()` 后暂停，主线程执行并返回
`shutdown_logger()`、移动已关闭文件，再恢复 emit。结果：

```text
shutdown_race errors []
original_recreated True
handler_reopened True
moved_lines 0
```

旧 `FileHandler` 以 append 模式在 close 后收到 `handle()` 会自动重开原路径；因此 shutdown
返回不再构成可靠关闭边界，事件写到新创建的原路径，且 handler 已不在 registry 中，形成泄漏。

### Required Behavior

- 同一 logger 的“验证 live handler + 完整 emit”与 shutdown/reconfigure 必须有明确原子顺序。
- 若 emit 已先开始，shutdown 必须等待该 emit 完整结束后再关闭并返回；若 shutdown 先完成，
  后续 emit 必须 `LoggingEmitError`，绝不能重开文件。
- shutdown 返回后 registry 不含该 logger、logger 不挂 handler、旧 handler 不持有 stream；文件可移动，
  且等待中的线程不得在旧路径创建新文件。
- 不得用 sleep 作为同步正确性；使用 lock/condition 或等价确定机制。

### Required Test

用 `threading.Event`/barrier 构造上述确定性交错，验证 shutdown 不会越过 in-flight emit；
完成后只有预期的一条完整 JSON，文件句柄关闭且旧路径不被重建。

## P1 — REV-G0T003-007：同名 logger 并发配置产生多个 handler

### Evidence

独立并发探针让两个线程在各自完成“drop none”后同时继续 add/register：

```text
concurrent_config errors []
results 2
handlers 2
registered_is_attached True
```

`_registry_lock` 只保护单次 dict 操作，没有保护 open/drop/add/register 整个状态转换；最终 logger
挂两个 handler，registry 只保存其中一个，另一个无法由 shutdown 管理。

### Required Behavior

- 同一 logger 名称的 configure/reconfigure 必须序列化完整状态转换。
- 任意并发配置完成后，logger 恰好挂一个 TGrid-owned handler，registry 与之同一对象；被替换或失败
  的 handler 全部关闭。
- 不同 logger 可共享实现锁或使用每名锁；正确性优先，不要求本任务优化吞吐。

### Required Test

并发配置同一名称（不同临时路径），全部线程结束后断言：无异常、registry/attached handler 一致、
只有一个 TGrid-owned handler；写一条事件只出现一次；shutdown 后所有候选文件均可移动/删除。

## Iteration 3 Completion

1. 只修 REV-G0T003-006 与 -007，不重复扩大已关闭问题。
2. 保持上一轮五项探针、139 项回归、AST 与 compileall 全部通过。
3. 保存两项确定性并发 Failure Injection 证据并更新报告。
4. 设置 `REVIEW_READY / owner=architect / iteration=3`，使用真实本机时间，释放 Lease并停止。

---

# Historical Fix Request — G0-T003 / Iteration 2

只修复以下 logging fail-closed 与生命周期问题，不扩大到 CLI、Event Queue、QMT 或交易功能。

## P0 — REV-G0T003-001：未配置或已 shutdown 的 logger 会静默丢日志

### Evidence

```text
emit_after_shutdown SILENT_SUCCESS lines 1
emit_unconfigured SILENT_SUCCESS
```

`emit()` 只调用 `logger.handle(record)`，未确认 logger 当前仍绑定由本模块管理的 handler。
调用方收到成功返回，但事件没有写入任何文件，违反成功事件可审计与禁止静默丢日志的契约。

### Required Behavior / Tests

- `emit()` 必须验证传入对象是当前已配置、仍注册、仍挂载对应 TGrid-owned handler 的 logger。
- 从未配置、shutdown 后、传入错误类型或伪造 logger 对象时同步抛 `LoggingEmitError`。
- 验证失败不得创建文件、写半行或发送到 root/其他 handler。
- 正常 logger 与并发写入行为保持通过。

## P0 — REV-G0T003-002：允许名称 `root`，会修改进程 root logger

### Evidence

```text
logging.getLogger("root") is logging.getLogger() -> True
```

当前 `configure_jsonl_logger("root", ...)` 会调用 `setLevel()`、设置 `propagate=False` 并添加
FileHandler，直接违反“不修改 root logger”的契约。任意第三方名称也会被修改。

### Required Behavior / Tests

- logger 名称只允许 `tgrid` 或 `tgrid.` 前缀下的非空名称。
- `root`、空白、`other`/第三方名称必须 `LoggingConfigError`。
- 对所有拒绝情况，root handlers、level、filters 与 propagate 状态完全不变。

## P1 — REV-G0T003-003：FileHandler 打开失败泄漏原始 OSError

### Evidence

```text
open_failure RAW OSError injected open failure
```

### Required Behavior / Tests

- `_JsonlFileHandler(...)` 创建/打开失败必须转换为 `LoggingConfigError` 并保留异常链。
- 用 mock 注入 `OSError`，验证不泄漏裸异常、未注册 handler、旧的已配置 handler（若存在）不受损。

## P1 — REV-G0T003-004：重配置 flush 失败时旧 handler 未 close

### Evidence

```text
reconfigure_flush_failure RAISED LoggingEmitError old_close_called False
```

`_drop_tgrid_handler()` 将 `flush()` 与 `close()` 放在同一顺序 try 内；flush 一旦失败就跳过 close，
且 registry 已 pop，可能留下不可再管理的文件句柄。

### Required Behavior / Tests

- 即使 flush 失败也必须在 `finally`/等价清理路径尝试 close。
- 若 flush/close 任一失败，仍抛明确 `LoggingEmitError`；新建 handler 必须关闭且不得注册。
- 测试必须断言旧 handler 的 close 被调用，并验证 registry/logger 不残留失败 handler。

## P1 — REV-G0T003-005：任意 int 与 bool 被当作合法 level

### Evidence

```text
level True ACCEPTED
level 12345 ACCEPTED
level -7 ACCEPTED
```

### Required Behavior / Tests

- 配置与 emit 只接受明确的标准 logging 整数级别；必须显式拒绝 bool、未知正整数和负数。
- `logging.DEBUG/INFO/WARNING/ERROR/CRITICAL` 必须工作；是否接受 `NOTSET` 由实现选择，但需一致并测试。
- 输出 `level` 必须是标准大写级别名，不能出现 `Level 12345` 等合成值。

## Iteration 2 Completion

1. 只处理 REV-G0T003-001 至 -005。
2. 运行全量回归、compileall、AST 扫描与上述独立 Failure Injection。
3. 更新完整测试输出和报告，逐 Issue 标记 `FIXED`/`NOT_FIXED`/`DISAGREE`。
4. 设置 `REVIEW_READY / owner=architect / iteration=2`，使用真实本机时间，释放 Lease并停止。

---

# Historical Fix Request — G0-T002 / Iteration 4

## P1 — REV-G0T002-001（OPEN）：partial unique index 仍被误判为完整 name 唯一约束

### Evidence

独立探针将内联 `name TEXT NOT NULL UNIQUE` 替换为：

```sql
CREATE UNIQUE INDEX uq_partial_name
ON schema_migrations(name)
WHERE version > 100;
```

`PRAGMA index_info` 仍返回单列 `name`，当前 `_get_unique_index_column_sets` 忽略
`PRAGMA index_list` 的 `partial` 标志，因此 `initialize()` 接受该 schema；但正常 migration
版本并不受这个索引约束，`name` 实际可重复。

```text
partial_unique_name ACCEPTED [(1, 'bootstrap', ...)]
```

### Required Behavior

- 只有覆盖恰好 `("name",)` 且 `partial=0` 的 UNIQUE index 才能满足契约。
- partial unique index 无论谓词为何，均不得被当作完整单列唯一约束。
- 保持 Iteration 3 已通过的 wrong-column、composite、CHECK 行为探针及合法 history 无副作用性质。

### Required Test

- 使用 `WHERE version > 100` 的 partial unique index 必须被 `SchemaVersionError`（或其他明确
  `PersistenceError` 子类）拒绝。
- 合法 bootstrap schema、`UNIQUE(applied_at)`、composite UNIQUE、永真 CHECK 的现有测试继续通过。
- 全量回归、compileall、AST 禁止 API 扫描继续通过。

### Scope / Completion

只修改 `src/tgrid/persistence/database.py`、`tests/unit/test_persistence.py` 及本任务允许的
Claude 报告/测试输出/状态文件。不得进入 logging、CLI、Event Queue、Gate 2 或 QMT。
完成后设置 `REVIEW_READY / owner=architect / iteration=4`，使用真实本机时间，释放 Lease并停止。

---

# Historical Fix Requests

> 下面内容均为已关闭或已被 Iteration 4 取代的历史记录；当前唯一授权是文件顶部的 Iteration 4 Active Fix Request。

# Active Fix Request — G0-T002 / Iteration 2

> Iteration 2 后 REV-G0T002-002、-004、-005 已关闭。REV-G0T002-001 与 -003 保持 OPEN；当前只处理下面的 Iteration 3 Active Fix Request。

# Iteration 3 Active Fix Request

## P1 — REV-G0T002-001（OPEN）：UNIQUE 约束验证未绑定 name 列

### Evidence

伪造 schema 使用：

```sql
CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY CHECK(version > 0),
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL UNIQUE
);
```

列形状正确且 DDL 含 `UNIQUE`，当前 `_verify_bootstrap_schema` 接受。独立行为探针结果：

```text
unique_wrong_column INITIALIZE_ACCEPTED DUPLICATE_NAME_ACCEPTED
```

### Required Behavior

- 验证唯一性约束确实覆盖且只覆盖 `schema_migrations.name`，不得只搜索任意 `UNIQUE` 文本。
- 优先使用 `PRAGMA index_list` + `PRAGMA index_info/index_xinfo` 等 SQLite 结构化元数据。
- 缺失 name 唯一约束、唯一约束落在错误列或错误组合列时必须 `PersistenceError` 子类。

### Required Test

- 上述 `UNIQUE(applied_at)` 伪造表必须拒绝。
- `UNIQUE(name, applied_at)` 但 name 单列不唯一时必须拒绝。
- 合法 bootstrap schema 必须接受。

## P1 — REV-G0T002-003（OPEN）：CHECK 正则接受永真约束

### Evidence

伪造 schema 使用：

```sql
version INTEGER PRIMARY KEY CHECK(version > 0 OR 1=1)
```

当前正则匹配到前缀后接受。行为探针结果：

```text
check_always_true INITIALIZE_ACCEPTED VERSION_ZERO_ACCEPTED
```

### Required Behavior

- 验证数据库实际拒绝 `version=0` 与负数，而不是仅匹配 DDL 文本。
- 建议在 `SAVEPOINT` 内执行约束探针，预期 `sqlite3.IntegrityError`，随后完整 rollback/release；不得留下 probe 行或改变 migration history。
- 若继续解析 DDL，必须能可靠拒绝永真/弱化表达式；不能使用当前前缀正则。
- 验证过程自身出现意外 SQLite 错误时按 persistence 异常边界 fail closed。

### Required Test

- `CHECK(version > 0 OR 1=1)` 伪造表必须拒绝。
- 无 CHECK 表必须拒绝。
- 合法表验证前后 migration history 完全不变。

## Iteration 3 Completion

1. 只修上述两个 OPEN 问题。
2. 完整运行回归、compileall、AST 扫描与两条独立语义 Failure Injection。
3. 更新报告/完整测试输出，逐项回复 `FIXED`。
4. `REVIEW_READY / owner=architect`，释放 Lease并只读等待。

---

# Iteration 2 Historical Request

只修复以下问题，不扩大到 logging、CLI、Event Queue、Gate 2 领域表或 QMT。

## P0 — REV-G0T002-001：版本记录正确时未验证真实 Bootstrap Schema

### Evidence

独立探针初始化合法数据库后执行：

```sql
DROP TABLE application_metadata;
```

再次调用 `initialize(path)` 的结果：

```text
missing_metadata ACCEPTED tables=['schema_migrations']
```

将 migration 1 的名称改成 `not_bootstrap` 后也被接受：

```text
name_tamper ACCEPTED [(1, 'not_bootstrap')]
```

### Why It Matters

`user_version` 与数字版本记录一致并不能证明实际 schema 与代码迁移定义一致。系统会把被删表、错表或被篡改迁移身份的数据库误判为可用，违反 fail-closed 和不可静默修复原则。

### Required Behavior

- 在返回已初始化连接前验证当前版本对应的 Bootstrap Schema Contract。
- `schema_migrations` 与 `application_metadata` 必须存在，列名、关键类型、NOT NULL、PK/UNIQUE/CHECK 约束满足契约。
- migration history 的 `(version, name)` 必须逐项匹配代码中的 `MIGRATIONS`，`applied_at` 必须非空。
- `application_metadata` 必须存在唯一 `project_name=TGrid` 且 `updated_at` 非空。
- 缺表、错列、错约束、改名或 metadata 缺失/篡改必须抛出明确的 `PersistenceError` 子类，禁止自动重建或修补。

### Required Tests

至少新增：删除 metadata 表、删除 project_name、篡改 project_name、篡改 migration name、缺列/错表结构，全部 fail closed。

---

## P1 — REV-G0T002-002：畸形 migration 表泄漏原始 OperationalError

### Evidence

数据库包含：

```sql
CREATE TABLE schema_migrations (wrong INTEGER);
PRAGMA user_version=1;
```

实际结果：

```text
malformed_history WRONG_EXCEPTION OperationalError no such column: version
```

### Required Behavior

- `initialize` / `open_database` 的数据库结构或 SQLite 操作失败必须转换成明确的 `PersistenceError` 子类并保留异常链。
- 不得通过宽泛捕获吞掉 `KeyboardInterrupt`/`SystemExit`，也不得把编程错误伪装为数据库损坏。
- 对已识别的 SQLite schema/查询错误做边界转换并关闭连接。

### Required Tests

验证 wrong-column `schema_migrations`、wrong-column `application_metadata` 均抛 `PersistenceError` 子类而非裸 `sqlite3.Error`，且连接/文件仍可审计。

---

## P1 — REV-G0T002-003：schema_migrations 缺少 version > 0 约束

### Evidence

任务的 Bootstrap Schema Contract 明确要求：

```text
version INTEGER PRIMARY KEY, > 0
```

当前 DDL 没有 `CHECK(version > 0)`，独立探针结果：

```text
version_zero INSERT_ACCEPTED
```

### Required Behavior / Test

- Bootstrap DDL 增加数据库级 `CHECK(version > 0)`。
- 测试插入 version 0 与负数均触发 `sqlite3.IntegrityError`。
- schema contract 验证能识别缺失该约束的伪造表并 fail closed。

---

## P1 — REV-G0T002-004：保存的禁止 API 扫描实际执行失败

### Evidence

`G0-T002-test-output.txt` 包含：

```text
grep: xtquant: No such file or directory
/usr/bin/bash: line 1: from: command not found
/usr/bin/bash: line 1: order_stock(: command not found
```

随后仍打印 `NO forbidden imports/calls`，该证据无效。架构师独立 AST 扫描当前源码确实通过，因此这是测试/报告可信度问题，不代表源码含禁用调用。

### Required Behavior / Test

- 使用 Python AST 测试扫描全部 `src/tgrid/**/*.py`：`ast.Assert`、`xtquant` import、`order_stock`/`cancel_order` Call。
- 命令任一错误必须非零退出，不得在失败后打印 PASS。
- 重新生成完整测试输出，不保留上述伪成功文本。

---

## P1 — REV-G0T002-005：journal mode 测试把 off/memory 视为安全

### Evidence

当前测试允许：

```python
{"delete", "wal", "truncate", "persist", "memory", "off"}
```

`OFF` 不提供回滚日志保护，`MEMORY` 也不满足文件数据库 crash durability 目标。

### Required Behavior / Test

- 初始化后的文件数据库 journal mode 只允许明确的持久化安全模式，例如 `delete`、`wal`、`truncate`、`persist`。
- 测试不得把 `off` 或 `memory` 判为 PASS。
- 若代码主动设置 journal mode，必须检查 SQLite 返回的实际模式；设置失败则 fail closed。

## Architect-Owned Audit Fix

父仓库 `.gitignore` 的通用 `reports/` 规则曾忽略完整测试输出。架构师已在 TGrid `.gitignore` 中显式恢复 `work/reports/**` 跟踪；Iteration 2 交接时应确认 `G0-T001-test-output.txt` 与 `G0-T002-test-output.txt` 均出现在 Git status/diff 中。

## Completion

1. 修复 REV-G0T002-001 至 REV-G0T002-005。
2. 运行完整回归、compileall、AST 安全扫描及上述 Failure Injection。
3. 更新 Implementation Report、Test Report、Claude Report 和完整测试输出，逐 Issue 回复 `FIXED`/`NOT_FIXED`/`DISAGREE`。
4. 更新为 `REVIEW_READY / owner=architect`，使用真实本机时间，释放 Lease并只读等待。

---

# Closed G0-T001 History

> G0-T001 的 REV-G0-001 至 REV-G0-007 已全部关闭。Iteration 3 已由架构师判定 PASS；本文件现仅作为历史证据，不再授权任何修改。

# Iteration 3 Fixes（CLOSED）

## P1 — REV-G0-006：Strict YAML Loader 泄漏原始 TypeError

### Evidence

独立 Failure Injection：

```yaml
? [a, b]
: value
```

实际结果：

```text
unhashable_key WRONG_EXCEPTION TypeError unhashable type: 'list'
```

`_construct_mapping_strict` 捕获 `key in mapping` 的 `TypeError` 后继续执行 `mapping[key] = ...`，再次触发未包装的 `TypeError`。

### Affected File

```text
src/tgrid/config.py
tests/unit/test_config.py
```

### Required Behavior

- 不可哈希或非标量 YAML mapping key 必须 fail closed。
- 对调用方统一暴露 `ConfigError`，不得泄漏 `TypeError` 或其他实现异常。
- 错误信息包含键所在 line/column，且说明 mapping key 不合法。
- 不得用宽泛的 `except Exception` 吞掉无关编程错误；应在严格构造器中显式处理键类型/可哈希性。

### Required Test

新增文件级测试，验证 sequence/list key 被拒绝为 `ConfigError`，包含位置和 key 相关说明。

## P1 — REV-G0-007：缺少 root 层重复键回归测试

### Evidence

Iteration 2 已测试重复 global 字段、symbol 字段和 symbol 名称，但没有上一轮 Required Behavior 明确要求的 root 层重复 `global` 或 `symbols` 测试。独立探针证明当前代码可以拒绝，但缺少自动回归证据。

### Required Behavior / Test

新增文件级测试，至少验证 root 层重复 `global` 被 `ConfigError` 拒绝，并检查 duplicate/key/location 信息。

## Iteration 3 Completion

1. 只修 REV-G0-006 和 REV-G0-007，不扩大范围。
2. 运行完整单测、compileall 和 AST 安全扫描。
3. 更新报告与完整测试输出，逐 Issue 标记 `FIXED`。
4. 使用实际本机时间更新 `REVIEW_READY / owner=architect`，释放 Lease 并等待。

---

## Iteration 2 Historical Fixes

只修复本文件列出的问题，不扩大任务范围。

## P0 — REV-G0-001：YAML 重复键被静默覆盖（CLOSED）

### Evidence

`src/tgrid/config.py::load_config` 使用默认 `yaml.safe_load`。独立探针输入重复键后得到：

```text
DUPLICATE_KEYS_ACCEPTED live_trading=True core_qty=0
```

即同一文件中后一个值可静默覆盖：

```yaml
live_trading: false
live_trading: true

core_qty: 600
core_qty: 0
```

### Affected File

```text
src/tgrid/config.py
tests/unit/test_config.py
```

### Why It Matters

重复键可绕过人工审阅，使安全敏感配置与阅读者看到的首个值不一致，违反 fail-closed、INV-009 和 Core Floor 安全意图。

### Required Behavior

- YAML 任意 mapping 层级出现重复键时必须抛出 `ConfigError`。
- 至少覆盖 root、global、symbol 字段和重复 symbol 名称。
- 错误应包含重复键名称及尽可能明确的路径/位置。
- 不得退回默认 `safe_load` 的 last-key-wins 行为。

### Required Test

新增文件级 Failure Injection，至少验证重复 `live_trading`、重复 `core_qty` 和重复 symbol 都被拒绝。

---

## P0 — REV-G0-002：已验证配置的 symbols 映射仍可修改

### Evidence

独立探针：

```python
cfg = parse_config(valid_data)
cfg.symbols.clear()
```

实际结果：

```text
FROZEN_ROOT_MAPPING_MUTABLE before=2 after=0
```

`RootConfig` 虽为 frozen dataclass，但内部保存普通 dict；调用方可在校验后替换或删除证券配置。

### Affected File

```text
src/tgrid/models.py
src/tgrid/config.py
tests/unit/test_models.py
```

### Why It Matters

校验后可变配置会使 `core_qty`、模式和风险参数绕过配置加载校验，且当前报告“不可变模型”的结论不成立。

### Required Behavior

- `parse_config` 返回的 `RootConfig.symbols` 必须是运行时只读映射。
- 调用方不能通过赋值、`clear`、`pop`、`update` 等方式改变它。
- 不要求本任务实现配置热更新。

### Required Test

验证对 `cfg.symbols` 的赋值和 `clear()` 均失败，并确认失败后原映射内容未变化。

---

## P1 — REV-G0-003：设计限定的枚举字段接受任意字符串

### Evidence

独立探针结果：

```text
UNSUPPORTED_ENUM_ACCEPTED bar_period=tick
UNSUPPORTED_ENUM_ACCEPTED anchor=UNSUPPORTED
```

### Affected File

```text
src/tgrid/config.py
src/tgrid/models.py（如需常量）
tests/unit/test_config.py
```

### Why It Matters

设计 V1 明确使用 5 分钟 K 线且禁止 Tick 驱动交易；Anchor 只定义了 `VWAP20` 与数据不足时的 `EMA20`。任意字符串会把错误推迟到未来策略执行阶段并形成设计漂移。

### Required Behavior

- `bar_period` 在 V1 只接受 `5m`。
- `anchor` 只接受设计已定义的 `VWAP20` 或 `EMA20`；未知值必须 `ConfigError`。
- 错误包含字段路径和允许值。

### Required Test

至少验证 `bar_period: tick`、`bar_period: 1m`、`anchor: UNSUPPORTED` 被拒绝，`VWAP20` 与 `EMA20` 被接受。

---

## P1 — REV-G0-004：交接时间戳晚于监控捕获时间

### Evidence

本地监控在：

```text
2026-08-14T16:24:46+08:00
```

捕获 `REVIEW_READY`，但状态与 heartbeat 写入：

```text
last_update: 2026-08-14T16:30:00+08:00
```

### Affected File

```text
work/control/WORKFLOW_STATE.yaml
work/control/CLAUDE_HEARTBEAT.md
```

### Why It Matters

未来时间会破坏 Lease/heartbeat 陈旧判断和审计顺序。

### Required Behavior

Iteration 2 完成交接时必须从本机实际时钟读取 ISO-8601 Asia/Shanghai 时间，不得估算或手写未来时间。两处时间保持一致。

### Required Test

交接前读取本机时间并在 Implementation Report 中记录所用命令与结果；该项人工验收。

---

## P2 — REV-G0-005：测试中的 assert 扫描不完整

### Evidence

当前测试只检查：

```python
line.strip().startswith("assert ")
```

无法发现 `assert(...)`、多行或其他合法语法形式。架构师 AST 扫描本轮确认源码当前没有 `ast.Assert`，因此此问题不代表当前实现已使用 assert。

### Required Behavior

建议将测试改为 `ast.parse` + `ast.walk` 检测 `ast.Assert`。该项为 P2，不单独阻塞本任务；若修改，仍须保持在 Allowed Files 内。

## Completion

修复 P0/P1 后：

1. 运行原 41 项及新增测试。
2. 更新 Implementation Report、Test Report、完整测试输出和 Claude Report。
3. 对每个 Issue ID 写明 `FIXED` / `NOT_FIXED` / `DISAGREE` 及证据。
4. 使用真实本机时间更新为 `REVIEW_READY / owner=architect`。
5. 释放 Lease并停止。
