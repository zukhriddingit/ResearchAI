from __future__ import annotations

from threading import RLock

from app.models import (
    AgentFinding,
    GraphEdge,
    GraphNode,
    GraphState,
    Paper,
    SessionState,
    new_id,
)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._lock = RLock()

    def create_session(self) -> SessionState:
        with self._lock:
            session = SessionState(session_id=new_id("session"))
            self._sessions[session.session_id] = session
            return session

    def get_session(self, session_id: str) -> SessionState:
        with self._lock:
            if session_id not in self._sessions:
                raise KeyError(session_id)
            return self._sessions[session_id]

    def add_paper(self, session_id: str, paper: Paper) -> Paper:
        with self._lock:
            session = self.get_session(session_id)
            session.papers = [p for p in session.papers if p.id != paper.id] + [paper]
            if paper.is_main:
                session.main_paper_id = paper.id
            return paper

    def add_node(self, session_id: str, node: GraphNode) -> GraphNode:
        with self._lock:
            session = self.get_session(session_id)
            session.graph.nodes = [n for n in session.graph.nodes if n.id != node.id] + [node]
            return node

    def add_edge(self, session_id: str, edge: GraphEdge) -> GraphEdge:
        with self._lock:
            session = self.get_session(session_id)
            session.graph.edges = [e for e in session.graph.edges if e.id != edge.id] + [edge]
            return edge

    def add_finding(self, session_id: str, finding: AgentFinding) -> AgentFinding:
        with self._lock:
            session = self.get_session(session_id)
            session.findings = [f for f in session.findings if f.id != finding.id] + [finding]
            return finding

    def update_graph(self, session_id: str, graph: GraphState) -> GraphState:
        with self._lock:
            session = self.get_session(session_id)
            session.graph = graph
            return graph


store = SessionStore()

