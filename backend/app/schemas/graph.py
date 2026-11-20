"""Pydantic v2 models for GraphDocument v1.

The authoritative field contract is ``contracts/graph.schema.json``; these
models mirror it (additionalProperties=forbid, same enums, same limits) so the
future FastAPI layer and the TypeScript renderer stay in sync.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"

MetadataValue = Union[str, bool, int, float, None]
StyleValue = Union[str, bool, int, float]
StyleMap = Dict[str, StyleValue]

NodeKind = Literal[
    "switch", "router", "firewall", "server", "vm",
    "cloud", "service", "database", "client", "generic",
]
DiagramType = Literal["network_topology", "business_architecture"]
EdgeKind = Literal["physical", "logical", "dataflow", "control", "dependency"]
EdgeDirection = Literal["undirected", "forward", "bidirectional"]
NodeOrigin = Literal["explicit", "ai", "imported"]
LayoutAlgorithm = Literal["layered", "manual"]
LayoutDirection = Literal["DOWN", "RIGHT", "UP", "LEFT"]


class Geometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class GraphNode(BaseModel):
    """Node in the semantic graph (schema ``$defs/node``)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1, max_length=500)
    kind: NodeKind
    groupId: Optional[str] = Field(default=None, pattern=ID_PATTERN)
    properties: Dict[str, MetadataValue] = Field(default_factory=dict)
    geometry: Optional[Geometry] = None
    manualLocked: bool = False
    style: StyleMap = Field(default_factory=dict)
    origin: Optional[NodeOrigin] = None


class GraphGroup(BaseModel):
    """Group container (schema ``$defs/group``); containment is not an Edge."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1, max_length=500)
    parentId: Optional[str] = Field(default=None, pattern=ID_PATTERN)
    geometry: Optional[Geometry] = None
    manualLocked: bool = False
    style: StyleMap = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Edge (schema ``$defs/edge``); both endpoints must be existing nodes."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=ID_PATTERN)
    source: str = Field(pattern=ID_PATTERN)
    target: str = Field(pattern=ID_PATTERN)
    kind: EdgeKind
    direction: EdgeDirection
    label: Optional[str] = Field(default=None, max_length=500)
    sourcePort: Optional[str] = Field(default=None, max_length=100)
    targetPort: Optional[str] = Field(default=None, max_length=100)
    waypoints: Optional[List[Point]] = None
    style: StyleMap = Field(default_factory=dict)


class LayoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: LayoutAlgorithm
    direction: LayoutDirection
    preserveManualPositions: bool


class GraphWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    relatedIds: Optional[List[str]] = None
    requiresConfirmation: bool


class GraphDocument(BaseModel):
    """Top-level semantic graph (schema ``GraphDocument v1``)."""

    model_config = ConfigDict(extra="forbid")

    schemaVersion: Literal["1.0"]
    diagramId: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    diagramType: DiagramType
    nodes: List[GraphNode] = Field(default_factory=list, max_length=1000)
    groups: List[GraphGroup] = Field(default_factory=list, max_length=200)
    edges: List[GraphEdge] = Field(default_factory=list, max_length=3000)
    layout: LayoutSpec
    metadata: Dict[str, MetadataValue] = Field(default_factory=dict)
    warnings: List[GraphWarning] = Field(default_factory=list)
