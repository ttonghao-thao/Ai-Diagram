"""Reconcile explicit quantities and review network links against their source."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

from app.llm.topology_text import (
    ALL_MEMBERS, ALTERNATIVE, MAX_EDGES, MAX_LABEL_LENGTH, MAX_NODES, NEGATIVE, QUALIFIED_SWITCH,
    counted_device_type, device_quantity, name_key, safe_id,
)
from app.schemas.graph import GraphDocument, GraphEdge, GraphNode, GraphWarning

CLAUSES = re.compile(r"[。！？；，;!?,\n\r]|\.(?:\s|$)")
LINK = re.compile(r"接入|相连|连接到|连接|连到|接到|直连|连至|接至|上联到|下联到|上联|下联|互联|→|->|⇄|"
                  r"\b(?:connect(?:s|ed)?|link(?:s|ed)?|attach(?:es|ed)?)\b|连|接", re.I)
COORDINATOR = re.compile(r"\s*(?:和|与|、|以及|及|跟|&|\band\b)\s*", re.I)
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


def _names(doc: GraphDocument, text: str) -> dict[str, str]:
    full: dict[str, set[str]] = defaultdict(set)
    short: dict[str, set[str]] = defaultdict(set)
    for node in doc.nodes:
        full[name_key(node.label)].add(node.id)
        match = QUALIFIED_SWITCH.fullmatch(node.label.strip()) if node.kind == "switch" else None
        if match:
            short[name_key(match[1])].add(node.id)
    names = {label: next(iter(ids)) for label, ids in (short | full).items() if len(ids) == 1}
    source_aliases: dict[str, set[str]] = defaultdict(set)
    for match in QUALIFIED_SWITCH.finditer(text):
        source_aliases[name_key(match[1])].add(name_key(match[0]))
    for label, aliases in source_aliases.items():
        if len(aliases) == 1 and label in names:
            qualified = next(iter(aliases))
            if qualified not in full:
                names.setdefault(qualified, names[label])
    return names


@dataclass(frozen=True)
class CountedDevices:
    count: int
    device: str
    peer_id: str | None = None
    count_is_source: bool = True


def _declared_counts(text: str, peer_names: dict[str, str]):
    for clause in CLAUSES.split(unicodedata.normalize("NFKC", text)):
        if NEGATIVE.search(clause) or ALTERNATIVE.search(clause):
            continue
        standalone = device_quantity(clause)
        if standalone and standalone[0] != 1 and counted_device_type(standalone[1]):
            yield CountedDevices(*standalone)
            continue
        matches = {}
        for verb in LINK.finditer(clause):
            left = ALL_MEMBERS.sub("", clause[:verb.start()]).strip()
            right = clause[verb.end():].strip()
            for counted, peer, count_is_source in ((left, right, True), (right, left, False)):
                peer_name = name_key(peer)
                peer_id = peer_names.get(peer_name)
                if not peer_id or device_quantity(peer):
                    continue
                quantities = [device_quantity(part) for part in COORDINATOR.split(counted)]
                if None not in quantities:
                    intents = tuple(CountedDevices(*quantity, peer_id, count_is_source)
                                    for quantity in quantities if quantity and quantity[0] != 1)
                    if intents:
                        matches[intents] = max(matches.get(intents, 0), len(peer_name))
        if matches:
            longest = max(matches.values())
            candidates = [intent for intent, length in matches.items() if length == longest]
            if len(candidates) == 1:
                yield from candidates[0]


def _slot(label: str, base: str) -> int | None:
    quantity = device_quantity(label)
    if quantity:
        return 1 if name_key(quantity[1]) == base else None
    label = name_key(label)
    if label == base:
        return 1
    if label.startswith(base):
        suffix = label[len(base):].lstrip("-_#")
        if suffix.isdecimal() and len(suffix) <= 4:
            return int(suffix)
    return None


def _complete_instances(doc: GraphDocument, intent: CountedDevices, used: set[str]) -> set[frozenset[str]] | None:
    """Create only the instances and shared links declared by this clause."""
    suffix_width = 1 + max(2, len(str(intent.count))) if intent.count > 1 else 0
    if not 1 < intent.count <= MAX_NODES or len(intent.device) + suffix_width > MAX_LABEL_LENGTH:
        return None
    key = name_key(intent.device)
    classification = counted_device_type(intent.device)
    if not classification:
        return None
    kind, device_type = classification
    numbered = {}
    aggregate_ids = set()
    for node in doc.nodes:
        if node.id == intent.peer_id:
            continue
        slot = _slot(node.label, key)
        if slot is None:
            if name_key(node.label).startswith(key) or (device_type and node.properties.get("deviceType") == device_type):
                return None
            continue
        if slot in numbered or not 1 <= slot <= intent.count:
            return None
        numbered[slot] = node
        if device_quantity(node.label):
            aggregate_ids.add(node.id)
    if aggregate_ids and len(numbered) > 1:
        return None

    linked = set()
    for edge in doc.edges:
        endpoints = {edge.source, edge.target}
        if endpoints & aggregate_ids and (intent.peer_id not in endpoints or edge.sourcePort or edge.targetPort):
            return None
        if intent.peer_id in endpoints:
            linked.update(endpoints - {intent.peer_id})
    needed = intent.count - sum(node.id in linked for node in numbered.values()) if intent.peer_id else 0
    if len(doc.nodes) + intent.count - len(numbered) > MAX_NODES or len(doc.edges) + needed > MAX_EDGES:
        return None

    confirmed: set[frozenset[str]] = set()
    for index in range(1, intent.count + 1):
        label = f"{intent.device} {index:02d}"
        node = numbered.get(index)
        if node is None:
            node = GraphNode(id=safe_id(f"{device_type or 'device'}_{index:02d}", used),
                             label=label, kind=kind, origin="ai")
            if aggregate_ids:
                node.groupId = numbered[1].groupId
            doc.nodes.append(node)
        elif node.id in aggregate_ids or name_key(node.label) == key:
            node.label = label
        node.kind = kind
        if device_type:
            node.properties["deviceType"] = device_type
        else:
            node.properties.pop("deviceType", None)
            node.properties["deviceTypeRaw"] = intent.device
        if not intent.peer_id:
            continue
        if node.id not in linked:
            source, target = (node.id, intent.peer_id) if intent.count_is_source else (intent.peer_id, node.id)
            doc.edges.append(GraphEdge(id=safe_id(f"{source[:26]}_to_{target[:26]}", used),
                                       source=source, target=target, direction="undirected", kind="physical"))
        confirmed.add(frozenset((node.id, intent.peer_id)))
    return confirmed


def _complete_quantities(text: str, doc: GraphDocument) -> set[frozenset[str]]:
    if doc.diagramType != "network_topology":
        return set()
    by_device = defaultdict(set)
    network_ids = {node.id for node in doc.nodes if node.kind != "service"}
    peer_names = {name: id_ for name, id_ in _names(doc, text).items() if id_ in network_ids}
    for intent in _declared_counts(text, peer_names):
        by_device[name_key(intent.device)].add(intent)
    used = {item.id for item in (*doc.nodes, *doc.edges, *doc.groups)}
    confirmed = set()
    unresolved = set()
    for base, intents in by_device.items():
        intent = next(iter(intents))
        links = _complete_instances(doc, intent, used) if len(intents) == 1 else None
        if links is None:
            unresolved.add(base)
        else:
            confirmed.update(links)
    for node in doc.nodes:
        quantity = device_quantity(node.label)
        if quantity and quantity[0] != 1 and _occurrences(_normal(text), _normal(node.label)):
            unresolved.add(name_key(quantity[1]))
    if unresolved:
        doc.warnings.append(GraphWarning(
            code="AMBIGUOUS_DEVICE_COUNT",
            message="部分设备数量或对应的连线端点需确认，请核对图模型。",
            requiresConfirmation=True,
        ))
    return confirmed


def _adjacent_mentions(clause: str, mentions: list[tuple[int, int, str]]) -> list[str]:
    if not mentions:
        return []
    connected = [mentions[0][2]]
    for previous, current in zip(mentions, mentions[1:]):
        gap = clause[min(previous[1], current[1]):max(previous[0], current[0])]
        if not COORDINATOR.fullmatch(gap):
            break
        connected.append(current[2])
    return connected


def review_draft(text: str, doc: GraphDocument) -> None:
    """Confirm source-backed links and preserve unresolved topology for review."""
    source = _normal(text)
    confirmed = _complete_quantities(text, doc)
    names = _names(doc, text)
    for clause in CLAUSES.split(source):
        if NEGATIVE.search(clause) or ALTERNATIVE.search(clause):
            continue
        links = list(LINK.finditer(clause))
        if not links:
            continue
        mentions = sorted((match.start(), match.end(), id_) for label, id_ in names.items()
                          for match in _occurrences(clause, label))
        # Prefer the most specific name where a short device category occurs
        # inside an explicitly named variant such as "核心交换机".
        mentions = [match for match in mentions if not any(other[0] <= match[0] and other[1] >= match[1]
                    and other[:2] != match[:2] for other in mentions)]
        links = [link for link in links if not any(start <= link.start() and end >= link.end()
                                                   for start, end, _ in mentions)]
        for i, link in enumerate(links):
            previous = links[i - 1].end() if i else 0
            boundary = links[i + 1].start() if i + 1 < len(links) else len(clause)
            left = _adjacent_mentions(clause, [span for span in reversed(mentions) if previous <= span[0] and span[1] <= link.start()])
            right = _adjacent_mentions(clause, [span for span in mentions if link.end() <= span[0] and span[1] <= boundary])
            if left and right and min(len(left), len(right)) == 1:
                confirmed.update(frozenset((a, b)) for a in left for b in right)
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
