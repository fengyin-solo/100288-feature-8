"""季度养护方案接口：维护养护方案，支持批量送审、批量审批与审批汇总对账。

字面值路径（/summary、/batches、/export）要放在 /{entry_id} 之前声明，
否则会被路径参数抢走，请求直接 422。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.seasonplan import SeasonplanService

router = APIRouter(prefix="/api/seasonplan", tags=["季度养护方案"])

service = SeasonplanService()

LIST_FIELDS = ["方案编号", "方案季度", "覆盖绿地", "方案内容", "预算金额", "编制人", "审批人", "方案状态"]
STATUSES = ["待编制", "已编制", "已审批", "执行中"]


@router.get("/summary")
def approval_summary(
    quarter: str | None = Query(default=None, alias="方案季度", description="方案季度，与预算条件同时给时以它为准"),
    budget_min: float | None = Query(default=None, alias="预算下限", description="预算金额下限（万元）"),
    budget_max: float | None = Query(default=None, alias="预算上限", description="预算金额上限（万元）"),
) -> dict[str, Any]:
    """审批汇总：按季度（优先）或预算条件汇总审批通过的方案，并和方案台账、批次留痕对账。"""
    return service.summary(quarter=quarter, budget_min=budget_min, budget_max=budget_max)


@router.get("/batches", response_model=PageResult[dict])
def list_batches(
    quarter: str | None = Query(default=None, alias="方案季度", description="按方案季度过滤批次"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """送审批次列表：最近的批次排前面。"""
    items, total = service.list_batches(quarter=quarter, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/batches", response_model=ActionResult)
def submit_batch(payload: EntryPayload) -> ActionResult:
    """批量送审：同一季度的方案多选后一次送出；同一批复式提交只认第一次。"""
    batch, _created, message = service.submit_batch(payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/batches/{batch_no}", response_model=dict)
def get_batch(batch_no: str) -> dict:
    """批次详情：顺带带上每片绿地方案的当前状态，审批面板要用。"""
    batch = service.get_batch(batch_no)
    if batch is None:
        raise HTTPException(status_code=404, detail=f"送审批次 {batch_no} 不存在")
    plans = []
    for pid in batch.get("方案ids") or []:
        entry = service.get_entry(int(pid))
        if entry is not None:
            plans.append(entry)
    return {**batch, "方案明细": plans}


@router.post("/batches/{batch_no}/approve", response_model=ActionResult)
def approve_batch(batch_no: str, payload: EntryPayload) -> ActionResult:
    """批量审批：未编完的先挑出来，退回的留在原处等重提，其余一次审完。"""
    batch, message = service.approve_batch(batch_no, payload.values)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出季度养护方案清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "seasonplan", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, alias="方案编号", description="按方案编号检索"),
    quarter: str | None = Query(default=None, alias="方案季度", description="按方案季度过滤"),
    plot: str | None = Query(default=None, alias="覆盖绿地", description="按覆盖绿地检索"),
    status: str | None = Query(default=None, alias="状态", description="待编制、已编制、已审批、执行中"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按方案编号、方案季度、覆盖绿地与状态过滤列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, quarter=quarter, plot=plot, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条养护方案明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"养护方案 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条养护方案，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="养护方案已登记", entry=entry)


@router.post("/{entry_id}/contents", response_model=ActionResult)
def add_contents(entry_id: int, payload: EntryPayload) -> ActionResult:
    """养护内容逐条补录；方案进入审批后就封板，不能再改。"""
    entry, message = service.add_contents(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条养护方案执行编制方案、审批方案、启动执行；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
