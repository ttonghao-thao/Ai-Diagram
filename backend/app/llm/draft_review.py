"""Flag model-generated physical links that lack a recognizable text reference."""
from __future__ import annotations

import re
import unicodedata

from app.schemas.graph import GraphDocument, GraphWarning

CLAUSES = re.compile(r"[。！？；，;\n]|\.(?:\s|$)")
LINK = re.compile(r"接入|相连|连接|连到|接到|直连|连至|接至|上联|下联|互联|→|->|⇄|"
                  r"\b(?:connect(?:s|ed)?|link(?:s|ed)?|attach(?:es|ed)?)\b|连|接", re.I)
NEGATIVE = re.compile(r"未指定|没有连接|无连接|不连接|\bno\s+(?:physical\s+)?(?:links?|connections?)\b", re.I)
SPACING = re.compile(r"\s+")
DATA_KEYS = {"ip", "ipaddress", "ipv4", "ipv6", "interface", "port", "vendor", "manufacturer", "model", "subnet"}


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _occurrences(text: str, label: str):
    compact = SPACING.sub("", label)
    if not compact:
        return []
    pattern = r"\s*".join(re.escape(char) for char in compact)
    if compact[-1].isdigit():
        pattern += r"(?!\d)"
    if compact.isascii() and compact[0].isalnum():
        pattern = r"(?<![a-z0-9])" + pattern
    if compact.isascii() and compact[-1].isalpha():
        pattern += r"(?![a-z0-9])"
    return list(re.finditer(pattern, text))


def review_draft(text: str, doc: GraphDocument) -> None:
    """Leave proposed topology intact and require review of ungrounded links."""
    source = _normal(text)
    labels = {node.id: _normal(node.label) for node in doc.nodes}
    confirmed = set()
    for clause in CLAUSES.split(source):
        if NEGATIVE.search(clause):
            continue
        links = list(LINK.finditer(clause))
        if not links:
            continue
        mentions = sorted((match.start(), match.end(), id_) for id_, label in labels.items()
                          for match in _occurrences(clause, label))
        # Prefer the most specific name where a short device category occurs
        # inside an explicitly named variant such as "核心交换机".
        mentions = [match for match in mentions if not any(other[0] <= match[0] and other[1] >= match[1]
                    and other[:2] != match[:2] for other in mentions)]
        links = [link for link in links if not any(start <= link.start() and end >= link.end()
                                                   for start, end, _ in mentions)]
        for i, link in enumerate(links):
            left = [id_ for _, end, id_ in mentions if end <= link.start()]
            boundary = links[i + 1].start() if i + 1 < len(links) else len(clause)
            right = [id_ for start, _, id_ in mentions if link.end() <= start < boundary]
            if left and right:
                confirmed.update(frozenset((left[-1], target)) for target in right)
            elif len(set(left or right)) == 2 and len(links) == 1:
                confirmed.add(frozenset(left or right))
    warned = {tuple(warning.relatedIds or ()) for warning in doc.warnings if warning.code == "AMBIGUOUS_RELATION"}
    for edge in doc.edges:
        if edge.kind != "physical" or frozenset((edge.source, edge.target)) in confirmed:
            continue
        if (edge.id,) not in warned:
            doc.warnings.append(GraphWarning(
                code="AMBIGUOUS_RELATION", message="原文中的物理连线端点未能核实，请核对图模型。",
                relatedIds=[edge.id], requiresConfirmation=True,
            ))
    for node in doc.nodes:
        for key, value in list(node.properties.items()):
            if key.casefold().replace("_", "") in DATA_KEYS and value is not None and _normal(str(value)) not in source:
                del node.properties[key]
                doc.warnings.append(GraphWarning(
                    code="UNVERIFIED_DEVICE_PROPERTY", message="已移除无法从绘图需求中找到依据的设备属性。",
                    relatedIds=[node.id], requiresConfirmation=False,
                ))
    for edge in doc.edges:
        for name in ("sourcePort", "targetPort"):
            value = getattr(edge, name)
            if value and _normal(value) not in source:
                setattr(edge, name, None)
