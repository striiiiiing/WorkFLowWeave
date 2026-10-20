"""Serve installed web assets without masking API or missing asset errors."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


class WebAppFiles(StaticFiles):
    async def get_response(self, path, scope):
        first = path.split("/", 1)[0]
        if first in {"api", "docs", "redoc", "openapi.json"}:
            raise HTTPException(404)
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if first == "assets" or Path(path).suffix:
                raise
            if scope["method"] not in {"GET", "HEAD"}:
                raise
            return FileResponse(Path(self.directory) / "index.html")
