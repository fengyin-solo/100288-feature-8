"""季度养护方案业务规则：状态流转、批量送审与审批汇总的口径都收在这里。"""
from __future__ import annotations

import hashlib
from typing import Any

from app.store import store

MODULE = "seasonplan"
BATCH_MODULE = "seasonplan_batch"
REQUIRED_FIELDS = ["方案编号", "方案季度", "覆盖绿地"]
STATUS_ORDER = ["待编制", "已编制", "已审批", "执行中"]
ACTION_RULES = {"编制方案": "已编制", "审批方案": "已审批", "启动执行": "执行中"}
NEGATIVE_ACTIONS: list[str] = []
EDITABLE_STATUSES = {"待编制", "已编制"}
SUBMITTABLE_STATUSES = {"待编制", "已编制"}
APPROVED_STATUSES = {"已审批", "执行中"}


def _content_lines(value: Any) -> list[str]:
    """养护内容统一按行收纳：逐条填进来的是列表，整段文字按行或分号切。"""
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace("；", "\n").replace(";", "\n").splitlines()
    elif isinstance(value, (list, tuple)):
        parts = [str(item) for item in value]
    else:
        parts = [str(value)]
    return [part.strip() for part in parts if part.strip()]


def _budget(value: Any) -> float:
    """预算金额统一成两位小数的数值，填不出来的按 0 落。"""
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _brief(entry: dict[str, Any]) -> dict[str, Any]:
    """批次结果与汇总明细里只留识别方案需要的几个字段。"""
    return {
        "id": entry.get("id"),
        "方案编号": entry.get("方案编号"),
        "覆盖绿地": entry.get("覆盖绿地"),
        "预算金额": _budget(entry.get("预算金额")),
    }


