# WaveFlow 自动任务架构实施记录

> 本文记录自动任务架构各落地批次的背景、成因、方案、实现、边界和验证结果。
> 架构决策以 `docs/automation-architecture.md` 为准；本文只记录已经实际完成的能力，不把后续计划写成已实现。

## M2A-1：自动任务持久化底座

### 背景与成因

Market 自动检查和自动更新需要跨进程重启保存配置及最近运行状态。仅依赖进程内 `asyncio.Lock` 无法处理异常退出，也无法阻止旧运行结果覆盖新运行，因此需要数据库级执行权和状态所有权。

### 采用方案

- 使用独立通用表 `automation_task_config` 保存任务配置。
- 使用 `automation_task_state` 保存当前或最近一次运行状态。
- 使用 `conflict_group` partial unique index保证同一互斥域最多一条 `running`。
- 使用 `BEGIN IMMEDIATE` 在短事务内完成非排队 claim。
- 使用 `task_id + run_token + running` 条件更新进度和最终状态。
- 启动恢复时将残留 `running` 转换为 `interrupted`。
- 为 Market install 增加最近检查和更新状态，并使用单包 run token 防止晚到结果覆盖。

### 实际落地

- 修改 `backend/database.py`，沿用 `_SCHEMA` 和幂等 `ALTER TABLE ADD COLUMN`。
- 新增配置、claim、progress、complete、busy 查询和 interrupted 恢复数据库入口。
- 新增 Market install 检查及更新状态入口。
- 保持 M1 package 原地更新、subscription/channel 行和公开 `source_id` 不变。

### 验证结果

- 新增 `backend/tests/test_automation_persistence.py`。
- 覆盖新库初始化、旧库升级、重复初始化、配置持久化、并发 claim、run token、interrupted 恢复、Market install 状态和 M1 事务兼容。
- 后端全量回归通过。

### 边界

本批未实现 Runner、Scheduler、长期后台任务、lifespan 或 API。

## M2A-2a：通用 Automation Runner 与执行模型

### 背景与成因

M2A-1 只提供数据库所有权。如果 Scheduler、管理 API 和业务模块各自拼接 claim、handler、状态计算和 complete，会形成多套执行路径，导致 busy 语义、取消处理、错误净化和 run token 条件完成不一致。因此需要一个不负责调度的统一单轮 Runner。

### 采用方案

- 使用 dataclass 定义任务、运行请求、handler 结果、运行结果、busy、配置和状态模型。
- 使用显式 `AutomationRegistry` 注册唯一 `task_id`，不做插件扫描或动态 import。
- 使用 `AutomationRepository` 薄封装 M2A-1 数据库入口，不复制 SQL 和事务。
- `AutomationTaskContext` 提供 stop 查询和受 run token 保护的 progress 上报。
- `AutomationRunner.run()` 作为 scheduler、API 和内部调用未来的唯一执行入口。
- Runner 只同步执行一轮任务，不等待、不排队、不创建后台 task。

### 执行流程

```text
查找 definition
→ 校验 task_type、trigger 和配置一致性
→ 生成唯一 run token
→ 数据库原子 claim
→ busy 时立即返回
→ 创建 context 并执行 handler
→ 统一计算 success / partial / failed / cancelled
→ run token 条件完成
→ 返回统一结果
```

### 状态和所有权语义

- 无失败，包括没有可处理项目：`success`。
- 有有效工作且部分业务项失败：`partial`。
- 全部必要工作失败、handler 异常或非法结果：`failed`。
- 协作式停止或 handler 在安全边界返回取消：`cancelled`。
- progress 或 complete 的 token 条件更新失败时抛出所有权丢失，不能返回虚假的 success。
- `AutomationBusy` 和 `AutomationRunResult` 不暴露 run token。

### 异常和取消

- 普通异常转换为 `failed`；数据库和返回结果只保存净化后的简化错误。
- 错误去除 NUL、限制长度并隐藏本地绝对路径，不暴露 traceback。
- 强制 `CancelledError` 会尽力写入 `cancelled`，随后继续传播取消。
- 测试发现并修复了一个取消竞态：当取消时 run token 已失效，状态写入失败不能用所有权异常替换原始 `CancelledError`。

### 实际落地

- 新增 `backend/automation.py`。
- 新增 `backend/tests/test_automation_runner.py`。
- 未修改 `backend/database.py`、`backend/main.py`、Market 业务或前端。

### 测试先行证据

1. 创建 Runner 测试后，当前 HEAD 因不存在 `automation.py` 稳定出现 15 个导入错误。
2. 初版实现后新增 token 已失效的强制取消测试，稳定复现 `AutomationOwnershipLostError` 替换 `CancelledError`。
3. 最小修复后 Runner 定向测试 17 项全部通过。

### 验证结果

- Runner 定向测试：17 passed。
- Runner、M2A-1 持久化和 Market 生命周期：52 passed。
- 后端全量：273 passed，54 subtests passed。
- `git diff --check` 和 Python 编译检查通过。
- 确认生产实现中不存在 Scheduler、AutomationService、`asyncio.create_task()` 或周期等待。

### 边界

本批未实现 Scheduler、AutomationService 生命周期、FastAPI lifespan、Market task handler 或 API。
