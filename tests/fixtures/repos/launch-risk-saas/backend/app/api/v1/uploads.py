from pathlib import Path

from fastapi import APIRouter, File, UploadFile

router = APIRouter()
UPLOAD_ROOT = Path("/srv/app/uploads")


@router.post("/tenants/{tenant_id}/uploads")
async def upload_file(tenant_id: str, file: UploadFile = File(...)):
    # Vulnerable fixture: unauthenticated route, tenant_id is trusted, filename
    # can escape UPLOAD_ROOT, and there is no size/content validation.
    destination = UPLOAD_ROOT / tenant_id / file.filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(await file.read())
    return {"path": str(destination)}
