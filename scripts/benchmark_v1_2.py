"""Measure deterministic drawing and a one-device incremental insertion."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "renderer/dist/src/cli.js"


def graph_fixture(size: int) -> dict:
    nodes = [{"id": f"n{i}", "label": f"设备 {i}", "kind": ("switch" if i < size / 4 else "server")}
             for i in range(size)]
    edges = [{"id": f"l{i}", "source": f"n{(i - 1) // 4}", "target": f"n{i}",
              "kind": "physical", "direction": "undirected"} for i in range(1, size)]
    return {"schemaVersion": "1.1", "diagramId": "benchmark", "name": f"性能样本 {size}",
            "diagramType": "network_topology", "nodes": nodes, "groups": [], "edges": edges,
            "layout": {"algorithm": "layered", "direction": "DOWN", "preserveManualPositions": True}}


def invoke(command, source, output, *extra):
    start = time.perf_counter()
    subprocess.run(["node", str(CLI), command, "--input", str(source), "--output", str(output), *extra],
                   check=True, capture_output=True, timeout=60)
    return round((time.perf_counter() - start) * 1000, 1)


def main():
    with tempfile.TemporaryDirectory(prefix="ai-diagram-performance-") as folder:
        root = Path(folder)
        source, context, quality = (root / name for name in ("graph.json", "context.json", "quality.json"))
        output, resolved = (root / name for name in ("diagram.drawio", "resolved.json"))
        for count in (10, 50, 200, 500, 1000):
            graph = graph_fixture(count)
            source.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            started = time.perf_counter()
            complete = invoke("generate", source, output, "--report", str(quality))
            report = json.loads(quality.read_text())
            result = {"nodes": count, "edges": count - 1, "totalMs": complete,
                      **{key: round(value, 1) for key, value in report["metrics"].items()},
                      "xmlBytes": output.stat().st_size, "qualityWarnings": report["counts"]["warnings"]}
            invoke("resolve", source, resolved)
            prior = json.loads(resolved.read_text())
            # At the schema limit remove the last leaf before inserting one.
            if count == 1000:
                graph["nodes"].pop()
                graph["edges"].pop()
            for node in graph["nodes"]:
                node["geometry"] = prior["nodes"][node["id"]]["geometry"]
            graph["nodes"].append({"id": "new_leaf", "label": "新增服务器", "kind": "server"})
            graph["edges"].append({"id": "added", "source": "n0", "target": "new_leaf",
                                   "kind": "physical", "direction": "undirected"})
            source.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
            context.write_text('{"scope":"local"}', encoding="utf-8")
            result["localInsertionMs"] = invoke("resolve", source, resolved, "--context", str(context))
            result["wallMs"] = round((time.perf_counter() - started) * 1000, 1)
            print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
