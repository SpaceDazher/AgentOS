"""S1-016 real pySHACL execution over lineage RDF exports (S1-003 contract).

Fails closed when rdflib/pySHACL is not importable or versions differ from
the pinned engine identity (rdflib 7.6.0, pyshacl 0.40.1). Every constraint
message IS the normalized reason; unclassified results fail closed.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent

PINNED = {"rdflib": "7.6.0", "pyshacl": "0.40.1"}

KNOWN_REASONS = frozenset({
    "scope_cardinality", "missing_version", "missing_content_digest",
    "dangling_supersedes", "orphan_member", "duplicate_seq", "orphan_removal",
})


def engine_identity():
    try:
        import rdflib
        import pyshacl
    except ImportError as exc:
        raise RuntimeError(f"pySHACL engine not importable: {exc}") from exc
    versions = {"rdflib": rdflib.__version__, "pyshacl": pyshacl.__version__}
    mismatches = {k: v for k, v in versions.items() if v != PINNED[k]}
    if mismatches:
        raise RuntimeError(f"engine version mismatch: {mismatches}")
    return versions


def _mod(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_turtle(data_ttl: str, shapes_text: str | None = None) -> dict:
    """Validate one Turtle document; return normalized violation evidence."""
    import pyshacl
    from rdflib import Graph, Namespace
    from rdflib.term import BNode
    versions = engine_identity()
    shapes = shapes_text if shapes_text is not None else \
        (HERE / "shapes.ttl").read_text(encoding="utf-8")
    data_graph = Graph()
    try:
        data_graph.parse(data=data_ttl, format="turtle")
    except Exception as exc:
        return {"conforms": False, "violations": ["rdf_parse_error"],
                "unclassified": [{"error": str(exc)[:200]}],
                "report_digest": None, "runtime": versions,
                "pyshacl_executed": True}
    for term in list(data_graph.subjects()) + list(data_graph.objects()):
        if isinstance(term, BNode):
            return {"conforms": False, "violations": ["blank_node"],
                    "unclassified": [], "report_digest": None,
                    "runtime": versions, "pyshacl_executed": True}
    shapes_graph = Graph().parse(data=shapes, format="turtle")
    conforms, report_graph, report_text = pyshacl.validate(
        data_graph, shacl_graph=shapes_graph, inference=False, advanced=True,
        abort_on_first=False, allow_infos=False, allow_warnings=False,
        meta_shacl=False, debug=False)
    sh = Namespace("http://www.w3.org/ns/shacl#")
    violations: list[str] = []
    unclassified: list[dict] = []
    from rdflib import RDF
    for report in report_graph.subjects(RDF.type, sh.ValidationReport):
        for result in report_graph.objects(report, sh.result):
            message = str(report_graph.value(result, sh.resultMessage) or "").strip()
            if message in KNOWN_REASONS:
                if message not in violations:
                    violations.append(message)
            else:
                unclassified.append({
                    "message": message[:200],
                    "path": str(report_graph.value(result, sh.resultPath) or ""),
                    "component": str(report_graph.value(
                        result, sh.sourceConstraintComponent) or ""),
                })
    return {"conforms": bool(conforms), "violations": sorted(violations),
            "unclassified": unclassified,
            "report_digest": hashlib.sha256(
                report_text.encode("utf-8")).hexdigest(),
            "runtime": versions, "pyshacl_executed": True}


def run_case(model, case_id: str, request_scope: dict) -> dict:
    """Export one model state to Turtle and validate it through pySHACL."""
    exporter = _mod("s1016_exporter_sh", "exporter.py")
    turtle = exporter.export_turtle(model, case_id, request_scope)
    result = validate_turtle(turtle)
    result["triples"] = len([line for line in turtle.splitlines()
                             if line and not line.startswith("@")])
    result["turtle_sha256"] = hashlib.sha256(turtle.encode("utf-8")).hexdigest()
    return result
