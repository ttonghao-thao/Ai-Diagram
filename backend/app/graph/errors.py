"""Error codes for graph validation (docs/04 section 3).

GRAPH_PHYSICAL_EDGE_DIRECTION is a Phase 0 addition documented in
IMPLEMENTATION_REPORT.md: physical links carry no data direction, so a
directional physical edge yields a warning rather than an error.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


class GraphErrorCode:
    SCHEMA_INVALID = "SCHEMA_INVALID"
    GRAPH_DUPLICATE_ID = "GRAPH_DUPLICATE_ID"
    GRAPH_INVALID_REFERENCE = "GRAPH_INVALID_REFERENCE"
    GRAPH_GROUP_CYCLE = "GRAPH_GROUP_CYCLE"
    GRAPH_PHYSICAL_EDGE_DIRECTION = "GRAPH_PHYSICAL_EDGE_DIRECTION"
    AMBIGUOUS_RELATION = "AMBIGUOUS_RELATION"
    DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED = "DESTRUCTIVE_CHANGE_CONFIRMATION_REQUIRED"
    LAYOUT_CONFLICT = "LAYOUT_CONFLICT"
    DRAWIO_PARSE_FAILED = "DRAWIO_PARSE_FAILED"
    DRAWIO_UNSUPPORTED_CONTENT = "DRAWIO_UNSUPPORTED_CONTENT"
    VERSION_CONFLICT = "VERSION_CONFLICT"


@dataclass
class ValidationIssue:
    """One finding of the validator; severity error blocks rendering."""

    code: str
    message: str
    relatedIds: List[str] = field(default_factory=list)
    severity: str = "error"  # "error" | "warning"

    def __str__(self) -> str:
        ids = f" (ids: {', '.join(self.relatedIds)})" if self.relatedIds else ""
        return f"[{self.code}] {self.message}{ids}"


class GraphValidationError(Exception):
    """Raised when a graph has at least one error-severity issue."""

    def __init__(self, issues: List[ValidationIssue]) -> None:
        self.issues = issues
        super().__init__("Graph validation failed:\n" + "\n".join(str(i) for i in issues))

    @property
    def codes(self) -> List[str]:
        return [i.code for i in self.issues]


def issue(code: str, message: str, related_ids: Optional[List[str]] = None, severity: str = "error") -> ValidationIssue:
    return ValidationIssue(code=code, message=message, relatedIds=related_ids or [], severity=severity)
