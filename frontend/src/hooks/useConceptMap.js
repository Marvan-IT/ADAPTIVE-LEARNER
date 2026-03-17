import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { getGraphFull, getNextConcepts, translateConceptTitles } from "../api/concepts";
import { useStudent } from "../context/StudentContext";
import { formatConceptTitle } from "../utils/formatConceptTitle";

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
      const [graphRes, nextRes] = await Promise.all([
        getGraphFull(bookSlug),
        getNextConcepts(masteredConcepts, bookSlug),
      ]);

      let graphNodes = graphRes.data.nodes;
      setEdges(graphRes.data.edges);

      // Translate concept titles if language is not English
      if (i18n.language && i18n.language !== "en") {
        try {
          const titlesMap = {};
          graphNodes.forEach((n) => {
            titlesMap[n.concept_id] = n.title || formatConceptTitle(n.concept_id);
          });
          const transRes = await translateConceptTitles(titlesMap, i18n.language);
          const translations = transRes.data.translations || {};
          graphNodes = graphNodes.map((n) => ({
            ...n,
            title: translations[n.concept_id] || n.title,
          }));
        } catch {
          // Silently fall back to English titles
        }
      }

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
