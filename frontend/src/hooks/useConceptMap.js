import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { getGraphFull, getNextConcepts } from "../api/concepts";
import { useStudent } from "../context/StudentContext";

export function useConceptMap(bookSlug = "prealgebra") {
  const { masteredConcepts } = useStudent();
  const { i18n } = useTranslation();
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [nodeStatuses, setNodeStatuses] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let graphRes, nextRes;
      try {
        [graphRes, nextRes] = await Promise.all([
          getGraphFull(bookSlug),
          getNextConcepts(masteredConcepts, bookSlug),
        ]);
      } catch (fetchErr) {
        if (fetchErr.response?.status === 404) {
          // Book not yet processed — show empty graph instead of error
          setNodes([]);
          setEdges([]);
          setNodeStatuses({});
          setError("not_ready");
          return;
        }
        throw fetchErr;
      }

      const graphNodes = graphRes.data.nodes;
      setEdges(graphRes.data.edges);
      setNodes(graphNodes);

      // Build status map
      const statuses = {};
      const readySet = new Set(
        (nextRes.data.ready_to_learn || []).map((c) => c.concept_id)
      );

      for (const node of graphNodes) {
        if (masteredConcepts.includes(node.concept_id)) {
          statuses[node.concept_id] = "mastered";
        } else if (readySet.has(node.concept_id)) {
          statuses[node.concept_id] = "ready";
        } else {
          statuses[node.concept_id] = "locked";
        }
      }

      setNodeStatuses(statuses);
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
    } finally {
      setLoading(false);
    }
  }, [masteredConcepts, i18n.language, bookSlug]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return { nodes, edges, nodeStatuses, loading, error, refetch: fetchData };
}
