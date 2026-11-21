from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.models import User
from app.db.session import get_db
from app.services import audit, dashboard_telemetry

router = APIRouter(
    prefix="/api/admin/dashboards",
    tags=["admin-dashboards"],
    dependencies=[Depends(require_admin)],
)


@router.get("/schedules")
async def get_schedules_dashboard(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await dashboard_telemetry.collect_schedules_dashboard(db, days=days)


@router.get("/http-tools")
async def get_http_tools_dashboard(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await dashboard_telemetry.collect_http_tools_dashboard(db, days=days)


@router.get("/web-search")
async def get_web_search_dashboard(
    days: int = Query(default=14, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await dashboard_telemetry.collect_web_search_dashboard(db, days=days)


@router.get("/export")
async def export_dashboards_csv(
    request: Request,
    days: int = Query(default=14, ge=1, le=90),
    section: Literal["all", "schedules", "http", "search"] = Query(default="all"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    sched_data = (
        await dashboard_telemetry.collect_schedules_dashboard(db, days=days)
        if section in ("all", "schedules")
        else None
    )
    http_data = (
        await dashboard_telemetry.collect_http_tools_dashboard(db, days=days)
        if section in ("all", "http")
        else None
    )
    search_data = (
        await dashboard_telemetry.collect_web_search_dashboard(db, days=days)
        if section in ("all", "search")
        else None
    )

    await audit.record(
        "admin.dashboard_export",
        actor=admin,
        target_type="admin_dashboard",
        request=request,
        metadata={"days": days, "section": section},
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "section",
            "day",
            "total",
            "succeeded",
            "failed",
            "success_rate_pct",
            "extra_1",
            "extra_2",
        ]
    )
    if sched_data is not None:
        for row in sched_data["daily"]:
            writer.writerow(
                [
                    "schedules",
                    row["day"],
                    row["total"],
                    row["completed"],
                    row["failed"],
                    row["success_rate_pct"] if row["success_rate_pct"] is not None else "",
                    f"tokens={row['tokens']}",
                    f"cancelled={row['cancelled']};skipped={row['skipped']}",
                ]
            )
    if http_data is not None:
        for row in http_data["http_request"]["daily"]:
            writer.writerow(
                [
                    "http_request",
                    row["day"],
                    row["total"],
                    row["succeeded"],
                    row["failed"],
                    row["success_rate_pct"] if row["success_rate_pct"] is not None else "",
                    f"avg_ms={row['avg_duration_ms'] if row['avg_duration_ms'] is not None else ''}",
                    "",
                ]
            )
        for row in http_data["execute_code"]["daily"]:
            writer.writerow(
                [
                    "execute_code",
                    row["day"],
                    row["total"],
                    row["succeeded"],
                    row["failed"],
                    row["success_rate_pct"] if row["success_rate_pct"] is not None else "",
                    f"denied={row['denied']}",
                    "",
                ]
            )
    if search_data is not None:
        for row in search_data["daily"]:
            writer.writerow(
                [
                    "web_search",
                    row["day"],
                    row["total"],
                    row["succeeded"],
                    row["failed"],
                    row["success_rate_pct"] if row["success_rate_pct"] is not None else "",
                    f"with_results={row['with_results']}",
                    f"fallback={row['fallback_count']}",
                ]
            )

    ts_tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="whitz-automation-{section}-{days}d-{ts_tag}.csv"'
        },
    )
