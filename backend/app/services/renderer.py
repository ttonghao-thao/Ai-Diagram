"""Bounded, shell-free bridge to the TypeScript renderer CLI."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.schemas.api import ApiException, ErrorCode

ERROR_LINE = re.compile(r"^(ERROR|WARNING)\s+([A-Z0-9_]+):\s+(.*)$")
KNOWN_ERRORS = {
    ErrorCode.SCHEMA_INVALID, ErrorCode.GRAPH_DUPLICATE_ID, ErrorCode.GRAPH_INVALID_REFERENCE,
    ErrorCode.GRAPH_GROUP_CYCLE, ErrorCode.LAYOUT_CONFLICT, ErrorCode.DRAWIO_PARSE_FAILED,
    ErrorCode.DRAWIO_UNSUPPORTED_CONTENT, ErrorCode.TOPOLOGY_MISMATCH,
}


@dataclass
class RenderResult:
    drawio_bytes: bytes
    warnings: list[dict]
    quality: dict


def _parse_cli_output(stderr: str) -> list[dict]:
    issues = []
    for line in stderr.splitlines():
        match = ERROR_LINE.match(line.strip())
        if match:
            issues.append({"severity": match[1].lower(), "code": match[2], "message": match[3]})
    return issues


class RendererService:
    def __init__(
        self,
        cli_path: Path,
        icons_dir: Optional[Path] = None,
        timeout_seconds: int = 60,
        output_limit_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.cli_path = cli_path
        self.icons_dir = icons_dir
        self.timeout_seconds = timeout_seconds
        self.output_limit_bytes = output_limit_bytes

    def available(self) -> bool:
        return self.cli_path.is_file()

    def _run(self, command: str, args: list[str]) -> tuple[int, list[dict]]:
        if not self.available():
            raise ApiException(ErrorCode.RENDERER_UNAVAILABLE, "renderer CLI not found; build renderer with npm run build")
        argv = ["node", str(self.cli_path), command, *args]
        if self.icons_dir is not None and command != "validate":
            argv.extend(["--icons-dir", str(self.icons_dir)])
        try:
            with tempfile.TemporaryFile() as diagnostics:
                proc = subprocess.run(
                    argv, shell=False, stdout=subprocess.DEVNULL, stderr=diagnostics, timeout=self.timeout_seconds,
                )
                diagnostics.seek(0)
                stderr = diagnostics.read(min(self.output_limit_bytes, 64 * 1024)).decode("utf-8", "replace")
        except subprocess.TimeoutExpired as exc:
            raise ApiException(ErrorCode.RENDERER_FAILED, f"renderer timed out after {self.timeout_seconds}s") from exc
        except OSError as exc:
            raise ApiException(ErrorCode.RENDERER_UNAVAILABLE, "renderer could not be started") from exc
        return proc.returncode, _parse_cli_output(stderr)

    def _read(self, path: Path) -> bytes:
        if not path.is_file() or path.stat().st_size > self.output_limit_bytes:
            raise ApiException(ErrorCode.RENDERER_FAILED, "renderer output is missing or exceeds the size limit")
        return path.read_bytes()

    def _invoke(self, command: str, graph: Dict[str, Any], context=None, drawio=None) -> tuple[bytes, Any]:
        with tempfile.TemporaryDirectory(prefix="ai-render-") as folder:
            root = Path(folder)
            graph_path = root / "graph.json"
            result = root / "result"
            graph_path.write_text(json.dumps(graph, ensure_ascii=False, allow_nan=False), encoding="utf-8")
            args = ["--input", str(graph_path), "--output", str(result)]
            if context:
                context_path = root / "context.json"
                context_path.write_text(json.dumps(context, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                args.extend(["--context", str(context_path)])
            if drawio is not None:
                drawio_path = root / "input.drawio"
                drawio_path.write_bytes(drawio)
                args.extend(["--drawio", str(drawio_path)])
            if command == "generate":
                report = root / "quality.json"
                args.extend(["--report", str(report)])
            code, issues = self._run(command, args)
            if code:
                first = next((issue for issue in issues if issue["severity"] == "error"), {})
                error = first.get("code")
                raise ApiException(
                    error if error in KNOWN_ERRORS else ErrorCode.RENDERER_FAILED,
                    first.get("message", "renderer failed to process the graph"),
                )
            extra = (issues, json.loads(self._read(report))) if command == "generate" else None
            return self._read(result), extra

    def render(self, graph: Dict[str, Any], context=None) -> RenderResult:
        data, (issues, report) = self._invoke("generate", graph, context)
        return RenderResult(data, [i for i in issues if i["severity"] == "warning"], report)

    def resolve(self, graph: Dict[str, Any], context=None) -> dict:
        data, _ = self._invoke("resolve", graph, context)
        return json.loads(data)

    def quality(self, graph: Dict[str, Any], drawio: bytes, context=None) -> dict:
        data, _ = self._invoke("quality", graph, context, drawio)
        return json.loads(data)

    def validate_drawio_file(self, path: Path) -> Tuple[bool, str]:
        code, issues = self._run("validate", ["--input", str(path)])
        return (False, "; ".join(i["message"] for i in issues) or "validation failed") if code else (True, "")
