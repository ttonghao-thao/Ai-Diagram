"""Bridge to the TypeScript renderer CLI (docs/01 section 7).

Security rules (docs/04 section 6):
  - the renderer is invoked with an argv array, shell=False;
  - fixed timeout and captured-output size limit;
  - user input never touches a shell string.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.schemas.api import ApiException, ErrorCode

ERROR_LINE = re.compile(r"^(ERROR|WARNING)\s+([A-Z0-9_]+):\s+(.*)$")


class RenderResult:
    def __init__(self, drawio_bytes: bytes, warnings: list[dict]) -> None:
        self.drawio_bytes = drawio_bytes
        self.warnings = warnings  # [{code, message, severity}]


def _parse_cli_output(stderr: str) -> list[dict]:
    issues = []
    for line in stderr.splitlines():
        m = ERROR_LINE.match(line.strip())
        if m:
            issues.append({"severity": m.group(1).lower(), "code": m.group(2), "message": m.group(3)})
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

    def render(self, graph: Dict[str, Any]) -> RenderResult:
        if not self.available():
            raise ApiException(
                ErrorCode.RENDERER_UNAVAILABLE,
                f"renderer CLI not found at {self.cli_path}; run `cd renderer && npm run build`",
            )
        with tempfile.TemporaryDirectory(prefix="ai-render-") as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "graph.json"
            output_path = tmp_path / "diagram.drawio"
            input_path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            argv = ["node", str(self.cli_path), "generate", "--input", str(input_path), "--output", str(output_path)]
            if self.icons_dir is not None:
                argv += ["--icons-dir", str(self.icons_dir)]
            try:
                proc = subprocess.run(
                    argv,
                    shell=False,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise ApiException(
                    ErrorCode.RENDERER_FAILED,
                    f"renderer timed out after {self.timeout_seconds}s",
                ) from exc
            stderr = (proc.stderr or b"").decode("utf-8", "replace")[: self.output_limit_bytes]
            stdout = (proc.stdout or b"").decode("utf-8", "replace")[: self.output_limit_bytes]
            issues = _parse_cli_output(stderr)
            if proc.returncode != 0:
                codes = [i["code"] for i in issues if i["severity"] == "error"]
                code = codes[0] if codes else ErrorCode.RENDERER_FAILED
                # Domain codes from the renderer keep their meaning; renderer
                # internal failures map to RENDERER_FAILED.
                known = {ErrorCode.SCHEMA_INVALID, ErrorCode.GRAPH_DUPLICATE_ID,
                         ErrorCode.GRAPH_INVALID_REFERENCE, ErrorCode.GRAPH_GROUP_CYCLE}
                if code not in known:
                    code = ErrorCode.RENDERER_FAILED
                raise ApiException(
                    code,
                    f"renderer rejected the graph: {'; '.join(i['message'] for i in issues if i['severity'] == 'error') or stdout or 'unknown error'}",
                )
            if not output_path.is_file():
                raise ApiException(ErrorCode.RENDERER_FAILED, "renderer produced no output file")
            size = output_path.stat().st_size
            if size > self.output_limit_bytes:
                raise ApiException(
                    ErrorCode.RENDERER_FAILED,
                    f"renderer output {size} bytes exceeds limit {self.output_limit_bytes}",
                )
            return RenderResult(output_path.read_bytes(), [i for i in issues if i["severity"] == "warning"])

    def validate_drawio_file(self, path: Path) -> Tuple[bool, str]:
        """Structural validation of a .drawio file through the renderer CLI."""
        if not self.available():
            raise ApiException(ErrorCode.RENDERER_UNAVAILABLE, f"renderer CLI not found at {self.cli_path}")
        try:
            proc = subprocess.run(
                ["node", str(self.cli_path), "validate", "--input", str(path)],
                shell=False,
                capture_output=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ApiException(ErrorCode.RENDERER_FAILED, f"renderer validate timed out after {self.timeout_seconds}s") from exc
        stderr = (proc.stderr or b"").decode("utf-8", "replace")[: self.output_limit_bytes]
        issues = _parse_cli_output(stderr)
        if proc.returncode != 0:
            msg = "; ".join(i["message"] for i in issues) or "validation failed"
            return False, msg
        return True, ""
