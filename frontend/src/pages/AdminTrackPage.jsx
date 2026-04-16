import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Check, X } from "lucide-react";
import { getBookStatus } from "../api/admin";

function getStages(t) {
  return [
    { num: 1, label: t("admin.pipeline.stage1Label", "Register book"),             estimate: t("admin.pipeline.stage1Est", "~5 sec"),     desc: t("admin.pipeline.stage1Desc", "Register book metadata and prepare output directory") },
    { num: 2, label: t("admin.pipeline.stage2Label", "Mathpix PDF extraction"),    estimate: t("admin.pipeline.stage2Est", "~20-45 min"), desc: t("admin.pipeline.stage2Desc", "Convert PDF to structured Markdown (MMD) with LaTeX and images") },
    { num: 3, label: t("admin.pipeline.stage3Label", "Build chunks & embeddings"), estimate: t("admin.pipeline.stage3Est", "~2-5 min"),   desc: t("admin.pipeline.stage3Desc", "Split content into teaching chunks, generate embeddings, save to database") },
    { num: 4, label: t("admin.pipeline.stage4Label", "Validate chunks"),           estimate: t("admin.pipeline.stage4Est", "~10 sec"),    desc: t("admin.pipeline.stage4Desc", "Check TOC coverage, section ordering, chunk quality") },
    { num: 5, label: t("admin.pipeline.stage5Label", "Build dependency graph"),    estimate: t("admin.pipeline.stage5Est", "~1 min"),     desc: t("admin.pipeline.stage5Desc", "Build prerequisite graph linking sections in reading order") },
    { num: 6, label: t("admin.pipeline.stage6Label", "Ready for review"),          estimate: null,                                         desc: t("admin.pipeline.stage6Desc", "Pipeline complete — book is ready for admin review") },
  ];
}

