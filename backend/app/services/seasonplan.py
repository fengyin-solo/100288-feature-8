"""季度养护方案业务规则：多片绿地整季送审、逐条编制、批量审批/退回与预算对账。

一条方案对应「一个季度 + 一片绿地」；同一季度勾选多片绿地一次性送审会生成
一张批件（seasonplan batch）。所有状态流转只在本文件内发生，路由层不做判断。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "seasonplan"
BATCH_MODULE = "_seasonplan_batch"  # 批件内部表，下划线开头，不计入运营概览的业务模块
PLOT_MODULE = "plot"

REQUIRED_FIELDS = ["方案编号", "方案季度", "覆盖绿地"]
# 逐条编制时必须齐全才算「编完」：养护内容一条一条填，预算随该条方案落
CONTENT_FIELDS = ["方案内容", "预算金额"]
QUARTERS = ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]

STATUS_DRAFT = "待编制"
STATUS_DONE = "已编制"      # 编完，在批件里等审批
STATUS_APPROVED = "已审批"
STATUS_RUNNING = "执行中"
STATUS_ORDER = [STATUS_DRAFT, STATUS_DONE, STATUS_APPROVED, STATUS_RUNNING]

BATCH_WAITING = "待审批"
BATCH_APPROVED = "已审批"
BATCH_PARTIAL = "部分审批"

ACTION_RULES = {"编制方案": STATUS_DONE, "审批方案": STATUS_APPROVED, "启动执行": STATUS_RUNNING}
NEGATIVE_ACTIONS = []


def _to_number(value: Any) -> float | None:
    """预算金额宽松转数值；空值与非法值都按未填处理，由完整性校验兜住。"""
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2)


def _content_lines(entry: dict[str, Any]) -> list[str]:
    raw = str(entry.get("方案内容") or "")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _is_complete(entry: dict[str, Any]) -> bool:
    """编完的口径：养护内容至少有一条，预算金额是不小于 0 的数。"""
    return bool(_content_lines(entry)) and (_to_number(entry.get("预算金额")) is not None)


class SeasonplanService:
    # ---------------- 方案台账 ----------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        quarter: str | None = None,
        status: str | None = None,
        budget_min: str | None = None,
        budget_max: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("方案编号", ""))
                or keyword in str(row.get("覆盖绿地", ""))
            ]
        if quarter:
            rows = [row for row in rows if row.get("方案季度") == quarter]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        low = _to_number(budget_min)
        high = _to_number(budget_max)
        if low is not None:
            rows = [row for row in rows if (_to_number(row.get("预算金额")) or 0) >= low]
        if high is not None:
            rows = [row for row in rows if (_to_number(row.get("预算金额")) or 0) <= high]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["方案内容"] = values.get("方案内容") or ""
        entry["预算金额"] = _to_number(values.get("预算金额"))
        entry["编制人"] = values.get("编制人") or ""
        entry["审批人"] = ""
        entry["批次编号"] = ""
        entry["status"] = STATUS_DRAFT
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护方案 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于季度养护方案可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_RUNNING
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"养护方案已{action}"

    # ---------------- 整季选绿地 ----------------
    def quarter_plots(self, quarter: str) -> list[dict[str, Any]]:
        """某季度可勾选的绿地清单，并带出每片绿地在该季度的方案编制情况。"""
        entries = {
            str(row.get("覆盖绿地编号")): row
            for row in store.rows(MODULE)
            if row.get("方案季度") == quarter
        }
        result: list[dict[str, Any]] = []
        for plot in store.rows(PLOT_MODULE):
            code = str(plot.get("绿地编号") or "")
            entry = entries.get(code)
            result.append({
                "id": plot.get("id"),
                "绿地编号": code,
                "绿地名称": plot.get("绿地名称") or "",
                "所属区域": plot.get("所属区域") or "",
                "方案id": entry.get("id") if entry else None,
                "方案编号": entry.get("方案编号") if entry else "",
                "编制状态": entry.get("status") if entry else "未编制",
                "批次编号": entry.get("批次编号") if entry else "",
                "已编完": _is_complete(entry) if entry else False,
            })
        return result

    # ---------------- 一次性送审（幂等：同一批只认第一次） ----------------
    def submit_batch(
        self, quarter: str, plot_ids: list[int], operator: str
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """把同一季度覆盖的多片绿地一次性送审。

        幂等口径：方案季度相同、绿地集合相同即视为同一批，重复提交只认第一次，
        直接把首张批件原样带回，不再生成新批件、不覆盖任何已填内容。
        """
        if quarter not in QUARTERS:
            return None, f"方案季度「{quarter}」不在可编方案的季度范围内", False
        plots = [row for row in store.rows(PLOT_MODULE) if int(row.get("id", 0)) in plot_ids]
        if not plots:
            return None, "请至少勾选一片同一季度覆盖的绿地", False
        plot_codes = sorted(str(row.get("绿地编号") or "") for row in plots)
        key = frozenset(plot_codes)

        batches = store.rows(BATCH_MODULE)
        for batch in batches:
            existing = self._batch_plot_keys(batch)
            if batch.get("方案季度") == quarter and existing == key:
                return batch, "同一批方案重复提交，只认第一次，沿用首张批件", True

        entries = store.rows(MODULE)
        next_entry_id = max((int(row.get("id", 0)) for row in entries), default=0) + 1
        next_batch_id = max((int(row.get("id", 0)) for row in batches), default=0) + 1
        batch_no = f"BATCH-{quarter.replace('-', '')}-{next_batch_id:02d}"

        line_ids: list[int] = []
        for plot in plots:
            code = str(plot.get("绿地编号") or "")
            name = str(plot.get("绿地名称") or "")
            # 同季度同绿地已有方案条（例如上一张批件退回后留在原处）就沿用，不重建
            line = next(
                (
                    row
                    for row in entries
                    if row.get("方案季度") == quarter and row.get("覆盖绿地编号") == code
                ),
                None,
            )
            if line is None:
                line = {
                    "id": next_entry_id,
                    "方案编号": f"SEAS-{next_entry_id:04d}",
                    "方案季度": quarter,  # 方案季度统一带出，不逐条录
                    "覆盖绿地编号": code,
                    "覆盖绿地": f"{code} {name}".strip(),
                    "方案内容": "",
                    "预算金额": None,
                    "编制人": operator,
                    "审批人": "",
                    "批次编号": batch_no,
                    "status": STATUS_DRAFT,
                    "pending": True,
                    "abnormal": False,
                }
                entries.append(line)
                next_entry_id += 1
            else:
                line["批次编号"] = batch_no
                if operator and not line.get("编制人"):
                    line["编制人"] = operator
            line_ids.append(int(line["id"]))

        batch = {
            "id": next_batch_id,
            "批次编号": batch_no,
            "方案季度": quarter,
            "条目ids": line_ids,
            "status": BATCH_WAITING,
            "送审人": operator,
            "审批人": "",
            "预算合计": None,  # 审批时按整体结果落
            "退回说明": "",
            "pending": True,
            "abnormal": False,
        }
        batches.append(batch)
        return batch, f"已按 {quarter} 一次性送审 {len(line_ids)} 片绿地，待逐条编制后审批", False

    def list_batches(self, quarter: str | None = None) -> list[dict[str, Any]]:
        batches = store.rows(BATCH_MODULE)
        if quarter:
            batches = [row for row in batches if row.get("方案季度") == quarter]
        return sorted(batches, key=lambda row: int(row.get("id", 0)), reverse=True)

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        return store.find(BATCH_MODULE, batch_id)

    def batch_lines(self, batch: dict[str, Any]) -> list[dict[str, Any]]:
        ids = [int(value) for value in batch.get("条目ids", [])]
        return [line for line_id in ids if (line := store.find(MODULE, line_id))]

    # ---------------- 逐条编制 ----------------
    def fill_entry(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        """逐条养护内容回填：内容/预算齐全即「已编制」，缺一项就留在「待编制」。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"养护方案 {entry_id} 不存在或已归档"
        if entry.get("status") in (STATUS_APPROVED, STATUS_RUNNING):
            return None, "该条方案已审批锁定，养护内容不能再改"
        if "方案内容" in values:
            entry["方案内容"] = str(values.get("方案内容") or "").strip()
        if "预算金额" in values:
            budget = _to_number(values.get("预算金额"))
            if values.get("预算金额") not in (None, "") and budget is None:
                return None, "预算金额需填数字"
            entry["预算金额"] = budget
        if values.get("编制人"):
            entry["编制人"] = str(values.get("编制人"))

        if not _content_lines(entry):
            entry["status"] = STATUS_DRAFT
            entry["pending"] = True
            return entry, "已暂存，养护内容还没填完，仍为待编制"
        if _to_number(entry.get("预算金额")) is None:
            entry["status"] = STATUS_DRAFT
            entry["pending"] = True
            return entry, "已暂存，预算金额还没填，仍为待编制"
        entry["status"] = STATUS_DONE
        entry["pending"] = True
        return entry, "该条方案已编制完成，可随批送审"

    # ---------------- 批量审批 / 退回 ----------------
    def approve_batch(
        self, batch_id: int, reviewer: str
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any]]:
        """审批一张批件：先挑出没编完的，只审已编完的那几条。

        已审批的条不动（重复审批幂等）；批件预算合计按本次整体审批结果落。
        """
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"批件 {batch_id} 不存在", {}
        approved_ids: list[int] = []
        skipped_ids: list[int] = []
        untouched_ids: list[int] = []
        for line in self.batch_lines(batch):
            status = line.get("status")
            if status == STATUS_DONE:
                line["status"] = STATUS_APPROVED
                line["审批人"] = reviewer
                line["pending"] = False
                approved_ids.append(int(line["id"]))
            elif status == STATUS_DRAFT:
                skipped_ids.append(int(line["id"]))  # 还没编完，挑出来不审
            else:
                untouched_ids.append(int(line["id"]))  # 已审/执行中的不动

        approved_lines = [
            line for line in self.batch_lines(batch) if line.get("status") == STATUS_APPROVED
        ]
        total = round(sum(_to_number(line.get("预算金额")) or 0 for line in approved_lines), 2)
        if approved_ids:
            batch["审批人"] = reviewer
            batch["预算合计"] = total  # 按整体结果落预算
        all_lines = self.batch_lines(batch)
        if approved_lines and len(approved_lines) == len(all_lines):
            batch["status"] = BATCH_APPROVED
            batch["pending"] = False
        else:
            batch["status"] = BATCH_PARTIAL
            batch["pending"] = True
        detail = {
            "approved_ids": approved_ids,
            "skipped_unfinished_ids": skipped_ids,
            "untouched_ids": untouched_ids,
            "预算合计": total,
        }
        if not approved_ids:
            return batch, "本批没有已编完的方案可审，未编完的已挑出，批件保持待审批", detail
        message = f"已审批 {len(approved_ids)} 条；{len(skipped_ids)} 条未编完暂缓，已审条不动"
        return batch, message, detail

    def return_batch(
        self, batch_id: int, entry_ids: list[int], reason: str
    ) -> tuple[dict[str, Any] | None, str]:
        """退回批件里指定的条：已审的不动，退回的几条留在原批件处等重提。"""
        batch = store.find(BATCH_MODULE, batch_id)
        if batch is None:
            return None, f"批件 {batch_id} 不存在"
        members = {int(line["id"]): line for line in self.batch_lines(batch)}
        targets = [members.get(int(value)) for value in entry_ids if members.get(int(value))]
        returned = [line for line in targets if line and line.get("status") == STATUS_DONE]
        if not returned:
            return None, "勾选的条里没有待审批的已编制方案，可退回数为 0"
        for line in returned:
            line["status"] = STATUS_DRAFT
            line["pending"] = True
            line["abnormal"] = True
        batch["abnormal"] = True
        batch["退回说明"] = reason or "审批退回，请完善后重提"
        if any(line.get("status") == STATUS_APPROVED for line in self.batch_lines(batch)):
            batch["status"] = BATCH_PARTIAL
        return batch, f"已退回 {len(returned)} 条，已审的不动；退回条留在原批件等重提"

    # ---------------- 审批汇总与台账对账 ----------------
    def summary(
        self,
        *,
        quarter: str | None = None,
        budget_min: str | None = None,
        budget_max: str | None = None,
    ) -> dict[str, Any]:
        """审批汇总：批件预算合计必须与方案台账对得上。

        方案季度与预算两个条件相互牵连时以方案季度为准：先按季度收口，
        预算区间只在该季度内继续收窄，不跨季度取数。
        """
        rows = store.rows(MODULE)
        quarter_wins = bool(quarter) and (
            _to_number(budget_min) is not None or _to_number(budget_max) is not None
        )
        if quarter:
            rows = [row for row in rows if row.get("方案季度") == quarter]
        low = _to_number(budget_min)
        high = _to_number(budget_max)
        filtered = rows
        if low is not None:
            filtered = [row for row in filtered if (_to_number(row.get("预算金额")) or 0) >= low]
        if high is not None:
            filtered = [row for row in filtered if (_to_number(row.get("预算金额")) or 0) <= high]

        approved_rows = [row for row in filtered if row.get("status") == STATUS_APPROVED]
        ledger_total = round(
            sum(_to_number(row.get("预算金额")) or 0 for row in approved_rows), 2
        )

        batch_checks: list[dict[str, Any]] = []
        batches = store.rows(BATCH_MODULE)
        if quarter:
            batches = [row for row in batches if row.get("方案季度") == quarter]
        for batch in batches:
            approved_in_batch = [
                line
                for line in self.batch_lines(batch)
                if line.get("status") == STATUS_APPROVED
            ]
            ledger_value = round(
                sum(_to_number(line.get("预算金额")) or 0 for line in approved_in_batch), 2
            )
            snapshot = _to_number(batch.get("预算合计")) or 0
            batch_checks.append({
                "批次编号": batch.get("批次编号"),
                "方案季度": batch.get("方案季度"),
                "批件状态": batch.get("status"),
                "审批汇总预算": snapshot,          # 审批时按整体结果落下的数
                "台账核对预算": ledger_value,       # 方案台账逐条加总的数
                "已审批条数": len(approved_in_batch),
                "对得上": snapshot == ledger_value,
            })
        batch_total = round(sum(item["审批汇总预算"] for item in batch_checks), 2)
        return {
            "方案季度": quarter or "全部季度",
            "预算下限": low,
            "预算上限": high,
            "季度优先": quarter_wins,
            "口径说明": "方案季度与预算条件牵连时以方案季度为准，预算区间仅在季度内收窄"
            if quarter_wins
            else "",
            "台账已审批条数": len(approved_rows),
            "台账审批预算合计": ledger_total,
            "批件审批汇总预算": batch_total,
            "批件核对": batch_checks,
            "汇总对得上": batch_total == ledger_total,
        }

    # ---------------- 内部辅助 ----------------
    def _batch_plot_keys(self, batch: dict[str, Any]) -> frozenset[str]:
        codes = []
        for line in self.batch_lines(batch):
            code = str(line.get("覆盖绿地编号") or "")
            if code:
                codes.append(code)
        return frozenset(codes)
