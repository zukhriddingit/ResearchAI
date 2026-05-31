import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle } from "lucide-react";
import { apiBase, clickCitation, createSession, getEvents, getSession, loadPaper, runAgent, subscribeEvents } from "./api";
import AgentPanel from "./components/AgentPanel";
import CitationPopover from "./components/CitationPopover";
import KnowledgeGraph from "./components/KnowledgeGraph";
import PaperViewer from "./components/PaperViewer";
import UploadBar from "./components/UploadBar";
import type { AgentEvent, CitationClickResponse, Paper, SessionState } from "./types";

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [selectedCitation, setSelectedCitation] = useState<CitationClickResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
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

  const refreshSession = useCallback(async () => {
    if (!sessionId) return;
    const state = await getSession(sessionId);
    setSession(state);
  }, [sessionId]);

  const handleLoad = async (sourceType: "arxiv_url" | "pdf_text" | "demo", source: string) => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    setSelectedCitation(null);
    try {
      await loadPaper(sessionId, sourceType, source);
      await refreshSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load paper");
    } finally {
      setBusy(false);
    }
  };

  const handleCitationClick = async (citationId: string) => {
    if (!sessionId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await clickCitation(sessionId, citationId);
      setSelectedCitation(result);
      await refreshSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resolve citation");
    } finally {
      setBusy(false);
    }
  };

  const handleRunAgent = async (agentName: string, payload: { section_id?: string } = {}) => {
    if (!sessionId || !mainPaper) return;
    setBusy(true);
    setError(null);
    try {
      await runAgent(sessionId, agentName, { paper_id: mainPaper.id, ...payload });
      await refreshSession();
    } catch (err) {
      setError(err instanceof Error ? err.message : `Failed to run ${agentName}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <UploadBar busy={busy} onLoad={handleLoad} />
      {error && (
        <div className="error-banner">
          <AlertCircle size={16} />
          <span>{error}</span>
        </div>
      )}
      <main className="workspace">
        <section className="graph-column" aria-label="Knowledge graph">
          <KnowledgeGraph graph={session?.graph ?? { nodes: [], edges: [] }} />
        </section>
        <section className="reader-column" aria-label="Paper reader">
          <PaperViewer paper={mainPaper} busy={busy} onCitationClick={handleCitationClick} onRunAgent={handleRunAgent} />
          {selectedCitation && <CitationPopover result={selectedCitation} />}
        </section>
        <section className="agent-column" aria-label="Agent events">
          <AgentPanel events={session?.events ?? []} findings={session?.findings ?? []} onRunAgent={handleRunAgent} disabled={!mainPaper || busy} />
        </section>
      </main>
    </div>
  );
}

export default App;

