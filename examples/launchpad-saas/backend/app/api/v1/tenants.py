from typing import Any

from fastapi import APIRouter, Depends

router = APIRouter()
db: Any = None


def current_user():
    return {"id": "user_123", "tenant_id": "tenant_a", "role": "member"}


@router.get("/tenants/{tenant_id}/settings")
def get_tenant_settings(tenant_id: str, user=Depends(current_user)):
    return db.fetch_one(
        "select * from tenant_settings where tenant_id = :tenant_id",
        tenant_id=tenant_id,
    )


@router.post("/tenants/{tenant_id}/admins/{user_id}")
def promote_admin(tenant_id: str, user_id: str, user=Depends(current_user)):
    db.execute(
        "update memberships set role = 'admin' "
        "where tenant_id = :tenant_id and user_id = :user_id",
        tenant_id=tenant_id,
        user_id=user_id,
    )
    return {"ok": True}
