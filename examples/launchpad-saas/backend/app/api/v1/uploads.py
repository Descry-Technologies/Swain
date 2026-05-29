from pathlib import Path

from fastapi import APIRouter, File, UploadFile

router = APIRouter()
UPLOAD_ROOT = Path("/srv/launchpad/uploads")


@router.post("/tenants/{tenant_id}/uploads")
async def upload_file(tenant_id: str, file: UploadFile = File(...)):
    destination = UPLOAD_ROOT / tenant_id / file.filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(await file.read())
    return {"path": str(destination)}
