import { Minus, Plus, RotateCcw } from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import type { GraphNode, KnowledgeGraph } from '../types';

const relationLabel = { prerequisite: '先修', contains: '包含', application: '应用', contrast: '对比' };
const relationColor = { prerequisite: '#7b82ef', contains: '#22a99a', application: '#e58c4c', contrast: '#d36d86' };

type Props = { graph: KnowledgeGraph; onNodeClick?: (node: GraphNode) => void };

export default function KnowledgeGraphView({ graph, onNodeClick }: Props) {
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const nodeById = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes]);
  const adjustScale = (next: number) => setScale(Math.max(.65, Math.min(2.4, next)));
  return <div className="graph-view">
    <div className="graph-view-toolbar" aria-label="图谱视图控制">
      <button aria-label="缩小图谱" onClick={() => adjustScale(scale - .15)}><Minus size={15} /></button>
      <span>{Math.round(scale * 100)}%</span>
      <button aria-label="放大图谱" onClick={() => adjustScale(scale + .15)}><Plus size={15} /></button>
      <button aria-label="重置图谱" onClick={() => { setScale(1); setOffset({ x: 0, y: 0 }); }}><RotateCcw size={15} /></button>
    </div>
    <svg
      role="img" aria-label={`${graph.title}，${graph.nodes.length}个知识点，${graph.edges.length}条关系`}
      viewBox="0 0 930 480"
      onWheel={(event) => { event.preventDefault(); adjustScale(scale + (event.deltaY < 0 ? .1 : -.1)); }}
      onPointerDown={(event) => { if ((event.target as Element).closest('.graph-node')) return; drag.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y }; (event.currentTarget as SVGSVGElement).setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (!drag.current) return; setOffset({ x: drag.current.ox + event.clientX - drag.current.x, y: drag.current.oy + event.clientY - drag.current.y }); }}
      onPointerUp={() => { drag.current = null; }}
    >
      <defs><marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" /></marker></defs>
      <g transform={`translate(${offset.x} ${offset.y}) scale(${scale})`}>
        {graph.edges.map((edge, index) => {
          const source = nodeById.get(edge.from_node_id); const target = nodeById.get(edge.to_node_id);
          if (!source || !target) return null;
          const dx = target.position_x - source.position_x; const dy = target.position_y - source.position_y;
          const length = Math.max(1, Math.hypot(dx, dy)); const ux = dx / length; const uy = dy / length;
          const x1 = source.position_x + ux * 38; const y1 = source.position_y + uy * 38;
          const x2 = target.position_x - ux * 42; const y2 = target.position_y - uy * 42;
          const labelOffset = (index % 2 === 0 ? 1 : -1) * (12 + (index % 3) * 9);
          const mx = (x1 + x2) / 2 - uy * labelOffset; const my = (y1 + y2) / 2 + ux * labelOffset;
          return <g key={edge.id} className="graph-edge"><line x1={x1} y1={y1} x2={x2} y2={y2} stroke={relationColor[edge.relation]} markerEnd="url(#graph-arrow)" /><rect x={mx - 21} y={my - 10} width="42" height="20" rx="9" /><text x={mx} y={my + 3}>{relationLabel[edge.relation]}</text></g>;
        })}
        {graph.nodes.map((node) => <g key={node.id} className={`graph-node graph-node--${node.node_type}`} transform={`translate(${node.position_x} ${node.position_y})`} onClick={() => onNodeClick?.(node)}>
          <circle r="37" /><text y="-2">{node.label.length > 5 ? node.label.slice(0, 4) : node.label}</text>{node.mastery != null && <text className="graph-node-mastery" y="15">掌握度 {Math.round(node.mastery)}%</text>}
        </g>)}
      </g>
    </svg>
    <div className="graph-legend"><span><i className="foundation" />基础</span><span><i className="core" />核心</span><span><i className="application" />应用</span></div>
  </div>;
}