function fmt(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export default function AdminTrackPage() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const STAGES = getStages(t);
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

        if (data.stage_number !== lastStageRef.current) {
          lastStageRef.current = data.stage_number;
          stageStartRef.current = Date.now();
          setElapsed(0);
        }

        if (data.status === "READY_FOR_REVIEW" || data.stage_number >= 6) {
          clearInterval(pollRef.current);
          clearInterval(timerRef.current);
          setTimeout(() => navigate(`/admin/books/${slug}/review`), 1500);
        }
        if (data.status === "FAILED" || data.status === "VALIDATION_FAILED") {
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

  const currentStage = status?.stage_number ?? 0;
  const isFailed = status?.status === "FAILED";
  const isComplete = status?.status === "READY_FOR_REVIEW";
  const isDropped = status?.status === "DROPPED";
  const notStarted = currentStage === 0 && !isFailed && !isDropped;
  const isInitializing = currentStage === -1;

  const statusText = isDropped
    ? t("admin.pipeline.statusDropped", "Book was dropped -- go back and upload again")
    : isFailed
    ? t("admin.pipeline.statusFailed", "Pipeline failed")
    : isComplete
    ? t("admin.pipeline.statusComplete", "Complete -- redirecting...")
    : notStarted
    ? t("admin.pipeline.statusWaiting", "Waiting for pipeline to start...")
    : isInitializing
    ? (status?.stage_label || t("admin.pipeline.statusInitializing", "Initializing..."))
    : t("admin.pipeline.statusProcessing", "Processing...");

  return (
    <div style={{ margin: "0 auto" }}>
      <h2 style={{ fontSize: "26px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", marginBottom: "4px" }}>
        {t("admin.pipeline.heading", "Pipeline Progress")}
      </h2>
      <p style={{ fontSize: "14px", marginBottom: "32px", color: isFailed ? "#EF4444" : "#64748B" }}>
        {slug.replace(/_/g, " ")} &mdash; {statusText}
      </p>

      {/* Waiting / initializing spinner */}
      {(notStarted || isInitializing) && (
        <div className="flex items-center gap-3 mb-7 text-[var(--color-text-secondary)] text-sm">
          <span className="inline-block w-4.5 h-4.5 border-2 border-gray-300 border-t-gray-500 rounded-full animate-spin" />
          <span>{isInitializing ? (status?.stage_label || t("admin.pipeline.statusInitializing", "Initializing...")) : t("admin.pipeline.statusWaiting", "Waiting for pipeline to start...")}</span>
        </div>
      )}

      {/* Horizontal stepper */}
      <div style={{ borderRadius: "16px", border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF", padding: "32px 24px", marginBottom: "24px", overflowX: "auto" }}>
        <div style={{ display: "flex", alignItems: "flex-start", minWidth: "700px" }}>
          {STAGES.map((stage, idx) => {
            const isStageComplete =
              currentStage > stage.num ||
              (currentStage === stage.num && status?.stage_label?.includes("\u2713"));
            const isRunning = currentStage === stage.num && !isStageComplete && !isFailed;
            const isFailedStage = isFailed && currentStage === stage.num;
            const isLast = idx === STAGES.length - 1;

            return (
              <div key={stage.num} style={{ display: "flex", alignItems: "center", flex: isLast ? "none" : 1 }}>
                {/* Circle + label group */}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                  {/* Circle */}
                  <div
                    style={{
                      width: "44px", height: "44px", borderRadius: "50%",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: "14px", fontWeight: 700, flexShrink: 0, transition: "all 0.2s",
                      backgroundColor: isFailedStage ? "#EF4444" : isStageComplete ? "#22C55E" : isRunning ? "#F97316" : "#E2E8F0",
                      color: (isFailedStage || isStageComplete || isRunning) ? "#FFFFFF" : "#94A3B8",
                      animation: isRunning ? "pulse 2s infinite" : "none",
                    }}
                  >
                    {isStageComplete ? <Check size={18} strokeWidth={3} /> : isFailedStage ? <X size={18} strokeWidth={3} /> : stage.num}
                  </div>
                  {/* Label below */}
                  <div style={{ marginTop: "10px", textAlign: "center", maxWidth: "100px" }}>
                    <div style={{
                      fontSize: "12px", lineHeight: 1.3, fontWeight: 500,
                      color: isRunning || isStageComplete ? "#0F172A" : isFailedStage ? "#EF4444" : "#94A3B8",
                    }}>
                      {stage.label}
                    </div>
                    {isRunning && (
                      <div style={{ fontSize: "11px", color: "#F97316", fontWeight: 600, marginTop: "3px" }}>
                        {fmt(elapsed)}
                      </div>
                    )}
                    {!isRunning && stage.estimate && (
                      <div style={{ fontSize: "11px", color: "#CBD5E1", marginTop: "3px" }}>{stage.estimate}</div>
                    )}
                  </div>
                </div>

                {/* Connecting line */}
                {!isLast && (
                  <div
                    style={{
                      height: "3px", flex: 1, margin: "0 8px", marginTop: "-24px",
                      borderRadius: "9999px", transition: "background-color 0.2s",
                      backgroundColor: isStageComplete ? "#4ADE80" : isRunning ? "#FDBA74" : "#E2E8F0",
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Running stage detail card */}
      {STAGES.map((stage) => {
        const isRunning = currentStage === stage.num && !(currentStage > stage.num || (currentStage === stage.num && status?.stage_label?.includes("\u2713"))) && !isFailed;
        if (!isRunning) return null;
        return (
          <div key={stage.num} style={{ borderRadius: "16px", border: "1px solid #FED7AA", backgroundColor: "#FFF7ED", padding: "24px", marginBottom: "24px" }}>
            <div style={{ fontSize: "15px", fontWeight: 600, color: "#EA580C" }}>
              {t("admin.pipeline.stageNum", "Stage {{num}}", { num: stage.num })} &mdash; {stage.label}
            </div>
            <div style={{ fontSize: "13px", color: "#64748B", marginTop: "6px" }}>{stage.desc}</div>
            <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "12px", fontSize: "13px" }}>
              <span style={{ color: "#EA580C", fontWeight: 600 }}>{fmt(elapsed)} {t("admin.pipeline.elapsed", "elapsed")}</span>
              {stage.estimate && <span style={{ color: "#94A3B8" }}>(est. {stage.estimate})</span>}
            </div>
            {status?.stage_label && (
              <div className="text-xs text-[var(--color-text-secondary)] mt-1">{status.stage_label}</div>
            )}
          </div>
        );
      })}

      {/* Failed stage message */}
      {isFailed && (
        <div className="rounded-2xl border border-red-200 bg-red-50 dark:bg-red-950/20 dark:border-red-900/40 p-5 mb-6">
          <div className="text-sm font-medium text-red-500">{t("admin.pipeline.failedAtStage", "Pipeline failed at Stage {{stage}}", { stage: currentStage })}</div>
          {status?.stage_label && (
            <div className="text-xs text-red-400 mt-1">{status.stage_label}</div>
          )}
        </div>
      )}

      {/* Stage progression log */}
      {status?.stage_lines?.length > 0 && (
        <div style={{ borderRadius: "12px", backgroundColor: "#1E293B", padding: "20px", fontFamily: "monospace", fontSize: "13px", lineHeight: 1.7, marginBottom: "16px" }}>
          <div style={{ color: "#64748B", fontSize: "11px", letterSpacing: "0.05em", marginBottom: "8px", textTransform: "uppercase" }}>{t("admin.pipeline.stageProgressionHeader", "STAGE PROGRESSION")}</div>
          {status.stage_lines.map((line, i) => (
            <div key={`s${i}`} className="text-cyan-300">{line}</div>
          ))}
        </div>
      )}

      {/* Pipeline log tail */}
      {status?.log_tail?.length > 0 && (
        <div style={{ borderRadius: "12px", backgroundColor: "#1E293B", padding: "20px", fontFamily: "monospace", fontSize: "13px", lineHeight: 1.7, maxHeight: "300px", overflowY: "auto", color: isFailed ? "#FCA5A5" : "#94A3B8" }}>
          <div style={{ color: "#64748B", fontSize: "11px", letterSpacing: "0.05em", marginBottom: "8px", textTransform: "uppercase" }}>{t("admin.pipeline.logHeader", "PIPELINE LOG")}</div>
          {status.log_tail.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      )}

      {/* Poll note */}
      {!isFailed && !isComplete && (
        <p className="text-gray-300 text-xs mt-4 text-center">
          {t("admin.pipeline.refreshNote", "Refreshing every 5 seconds")}
        </p>
      )}
    </div>
  );
}
