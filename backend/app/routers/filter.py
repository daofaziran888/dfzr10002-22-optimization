"""全局筛选器接口：维护筛选器定义与全系统共享的筛选运行态。

除常规列表/动作外，还提供：
- GET  /api/filter/state           全量有效筛选状态（图表、看板、导出统一读取）
- GET  /api/filter/state/{id}      单个筛选器的有效状态与规则校验
- POST /api/filter/state/{id}/select   用户选择（带版本号，拒绝过期并发写入）
- POST /api/filter/state/{id}/reset    清空，回到系统默认值
- POST /api/filter/state/{id}/source   切换可选值来源，失效默认值给出提示
- POST /api/filter/{id}/default        保存默认值，规则不通过则拒绝并返回依据
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.filter import FilterService
from app.services.filter_state import filter_state_service

router = APIRouter(prefix="/api/filter", tags=["全局筛选器"])

service = FilterService()

LIST_FIELDS = ["筛选器编号", "筛选器名称", "关联字段", "筛选类型", "默认值", "可选值来源", "联动维度", "是否启用"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按筛选器编号、关联字段或联动维度检索"),
    field: str | None = Query(default=None, description="限定检索字段：筛选器编号/关联字段/联动维度"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、关联字段、联动维度过滤全局筛选器列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, field=field, status=status, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/state")
def get_all_state() -> dict[str, Any]:
    """全量有效筛选状态快照：图表配置、看板、导出任务都读取这一份数据。"""
    return filter_state_service.snapshot()


@router.get("/state/{filter_id}")
def get_state(filter_id: int) -> dict[str, Any]:
    """单个筛选器的有效状态，含系统默认值、用户选择、当前有效值与规则校验依据。"""
    state = filter_state_service.get_state(filter_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"筛选器 {filter_id} 不存在或已归档")
    return state


@router.post("/state/{filter_id}/select")
def select_value(filter_id: int, payload: EntryPayload) -> ActionResult:
    """记录用户选择。values.value 为 null 表示清空；values.version 为客户端基准版本。

    并发切换时，过期版本的请求会被拒绝，只有最后一次选择生效。
    """
    value = payload.values.get("value")
    if value is not None:
        value = str(value)
    raw_version = payload.values.get("version")
    client_version = int(raw_version) if isinstance(raw_version, int) else None
    state, conflict = filter_state_service.select(filter_id, value, client_version)
    if state is None:
        raise HTTPException(status_code=404, detail=conflict)
    if conflict:
        return ActionResult(ok=False, message=conflict, entry=state)
    return ActionResult(ok=True, message=f"当前有效值已更新为「{state['当前有效值']}」", entry=state)


@router.post("/state/{filter_id}/reset")
def reset_value(filter_id: int) -> ActionResult:
    """清空用户临时选择，明确回到系统默认值（不是上一次临时选择）。"""
    state, error = filter_state_service.reset_to_default(filter_id)
    if state is None:
        raise HTTPException(status_code=404, detail=error)
    return ActionResult(
        ok=True,
        message=f"已清空临时选择，回到系统默认值「{state['系统默认值']}」",
        entry=state,
    )


@router.post("/state/{filter_id}/source")
def change_source(filter_id: int, payload: EntryPayload) -> ActionResult:
    """切换默认值/可选值来源；旧默认值失效时返回来源变更提示，失效值不允许恢复。"""
    source = str(payload.values.get("source") or "").strip()
    options = payload.values.get("options")
    if not source:
        return ActionResult(ok=False, message="缺少可选值来源名称，来源未切换")
    if not isinstance(options, list) or not options:
        return ActionResult(ok=False, message="新来源必须提供非空可选值清单，来源未切换")
    options = [str(item) for item in options]
    state, error = filter_state_service.change_source(filter_id, source, options)
    if state is None:
        raise HTTPException(status_code=404, detail=error)
    if error:
        return ActionResult(ok=False, message=error, entry=state)
    return ActionResult(ok=True, message=f"可选值来源已切换为「{source}」", entry=state)


@router.post("/{filter_id}/default")
def save_default(filter_id: int, payload: EntryPayload) -> ActionResult:
    """保存筛选器默认值配置；不满足可选值范围、关联字段标准、联动条件规则时拒绝保存。"""
    state, checks = filter_state_service.save_default(filter_id, payload.values)
    if not checks:
        raise HTTPException(status_code=404, detail=f"筛选器 {filter_id} 不存在或已归档")
    if state is None:
        failed = [item["rule"] for item in checks if item["passed"] != "true"]
        return ActionResult(
            ok=False,
            message=f"默认值规则校验未通过（{'、'.join(failed)}），配置未保存",
            entry={"规则校验": checks},
        )
    return ActionResult(ok=True, message="筛选器配置与默认值已保存", entry=state)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条筛选器明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"筛选器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条筛选器，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="筛选器已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条筛选器执行提交校验、启用配置、停用配置；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出全局筛选器清单：随当前有效筛选状态同步导出。"""
    snapshot = filter_state_service.snapshot()
    return {
        "module": "filter",
        "total": len(snapshot["items"]),
        "notice": snapshot["notice"],
        "items": snapshot["items"],
    }
