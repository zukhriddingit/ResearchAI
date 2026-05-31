import { GitBranch } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { GraphNode, GraphState } from "../types";

interface Props {
  graph: GraphState;
  selectedPaperId?: string | null;
  historyPaperIds?: string[];
  onPaperSelect?: (paperId: string) => void;
}

function KnowledgeGraph({ graph, selectedPaperId, historyPaperIds = [], onPaperSelect }: Props) {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const previousPaperId = useRef<string | null | undefined>(undefined);
  const width = 360;
  const height = 520;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.32;
  const nodes = useMemo(() => graph.nodes.map((node, index) => {
    if (index === 0 || node.status === "main") return { ...node, x: centerX, y: centerY };
    const angle = ((index - 1) / Math.max(1, graph.nodes.length - 1)) * Math.PI * 2 - Math.PI / 2;
    return { ...node, x: centerX + Math.cos(angle) * radius, y: centerY + Math.sin(angle) * radius };
  }), [graph.nodes]);
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const selectedPaperNode = selectedPaperId ? graph.nodes.find((node) => node.paper_id === selectedPaperId) : null;
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? graph.nodes.find((node) => node.status === "main") ?? graph.nodes[0];
  const historyNodes = historyPaperIds
    .map((paperId) => graph.nodes.find((node) => node.paper_id === paperId))
    .filter((node): node is GraphNode => Boolean(node));

  useEffect(() => {
    if (!graph.nodes.length) {
      setSelectedNodeId(null);
      previousPaperId.current = selectedPaperId;
      return;
    }
    const selectedPaperChanged = previousPaperId.current !== selectedPaperId;
    previousPaperId.current = selectedPaperId;
    if (selectedPaperChanged && selectedPaperNode && selectedNodeId !== selectedPaperNode.id) {
      setSelectedNodeId(selectedPaperNode.id);
      return;
    }
    if (!selectedNodeId || !graph.nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(graph.nodes.find((node) => node.status === "main")?.id ?? graph.nodes[0].id);
    }
  }, [graph.nodes, selectedNodeId, selectedPaperNode]);

  return (
    <div className="panel graph-panel">
      <div className="panel-title">
        <GitBranch size={16} />
        <span>Research Map</span>
      </div>
      {nodes.length === 0 ? (
        <div className="empty-graph">No map yet.</div>
      ) : (
        <svg className="graph-svg" viewBox={`0 0 ${width} ${height}`} role="img">
          {graph.edges.map((edge) => {
            const source = byId.get(edge.source);
            const target = byId.get(edge.target);
            if (!source || !target) return null;
            const midX = (source.x + target.x) / 2;
            const midY = (source.y + target.y) / 2;
            return (
              <g key={edge.id}>
                <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} className={`edge edge-${edge.type}`} />
                <text x={midX} y={midY - 5} className="edge-label">
                  {edge.label}
                </text>
              </g>
            );
          })}
          {nodes.map((node) => (
            <GraphNodeView
              key={node.id}
              node={node}
              selected={selectedNode?.id === node.id}
              onSelect={() => selectNode(node, setSelectedNodeId, onPaperSelect)}
              onPreview={() => setSelectedNodeId(node.id)}
            />
          ))}
        </svg>
      )}
      <div className="legend-row">
        <span><i className="dot main-dot" /> current</span>
        <span><i className="dot ref-dot" /> paper</span>
        <span><i className="dot code-dot" /> code</span>
      </div>
      {historyNodes.length > 0 && (
        <div className="graph-history">
          <h3>Reading History</h3>
          <div>
            {historyNodes.map((node) => (
              <button
                key={node.id}
                className={node.paper_id === selectedPaperId ? "is-active" : ""}
                onClick={() => node.paper_id && onPaperSelect?.(node.paper_id)}
              >
                {shortLabel(node.label, 34)}
              </button>
            ))}
          </div>
        </div>
      )}
      {selectedNode && <NodeDetail node={selectedNode} />}
    </div>
  );
}

function GraphNodeView({
  node,
  selected,
  onSelect,
  onPreview,
}: {
  node: GraphNode & { x: number; y: number };
  selected: boolean;
  onSelect: () => void;
  onPreview: () => void;
}) {
  const url = externalUrl(node);
  const content = (
    <g
      transform={`translate(${node.x} ${node.y})`}
      className={`graph-node ${selected ? "is-selected" : ""}`}
      role={url ? "link" : "button"}
      tabIndex={0}
      onClick={url ? onPreview : onSelect}
      onKeyDown={(event) => {
        if (!url && (event.key === "Enter" || event.key === " ")) onSelect();
      }}
    >
      <circle r={node.status === "main" ? 34 : 25} className={`node-circle node-${node.type} status-${node.status}`} />
      <text y={4} className="node-initials">
        {initials(node.label)}
      </text>
      <text y={node.status === "main" ? 51 : 42} className="node-label">
        {shortLabel(node.label)}
      </text>
      <title>{node.label}</title>
    </g>
  );
  if (!url) return content;
  return (
    <a href={url} target="_blank" rel="noreferrer" onClick={onPreview}>
      {content}
    </a>
  );
}

function selectNode(node: GraphNode, setSelectedNodeId: (id: string) => void, onPaperSelect?: (paperId: string) => void) {
  setSelectedNodeId(node.id);
  if (node.paper_id) onPaperSelect?.(node.paper_id);
  const url = externalUrl(node);
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

function initials(label: string) {
  return label
    .split(/[\s:/-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function shortLabel(label: string, length = 20) {
  return label.length > length ? `${label.slice(0, length - 2)}...` : label;
}

function NodeDetail({ node }: { node: GraphNode }) {
  const url = externalUrl(node);
  const metadataRows = Object.entries(node.metadata ?? {})
    .filter(([key, value]) => key !== "html_url" && value !== null && value !== undefined)
    .slice(0, 4);
  return (
    <div className="node-detail">
      <div className="node-detail-head">
        <strong>{node.label}</strong>
        <span>{node.status}</span>
      </div>
      <p>{node.type === "code" ? "Implementation artifact" : "Research paper"}</p>
      {url && (
        <a className="node-link" href={url} target="_blank" rel="noreferrer">
          Open GitHub repository
        </a>
      )}
      {metadataRows.length > 0 && (
        <dl>
          {metadataRows.map(([key, value]) => (
            <div key={key}>
              <dt>{key.replace(/_/g, " ")}</dt>
              <dd>{formatValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function externalUrl(node: GraphNode) {
  if (node.type !== "code") return null;
  const value = node.metadata?.html_url ?? node.metadata?.url;
  if (typeof value === "string" && /^https?:\/\//.test(value)) return value;
  const fullName = node.metadata?.full_name;
  return typeof fullName === "string" && /^[\w.-]+\/[\w.-]+$/.test(fullName) ? `https://github.com/${fullName}` : null;
}

function formatValue(value: unknown) {
  if (Array.isArray(value)) return value.slice(0, 3).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default KnowledgeGraph;
