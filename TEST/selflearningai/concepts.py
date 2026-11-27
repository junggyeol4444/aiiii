from collections import deque
from dataclasses import dataclass


CLAIM_SUFFIXES = {"의 한 종류": "종류", "의 일부": "부분"}


def parse_relation_claim(value):
    if not isinstance(value, str):
        return None
    for suffix, kind in CLAIM_SUFFIXES.items():
        if value.endswith(suffix):
            target = value[:-len(suffix)]
            if target and target == target.strip():
                return kind, target
    return None


@dataclass(frozen=True)
class ConceptEdge:
    subject: str
    kind: str
    target: str
    supporting: tuple[tuple[str, int], ...]
    refuting: tuple[tuple[str, int], ...]


class ConceptGraph:
    def __init__(self, records):
        evidence_by_relation = {}
        for subject, value, source, negated, evidence_id in records:
            relation = parse_relation_claim(value)
            if not subject or relation is None:
                continue
            kind, target = relation
            if subject == target:
                continue
            supporting, refuting = evidence_by_relation.setdefault((subject, kind, target), ([], []))
            evidence = (source, evidence_id)
            if negated:
                refuting.append(evidence)
            else:
                supporting.append(evidence)

        self._edges = {}
        by_subject = {}
        for key, (supporting, refuting) in sorted(evidence_by_relation.items()):
            edge = ConceptEdge(*key, tuple(sorted(supporting)), tuple(sorted(refuting)))
            self._edges[key] = edge
            by_subject.setdefault(edge.subject, []).append(edge)
        self._by_subject = {subject: tuple(edges) for subject, edges in by_subject.items()}

    def direct_from(self, subject):
        return self._by_subject.get(subject, ())

    def direct(self, subject, kind, target):
        return self._edges.get((subject, kind, target))

    def find_path(self, subject, kind, target):
        if subject == target:
            return ()
        direct = self.direct(subject, kind, target)
        if direct is not None:
            if direct.refuting:
                return ()
            if direct.supporting:
                return (direct,)
        if kind != "종류":
            return ()

        # 이전 간선만 보관하고 목적지에 도달한 뒤 경로를 복원한다.
        previous = {subject: None}
        queue = deque([subject])
        while queue:
            current = queue.popleft()
            for edge in self.direct_from(current):
                if edge.kind != kind or not edge.supporting or edge.refuting or edge.target in previous:
                    continue
                direct_to_step = self.direct(subject, kind, edge.target)
                if direct_to_step is not None and direct_to_step.refuting:
                    continue
                previous[edge.target] = edge
                if edge.target == target:
                    path = [edge]
                    while path[-1].subject != subject:
                        path.append(previous[path[-1].subject])
                    return tuple(reversed(path))
                queue.append(edge.target)
        return ()
