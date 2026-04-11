import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getBookStatus } from "../api/admin";

const STAGES = [
  { num: 1, label: "Font calibration", estimate: "~1 min" },
  { num: 2, label: "Mathpix PDF extraction", estimate: "~20–45 min" },
  { num: 3, label: "Build chunks & embeddings", estimate: "~2–5 min" },
  { num: 4, label: "Build dependency graph", estimate: "~1 min" },
  { num: 5, label: "Ready for review", estimate: null },
];

function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function AdminTrackPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const pollRef = useRef(null);
  const timerRef = useRef(null);
  const stageStartRef = useRef(null);
  const lastStageRef = useRef(null);

  const load = () => {
    getBookStatus(slug)
      .then((r) => {
        const data = r.data;
        setStatus(data);

        // Reset elapsed timer when stage advances
        if (data.stage_number !== lastStageRef.current) {
          lastStageRef.current = data.stage_number;
          stageStartRef.current = Date.now();
          setElapsed(0);
        }

        if (data.status === "READY_FOR_REVIEW") {
          clearInterval(pollRef.current);
          clearInterval(timerRef.current);
          setTimeout(() => navigate(`/admin/books/${slug}/review`), 1500);
        }
        if (data.status === "FAILED") {
          clearInterval(pollRef.current);
          clearInterval(timerRef.current);
        }
      })
      .catch(console.error);
  };

  useEffect(() => {
    load();
    pollRef.current = setInterval(load, 5000);

    timerRef.current = setInterval(() => {
      if (stageStartRef.current) {
        setElapsed(Math.floor((Date.now() - stageStartRef.current) / 1000));
      }
    }, 1000);

    return () => {
      clearInterval(pollRef.current);
      clearInterval(timerRef.current);
    };
  }, [slug]);

  const currentStage = status?.stage_number || 0;
  const isFailed = status?.status === "FAILED";
  const isComplete = status?.status === "READY_FOR_REVIEW";
  const isDropped = status?.status === "DROPPED";
  const notStarted = currentStage === 0 && !isFailed && !isDropped;

  const statusText = isDropped
    ? "Book was dropped — go back and upload again"
    : isFailed
    ? "Pipeline failed"
    : isComplete
    ? "Complete — redirecting..."
    : notStarted
    ? "Waiting for pipeline to start..."
    : "Processing...";

  return (
    <div style={{ padding: 40, fontFamily: "sans-serif", maxWidth: 640, margin: "0 auto" }}>
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.3); }
        }
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
        .stage-pulse {
          animation: pulse-dot 1.4s ease-in-out infinite;
          background: #3b82f6;
        }
        .spinner {
          width: 18px;
          height: 18px;
          border: 2px solid #d1d5db;
          border-top-color: #6b7280;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
          display: inline-block;
        }
      `}</style>

      <button
        onClick={() => navigate(-1)}
        style={{
          background: "none",
          border: "none",
          color: "#3b82f6",
          cursor: "pointer",
          fontSize: 14,
          padding: "0 0 24px",
        }}
      >
        ← Back
      </button>

      <h2 style={{ margin: "0 0 4px", fontSize: 22, fontWeight: 600 }}>
        {slug.replace(/_/g, " ")}
      </h2>
      <p style={{ color: isFailed ? "#ef4444" : "#6b7280", margin: "0 0 32px", fontSize: 14 }}>
        {statusText}
      </p>

      {notStarted && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28, color: "#6b7280", fontSize: 14 }}>
          <span className="spinner" />
          <span>Waiting for pipeline to start...</span>
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 0, marginBottom: 32 }}>
        {STAGES.map((stage, idx) => {
          const isStageComplete =
            currentStage > stage.num ||
            (currentStage === stage.num && status?.stage_label?.toLowerCase().includes("done"));
          const isRunning = currentStage === stage.num && !isStageComplete && !isFailed;
          const isWaiting = currentStage < stage.num && !isFailed;
          const isFailedStage = isFailed && currentStage === stage.num;
          const isLast = idx === STAGES.length - 1;

          return (
            <div key={stage.num} style={{ display: "flex", alignItems: "stretch", gap: 0 }}>
              {/* Connector column */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 32, flexShrink: 0 }}>
                {/* Circle */}
                <div
                  className={isRunning ? "stage-pulse" : ""}
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 13,
                    background: isFailedStage
                      ? "#ef4444"
                      : isStageComplete
                      ? "#10b981"
                      : isRunning
                      ? "#3b82f6"
                      : "#f3f4f6",
                    color: isStageComplete || isRunning || isFailedStage ? "#fff" : "#9ca3af",
                    flexShrink: 0,
                    fontWeight: 600,
                    zIndex: 1,
                    position: "relative",
                  }}
                >
                  {isStageComplete ? "✓" : isFailedStage ? "✗" : stage.num}
                </div>
                {/* Vertical line */}
                {!isLast && (
                  <div
                    style={{
                      width: 2,
                      flex: 1,
                      minHeight: 20,
                      background: isStageComplete ? "#10b981" : "#e5e7eb",
                      margin: "2px 0",
                    }}
                  />
                )}
              </div>

              {/* Text column */}
              <div style={{ paddingLeft: 16, paddingBottom: isLast ? 0 : 20, paddingTop: 4, flex: 1 }}>
                <div
                  style={{
                    fontWeight: isRunning || isStageComplete ? 500 : 400,
                    color: isFailedStage ? "#ef4444" : isWaiting ? "#9ca3af" : "#111827",
                    fontSize: 15,
                  }}
                >
                  Stage {stage.num} — {stage.label}
                </div>

                {/* Estimate hint for waiting stages */}
                {isWaiting && stage.estimate && (
                  <div style={{ fontSize: 12, color: "#d1d5db", marginTop: 2 }}>
                    {stage.estimate}
                  </div>
                )}

                {/* Running: live elapsed + stage label + estimate */}
                {isRunning && (
                  <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 2 }}>
                    <div style={{ fontSize: 13, color: "#3b82f6", fontWeight: 500 }}>
                      {fmt(elapsed)} elapsed
                      {stage.estimate && (
                        <span style={{ color: "#9ca3af", fontWeight: 400, marginLeft: 6 }}>
                          (est. {stage.estimate})
                        </span>
                      )}
                    </div>
                    {status?.stage_label && (
                      <div style={{ fontSize: 12, color: "#6b7280" }}>{status.stage_label}</div>
                    )}
                  </div>
                )}

                {/* Failed stage message */}
                {isFailedStage && status?.stage_label && (
                  <div style={{ fontSize: 12, color: "#ef4444", marginTop: 2 }}>
                    {status.stage_label}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Log tail */}
      {status?.log_tail?.length > 0 && (
        <div
          style={{
            background: "#1e293b",
            borderRadius: 8,
            padding: "12px 16px",
            fontFamily: "monospace",
            fontSize: 12,
            color: isFailed ? "#fca5a5" : "#94a3b8",
            lineHeight: 1.6,
          }}
        >
          <div style={{ color: "#64748b", fontSize: 11, marginBottom: 6, letterSpacing: "0.05em" }}>
            PIPELINE LOG
          </div>
          {status.log_tail.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}

      {/* Poll note */}
      {!isFailed && !isComplete && (
        <p style={{ color: "#d1d5db", fontSize: 12, marginTop: 16, textAlign: "center" }}>
          Refreshing every 5 seconds
        </p>
      )}
    </div>
  );
}
