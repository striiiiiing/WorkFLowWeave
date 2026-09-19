"""Thin Typer CLI; business commands call the HTTP API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer
import uvicorn

from logagent.lifecycle import ApplicationLifecycle
from logagent.models import ErrorInfo, ErrorResponse, SystemConfig

from .app import create_app

app = typer.Typer(no_args_is_help=True, help="LogAgent service and API client.")
resource_app = typer.Typer(no_args_is_help=True, help="Manage saved resources.")
app.add_typer(resource_app, name="resource")

ApiUrl = Annotated[
    str,
    typer.Option("--api-url", envvar="LOGAGENT_API_URL", help="LogAgent API base URL."),
]


def _print_json(value: Any, *, error: bool = False) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2), err=error)


def _request(
    method: str,
    path: str,
    *,
    api_url: str,
    json_body: Any | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        with httpx.Client(base_url=api_url, timeout=httpx.Timeout(30.0)) as client:
            response = client.request(method, path, json=json_body, params=params)
    except httpx.HTTPError:
        body = ErrorResponse(
            error=ErrorInfo(code="connection_failed", message="Unable to reach LogAgent API")
        )
        _print_json(body.model_dump(mode="json"), error=True)
        raise typer.Exit(1) from None

    if response.status_code >= 400:
        try:
            body = response.json()
        except ValueError:
            body = ErrorResponse(
                error=ErrorInfo(code="http_error", message="API returned an error")
            ).model_dump(mode="json")
        _print_json(body, error=True)
        raise typer.Exit(2 if response.status_code < 500 else 1)
    if response.status_code == 204:
        return None
    return response.json()


async def _serve(config_path: Path) -> None:
    lifecycle = await ApplicationLifecycle.from_file(config_path)
    config = uvicorn.Config(
        create_app(lifecycle),
        host=lifecycle.config.host,
        port=lifecycle.config.port,
        lifespan="on",
        workers=1,
    )
    await uvicorn.Server(config).serve()


@app.command()
def start(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", exists=True, dir_okay=False, readable=True),
    ] = Path("config.json"),
) -> None:
    """Start the API service with one process and one lifecycle owner."""
    asyncio.run(_serve(config))


@app.command("config-example")
def config_example(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", dir_okay=False),
    ] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Print or write a strict SystemConfig example."""
    value = SystemConfig().model_dump(mode="json")
    if output is None:
        _print_json(value)
        return
    if output.exists() and not force:
        raise typer.BadParameter("output already exists; use --force to replace it")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _print_json({"config": str(output)})


@resource_app.command("list")
def resource_list(
    kind: str,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(_request("GET", f"/api/{kind}", api_url=api_url))


@resource_app.command("show")
def resource_show(
    kind: str,
    ident: str,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(_request("GET", f"/api/{kind}/{ident}", api_url=api_url))


@resource_app.command("save")
def resource_save(
    kind: Annotated[str, typer.Argument()],
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    create: Annotated[bool, typer.Option("--create")] = False,
    replace: Annotated[bool, typer.Option("--replace")] = False,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    if create and replace:
        raise typer.BadParameter("--create and --replace are mutually exclusive")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        body = ErrorResponse(
            error=ErrorInfo(code="invalid_config", message="Resource file is not valid JSON")
        )
        _print_json(body.model_dump(mode="json"), error=True)
        raise typer.Exit(2) from None
    if not isinstance(payload, dict):
        body = ErrorResponse(
            error=ErrorInfo(code="invalid_config", message="Resource must be a JSON object")
        )
        _print_json(body.model_dump(mode="json"), error=True)
        raise typer.Exit(2)
    ident = payload.get("id")
    if not isinstance(ident, str) or not ident:
        body = ErrorResponse(
            error=ErrorInfo(code="invalid_config", message="Resource requires a string id")
        )
        _print_json(body.model_dump(mode="json"), error=True)
        raise typer.Exit(2)
    if create:
        result = _request("POST", f"/api/{kind}", api_url=api_url, json_body=payload)
    else:
        result = _request("PUT", f"/api/{kind}/{ident}", api_url=api_url, json_body=payload)
    _print_json(result)


@resource_app.command("delete")
def resource_delete(
    kind: str,
    ident: str,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _request("DELETE", f"/api/{kind}/{ident}", api_url=api_url)
    _print_json({"deleted": ident, "kind": kind})


@app.command()
def run(
    workflow_id: str,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(
        _request(
            "POST",
            "/api/workflows/trigger",
            api_url=api_url,
            json_body={"workflow_id": workflow_id},
        )
    )


@app.command()
def sessions(
    workflow_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    after: str | None = None,
    before: str | None = None,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    params = {
        "workflow_id": workflow_id,
        "limit": limit,
        "offset": offset,
        "after": after,
        "before": before,
    }
    _print_json(
        _request(
            "GET",
            "/api/sessions",
            api_url=api_url,
            params={key: value for key, value in params.items() if value is not None},
        )
    )


@app.command()
def session(
    session_id: str,
    version: int | None = None,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    params = {"version": version} if version is not None else None
    _print_json(
        _request(
            "GET",
            f"/api/sessions/{session_id}",
            api_url=api_url,
            params=params,
        )
    )


@app.command()
def phase(
    session_id: str,
    stage: str,
    version: int,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(
        _request(
            "GET",
            f"/api/sessions/{session_id}/phases/{stage}",
            api_url=api_url,
            params={"version": version},
        )
    )


@app.command()
def recover(
    session_id: str,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(
        _request("POST", f"/api/sessions/{session_id}/recover", api_url=api_url)
    )


@app.command()
def cancel(
    session_id: str,
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(_request("POST", f"/api/sessions/{session_id}/cancel", api_url=api_url))


@app.command()
def plugins(api_url: ApiUrl = "http://127.0.0.1:8000") -> None:
    _print_json(_request("GET", "/api/plugins", api_url=api_url))


@app.command()
def health(api_url: ApiUrl = "http://127.0.0.1:8000") -> None:
    _print_json(_request("GET", "/api/health", api_url=api_url))


@app.command()
def reload(
    scope: str = "resources",
    api_url: ApiUrl = "http://127.0.0.1:8000",
) -> None:
    _print_json(
        _request(
            "POST",
            "/api/reload",
            api_url=api_url,
            params={"scope": scope},
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
