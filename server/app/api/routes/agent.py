from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.db.models import User
from app.services.hermes import HermesClient, HermesError

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/status")
async def agent_status(user: User = Depends(get_current_user)) -> dict:
    client = HermesClient(user.hermes_profile, user.hermes_api_key)
    try:
        ready = await client.health()
        if not ready:
            return {"ready": False, "status": "warming_up"}
        capabilities = await client.capabilities()
        toolsets = await client.toolsets()
        enabled = [t["name"] for t in toolsets.get("data", []) if t.get("enabled")]
        return {
            "ready": True,
            "status": "online",
            "version": capabilities.get("version"),
            "model": capabilities.get("model"),
            "enabled_toolsets": enabled,
        }
    except HermesError as exc:
        return {"ready": False, "status": "error", "detail": exc.detail}
    finally:
        await client.aclose()