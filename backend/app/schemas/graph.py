"""Pydantic v2 models for GraphDocument v1.

The authoritative field contract is ``contracts/graph.schema.json``; these
models mirror it (additionalProperties=forbid, same enums, same limits) so the
future FastAPI layer and the TypeScript renderer stay in sync.
"""
from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
LayoutAlgorithm = Literal["layered", "manual", "star", "grouped"]
LayoutDirection = Literal["DOWN", "RIGHT", "UP", "LEFT"]
GraphId = Annotated[str, Field(pattern=ID_PATTERN)]
LayoutAxis = Literal["x", "y"]


class Geometry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    x: float
    y: float


class GraphNode(BaseModel):
    """Node in the semantic graph (schema ``$defs/node``)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

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

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1, max_length=500)
    parentId: Optional[str] = Field(default=None, pattern=ID_PATTERN)
    geometry: Optional[Geometry] = None
    manualLocked: bool = False
    style: StyleMap = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Edge (schema ``$defs/edge``); both endpoints must be existing nodes."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

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


class ConstraintNodes(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: List[GraphId] = Field(min_length=1, max_length=1000)

    @field_validator("nodes")
    @classmethod
    def distinct_nodes(cls, nodes: List[str]) -> List[str]:
        if len(nodes) != len(set(nodes)):
            raise ValueError("constraint target IDs must be unique")
        return nodes


class SameRank(ConstraintNodes):
    type: Literal["sameRank"]
    nodes: List[GraphId] = Field(min_length=2, max_length=1000)


class Order(ConstraintNodes):
    type: Literal["order"]
    axis: LayoutAxis
    nodes: List[GraphId] = Field(min_length=2, max_length=1000)


class Align(ConstraintNodes):
    type: Literal["align"]
    axis: LayoutAxis
    mode: Literal["start", "center", "end"]
    nodes: List[GraphId] = Field(min_length=2, max_length=1000)


class RelativePosition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["relativePosition"]
    source: GraphId
    target: GraphId
    position: Literal["above", "below", "left", "right"]


class Rank(ConstraintNodes):
    type: Literal["rank"]
    rank: int = Field(ge=0, le=999, strict=True)


class PreservePosition(ConstraintNodes):
    type: Literal["preservePosition"]


LayoutConstraint = Annotated[
    Union[SameRank, Order, Align, RelativePosition, Rank, PreservePosition],
    Field(discriminator="type"),
]


class LayoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: LayoutAlgorithm
    direction: LayoutDirection
    preserveManualPositions: bool
    constraints: Optional[List[LayoutConstraint]] = Field(default=None, max_length=100)
    centerNodeId: Optional[GraphId] = None


class Appearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    themeId: Optional[str] = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    edgeRouting: Optional[Literal["auto", "straight", "orthogonal"]] = None
    edgeLabelPolicy: Optional[Literal["hidden", "explicit_only", "all"]] = None
    edgeArrowPolicy: Optional[Literal["semantic", "hidden"]] = None
    showGroups: Optional[bool] = None


class GraphWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    relatedIds: Optional[List[str]] = None
    requiresConfirmation: bool


class GraphDocument(BaseModel):
    """Top-level semantic graph (schema ``GraphDocument v1``)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schemaVersion: Literal["1.0", "1.1"]
    diagramId: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    diagramType: DiagramType
    nodes: List[GraphNode] = Field(default_factory=list, max_length=1000)
    groups: List[GraphGroup] = Field(default_factory=list, max_length=200)
    edges: List[GraphEdge] = Field(default_factory=list, max_length=3000)
    layout: LayoutSpec
    appearance: Optional[Appearance] = None
    metadata: Dict[str, MetadataValue] = Field(default_factory=dict)
    warnings: List[GraphWarning] = Field(default_factory=list)
