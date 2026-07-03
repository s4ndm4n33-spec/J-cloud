"""Upload + download routes (single file, zip, folder, download_zip)."""
from __future__ import annotations

import io
import json
import shutil
import zipfile

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from deps import get_current_user, project_path, safe_join

router = APIRouter()


@router.post("/projects/{project_id}/upload")
async def upload_file(project_id: str, path: str = "", file: UploadFile = File(...),
                      user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    rel = path or file.filename or "upload.bin"
    target = safe_join(base, rel)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    target.write_bytes(content)
    return {"ok": True, "path": rel, "bytes": len(content)}


@router.post("/projects/{project_id}/upload_zip")
async def upload_zip(
    project_id: str,
    file: UploadFile = File(...),
    dest: str = "",
    strip_root: bool = True,
    user: dict = Depends(get_current_user),
):
    """Ingest a .zip into the workspace. Path-traversal safe, ignores junk dirs.

    strip_root=True drops the single top-level folder common in GitHub-style zips.
    """
    base = project_path(user["user_id"], project_id)
    dest_dir = safe_join(base, dest) if dest else base
    dest_dir.mkdir(parents=True, exist_ok=True)

    SKIP_PARTS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".DS_Store"}
    MAX_TOTAL_BYTES = 500 * 1024 * 1024
    MAX_FILE_BYTES = 100 * 1024 * 1024

    raw = await file.read()
    if len(raw) > MAX_TOTAL_BYTES:
        raise HTTPException(status_code=413, detail=f"Zip too large (>{MAX_TOTAL_BYTES // (1024*1024)}MB)")

    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise HTTPException(status_code=400, detail=f"Invalid zip: {e}") from e

    names = [n for n in zf.namelist() if not n.endswith("/")]
    if not names:
        raise HTTPException(status_code=400, detail="Zip is empty")

    strip_prefix = ""
    if strip_root:
        tops = {n.split("/", 1)[0] for n in names if "/" in n}
        only_tops = {n for n in names if "/" not in n}
        if len(tops) == 1 and not only_tops:
            strip_prefix = next(iter(tops)) + "/"

    total = 0
    written = 0
    skipped = 0
    written_paths: list[str] = []

    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        name = name.replace("\\", "/").lstrip("/")
        if strip_prefix and name.startswith(strip_prefix):
            name = name[len(strip_prefix):]
        if not name:
            continue
        parts = name.split("/")
        if any(p in SKIP_PARTS for p in parts) or any(p.startswith("..") for p in parts):
            skipped += 1
            continue
        if info.file_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Total uncompressed size exceeds 500MB cap")
        try:
            target = safe_join(dest_dir, name)
        except HTTPException:
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out, length=64 * 1024)
        written += 1
        if len(written_paths) < 200:
            written_paths.append(name)

    return {
        "ok": True,
        "files_written": written,
        "files_skipped": skipped,
        "total_bytes": total,
        "stripped_prefix": strip_prefix or None,
        "dest": dest or "(root)",
        "sample_paths": written_paths[:50],
    }


@router.post("/projects/{project_id}/upload_folder")
async def upload_folder(
    project_id: str,
    files: list[UploadFile] = File(...),
    paths: str = "",
    user: dict = Depends(get_current_user),
):
    """Upload multiple files preserving relative paths (browser folder picker)."""
    base = project_path(user["user_id"], project_id)
    rel_paths: list[str] = []
    if paths:
        try:
            rel_paths = json.loads(paths)
        except json.JSONDecodeError:
            rel_paths = []
    written: list[str] = []
    total_bytes = 0
    for i, f in enumerate(files):
        rel = rel_paths[i] if i < len(rel_paths) and rel_paths[i] else (f.filename or f"upload_{i}.bin")
        rel = rel.replace("\\", "/").lstrip("/")
        if any(p in (".git", "node_modules", "__pycache__") for p in rel.split("/")):
            continue
        try:
            target = safe_join(base, rel)
        except HTTPException:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await f.read()
        target.write_bytes(content)
        total_bytes += len(content)
        written.append(rel)
    return {"ok": True, "files_written": len(written), "total_bytes": total_bytes, "paths": written[:200]}


@router.get("/projects/{project_id}/download")
async def download_file(project_id: str, path: str,
                        user: dict = Depends(get_current_user)):
    base = project_path(user["user_id"], project_id)
    target = safe_join(base, path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, filename=target.name)


@router.get("/projects/{project_id}/download_zip")
async def download_zip(project_id: str, path: str = "",
                       user: dict = Depends(get_current_user)):
    """Download a project — or a specific folder inside it — as a .zip."""
    base = project_path(user["user_id"], project_id)
    if path:
        target = safe_join(base, path)
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=404, detail="Folder not found")
        zip_root = target
        zip_name = target.name or project_id
        path_prefix = target.name + "/"
    else:
        zip_root = base
        zip_name = project_id
        path_prefix = ""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in zip_root.rglob("*"):
            if any(part in (".git", "node_modules", "__pycache__", ".venv")
                   for part in p.parts):
                continue
            if p.is_file():
                rel = p.relative_to(zip_root).as_posix()
                zf.write(p, path_prefix + rel)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )
