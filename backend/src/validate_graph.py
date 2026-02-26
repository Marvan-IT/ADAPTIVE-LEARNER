"""
validate_graph.py — Validates the dependency graph output.

Checks:
  1. Loads the JSON graph
  2. Checks for missing prerequisite references
  3. Checks for cycles
  4. Prints topological order length and first 30 nodes
  5. Verifies parallel branches exist (not a linear chain)
  6. Shows graph statistics
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import networkx as nx
except ImportError:
    print("ERROR: networkx is required. Run: pip install networkx")
    sys.exit(1)

from graph.graph_store import load_graph_json


def load_dependency_edges(path: Path) -> list[dict]:
    """Load dependency_edges.json."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_from_edges(edges_path: Path):
    """Validate using dependency_edges.json."""
    print(f"\n{'='*70}")
    print(f"  DEPENDENCY GRAPH VALIDATION")
    print(f"  Source: {edges_path}")
    print(f"{'='*70}\n")

    edges = load_dependency_edges(edges_path)

    # Collect all concept IDs and all referenced prerequisites
    all_ids = {e["concept_id"] for e in edges}
    all_prereqs = set()
    for e in edges:
        for p in e.get("prerequisites", []):
            all_prereqs.add(p)

    # ── Check 1: Missing prerequisite references ──────────────────────
    missing = all_prereqs - all_ids
    print(f"[Check 1] Missing prerequisite references:")
    if missing:
        print(f"  FAIL — {len(missing)} prerequisites reference non-existent concepts:")
        for m in sorted(missing):
            print(f"    - {m}")
    else:
        print(f"  PASS — All {len(all_prereqs)} prerequisite references are valid")

    # ── Build NetworkX graph ──────────────────────────────────────────
    G = nx.DiGraph()
    for e in edges:
        G.add_node(e["concept_id"])
    for e in edges:
        for p in e.get("prerequisites", []):
            if p in all_ids:
                G.add_edge(p, e["concept_id"])

    # ── Check 2: Cycles ───────────────────────────────────────────────
    print(f"\n[Check 2] Cycle detection:")
    is_dag = nx.is_directed_acyclic_graph(G)
    if is_dag:
        print(f"  PASS — Graph is a valid DAG (no cycles)")
    else:
        cycles = list(nx.simple_cycles(G))
        print(f"  FAIL — Found {len(cycles)} cycle(s):")
        for i, cycle in enumerate(cycles[:10]):
            print(f"    Cycle {i+1}: {' -> '.join(cycle)} -> {cycle[0]}")

    # ── Check 3: Topological order ────────────────────────────────────
    print(f"\n[Check 3] Topological order:")
    if is_dag:
        topo_order = list(nx.topological_sort(G))
        print(f"  Length: {len(topo_order)} nodes")
        print(f"  First 30 nodes in topological order:")
        for i, node in enumerate(topo_order[:30]):
            prereqs = [e["prerequisites"] for e in edges if e["concept_id"] == node][0]
            prereq_str = f" <- [{', '.join(p.split('.')[-1] for p in prereqs)}]" if prereqs else " (ROOT)"
            print(f"    {i+1:3d}. {node}{prereq_str}")
        if len(topo_order) > 30:
            print(f"    ... and {len(topo_order) - 30} more")
    else:
        print(f"  SKIP — Cannot compute topological order (graph has cycles)")

    # ── Check 4: Parallel branches (not a linear chain) ───────────────
    print(f"\n[Check 4] Parallel branch detection:")
    # In a linear chain, every node (except root) has exactly 1 in-edge
    # and every node (except leaf) has exactly 1 out-edge
    in_degrees = [G.in_degree(n) for n in G.nodes]
    out_degrees = [G.out_degree(n) for n in G.nodes]

    multi_prereq_nodes = sum(1 for d in in_degrees if d > 1)
    multi_child_nodes = sum(1 for d in out_degrees if d > 1)
    root_nodes = sum(1 for d in in_degrees if d == 0)
    leaf_nodes = sum(1 for d in out_degrees if d == 0)

    is_linear = (multi_child_nodes == 0 and multi_prereq_nodes == 0 and root_nodes == 1)

    if is_linear:
        print(f"  FAIL — Graph appears to be a linear chain")
    else:
        print(f"  PASS — Graph has parallel branches")
        print(f"    Nodes with multiple prerequisites (convergence points): {multi_prereq_nodes}")
        print(f"    Nodes with multiple children (branch points): {multi_child_nodes}")

    # ── Check 5: Graph statistics ─────────────────────────────────────
    print(f"\n[Check 5] Graph statistics:")
    print(f"  Nodes:         {G.number_of_nodes()}")
    print(f"  Edges:         {G.number_of_edges()}")
    print(f"  Root nodes:    {root_nodes} (no prerequisites)")
    print(f"  Leaf nodes:    {leaf_nodes} (nothing depends on them)")
    print(f"  Is DAG:        {is_dag}")

    if is_dag:
        longest_path = nx.dag_longest_path(G)
        print(f"  Longest path:  {len(longest_path)} nodes")
        print(f"    Path: {' -> '.join(n.split('.')[-1] for n in longest_path)}")

    # Average prerequisites per concept
    avg_prereqs = sum(len(e["prerequisites"]) for e in edges) / len(edges) if edges else 0
    print(f"  Avg prereqs:   {avg_prereqs:.1f} per concept")

    # ── Check 6: Orphan nodes ─────────────────────────────────────────
    print(f"\n[Check 6] Orphan detection (no edges at all):")
    orphans = [n for n in G.nodes if G.in_degree(n) == 0 and G.out_degree(n) == 0]
    if orphans:
        print(f"  WARNING — {len(orphans)} orphan node(s):")
        for o in orphans:
            print(f"    - {o}")
    else:
        print(f"  PASS — No orphan nodes")

    # ── Check 7: Chapter-level dependency summary ─────────────────────
    print(f"\n[Check 7] Chapter dependency map:")
    chapter_deps = defaultdict(set)
    for e in edges:
        target_ch = e["concept_id"].split(".")[1]  # e.g., "C1"
        for p in e.get("prerequisites", []):
            prereq_ch = p.split(".")[1]
            if prereq_ch != target_ch:
                chapter_deps[target_ch].add(prereq_ch)

    for ch in sorted(chapter_deps.keys()):
        deps = sorted(chapter_deps[ch])
        print(f"  {ch} depends on: {', '.join(deps)}")

    chapters_with_no_external = []
    all_chapters = sorted(set(e["concept_id"].split(".")[1] for e in edges))
    for ch in all_chapters:
        if ch not in chapter_deps:
            chapters_with_no_external.append(ch)
    if chapters_with_no_external:
        print(f"  Self-contained chapters: {', '.join(chapters_with_no_external)}")

    # ── Final verdict ─────────────────────────────────────────────────
    print(f"\n{'='*70}")
    issues = []
    if missing:
        issues.append(f"{len(missing)} missing references")
    if not is_dag:
        issues.append("has cycles")
    if is_linear:
        issues.append("linear chain (no branching)")
    if orphans:
        issues.append(f"{len(orphans)} orphan nodes")

    if issues:
        print(f"  VERDICT: ISSUES FOUND — {'; '.join(issues)}")
    else:
        print(f"  VERDICT: GRAPH IS VALID")
        print(f"    - DAG with {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        print(f"    - Has parallel branches ({multi_child_nodes} branch points)")
        print(f"    - All prerequisite references valid")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    # Default path
    default_path = Path(__file__).parent.parent / "output" / "prealgebra" / "dependency_edges.json"

    if len(sys.argv) > 1:
        edges_path = Path(sys.argv[1])
    else:
        edges_path = default_path

    if not edges_path.exists():
        print(f"ERROR: File not found: {edges_path}")
        print(f"Usage: python validate_graph.py [path/to/dependency_edges.json]")
        sys.exit(1)

    validate_from_edges(edges_path)
