import { GitBranch } from "lucide-react";
import type { GraphState } from "../types";

interface Props {
  graph: GraphState;
}

function KnowledgeGraph({ graph }: Props) {
  const width = 360;
  const height = 520;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.32;
  const nodes = graph.nodes.map((node, index) => {
    if (index === 0 || node.status === "main") return { ...node, x: centerX, y: centerY };
    const angle = ((index - 1) / Math.max(1, graph.nodes.length - 1)) * Math.PI * 2 - Math.PI / 2;
    return { ...node, x: centerX + Math.cos(angle) * radius, y: centerY + Math.sin(angle) * radius };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));

  return (
    <div className="panel graph-panel">
      <div className="panel-title">
        <GitBranch size={16} />
        <span>Knowledge Graph</span>
      </div>
      {nodes.length === 0 ? (
        <div className="empty-graph">Load the demo to seed the main paper node.</div>
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
            <g key={node.id} transform={`translate(${node.x} ${node.y})`} className="graph-node">
              <circle r={node.status === "main" ? 34 : 25} className={`node-circle node-${node.type} status-${node.status}`} />
              <text y={4} className="node-initials">
                {initials(node.label)}
              </text>
              <title>{node.label}</title>
            </g>
          ))}
        </svg>
      )}
      <div className="legend-row">
        <span><i className="dot main-dot" /> main</span>
        <span><i className="dot ref-dot" /> paper</span>
        <span><i className="dot code-dot" /> code</span>
      </div>
    </div>
  );
}

function initials(label: string) {
  return label
    .split(/[\s:/-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export default KnowledgeGraph;

