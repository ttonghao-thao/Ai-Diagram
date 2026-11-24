"""Score the fixed V1.2 corpus against a configured real OpenAI-compatible model."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings
from app.graph.patch import preview_patch
from app.graph.validate import collect_graph_issues
from app.llm.adapter import build_adapter
from app.schemas.api import ApiException
from app.schemas.graph import GraphDocument
from app.services.materials import normalize_devices
from app.services.renderer import RendererService


def label(value: str) -> str:
    return re.sub(r"[\s\-]+", "", unicodedata.normalize("NFKC", value).casefold())


def relation(source: str, target: str, kind: str) -> tuple[str, str, str]:
    a, b = label(source), label(target)
    if kind == "physical":
        a, b = sorted((a, b))
    return a, b, kind


def counts(actual, expected):
    return [len(actual & expected), len(actual - expected), len(expected - actual)]


def score(members):
    correct, extra, missing = (sum(values) for values in zip(*members))
    return {"precision": correct / max(1, correct + extra),
            "recall": correct / max(1, correct + missing),
            "f1": 2 * correct / max(1, 2 * correct + extra + missing),
            "correct": correct, "extra": extra, "missing": missing}


async def run(settings, output: Path) -> None:
    if not settings.llm_enabled or settings.llm_provider == "mock" or not settings.llm_model:
        raise SystemExit("启用并配置真实 OpenAI-compatible 模型后再执行。")
    adapter = build_adapter(settings)
    renderer = RendererService(settings.renderer_cli)
    cases = json.loads((ROOT / "fixtures/acceptance/v1_2_natural_language.json").read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        started = time.perf_counter()
        row = {"id": case["id"], "schemaValid": False, "semanticValid": False, "rendered": False}
        expected_nodes = {(label(name), kind) for name, kind in case["nodes"]}
        expected_edges = {relation(*edge) for edge in case["edges"]}
        nodes, edges = set(), set()
        try:
            graph = await adapter.parse_graph(case["text"], case["diagramType"])
            row["schemaValid"] = True
            graph.schemaVersion = "1.1"
            normalize_devices(graph)
            errors, _ = collect_graph_issues(graph)
            row["semanticValid"] = not errors
            names = {node.id: node.label for node in graph.nodes}
            nodes = {(label(node.label), node.kind) for node in graph.nodes}
            edges = {relation(names.get(edge.source, edge.source), names.get(edge.target, edge.target), edge.kind)
                     for edge in graph.edges}
            if not errors:
                result = renderer.render(graph.model_dump(exclude_none=True))
                row["rendered"] = result.quality["ok"]
                row["matchedShapes"] = result.quality["counts"]["matchedShapes"]
                row["renderedNodes"] = result.quality["counts"]["nodes"]
                row["qualityWarnings"] = result.quality["counts"]["warnings"]
            else:
                row["errors"] = [issue.code for issue in errors]
        except ApiException as exc:
            row["error"] = exc.code
        row["nodes"], row["edges"] = counts(nodes, expected_nodes), counts(edges, expected_edges)
        row["unrequestedPhysicalEdges"] = sum(1 for item in edges - expected_edges if item[2] == "physical")
        row["durationMs"] = round((time.perf_counter() - started) * 1000)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    reference = GraphDocument.model_validate_json((ROOT / "fixtures/network.graph.json").read_text(encoding="utf-8"))
    patch_cases = (
        ("M01", "只把节点 core_switch 的名称改为主交换机。", "update_node", "core_switch", {"label": "主交换机"}),
        ("M02", "只新增服务器4（id server_04），并用物理线连接核心交换机 core_switch。", "add_node", "server_04", {}),
        ("M03", "只将整图主题切换到 networks 并隐藏连线标签。", "update_theme", "sample_network",
         {"themeId": "networks", "edgeLabelPolicy": "hidden"}),
    )
    patch_results = []
    for id_, instruction, operation, target, changes in patch_cases:
        row = {"id": id_, "pass": False}
        started = time.perf_counter()
        try:
            patch = await adapter.propose_patch(instruction, reference, 1)
            preview_patch(reference, patch)
            ops = patch["operations"]
            matches = [op for op in ops if op["op"] == operation and op["id"] == target
                       and all((op.get("changes") or {}).get(k) == v for k, v in changes.items())]
            if id_ == "M02":
                row["pass"] = bool(matches) and len(ops) == 2 and any(
                    op["op"] == "add_edge" and {op["value"]["source"], op["value"]["target"]} == {"server_04", "core_switch"}
                    and op["value"]["kind"] == "physical" for op in ops
                )
            else:
                row["pass"] = bool(matches) and len(ops) == 1
        except ApiException as exc:
            row["error"] = exc.code
        row["durationMs"] = round((time.perf_counter() - started) * 1000)
        patch_results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    report = {"model": settings.llm_model, "reasoningEffort": settings.llm_reasoning_effort,
              "cases": rows, "total": len(rows), "schemaValid": sum(row["schemaValid"] for row in rows),
              "semanticValid": sum(row["semanticValid"] for row in rows),
              "rendered": sum(row["rendered"] for row in rows),
              "nodes": score([row["nodes"] for row in rows]),
              "edges": score([row["edges"] for row in rows]),
              "unrequestedPhysicalEdges": sum(row["unrequestedPhysicalEdges"] for row in rows),
              "matchedShapes": sum(row.get("matchedShapes", 0) for row in rows),
              "renderedNodes": sum(row.get("renderedNodes", 0) for row in rows),
              "patches": patch_results}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(Settings(), parser.parse_args().output))
