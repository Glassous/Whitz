import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.schemas import (
    ScheduleOverviewOut,
    SchedulePreviewOut,
    SchedulePreviewRequest,
    ScheduledTaskCreateRequest,
    ScheduledTaskDetailOut,
    ScheduledTaskOut,
    ScheduledTaskPendingOut,
    ScheduledTaskPendingResolveRequest,
    ScheduledTaskRunOut,
    ScheduledTaskUpdateRequest,
)
from app.db.models import User
from app.db.session import get_db
from app.services import audit, schedule_calc, scheduler_service

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=ScheduleOverviewOut)
async def list_schedules(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleOverviewOut:
    data = await scheduler_service.list_overview(db, user)
    return ScheduleOverviewOut(**data)


@router.post("/preview", response_model=SchedulePreviewOut)
async def preview_schedule(
    body: SchedulePreviewRequest,
    user: User = Depends(get_current_user),
) -> SchedulePreviewOut:
    quota = scheduler_service.quota_for_user(user)
    tz_val = (body.timezone or "").strip() or (user.timezone or "Asia/Shanghai")
    try:
        desc, runs = schedule_calc.preview_next_runs(
            body.schedule_type,
            body.schedule_config,
            tz_val,
            count=body.count,
            min_interval_minutes=quota["min_interval_minutes"],
        )
        return SchedulePreviewOut(valid=True, schedule_description=desc, next_runs=runs)
    except schedule_calc.ScheduleValidationError as exc:
        return SchedulePreviewOut(valid=False, error=str(exc))


@router.get("/pending", response_model=list[ScheduledTaskPendingOut])
async def list_pending_schedule_proposals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduledTaskPendingOut]:
    items = await scheduler_service.list_pending(db, user.id)
    return [ScheduledTaskPendingOut(**item) for item in items]


@router.post("/pending/{proposal_id}")
async def resolve_pending_schedule_proposal(
    proposal_id: uuid.UUID,
    body: ScheduledTaskPendingResolveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await scheduler_service.resolve_proposal(db, user, proposal_id, body.action)
    except scheduler_service.ScheduleServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    await audit.record(
        "schedule.proposal.resolve",
        actor=user,
        target_type="scheduled_task_proposal",
        target_id=str(proposal_id),
        request=request,
        metadata={"decision": body.action, "status": result.get("status")},
    )
    return result


@router.post("", response_model=ScheduledTaskOut, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    body: ScheduledTaskCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduledTaskOut:
    try:
        created = await scheduler_service.create_task(
            db,
            user,
            name=body.name,
            prompt=body.prompt,
            schedule_type=body.schedule_type,
            schedule_config=body.schedule_config,
            timezone_name=body.timezone,
            target_mode=body.target_mode,
            conversation_id=body.conversation_id,
            model_route=body.model_route,
            skill_names=body.skill_names,
            enabled=body.enabled,
            max_runs=body.max_runs,
            source="manual",
        )
    except scheduler_service.ScheduleServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "schedule.create",
        actor=user,
        target_type="scheduled_task",
        target_id=str(created["id"]),
        request=request,
        metadata={"schedule_type": created["schedule_type"], "enabled": created["enabled"]},
    )
    return ScheduledTaskOut(**created)


@router.get("/{task_id}", response_model=ScheduledTaskDetailOut)
async def get_schedule(
    task_id: uuid.UUID,
    runs_limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduledTaskDetailOut:
    try:
        detail = await scheduler_service.get_task_detail(db, user, task_id, runs_limit=runs_limit)
    except scheduler_service.ScheduleServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return ScheduledTaskDetailOut(**detail)


@router.patch("/{task_id}", response_model=ScheduledTaskOut)
async def update_schedule(
    task_id: uuid.UUID,
    body: ScheduledTaskUpdateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduledTaskOut:
    try:
        updated = await scheduler_service.update_task(
            db,
            user,
            task_id,
            name=body.name,
            prompt=body.prompt,
            schedule_type=body.schedule_type,
            schedule_config=body.schedule_config,
            timezone_name=body.timezone,
            target_mode=body.target_mode,
            conversation_id=body.conversation_id,
            model_route=body.model_route,
            skill_names=body.skill_names,
            enabled=body.enabled,
            max_runs=body.max_runs,
        )
    except scheduler_service.ScheduleServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "schedule.update",
        actor=user,
        target_type="scheduled_task",
        target_id=str(task_id),
        request=request,
        metadata={"enabled": updated["enabled"], "schedule_type": updated["schedule_type"]},
    )
    return ScheduledTaskOut(**updated)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await scheduler_service.delete_task(db, user, task_id)
    except scheduler_service.ScheduleServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    await audit.record(
        "schedule.delete",
        actor=user,
        target_type="scheduled_task",
        target_id=str(task_id),
        request=request,
    )


@router.post("/{task_id}/run-now", response_model=ScheduledTaskRunOut)
async def run_schedule_now(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduledTaskRunOut:
    try:
        run_out = await scheduler_service.trigger_task_now(db, user, task_id)
    except scheduler_service.ScheduleServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    await audit.record(
        "schedule.run_now",
        actor=user,
        target_type="scheduled_task",
        target_id=str(task_id),
        request=request,
        metadata={"run_record_id": str(run_out["id"])},
    )
    return ScheduledTaskRunOut(**run_out)
