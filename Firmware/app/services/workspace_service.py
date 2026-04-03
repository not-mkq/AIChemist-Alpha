from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse
from urllib.parse import quote
from fastapi import UploadFile


class WorkspaceService:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def list_files(self) -> List[Dict]:
        entries = []
        for path in self.root.rglob("*"):
            if path.is_file():
                entries.append(self._file_entry(path))
        entries.sort(key=lambda item: item["path"])
        return entries

    def index(self) -> Dict:
        files = []
        total_size = 0
        last_modified = 0.0
        for path in self.root.rglob("*"):
            if path.is_file():
                entry = self._file_entry(path)
                files.append({"path": entry["path"], "size": entry["size"], "modified": entry["modified"]})
                total_size += entry["size"]
                last_modified = max(last_modified, entry["modified"])
        files.sort(key=lambda item: item["path"])
        return {"files": files, "total_size": total_size, "last_modified": last_modified}

    def last_modified(self) -> float:
        last_modified = 0.0
        for path in self.root.rglob("*"):
            if path.is_file():
                last_modified = max(last_modified, path.stat().st_mtime)
        return last_modified

    def preview_file(self, rel_path: str, max_bytes: int = 200_000) -> Dict:
        file_path = self._workspace_path(rel_path)
        entry = self._file_entry(file_path)
        file_type = entry["type"]
        if file_type == "text":
            entry["content"] = file_path.read_text(encoding="utf-8", errors="ignore")[:max_bytes]
        elif file_type == "image":
            data = file_path.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            mime, _ = mimetypes.guess_type(file_path.as_posix())
            entry["content_base64"] = f"data:{mime or 'image/png'};base64,{b64}"
        else:
            entry["content"] = None
        entry["download_url"] = f"/workspace/file/download?path={quote(rel_path)}"
        return entry

    def download_file(self, rel_path: str) -> FileResponse:
        file_path = self._workspace_path(rel_path)
        return FileResponse(file_path, filename=file_path.name)

    def save_upload(self, upload: UploadFile, target_path: Optional[str] = None) -> Dict:
        """Save an uploaded file into the workspace and return file metadata."""
        filename = target_path or upload.filename
        if not filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        target = (self.root / filename).resolve()
        if not str(target).startswith(str(self.root)):
            raise HTTPException(status_code=400, detail="Invalid workspace path")
        target.parent.mkdir(parents=True, exist_ok=True)
        overwritten = target.exists()
        try:
            data = upload.file.read()
            target.write_bytes(data)
        finally:
            upload.file.close()
        entry = self._file_entry(target)
        entry["download_url"] = f"/workspace/file/download?path={quote(entry['path'])}"
        entry["overwritten"] = overwritten
        return entry

    # helpers ----------------------------------------------------------

    def _workspace_path(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        if not str(target).startswith(str(self.root)):
            raise HTTPException(status_code=400, detail="Invalid workspace path")
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        return target

    def _file_entry(self, path: Path) -> Dict:
        stat = path.stat()
        rel = path.relative_to(self.root).as_posix()
        return {
            "path": rel,
            "name": path.name,
            "size": stat.st_size,
            "modified": stat.st_mtime,
            "type": self._file_type(path),
        }

    def _file_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}:
            return "image"
        if suffix in {".txt", ".log", ".json", ".md", ".csv", ".tsv"}:
            return "text"
        if suffix in {".zip", ".tar", ".gz", ".rar", ".7z"}:
            return "archive"
        mime, _ = mimetypes.guess_type(path.as_posix())
        if mime and mime.startswith("text/"):
            return "text"
        if mime and mime.startswith("image/"):
            return "image"
        return "binary"
