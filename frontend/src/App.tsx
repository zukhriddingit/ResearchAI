import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { AlertCircle } from "lucide-react";
import { analyzePaper, apiBase, clickCitation, createSession, getEvents, getSession, loadPaper, runAgent, subscribeEvents, uploadPaper } from "./api";
import AgentPanel from "./components/AgentPanel";
import CitationPopover from "./components/CitationPopover";
import KnowledgeGraph from "./components/KnowledgeGraph";
import PaperViewer from "./components/PaperViewer";
import UploadBar from "./components/UploadBar";
import type { AgentEvent, CitationClickResponse, Paper, SessionState } from "./types";

interface PendingCitation {
  id: string;
  label: string;
}

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<CitationClickResponse | null>(null);
  const [pendingCitation, setPendingCitation] = useState<PendingCitation | null>(null);
  const [selectedPaperId, setSelectedPaperId] = useState<string | null>(null);
  const [readingHistory, setReadingHistory] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [columns, setColumns] = useState({ left: 20, right: 30 });

  const workspaceStyle = useMemo(
    () =>
      ({
        "--left-column": leftCollapsed ? "52px" : `clamp(240px, ${columns.left}%, 460px)`,
        "--right-column": `clamp(300px, ${columns.right}%, 640px)`
      }) as CSSProperties,
    [columns.left, columns.right, leftCollapsed]
  );

  useEffect(() => {
    let cancelled = false;
    setSelectedCitation(null);
    setPendingCitation(null);
    setSelectedPaperId(null);
    setReadingHistory([]);
    createSession()
      .then((created) => {
        if (!cancelled) {
          setSessionId(created.session_id);
          return getSession(created.session_id);
        }
        return null;
      })
      .then((state) => {
        if (state && !cancelled) {
          setSession(state);
        }
      })
      .catch((err) => setError(`Backend unavailable at ${apiBase()}: ${err.message}`));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId) return undefined;
    let pollTimer: number | undefined;
    const onEvent = (event: AgentEvent) => {
      setSession((current) => {
        if (!current || current.events.some((existing) => existing.id === event.id)) return current;
        return { ...current, events: [...current.events, event] };
      });
    };
    const cleanup = subscribeEvents(
      sessionId,
      onEvent,
      () => {
        pollTimer = window.setInterval(async () => {
          const events = await getEvents(sessionId);
          setSession((current) => (current ? { ...current, events } : current));
        }, 1500);
      }
    );
    return () => {
      cleanup();
      if (pollTimer) window.clearInterval(pollTimer);
    };
  }, [sessionId]);

  const mainPaper = useMemo<Paper | null>(() => {
    if (!session) return null;
    return session.papers.find((paper) => paper.id === session.main_paper_id) ?? session.papers.find((paper) => paper.is_main) ?? null;
  }, [session]);

  const activePaper = useMemo<Paper | null>(() => {
    if (!session) return null;
    return session.papers.find((paper) => paper.id === selectedPaperId) ?? mainPaper;
  }, [mainPaper, selectedPaperId, session]);

  const rememberPaper = useCallback((paperId: string | null | undefined) => {
    if (!paperId) return;
    setReadingHistory((current) => [paperId, ...current.filter((id) => id !== paperId)].slice(0, 8));
  }, []);

  const applySessionState = useCallback((state: SessionState, preferredPaperId?: string | null, historySeed: string[] = []) => {
    setSession(state);
    const fallbackPaperId = state.main_paper_id ?? state.papers.find((paper) => paper.is_main)?.id ?? state.papers[0]?.id ?? null;
    const nextPaperId = preferredPaperId ?? fallbackPaperId;
    setSelectedPaperId(nextPaperId);
    const available = new Set(state.papers.map((paper) => paper.id));
    const nextHistory = uniqueIds([nextPaperId, ...historySeed]).filter((paperId) => available.has(paperId));
    setReadingHistory(nextHistory);
  }, []);

  useEffect(() => {
    if (!session) return;
    const available = new Set(session.papers.map((paper) => paper.id));
    if (selectedPaperId && available.has(selectedPaperId)) {
      setReadingHistory((current) => current.filter((paperId) => available.has(paperId)));
      return;
    }
    const fallbackPaperId = mainPaper?.id ?? session.papers[0]?.id ?? null;
    setSelectedPaperId(fallbackPaperId);
    if (fallbackPaperId) rememberPaper(fallbackPaperId);
  }, [mainPaper?.id, rememberPaper, selectedPaperId, session]);

  const refreshSession = useCallback(async () => {
    if (!sessionId) return;
    const state = await getSession(sessionId);
    setSession(state);
  }, [sessionId]);

  const startFreshSession = useCallback(async () => {
    const created = await createSession();
    setSessionId(created.session_id);
    const state = await getSession(created.session_id);
    applySessionState(state);
    return created.session_id;
  }, [applySessionState]);

  const appendLocalEvent = useCallback((agent: string, message: string, type = "agent.started") => {
    setSession((current) => {
      if (!current) return current;
      const event: AgentEvent = {
        id: `local_${Date.now()}_${agent}`,
        session_id: current.session_id,
        timestamp: new Date().toISOString(),
        type,
        agent,
        status: "running",
        message,
        payload: { local: true }
      };
      return { ...current, events: [...current.events, event] };
    });
  }, []);

  const handleLoad = async (sourceType: "arxiv_url" | "pdf_text", source: string) => {
    setBusy(true);
    setActiveAgent("parser");
    setError(null);
    setSelectedCitation(null);
    setPendingCitation(null);
    try {
      const activeSessionId = await startFreshSession();
      await loadPaper(activeSessionId, sourceType, source);
      applySessionState(await getSession(activeSessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load paper");
    } finally {
      setBusy(false);
      setActiveAgent(null);
    }
  };

  const handleUpload = async (file: File) => {
    setBusy(true);
    setActiveAgent("parser");
    setError(null);
    setSelectedCitation(null);
    setPendingCitation(null);
    try {
      const activeSessionId = await startFreshSession();
      await uploadPaper(activeSessionId, file);
      applySessionState(await getSession(activeSessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload paper");
    } finally {
      setBusy(false);
      setActiveAgent(null);
    }
  };

  const handleCitationClick = async (citationId: string) => {
    const sourcePaper = activePaper ?? mainPaper;
    if (!sessionId || !sourcePaper) return;
    const citation = sourcePaper.citations.find((item) => item.id === citationId);
    setBusy(true);
    setActiveAgent("reference");
    setError(null);
    setSelectedCitation(null);
    setPendingCitation({ id: citationId, label: citation?.title ?? citation?.raw ?? "citation" });
    appendLocalEvent("Reference", `Resolving ${citation?.raw ?? "citation"} against ${sourcePaper.title}.`);
    try {
      const result = await clickCitation(sessionId, citationId, sourcePaper.id);
      const state = await getSession(sessionId);
      applySessionState(state, result.referenced_paper.id, [sourcePaper.id, ...readingHistory]);
      setSelectedCitation(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve citation");
    } finally {
      setBusy(false);
      setActiveAgent(null);
      setPendingCitation(null);
    }
  };

  const handleRunAgent = async (agentName: string, payload: { section_id?: string } = {}) => {
    if (!sessionId || !mainPaper) return;
    const targetPaper = activePaper ?? mainPaper;
    const normalizedAgent = agentName.toLowerCase();
    if (normalizedAgent === "reference") {
      const citation = mainPaper.citations.find((item) => !item.resolved_paper_id) ?? mainPaper.citations[0];
      if (!citation) {
        setError("No citation is available for the Reference Agent yet.");
        return;
      }
      await handleCitationClick(citation.id);
      return;
    }
    if (agentName === "graph") {
      setActiveAgent("graph");
      appendLocalEvent("Graph", "Refreshing graph state from the session.");
      await refreshSession();
      window.setTimeout(() => setActiveAgent(null), 400);
      return;
    }
    setBusy(true);
    setActiveAgent(normalizedAgent);
    setError(null);
    appendLocalEvent(titleCase(normalizedAgent), agentActionMessage(normalizedAgent));
    try {
      await runAgent(sessionId, normalizedAgent, { paper_id: targetPaper.id, ...payload });
      await refreshSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to run ${agentName}`);
    } finally {
      setBusy(false);
      setActiveAgent(null);
    }
  };

  const handleAnalyzePaper = async (paperId: string) => {
    if (!sessionId) return;
    const trail = uniqueIds([paperId, activePaper?.id, mainPaper?.id, ...readingHistory]);
    setBusy(true);
    setActiveAgent("parser");
    setError(null);
    setSelectedCitation(null);
    setPendingCitation(null);
    appendLocalEvent("Parser", "Creating a new research session for this referenced paper.");
    try {
      const state = await analyzePaper(sessionId, paperId);
      setSessionId(state.session_id);
      applySessionState(state, state.main_paper_id, trail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to analyze referenced paper");
    } finally {
      setBusy(false);
      setActiveAgent(null);
    }
  };

  const handlePaperSelect = useCallback((paperId: string) => {
    setSelectedPaperId(paperId);
    rememberPaper(paperId);
    setSelectedCitation(null);
    setPendingCitation(null);
  }, [rememberPaper]);

  const startColumnResize = useCallback((side: "left" | "right", event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const workspace = event.currentTarget.closest(".workspace");
    if (!(workspace instanceof HTMLElement)) return;
    const rect = workspace.getBoundingClientRect();

    const handleMove = (moveEvent: PointerEvent) => {
      const pointerPercent =
        side === "left"
          ? ((moveEvent.clientX - rect.left) / rect.width) * 100
          : ((rect.right - moveEvent.clientX) / rect.width) * 100;

      setColumns((current) => {
        if (side === "left") {
          const maxLeft = Math.min(32, 68 - current.right);
          return { ...current, left: clamp(pointerPercent, 14, maxLeft) };
        }
        const maxRight = Math.min(42, 68 - current.left);
        return { ...current, right: clamp(pointerPercent, 24, maxRight) };
      });
    };

    const stopResize = () => {
      document.body.classList.remove("is-resizing-columns");
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", stopResize);
    };

    if (side === "left") setLeftCollapsed(false);
    document.body.classList.add("is-resizing-columns");
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", stopResize);
  }, []);

  return (
    <div className="app-shell">
      <UploadBar busy={busy} onLoad={handleLoad} onUpload={handleUpload} />
      {error && (
        <div className="error-banner">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}
      <main className={`workspace ${leftCollapsed ? "map-collapsed" : ""}`} style={workspaceStyle}>
        <section className={`graph-column ${leftCollapsed ? "is-collapsed" : ""}`} aria-label="Knowledge graph">
          <KnowledgeGraph
            graph={session?.graph ?? { nodes: [], edges: [] }}
            selectedPaperId={activePaper?.id ?? null}
            historyPaperIds={readingHistory}
            onPaperSelect={handlePaperSelect}
            collapsed={leftCollapsed}
            onToggleCollapsed={() => setLeftCollapsed((current) => !current)}
          />
        </section>
        <div
          className={`resize-handle left-resize ${leftCollapsed ? "is-disabled" : ""}`}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize research map"
          onPointerDown={(event) => !leftCollapsed && startColumnResize("left", event)}
        />
        <section className="reader-column" aria-label="Paper reader">
          <PaperViewer
            paper={activePaper}
            busy={busy}
            activeCitationId={pendingCitation?.id ?? null}
            onCitationClick={handleCitationClick}
            onRunAgent={handleRunAgent}
            onAnalyzePaper={handleAnalyzePaper}
          />
          {activePaper && (selectedCitation || pendingCitation) && <CitationPopover result={selectedCitation} pendingCitation={pendingCitation} />}
        </section>
        <div
          className="resize-handle right-resize"
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize research assistants"
          onPointerDown={(event) => startColumnResize("right", event)}
        />
        <section className="agent-column" aria-label="Agent events">
          <AgentPanel
            events={session?.events ?? []}
            findings={session?.findings ?? []}
            activeAgent={activeAgent}
            onRunAgent={handleRunAgent}
            disabled={!activePaper || busy}
          />
        </section>
      </main>
    </div>
  );
}

function uniqueIds(ids: Array<string | null | undefined>) {
  return ids.filter((id, index): id is string => Boolean(id) && ids.indexOf(id) === index);
}

function titleCase(value: string) {
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function agentActionMessage(agentName: string) {
  const messages: Record<string, string> = {
    parser: "Parser usually runs when loading or uploading a paper.",
    critique: "Critique Agent is looking for weak claims, missing baselines, and reproducibility gaps.",
    code: "Code Agent is searching for implementation repositories and connecting them to the paper.",
    math: "Math Agent is explaining equations and checking notation.",
    replication: "Replication Agent is building a dry-run scorecard for the current paper.",
    evaluation: "Evaluation Agent is suggesting benchmarks and measurement gaps.",
    adversarial: "Adversarial Agent is generating stress tests against the strongest claims.",
    graph: "Graph Agent is refreshing shared session memory."
  };
  return messages[agentName] ?? `${titleCase(agentName)} Agent started.`;
}

export default App;
