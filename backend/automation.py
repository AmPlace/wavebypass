"""通用自动任务定义、持久化适配和单轮执行器。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping

import database as default_database


logger = logging.getLogger(__name__)

AUTOMATION_TRIGGERS = frozenset({"scheduler", "manual_api", "internal"})
AUTOMATION_RESULT_STATUSES = frozenset({"success", "partial", "failed", "cancelled"})
AUTOMATION_ERROR_MAX_LENGTH = 2048

Handler = Callable[["AutomationTaskContext"], Awaitable["AutomationHandlerResult"]]


class AutomationError(Exception):
    """自动任务执行模型的基础异常。"""


class AutomationRegistrationError(AutomationError):
    pass


class AutomationTaskNotFoundError(AutomationError):
    pass


class AutomationConfigurationError(AutomationError):
    pass


class AutomationRequestError(AutomationError):
    pass


class AutomationTriggerNotAllowedError(AutomationError):
    pass


class AutomationOwnershipLostError(AutomationError):
    pass


def _normalize_identifier(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} 必须是字符串")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} 不能为空")
    return value


def _normalize_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} 必须是非负整数")
    if value < 0:
        raise ValueError(f"{field_name} 不能小于 0")
    return value


def _normalize_positive_int(value: Any, field_name: str) -> int:
    value = _normalize_non_negative_int(value, field_name)
    if value == 0:
        raise ValueError(f"{field_name} 必须大于 0")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("时间提供器必须返回 datetime")
    if value.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(timezone.utc).isoformat()


def _sanitize_error(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = text.replace("\x00", "").strip()
    text = re.sub(r"(?<![A-Za-z0-9])/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+", "<path>", text)
    text = re.sub(r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\s]+", "<path>", text)
    return text[:AUTOMATION_ERROR_MAX_LENGTH]


def _summarize_errors(error: str, errors: tuple[str, ...]) -> str:
    values = [item for item in (error, *errors) if item]
    return _sanitize_error("; ".join(values))


@dataclass(frozen=True, slots=True)
class AutomationTaskDefinition:
    task_id: str
    display_name: str
    conflict_group: str
    default_enabled: bool
    default_interval_seconds: int
    handler: Handler
    allow_manual_trigger: bool = True
    minimum_interval_seconds: int = 1
    maximum_interval_seconds: int | None = None
    initial_delay_seconds: int = 0
    allowed_task_types: frozenset[str] = field(default_factory=lambda: frozenset({"check"}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _normalize_identifier(self.task_id, "task_id"))
        object.__setattr__(self, "display_name", _normalize_identifier(self.display_name, "display_name"))
        object.__setattr__(self, "conflict_group", _normalize_identifier(self.conflict_group, "conflict_group"))
        if not isinstance(self.default_enabled, bool):
            raise TypeError("default_enabled 必须是布尔值")
        if not isinstance(self.allow_manual_trigger, bool):
            raise TypeError("allow_manual_trigger 必须是布尔值")
        minimum = _normalize_positive_int(self.minimum_interval_seconds, "minimum_interval_seconds")
        default_interval = _normalize_positive_int(self.default_interval_seconds, "default_interval_seconds")
        maximum = self.maximum_interval_seconds
        if maximum is not None:
            maximum = _normalize_positive_int(maximum, "maximum_interval_seconds")
            if minimum > maximum:
                raise ValueError("minimum_interval_seconds 不能大于 maximum_interval_seconds")
        if not minimum <= default_interval <= (maximum or default_interval):
            raise ValueError("default_interval_seconds 超出任务配置范围")
        initial_delay = _normalize_non_negative_int(self.initial_delay_seconds, "initial_delay_seconds")
        if not callable(self.handler):
            raise TypeError("handler 必须可调用")
        if isinstance(self.allowed_task_types, str):
            raise TypeError("allowed_task_types 必须是字符串集合")
        task_types = frozenset(self.allowed_task_types)
        if not task_types or any(not isinstance(item, str) or not item.strip() for item in task_types):
            raise ValueError("allowed_task_types 不能为空，且必须全部为非空字符串")
        object.__setattr__(self, "minimum_interval_seconds", minimum)
        object.__setattr__(self, "default_interval_seconds", default_interval)
        object.__setattr__(self, "maximum_interval_seconds", maximum)
        object.__setattr__(self, "initial_delay_seconds", initial_delay)
        object.__setattr__(self, "allowed_task_types", task_types)


@dataclass(frozen=True, slots=True)
class AutomationRunRequest:
    task_id: str
    task_type: str
    trigger: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    stop_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _normalize_identifier(self.task_id, "task_id"))
        object.__setattr__(self, "task_type", _normalize_identifier(self.task_type, "task_type"))
        object.__setattr__(self, "trigger", _normalize_identifier(self.trigger, "trigger"))
        if self.trigger not in AUTOMATION_TRIGGERS:
            raise ValueError(f"不支持的自动任务触发来源: {self.trigger}")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("parameters 必须是映射")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        if self.stop_event is not None and not isinstance(self.stop_event, asyncio.Event):
            raise TypeError("stop_event 必须是 asyncio.Event")


@dataclass(frozen=True, slots=True)
class AutomationHandlerResult:
    status: str | None = None
    checked_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error: str = ""
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status is not None and self.status not in AUTOMATION_RESULT_STATUSES:
            raise ValueError(f"非法自动任务结果状态: {self.status}")
        for field_name in ("checked_count", "updated_count", "skipped_count", "failed_count"):
            object.__setattr__(self, field_name, _normalize_non_negative_int(getattr(self, field_name), field_name))
        object.__setattr__(self, "error", _sanitize_error(self.error))
        if isinstance(self.errors, str):
            raise TypeError("errors 必须是错误字符串集合")
        normalized_errors = tuple(
            normalized
            for item in self.errors
            if (normalized := _sanitize_error(item))
        )
        object.__setattr__(self, "errors", normalized_errors)


@dataclass(frozen=True, slots=True)
class AutomationTaskConfig:
    task_id: str
    conflict_group: str
    enabled: bool
    interval_seconds: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class AutomationTaskState:
    task_id: str
    conflict_group: str
    task_type: str
    run_token: str
    last_started_at: str
    last_finished_at: str
    status: str
    checked_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    last_error: str


@dataclass(frozen=True, slots=True)
class AutomationClaim:
    claimed: bool
    state: AutomationTaskState


@dataclass(frozen=True, slots=True)
class AutomationBusy:
    task_id: str
    task_type: str
    conflict_group: str
    started_at: str
    status: str


@dataclass(frozen=True, slots=True)
class AutomationRunResult:
    task_id: str
    task_type: str
    status: str
    checked_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    error: str
    started_at: str
    finished_at: str
    errors: tuple[str, ...] = ()


def _config_from_row(row: Mapping[str, Any]) -> AutomationTaskConfig:
    return AutomationTaskConfig(
        task_id=row["task_id"],
        conflict_group=row["conflict_group"],
        enabled=bool(row["enabled"]),
        interval_seconds=int(row["interval_seconds"]),
        updated_at=row["updated_at"],
    )


def _state_from_row(row: Mapping[str, Any]) -> AutomationTaskState:
    return AutomationTaskState(
        task_id=row["task_id"],
        conflict_group=row["conflict_group"],
        task_type=row.get("task_type", "") if hasattr(row, "get") else row["task_type"],
        run_token=row.get("run_token", "") if hasattr(row, "get") else row["run_token"],
        last_started_at=row.get("last_started_at", "") if hasattr(row, "get") else row["last_started_at"],
        last_finished_at=row.get("last_finished_at", "") if hasattr(row, "get") else row["last_finished_at"],
        status=row.get("last_status", "never_run") if hasattr(row, "get") else row["last_status"],
        checked_count=int(row.get("checked_count", 0)) if hasattr(row, "get") else int(row["checked_count"]),
        updated_count=int(row.get("updated_count", 0)) if hasattr(row, "get") else int(row["updated_count"]),
        skipped_count=int(row.get("skipped_count", 0)) if hasattr(row, "get") else int(row["skipped_count"]),
        failed_count=int(row.get("failed_count", 0)) if hasattr(row, "get") else int(row["failed_count"]),
        last_error=row.get("last_error", "") if hasattr(row, "get") else row["last_error"],
    )


class AutomationRepository:
    """M2A-1 数据库入口的薄适配层，不包含业务或事务实现。"""

    def __init__(self, database_module=default_database):
        self._database = database_module

    async def ensure_config(self, definition: AutomationTaskDefinition) -> AutomationTaskConfig:
        row = await self._database.ensure_automation_task_config(
            definition.task_id,
            definition.conflict_group,
            definition.default_enabled,
            definition.default_interval_seconds,
        )
        return _config_from_row(row)

    async def get_config(self, task_id: str) -> AutomationTaskConfig | None:
        row = await self._database.get_automation_task_config(task_id)
        return _config_from_row(row) if row else None

    async def list_configs(self) -> list[AutomationTaskConfig]:
        rows = await self._database.list_automation_task_configs()
        return [_config_from_row(row) for row in rows]

    async def claim(
        self,
        task_id: str,
        conflict_group: str,
        task_type: str,
        run_token: str,
        started_at: str,
    ) -> AutomationClaim:
        result = await self._database.claim_automation_task(
            task_id=task_id,
            conflict_group=conflict_group,
            task_type=task_type,
            run_token=run_token,
            started_at=started_at,
        )
        return AutomationClaim(
            claimed=bool(result["claimed"]),
            state=_state_from_row(result.get("state") or result.get("current")),
        )

    async def update_progress(self, task_id: str, run_token: str, **counts: Any) -> bool:
        return await self._database.update_automation_task_progress(task_id, run_token, **counts)

    async def complete(self, task_id: str, run_token: str, **result: Any) -> bool:
        return await self._database.complete_automation_task(task_id, run_token, **result)

    async def get_state(self, task_id: str) -> AutomationTaskState | None:
        row = await self._database.get_automation_task_state(task_id)
        return _state_from_row(row) if row else None

    async def get_busy(self, conflict_group: str) -> AutomationTaskState | None:
        row = await self._database.get_automation_conflict_group_state(conflict_group)
        return _state_from_row(row) if row else None

    async def recover_interrupted(self, **kwargs: Any) -> int:
        return await self._database.recover_interrupted_automation_tasks(**kwargs)


class AutomationRegistry:
    def __init__(self):
        self._definitions: dict[str, AutomationTaskDefinition] = {}

    def register(self, definition: AutomationTaskDefinition) -> None:
        if not isinstance(definition, AutomationTaskDefinition):
            raise TypeError("definition 必须是 AutomationTaskDefinition")
        if definition.task_id in self._definitions:
            raise AutomationRegistrationError(f"自动任务已注册: {definition.task_id}")
        self._definitions[definition.task_id] = definition

    def get(self, task_id: str) -> AutomationTaskDefinition:
        try:
            return self._definitions[task_id]
        except KeyError as exc:
            raise AutomationTaskNotFoundError(f"未知自动任务: {task_id}") from exc

    def __contains__(self, task_id: str) -> bool:
        return task_id in self._definitions


class AutomationTaskContext:
    def __init__(
        self,
        *,
        task_id: str,
        task_type: str,
        trigger: str,
        parameters: Mapping[str, Any],
        run_token: str,
        stop_event: asyncio.Event,
        repository: AutomationRepository,
    ):
        self.task_id = task_id
        self.task_type = task_type
        self.trigger = trigger
        self.parameters = MappingProxyType(dict(parameters))
        self.run_token = run_token
        self._stop_event = stop_event
        self._repository = repository

    def stop_requested(self) -> bool:
        return self._stop_event.is_set()

    async def report_progress(
        self,
        *,
        checked_count: int | None = None,
        updated_count: int | None = None,
        skipped_count: int | None = None,
        failed_count: int | None = None,
        error: str | None = None,
    ) -> None:
        persisted = await self._repository.update_progress(
            self.task_id,
            self.run_token,
            checked_count=checked_count,
            updated_count=updated_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            error=error,
        )
        if not persisted:
            raise AutomationOwnershipLostError("自动任务执行权已失效")


class AutomationRunner:
    """执行单轮任务；不负责等待、调度或创建后台协程。"""

    def __init__(
        self,
        registry: AutomationRegistry,
        repository: AutomationRepository | None = None,
        *,
        token_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.registry = registry
        self.repository = repository or AutomationRepository()
        self._token_factory = token_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or _utc_now

    def _timestamp(self) -> str:
        return _format_timestamp(self._clock())

    async def run(self, request: AutomationRunRequest) -> AutomationRunResult | AutomationBusy:
        if not isinstance(request, AutomationRunRequest):
            raise AutomationRequestError("request 必须是 AutomationRunRequest")
        definition = self.registry.get(request.task_id)
        if request.task_type not in definition.allowed_task_types:
            raise AutomationRequestError(f"任务不支持 task_type: {request.task_type}")
        if request.trigger == "manual_api" and not definition.allow_manual_trigger:
            raise AutomationTriggerNotAllowedError(f"任务不允许手动触发: {request.task_id}")

        config = await self.repository.ensure_config(definition)
        if config.conflict_group != definition.conflict_group:
            raise AutomationConfigurationError(
                f"任务 conflict_group 与数据库配置不一致: {request.task_id}"
            )
        if not definition.minimum_interval_seconds <= config.interval_seconds:
            raise AutomationConfigurationError(f"任务 interval_seconds 小于定义下限: {request.task_id}")
        if definition.maximum_interval_seconds is not None and config.interval_seconds > definition.maximum_interval_seconds:
            raise AutomationConfigurationError(f"任务 interval_seconds 大于定义上限: {request.task_id}")

        run_token = _normalize_identifier(self._token_factory(), "run_token")
        started_at = self._timestamp()
        claim = await self.repository.claim(
            request.task_id,
            definition.conflict_group,
            request.task_type,
            run_token,
            started_at,
        )
        if not claim.claimed:
            return AutomationBusy(
                task_id=claim.state.task_id,
                task_type=claim.state.task_type,
                conflict_group=claim.state.conflict_group,
                started_at=claim.state.last_started_at,
                status=claim.state.status,
            )

        stop_event = request.stop_event or asyncio.Event()
        context = AutomationTaskContext(
            task_id=request.task_id,
            task_type=request.task_type,
            trigger=request.trigger,
            parameters=request.parameters,
            run_token=run_token,
            stop_event=stop_event,
            repository=self.repository,
        )

        try:
            if stop_event.is_set():
                handler_result = AutomationHandlerResult(status="cancelled", error="任务收到停止请求")
            else:
                raw_result = definition.handler(context)
                if not inspect.isawaitable(raw_result):
                    raise TypeError("handler 必须返回可等待对象")
                raw_result = await raw_result
                if not isinstance(raw_result, AutomationHandlerResult):
                    raise TypeError("handler 必须返回 AutomationHandlerResult")
                handler_result = raw_result
        except asyncio.CancelledError:
            await self._try_complete_cancelled(
                request,
                run_token,
            )
            raise
        except Exception as exc:
            logger.exception("自动任务执行失败: %s", request.task_id)
            handler_result = AutomationHandlerResult(
                status="failed",
                error=_sanitize_error(str(exc)),
            )

        status = self._resolve_status(handler_result)
        finished_at = self._timestamp()
        error = _summarize_errors(handler_result.error, handler_result.errors)
        completed = await self.repository.complete(
            request.task_id,
            run_token,
            status=status,
            finished_at=finished_at,
            checked_count=handler_result.checked_count,
            updated_count=handler_result.updated_count,
            skipped_count=handler_result.skipped_count,
            failed_count=handler_result.failed_count,
            error=error,
        )
        if not completed:
            raise AutomationOwnershipLostError("自动任务完成时执行权已失效")
        return AutomationRunResult(
            task_id=request.task_id,
            task_type=request.task_type,
            status=status,
            checked_count=handler_result.checked_count,
            updated_count=handler_result.updated_count,
            skipped_count=handler_result.skipped_count,
            failed_count=handler_result.failed_count,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            errors=handler_result.errors,
        )

    async def _try_complete_cancelled(
        self,
        request: AutomationRunRequest,
        run_token: str,
    ) -> None:
        try:
            completed = await self.repository.complete(
                request.task_id,
                run_token,
                status="cancelled",
                finished_at=self._timestamp(),
                checked_count=0,
                updated_count=0,
                skipped_count=0,
                failed_count=0,
                error="任务被取消",
            )
            if not completed:
                logger.warning("自动任务取消时执行权已失效: %s", request.task_id)
        except Exception:
            logger.exception("自动任务取消状态写入失败: %s", request.task_id)

    @staticmethod
    def _resolve_status(result: AutomationHandlerResult) -> str:
        if result.status == "cancelled":
            return "cancelled"
        if result.status == "failed":
            return "failed"
        if result.status == "partial":
            return "partial"
        if result.failed_count == 0:
            return "success"
        has_successful_work = (
            result.updated_count > 0
            or result.skipped_count > 0
            or result.checked_count > result.failed_count
        )
        return "partial" if has_successful_work else "failed"
