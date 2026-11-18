from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.api.schemas import (
    SkillCreateRequest,
    SkillGithubInstallRequest,
    SkillGithubPreviewOut,
    SkillGithubPreviewRequest,
    SkillOut,
    SkillPendingOut,
    SkillPendingResolveRequest,
    SkillToggleRequest,
)
from app.db.models import User
from app.services import audit, skills_service
from app.services.hermes import HermesClient, HermesError

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillUpdateBody(BaseModel):
    description: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=1, max_length=64000)
    category: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None


async def _fetch_hermes_skills(user: User) -> list:
    client = HermesClient(user.hermes_profile, user.hermes_api_key)
    try:
        return await client.skills()
    except HermesError:
        return []
    finally:
        await client.aclose()


@router.get("", response_model=list[SkillOut])
async def list_skills(user: User = Depends(get_current_user)) -> list[SkillOut]:
    hermes_skills = await _fetch_hermes_skills(user)
    items = skills_service.list_skills(user.hermes_profile, hermes_skills=hermes_skills)
    return [SkillOut(**item) for item in items]


@router.get("/pending", response_model=list[SkillPendingOut])
async def list_pending_skills(user: User = Depends(get_current_user)) -> list[SkillPendingOut]:
    items = skills_service.list_pending(user.hermes_profile)
    return [SkillPendingOut(**item) for item in items]


@router.post("", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill(
    body: SkillCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> SkillOut:
    try:
        created = skills_service.create_custom_skill(
            user,
            name=body.name,
            description=body.description,
            content=body.content,
            category=body.category,
            enabled=body.enabled,
        )
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "skill.create",
        actor=user,
        target_type="skill",
        target_id=created["name"],
        request=request,
        metadata={"enabled": created["enabled"]},
    )
    return SkillOut(**created)


@router.put("/{name}", response_model=SkillOut)
async def update_skill(
    name: str,
    body: SkillUpdateBody,
    request: Request,
    user: User = Depends(get_current_user),
) -> SkillOut:
    try:
        updated = skills_service.update_custom_skill(
            user,
            name,
            description=body.description,
            content=body.content,
            category=body.category,
            enabled=body.enabled,
        )
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "skill.update",
        actor=user,
        target_type="skill",
        target_id=updated["name"],
        request=request,
    )
    return SkillOut(**updated)


@router.patch("/{name}", response_model=SkillOut)
async def toggle_skill(
    name: str,
    body: SkillToggleRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> SkillOut:
    hermes_skills = await _fetch_hermes_skills(user)
    try:
        updated = skills_service.toggle_skill(
            user,
            name,
            body.enabled,
            hermes_skills=hermes_skills,
        )
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "skill.toggle",
        actor=user,
        target_type="skill",
        target_id=updated["name"],
        request=request,
        metadata={"enabled": body.enabled},
    )
    return SkillOut(**updated)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    try:
        skills_service.delete_skill(user, name)
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "skill.delete",
        actor=user,
        target_type="skill",
        target_id=name,
        request=request,
    )


@router.post("/preview-github", response_model=SkillGithubPreviewOut)
async def preview_github_skill(
    body: SkillGithubPreviewRequest,
    user: User = Depends(get_current_user),
) -> SkillGithubPreviewOut:
    try:
        preview = await skills_service.preview_github_skill(
            body.url,
            ref=body.ref,
            path=body.path,
        )
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return SkillGithubPreviewOut(**preview)


@router.post("/install-github", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def install_github_skill(
    body: SkillGithubInstallRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> SkillOut:
    try:
        installed = await skills_service.install_github_skill(
            user,
            body.url,
            name=body.name,
            ref=body.ref,
            path=body.path,
            enabled=body.enabled,
        )
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "skill.install_github",
        actor=user,
        target_type="skill",
        target_id=installed["name"],
        request=request,
        metadata={"repo_url": installed.get("repo_url")},
    )
    return SkillOut(**installed)


@router.post("/pending/{pending_id}")
async def resolve_pending_skill(
    pending_id: str,
    body: SkillPendingResolveRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    try:
        installed = skills_service.resolve_pending(
            user,
            pending_id,
            body.action,
            content_override=body.content,
            enabled=body.enabled,
        )
    except skills_service.SkillServiceError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc

    await audit.record(
        "skill.pending_resolve",
        actor=user,
        target_type="skill_pending",
        target_id=pending_id,
        request=request,
        metadata={"action": body.action, "name": installed["name"] if installed else None},
    )
    return {
        "status": "approved" if body.action == "approve" else "rejected",
        "pending_id": pending_id,
        "skill": SkillOut(**installed).model_dump() if installed else None,
    }
