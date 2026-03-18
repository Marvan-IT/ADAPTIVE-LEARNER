"""
Graph Store — creates, validates, and persists the NetworkX dependency graph.
"""

import json
from pathlib import Path

import networkx as nx
from networkx.readwrite import json_graph

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from extraction.domain_models import ConceptBlock, DependencyEdge


def create_graph(
    concept_blocks: list[ConceptBlock],
    edges: list[DependencyEdge],
) -> nx.DiGraph:
    """
    Create a NetworkX directed graph from concept blocks and dependency edges.

    Nodes: concept_id with attributes (title, chapter, section, book_slug).
    Edges: prerequisite -> target (source = prerequisite, target = concept that depends on it).
    """
    G = nx.DiGraph()

    # Add nodes with attributes
    for block in concept_blocks:
        G.add_node(
            block.concept_id,
            title=block.concept_title,
            chapter=block.chapter,
            section=block.section,
            book_slug=block.book_slug,
            book=block.book,
            word_count=len(block.text.split()),
        )

    # Add edges (prerequisite -> concept)
    for edge in edges:
        for prereq_id in edge.prerequisites:
            if prereq_id in G.nodes and edge.concept_id in G.nodes:
                G.add_edge(prereq_id, edge.concept_id)

    return G


def validate_graph(graph: nx.DiGraph) -> list[str]:
    """
    Validate graph properties:
      - Must be a DAG (no cycles)
      - All nodes should have concept attributes
      - Check for orphan nodes (no edges at all)
    Returns list of issues found.
    """
    issues = []

    # Check for cycles
    if not nx.is_directed_acyclic_graph(graph):
        cycles = list(nx.simple_cycles(graph))
        for cycle in cycles[:5]:  # report up to 5 cycles
            issues.append(f"CYCLE_DETECTED: {' -> '.join(cycle)}")

    # Check for orphan nodes (no in-edges AND no out-edges)
    for node in graph.nodes:
        if graph.in_degree(node) == 0 and graph.out_degree(node) == 0:
            issues.append(f"ORPHAN_NODE: {node}")

    # Check node count
    if graph.number_of_nodes() == 0:
        issues.append("EMPTY_GRAPH: No nodes in graph")

    return issues


def save_graph_json(graph: nx.DiGraph, output_path: Path) -> None:
    """Save graph as node-link JSON format."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = json_graph.node_link_data(graph)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_graph_json(input_path: Path) -> nx.DiGraph:
    """Load graph from node-link JSON."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return json_graph.node_link_graph(data, directed=True)


def get_graph_stats(graph: nx.DiGraph) -> dict:
    """Return summary statistics about the graph."""
    return {
        "num_nodes": graph.number_of_nodes(),
        "num_edges": graph.number_of_edges(),
        "is_dag": nx.is_directed_acyclic_graph(graph),
        "num_root_nodes": sum(1 for n in graph.nodes if graph.in_degree(n) == 0),
        "num_leaf_nodes": sum(1 for n in graph.nodes if graph.out_degree(n) == 0),
        "max_depth": _compute_max_depth(graph) if nx.is_directed_acyclic_graph(graph) else -1,
    }


def get_topological_order(graph: nx.DiGraph) -> list[str]:
    """Return concepts in topological order (valid learning sequence)."""
    if not nx.is_directed_acyclic_graph(graph):
        return sorted(graph.nodes)
    return list(nx.topological_sort(graph))


def get_learning_path(
    graph: nx.DiGraph,
    target_concept: str,
    mastered: set[str] | None = None,
) -> list[str]:
    """
    Compute the optimal learning path to reach a target concept.
    Returns concepts in topological order, excluding already-mastered ones.
    """
    if target_concept not in graph:
        return []

    mastered = mastered or set()

    # Get all ancestors (transitive prerequisites) + the target itself
    ancestors = nx.ancestors(graph, target_concept)
    ancestors.add(target_concept)

    # Remove mastered concepts
    needed = ancestors - mastered

    # Build subgraph and return topological order
    subgraph = graph.subgraph(needed)
    if not nx.is_directed_acyclic_graph(subgraph):
        return sorted(needed)
    return list(nx.topological_sort(subgraph))


def get_concept_depth(graph: nx.DiGraph) -> dict[str, int]:
    """
    Compute depth of each concept (longest path from any root to this concept).
    Root concepts have depth 0.
    """
    if not nx.is_directed_acyclic_graph(graph):
        return {}

    depths = {}
    for node in nx.topological_sort(graph):
        predecessors = list(graph.predecessors(node))
        if not predecessors:
            depths[node] = 0
        else:
            depths[node] = max(depths.get(p, 0) for p in predecessors) + 1
    return depths


def _compute_max_depth(graph: nx.DiGraph) -> int:
    """Compute the longest path length in a DAG."""
    if graph.number_of_nodes() == 0:
        return 0
    try:
        return nx.dag_longest_path_length(graph)
    except Exception:
        return -1