class SeasonplanService:
    # ---------- 列表与单条 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        quarter: str | None = None,
        plot: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("方案编号", ""))]
        if quarter:
            rows = [row for row in rows if str(row.get("方案季度", "")) == quarter]
        if plot:
            rows = [row for row in rows if plot in str(row.get("覆盖绿地", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记与编制 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field)).strip() for field in REQUIRED_FIELDS})
        entry["方案内容"] = _content_lines(values.get("方案内容"))
        entry["预算金额"] = _budget(values.get("预算金额"))
        entry["编制人"] = str(values.get("编制人") or "").strip()
        entry["审批人"] = ""
        entry["批次号"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["方案状态"] = STATUS_ORDER[0]
        rows.append(entry)
        return entry, []

    def add_contents(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """养护内容逐条补录：方案进入审批后就封板，不能再改。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护方案 {entry_id} 不存在或已归档"
        if entry.get("status") not in EDITABLE_STATUSES:
            return None, f"方案已流转到「{entry.get('status')}」，养护内容不能再改"
        lines = _content_lines(values.get("方案内容"))
        if not lines:
            return None, "养护内容至少填一条"
        content = _content_lines(entry.get("方案内容"))
        content.extend(lines)
        entry["方案内容"] = content
        if "预算金额" in values:
            entry["预算金额"] = _budget(values.get("预算金额"))
        return entry, f"养护内容已补录 {len(lines)} 条，现共 {len(content)} 条"

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于季度养护方案可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        current = str(entry.get("status") or STATUS_ORDER[0])
        expected = STATUS_ORDER[STATUS_ORDER.index(target) - 1]
        if current != expected:
            return None, f"要先流转到「{expected}」才能{action}，当前状态是「{current}」"
        if action == "编制方案" and not _content_lines(entry.get("方案内容")):
            return None, "养护内容还没逐条填写，不能标记为已编制"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "审批方案":
            approver = str((values or {}).get("审批人") or "").strip()
            if approver:
                entry["审批人"] = approver
        entry["方案状态"] = target
        return entry, f"养护方案已{action}"

    # ---------- 批量送审 ----------
    def submit_batch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, str]:
        """同一季度的方案多选后一次送审；同一批复式提交只认第一次。"""
        quarter = str(values.get("方案季度") or "").strip()
        if not quarter:
            return None, False, "方案季度不能为空：同一批方案按季度统一带出"
        plan_ids = self._resolve_plan_ids(values, quarter)
        if not plan_ids:
            return None, False, "至少选择一片本季度覆盖的绿地再送审"
        plans, missing, off_quarter, excluded = [], [], [], []
        for pid in plan_ids:
            entry = store.find(MODULE, pid)
            if entry is None:
                missing.append(pid)
            elif str(entry.get("方案季度") or "") != quarter:
                off_quarter.append(entry)
            elif entry.get("status") not in SUBMITTABLE_STATUSES:
                excluded.append(entry)
            else:
                plans.append(entry)
        if missing:
            return None, False, f"方案 {missing} 不存在或已归档，本批未送出"
        if off_quarter:
            names = "、".join(f"{p.get('方案编号')}({p.get('方案季度')})" for p in off_quarter)
            return None, False, f"以下方案不属于 {quarter}，不能混入本批：{names}"
        if not plans:
            return None, False, "所选方案都已审批过，没有可送审的内容"
        batch_no = str(values.get("批次号") or "").strip() or self._derive_batch_no(
            quarter, [int(p["id"]) for p in plans]
        )
        existing = self.get_batch(batch_no)
        if existing is not None:
            return existing, False, f"批次 {batch_no} 已送审过，同一批方案只认第一次提交"
        batches = store.rows(BATCH_MODULE)
        batch = {
            "id": max((int(b.get("id", 0)) for b in batches), default=0) + 1,
            "批次号": batch_no,
            "方案季度": quarter,
            "方案ids": [int(p["id"]) for p in plans],
            "方案数": len(plans),
            "状态": "已送审",
            "审批人": "",
            "退回原因": "",
            "审批结果": None,
            "预算合计": 0.0,
        }
        batches.append(batch)
        for plan in plans:
            plan["批次号"] = batch_no
        message = f"批次 {batch_no} 已送审：{quarter} 共 {len(plans)} 片绿地"
        if excluded:
            names = "、".join(str(p.get("方案编号")) for p in excluded)
            message += f"；{names} 已审批过，未纳入本批"
        return batch, True, message

    def list_batches(
        self, *, quarter: str | None = None, page: int = 1, size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(BATCH_MODULE)
        if quarter:
            rows = [b for b in rows if str(b.get("方案季度")) == quarter]
        rows = sorted(rows, key=lambda b: int(b.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_batch(self, batch_no: str) -> dict[str, Any] | None:
        for batch in store.rows(BATCH_MODULE):
            if str(batch.get("批次号")) == str(batch_no):
                return batch
        return None

    def approve_batch(self, batch_no: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """批量审批：未编完的先挑出来，退回的留在原处等重提，其余一次审完。

        批次一旦审过就封板：重复审批直接回第一次的结果，预算合计不会被改写。
        """
        batch = self.get_batch(batch_no)
        if batch is None:
            return None, f"送审批次 {batch_no} 不存在"
        if batch.get("审批结果"):
            return batch, f"批次 {batch_no} 已审批过，按第一次审批结果为准"
        approver = str(values.get("审批人") or "").strip()
        if not approver:
            return None, "审批人不能为空"
        reject_ids: set[int] = set()
        for raw in values.get("退回ids") or []:
            try:
                reject_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
        reason = str(values.get("退回原因") or "").strip()
        approved, unfinished, rejected, skipped = [], [], [], []
        for pid in batch.get("方案ids") or []:
            entry = store.find(MODULE, int(pid))
            if entry is None:
                skipped.append({"id": pid, "原因": "方案不存在或已归档"})
                continue
            status = str(entry.get("status") or "")
            if status == "待编制":
                unfinished.append(_brief(entry))
                continue
            if status != "已编制":
                skipped.append({**_brief(entry), "原因": f"已是「{status}」，不重复审"})
                continue
            if int(pid) in reject_ids:
                # 退回：状态留在已编制，等下一批重新送审
                rejected.append(_brief(entry))
                continue
            entry["status"] = "已审批"
            entry["pending"] = True
            entry["审批人"] = approver
            entry["方案状态"] = "已审批"
            approved.append(_brief(entry))
        budget_total = round(sum(item["预算金额"] for item in approved), 2)
        batch["审批人"] = approver
        batch["退回原因"] = reason
        batch["审批结果"] = {
            "已审": approved,
            "未编完挑出": unfinished,
            "退回": rejected,
            "跳过": skipped,
        }
        batch["预算合计"] = budget_total
        batch["状态"] = "部分退回" if rejected else "已审批"
        message = (
            f"批次 {batch_no} 审批完成：通过 {len(approved)} 条、退回 {len(rejected)} 条、"
            f"未编完挑出 {len(unfinished)} 条，预算合计 {budget_total} 万元"
        )
        return batch, message

    # ---------- 审批汇总 ----------
    def summary(
        self,
        *,
        quarter: str | None = None,
        budget_min: float | None = None,
        budget_max: float | None = None,
    ) -> dict[str, Any]:
        """审批汇总：方案季度与预算条件同时给时以方案季度为准，并和方案台账、批次留痕对账。"""
        notes = []
        ledger = [row for row in store.rows(MODULE) if row.get("status") in APPROVED_STATUSES]
        if quarter:
            rows = [row for row in ledger if str(row.get("方案季度") or "") == quarter]
            if budget_min is not None or budget_max is not None:
                notes.append("方案季度与预算条件同时存在，以方案季度为准")
        else:
            rows = ledger
            if budget_min is not None:
                rows = [row for row in rows if _budget(row.get("预算金额")) >= budget_min]
            if budget_max is not None:
                rows = [row for row in rows if _budget(row.get("预算金额")) <= budget_max]
        ledger_total = round(sum(_budget(row.get("预算金额")) for row in rows), 2)
        batches = [b for b in store.rows(BATCH_MODULE) if b.get("审批结果")]
        if quarter:
            batches = [b for b in batches if str(b.get("方案季度")) == quarter]
        trace_items = [
            item
            for batch in batches
            for item in (batch.get("审批结果") or {}).get("已审") or []
        ]
        if not quarter:
            if budget_min is not None:
                trace_items = [i for i in trace_items if _budget(i.get("预算金额")) >= budget_min]
            if budget_max is not None:
                trace_items = [i for i in trace_items if _budget(i.get("预算金额")) <= budget_max]
        trace_total = round(sum(_budget(item.get("预算金额")) for item in trace_items), 2)
        balanced = len(rows) == len(trace_items) and ledger_total == trace_total
        if not notes:
            notes.append("按方案季度汇总审批通过的方案" if quarter else "未限定季度，按预算条件汇总审批通过的方案")
        return {
            "方案季度": quarter or "全部",
            "口径说明": "；".join(notes),
            "审批汇总": {"条数": len(rows), "预算合计": ledger_total},
            "台账核对": {
                "台账条数": len(rows),
                "台账预算合计": ledger_total,
                "批次留痕条数": len(trace_items),
                "批次留痕预算合计": trace_total,
                "是否对上": balanced,
            },
            "明细": [
                {**_brief(row), "方案季度": row.get("方案季度"), "审批人": row.get("审批人")}
                for row in rows
            ],
        }

    # ---------- 内部小工具 ----------
    def _resolve_plan_ids(self, values: dict[str, Any], quarter: str) -> list[int]:
        """方案ids 直接给；给覆盖绿地名单时按季度落回方案id。"""
        ids: list[int] = []
        for raw in values.get("方案ids") or []:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        plots = {str(p).strip() for p in values.get("覆盖绿地") or [] if str(p).strip()}
        if plots:
            for row in store.rows(MODULE):
                if str(row.get("方案季度") or "") == quarter and str(row.get("覆盖绿地") or "") in plots:
                    ids.append(int(row.get("id", 0)))
        deduped: list[int] = []
        for pid in ids:
            if pid not in deduped:
                deduped.append(pid)
        return deduped

    @staticmethod
    def _derive_batch_no(quarter: str, plan_ids: list[int]) -> str:
        """没传批次号时按季度+方案清单算一个稳定号：同一批复式提交自然落到同一条。"""
        digest = hashlib.sha1(
            f"{quarter}|{','.join(map(str, sorted(plan_ids)))}".encode("utf-8")
        ).hexdigest()[:8]
        return f"{quarter}-{digest}"
