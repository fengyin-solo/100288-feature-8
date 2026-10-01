"""季度养护方案接口：多片绿地整季送审、逐条编制、批量审批/退回与预算汇总对账。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.seasonplan import QUARTERS, SeasonplanService

router = APIRouter(prefix="/api/seasonplan", tags=["季度养护方案"])

service = SeasonplanService()

LIST_FIELDS = ["方案编号", "方案季度", "覆盖绿地", "方案内容", "预算金额", "编制人", "审批人", "方案状态"]
STATUSES = ["待编制", "已编制", "已审批", "执行中"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按方案编号或覆盖绿地检索"),
    quarter: str | None = Query(default=None, description="方案季度，如 2026-Q3"),
    status: str | None = Query(default=None, description="待编制、已编制、已审批、执行中"),
    budget_min: float | None = Query(default=None, description="预算下限，仅在方案季度内收窄"),
    budget_max: float | None = Query(default=None, description="预算上限，仅在方案季度内收窄"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案季度、状态与预算过滤方案台账；方案季度与预算牵连时以方案季度为准。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        quarter=quarter,
        status=status,
        budget_min=None if budget_min is None else str(budget_min),
        budget_max=None if budget_max is None else str(budget_max),
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/quarters")
def list_quarters() -> dict[str, Any]:
    """可编制的方案季度列表，供前端统一带出方案季度。"""
    return {"items": QUARTERS}


@router.get("/plots")
def quarter_plots(quarter: str = Query(..., description="方案季度，如 2026-Q3")) -> dict[str, Any]:
    """某季度可勾选的绿地清单：带出每片绿地是否已有方案、编到哪一步。"""
    if quarter not in QUARTERS:
        raise HTTPException(status_code=400, detail=f"方案季度「{quarter}」暂不支持")
    return {"quarter": quarter, "items": service.quarter_plots(quarter)}


@router.get("/batches")
def list_batches(quarter: str | None = None) -> dict[str, Any]:
    """批件列表，可按方案季度收窄。"""
    return {"items": service.list_batches(quarter=quarter)}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int) -> dict[str, Any]:
    """读取一张送审批件及其全部方案条。"""
    batch = service.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"批件 {batch_id} 不存在")
    payload = dict(batch)
    payload["items"] = service.batch_lines(batch)
    return payload


@router.post("/batches/submit", response_model=ActionResult)
def submit_batch(payload: EntryPayload) -> ActionResult:
    """同一季度勾选多片绿地一次性送审；同批重复提交只认第一次。"""
    values = payload.values
    quarter = str(values.get("quarter") or "").strip()
    plot_ids = [int(value) for value in values.get("plot_ids", []) if str(value).strip()]
    operator = str(values.get("operator") or "").strip()
    batch, message, duplicated = service.submit_batch(quarter, plot_ids, operator)
    if batch is None:
        return ActionResult(ok=False, message=message)
    result = dict(batch)
    result["items"] = service.batch_lines(batch)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/batches/{batch_id}/approve", response_model=ActionResult)
def approve_batch(batch_id: int, payload: EntryPayload) -> ActionResult:
    """批量审批：先挑出未编完的，只审已编完的那几条；预算按整体结果落。"""
    reviewer = str(payload.values.get("reviewer") or "审批人").strip()
    batch, message, detail = service.approve_batch(batch_id, reviewer)
    if batch is None:
        return ActionResult(ok=False, message=message)
    result = dict(batch)
    result["items"] = service.batch_lines(batch)
    result.update(detail)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/batches/{batch_id}/return", response_model=ActionResult)
def return_batch(batch_id: int, payload: EntryPayload) -> ActionResult:
    """退回批件中勾选的条：已审的不动，退回的留在原批件等重提。"""
    values = payload.values
    entry_ids = [int(value) for value in values.get("entry_ids", []) if str(value).strip()]
    reason = str(values.get("reason") or "").strip()
    batch, message = service.return_batch(batch_id, entry_ids, reason)
    if batch is None:
        return ActionResult(ok=False, message=message)
    result = dict(batch)
    result["items"] = service.batch_lines(batch)
    return ActionResult(ok=True, message=message, entry=result)


@router.get("/summary")
def approval_summary(
    quarter: str | None = Query(default=None, description="方案季度优先：先按季度收口"),
    budget_min: float | None = Query(default=None, description="预算下限"),
    budget_max: float | None = Query(default=None, description="预算上限"),
) -> dict[str, Any]:
    """审批汇总：批件审批预算与方案台账逐条加总核对，并标出是否对得上。"""
    return service.summary(
        quarter=quarter,
        budget_min=None if budget_min is None else str(budget_min),
        budget_max=None if budget_max is None else str(budget_max),
    )


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条养护方案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"养护方案 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/fill", response_model=ActionResult)
def fill_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """逐条回填养护内容与预算；齐全自动转已编制，缺项留在待编制。"""
    entry, message = service.fill_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条养护方案，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="养护方案已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条养护方案执行编制方案、审批方案、启动执行；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出季度养护方案清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "seasonplan", "total": total, "items": items}
