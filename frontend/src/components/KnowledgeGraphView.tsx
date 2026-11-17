import { Expand, Focus, Minus, Plus, Search, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { GraphNode, KnowledgeGraph } from "../types";
import {
  filterGraph,
  fitCamera,
  nodeBox,
  relationFrom,
  relations,
  relationTypes,
  zoomAt,
} from "./graph-view-state";
import type { Camera, Relation } from "./graph-view-state";
import "./knowledge-workspace.css";

type Props = {
  graph: KnowledgeGraph;
  selectedNodeId?: string | null;
  expanded?: boolean;
  onNodeClick?: (node: GraphNode) => void;
  onDeselect?: () => void;
  onPractice?: (node: GraphNode) => void;
  onTutor?: (node: GraphNode) => void;
  onEditNode?: (node: GraphNode) => void;
};
const edgeColors = {
  prerequisite: "#6479a1",
  contains: "#36847c",
  application: "#b18248",
  contrast: "#a46a7c",
};

export default function KnowledgeGraphView(props: Props) {
  const g = props.graph;
  return (
    <Explorer
      key={`${g.course_id}/${g.id}/${g.revision_id}/${g.revision_no}`}
      {...props}
    />
  );
}

function Explorer({
  graph,
  selectedNodeId,
  expanded,
  onNodeClick,
  onDeselect,
  onPractice,
  onTutor,
  onEditNode,
}: Props) {
  const [query, setQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [localSelected, setLocalSelected] = useState<string | null>(null);
  const selected =
    selectedNodeId === undefined ? localSelected : selectedNodeId;
  const [types, setTypes] = useState<Relation[]>(relationTypes);
  const [mastery, setMastery] = useState("all");
  const [adjacent, setAdjacent] = useState(false);
  const [full, setFull] = useState(false);
  const [notice, setNotice] = useState("");
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [camera, setCamera] = useState<Camera>({ x: 0, y: 0, zoom: 1 });
  const svg = useRef<SVGSVGElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const cameraRef = useRef(camera);
  const initialized = useRef(false);
  const restoreAfterResize = useRef<Camera | null>(null);
  const previousSize = useRef(size);
  const previousFull = useRef(Boolean(expanded));
  const savedCamera = useRef<Camera | null>(null);
  const drag = useRef<{
    x: number;
    y: number;
    camera: Camera;
    node: string | null;
    moved: boolean;
  } | null>(null);
  const marker = "arrow-" + useId().replace(/:/g, "");
  const allNodes = useMemo(
    () => new Map(graph.nodes.map((n) => [n.id, n])),
    [graph.nodes],
  );
  const visible = useMemo(
    () => filterGraph(graph, types, mastery, selected, adjacent),
    [graph, types, mastery, selected, adjacent],
  );
  const node = selected ? allNodes.get(selected) : undefined;
  const neighbors = new Set([selected]);
  visible.edges.forEach((e) => {
    if (e.from_node_id === selected || e.to_node_id === selected) {
      neighbors.add(e.from_node_id);
      neighbors.add(e.to_node_id);
    }
  });
  const found = graph.nodes.filter((n) =>
    n.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  const links = node
    ? graph.edges.filter(
        (e) =>
          (e.from_node_id === node.id || e.to_node_id === node.id) &&
          allNodes.has(e.from_node_id) &&
          allNodes.has(e.to_node_id),
      )
    : [];
  const hasMastery = graph.nodes.some((n) => n.mastery != null);
  cameraRef.current = camera;

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ width, height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!size.width || !size.height) return;
    if (!initialized.current) {
      setCamera(fitCamera(graph.nodes, size.width, size.height));
      initialized.current = true;
    } else if (restoreAfterResize.current) {
      setCamera(restoreAfterResize.current);
      restoreAfterResize.current = null;
    } else {
      const old = previousSize.current;
      setCamera((c) => ({
        ...c,
        x: c.x + (size.width - old.width) / 2,
        y: c.y + (size.height - old.height) / 2,
      }));
    }
    previousSize.current = size;
  }, [size, graph.nodes]);

  const isFull = expanded ?? full;
  useEffect(() => {
    if (isFull && !previousFull.current)
      savedCamera.current = cameraRef.current;
    if (!isFull && previousFull.current && savedCamera.current) {
      restoreAfterResize.current = savedCamera.current;
      setCamera(savedCamera.current);
      savedCamera.current = null;
    }
    previousFull.current = isFull;
  }, [isFull]);

  useEffect(() => {
    const element = svg.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      const matrix = element.getScreenCTM();
      if (!matrix) return;
      const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(
        matrix.inverse(),
      );
      setCamera((c) =>
        zoomAt(c, c.zoom * Math.exp(-event.deltaY * 0.0015), point),
      );
    };
    const cancel = () => {
      drag.current = null;
    };
    element.addEventListener("wheel", wheel, { passive: false });
    window.addEventListener("blur", cancel);
    return () => {
      element.removeEventListener("wheel", wheel);
      window.removeEventListener("blur", cancel);
    };
  }, []);

  function focus(next: GraphNode) {
    const box = nodeBox(next);
    setCamera({
      zoom: 1,
      x: size.width / 2 - box.x,
      y: size.height / 2 - box.y,
    });
  }
  function choose(next: GraphNode, fromSearch = false) {
    if (!visible.nodes.some((n) => n.id === next.id)) {
      setTypes(relationTypes);
      setMastery("all");
      setAdjacent(false);
      setNotice("已恢复全部筛选，显示所选知识点");
    } else setNotice("");
    setLocalSelected(next.id);
    if (next.id !== selected) onNodeClick?.(next);
    focus(next);
    if (fromSearch) {
      setSearchOpen(false);
    }
  }
  function deselect() {
    const previous = selected;
    setLocalSelected(null);
    setAdjacent(false);
    onDeselect?.();
    requestAnimationFrame(() => {
      svg.current
        ?.querySelector<SVGGElement>(`[data-node-id="${CSS.escape(previous ?? "")}"]`)
        ?.focus();
    });
  }
  function reset() {
    setTypes(relationTypes);
    setMastery("all");
    setAdjacent(false);
    setQuery("");
    setNotice("");
    setCamera(fitCamera(graph.nodes, size.width, size.height));
  }
  function point(clientX: number, clientY: number) {
    const matrix = svg.current?.getScreenCTM();
    return matrix
      ? new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse())
      : new DOMPoint();
  }
  return (
    <section
      className={`knowledge-workspace${full ? " knowledge-workspace--full" : ""}`}
      aria-label="知识图谱探索"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          if (full) setFull(false);
          else if (searchOpen) setSearchOpen(false);
          else deselect();
        }
      }}
    >
      <div className="kg-toolbar">
        <div className="kg-search">
          <Search size={17} />
          <input
            aria-label="搜索知识点"
            value={query}
            placeholder="搜索知识点名称"
            onFocus={() => setSearchOpen(true)}
            onChange={(e) => {
              setQuery(e.target.value);
              setSearchOpen(true);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && found.length) choose(found[0], true);
            }}
          />
          {query && (
            <button
              aria-label="清空知识点搜索"
              onClick={() => {
                setQuery("");
                setSearchOpen(false);
              }}
            >
              <X size={15} />
            </button>
          )}
          {query.trim() && searchOpen && (
            <div className="kg-search-results" aria-label="知识点搜索结果">
              {found.length ? (
                found.map((n) => (
                  <button key={n.id} onClick={() => choose(n, true)}>
                    {n.label}
                    {!visible.nodes.some((v) => v.id === n.id) && (
                      <small>恢复显示并定位</small>
                    )}
                  </button>
                ))
              ) : (
                <p role="status">没有匹配的知识点</p>
              )}
            </div>
          )}
        </div>
        <div className="kg-controls">
          <button
            aria-label="缩小图谱"
            onClick={() =>
              setCamera((c) =>
                zoomAt(c, c.zoom / 1.2, {
                  x: size.width / 2,
                  y: size.height / 2,
                }),
              )
            }
          >
            <Minus size={16} />
          </button>
          <output aria-label="图谱缩放比例">
            {Math.round(camera.zoom * 100)}%
          </output>
          <button
            aria-label="放大图谱"
            onClick={() =>
              setCamera((c) =>
                zoomAt(c, c.zoom * 1.2, {
                  x: size.width / 2,
                  y: size.height / 2,
                }),
              )
            }
          >
            <Plus size={16} />
          </button>
          <button aria-label="适应全图" onClick={reset}>
            <Expand size={16} />
            <span>全图</span>
          </button>
          {node && (
            <button onClick={() => focus(node)}>
              <Focus size={16} />
              聚焦
            </button>
          )}
          {expanded === undefined && (
            <button onClick={() => setFull((v) => !v)}>
              {full ? "退出全屏" : "全屏查看"}
            </button>
          )}
        </div>
      </div>
      <div className="kg-filters" aria-label="图谱筛选">
        {relationTypes
          .filter((t) => graph.edges.some((e) => e.relation === t))
          .map((type) => (
            <label key={type}>
              <input
                type="checkbox"
                checked={types.includes(type)}
                onChange={() =>
                  setTypes((v) =>
                    v.includes(type)
                      ? v.filter((t) => t !== type)
                      : [...v, type],
                  )
                }
              />
              <i style={{ background: edgeColors[type] }} />
              {relations[type]}
            </label>
          ))}
        {hasMastery && (
          <select
            aria-label="掌握状态筛选"
            value={mastery}
            onChange={(e) => setMastery(e.target.value)}
          >
            <option value="all">全部掌握状态</option>
            <option value="weak">需巩固</option>
            <option value="mastered">已掌握</option>
            <option value="unseen">待积累证据</option>
          </select>
        )}
        {node && (
          <button
            aria-pressed={adjacent}
            onClick={() => setAdjacent((v) => !v)}
          >
            {adjacent ? "全部关系" : "当前关联"}
          </button>
        )}
        <span role="status">
          {visible.nodes.length}个知识点 · {visible.edges.length}条关系
        </span>
        {(types.length !== relationTypes.length ||
          mastery !== "all" ||
          adjacent) && <button onClick={reset}>清空筛选</button>}
      </div>
      {notice && (
        <p className="kg-notice" role="status">
          {notice}
        </p>
      )}
      <div className={`kg-content${node ? " kg-content--detail" : ""}`}>
        <div className="kg-canvas" ref={canvas}>
          {!visible.nodes.length && (
            <div className="kg-empty">
              <p>
                {graph.nodes.length ? "当前筛选没有匹配的知识点" : "暂无知识点"}
              </p>
              {graph.nodes.length > 0 && (
                <button onClick={reset}>恢复全图</button>
              )}
            </div>
          )}
          <svg
            ref={svg}
            role="group"
            aria-label={`${graph.title}，知识关系画布`}
            viewBox={`0 0 ${Math.max(1, size.width)} ${Math.max(1, size.height)}`}
            onPointerDown={(e) => {
              if (e.button !== 0) return;
              const p = point(e.clientX, e.clientY);
              drag.current = {
                x: p.x,
                y: p.y,
                camera,
                node:
                  (e.target as Element)
                    .closest("[data-node-id]")
                    ?.getAttribute("data-node-id") ?? null,
                moved: false,
              };
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              const start = drag.current;
              if (!start) return;
              const p = point(e.clientX, e.clientY);
              const dx = p.x - start.x;
              const dy = p.y - start.y;
              if (Math.hypot(dx, dy) > 5) start.moved = true;
              if (start.moved)
                setCamera({
                  ...start.camera,
                  x: start.camera.x + dx,
                  y: start.camera.y + dy,
                });
            }}
            onPointerUp={(e) => {
              const start = drag.current;
              drag.current = null;
              if (e.currentTarget.hasPointerCapture(e.pointerId))
                e.currentTarget.releasePointerCapture(e.pointerId);
              if (start && !start.moved && start.node) {
                const next = allNodes.get(start.node);
                if (next) choose(next);
              }
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
            onLostPointerCapture={() => {
              drag.current = null;
            }}
          >
            <defs>
              <marker
                id={marker}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="7"
                markerHeight="7"
                orient="auto-start-reverse"
              >
                <path d="M0 0 L10 5 L0 10 Z" fill="context-stroke" />
              </marker>
            </defs>
            <g
              transform={`translate(${camera.x} ${camera.y}) scale(${camera.zoom})`}
            >
              {visible.edges.map((edge, index) => {
                const source = allNodes.get(edge.from_node_id)!;
                const target = allNodes.get(edge.to_node_id)!;
                const a = nodeBox(source);
                const b = nodeBox(target);
                const dx = b.x - a.x;
                const dy = b.y - a.y;
                if (dx === 0 && dy === 0) return null;
                const boundary = (width: number, height: number) =>
                  Math.min(
                    Math.abs(dx) ? width / 2 / Math.abs(dx) : Infinity,
                    Math.abs(dy) ? height / 2 / Math.abs(dy) : Infinity,
                  );
                const from = boundary(a.width + 6, a.height + 6);
                const to = boundary(b.width + 12, b.height + 12);
                const x1 = a.x + dx * from;
                const y1 = a.y + dy * from;
                const x2 = b.x - dx * to;
                const y2 = b.y - dy * to;
                const length = Math.hypot(dx, dy);
                const offset = (index % 2 ? 1 : -1) * 14;
                const mx = (x1 + x2) / 2 - (dy / length) * offset;
                const my = (y1 + y2) / 2 + (dx / length) * offset;
                const active =
                  !selected ||
                  edge.from_node_id === selected ||
                  edge.to_node_id === selected;
                return (
                  <g
                    key={edge.id}
                    className={`kg-edge${active ? "" : " kg-dim"}`}
                  >
                    <line
                      x1={x1}
                      y1={y1}
                      x2={x2}
                      y2={y2}
                      stroke={edgeColors[edge.relation]}
                      markerEnd={`url(#${marker})`}
                    />
                    <rect
                      x={mx - 23}
                      y={my - 11}
                      width="46"
                      height="22"
                      rx="8"
                    />
                    <text x={mx} y={my + 4}>
                      {relations[edge.relation]}
                    </text>
                  </g>
                );
              })}
              {visible.nodes.map((n) => {
                const b = nodeBox(n);
                const active = !selected || neighbors.has(n.id);
                return (
                  <g
                    key={n.id}
                    data-node-id={n.id}
                    className={`kg-node kg-node--${n.node_type}${selected === n.id ? " kg-node--selected" : ""}${active ? "" : " kg-dim"}`}
                    transform={`translate(${b.x} ${b.y})`}
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected === n.id}
                    aria-label={n.label + "，查看知识内容"}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        choose(n);
                      }
                    }}
                  >
                    <title>{n.label}</title>
                    <rect
                      x={-b.width / 2}
                      y={-b.height / 2}
                      width={b.width}
                      height={b.height}
                      rx="15"
                    />
                    <text>
                      {b.lines.map((line, i) => (
                        <tspan key={i} x="0" y={-b.height / 2 + 25 + i * 21}>
                          {line}
                        </tspan>
                      ))}
                    </text>
                    {n.mastery != null && (
                      <text className="kg-mastery" y={b.height / 2 - 12}>
                        {n.mastery_state === "unseen"
                          ? "待积累证据"
                          : `掌握度 ${Math.round(n.mastery)}%`}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          </svg>
        </div>
        {node && (
          <aside className="kg-detail" aria-label="知识详情">
            <header>
              <span>
                {node.node_type === "foundation"
                  ? "基础知识"
                  : node.node_type === "core"
                    ? "核心知识"
                    : "应用知识"}
              </span>
              <button aria-label="关闭知识卡片" onClick={deselect}>
                <X size={16} />
              </button>
            </header>
            <h3>{node.label}</h3>
            {node.mastery != null && (
              <p className="kg-state">
                {node.mastery_state === "unseen"
                  ? "待积累证据"
                  : `当前掌握度 ${Math.round(node.mastery)}%`}
              </p>
            )}
            <p>{node.definition || "暂无定义"}</p>
            <h4>学习要点</h4>
            <p>{node.key_point || "暂无学习要点"}</p>
            <h4>常见误区</h4>
            <p>{node.misconception || "暂无误区说明"}</p>
            <h4>
              关联知识 <small>{links.length}</small>
            </h4>
            <ul>
              {links.map((e) => {
                const other = allNodes.get(
                  e.from_node_id === node.id ? e.to_node_id : e.from_node_id,
                )!;
                return (
                  <li key={e.id}>
                    <button
                      onClick={() => {
                        choose(other);
                      }}
                    >
                      <small>{relationFrom(e, node.id)}</small>
                      <span>{other.label}</span>
                      <span aria-hidden="true">→</span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {!links.length && <p>暂无已发布关联</p>}
            <footer>
              {onPractice && (
                <button onClick={() => onPractice(node)}>进入智适练习</button>
              )}
              {onTutor && (
                <button onClick={() => onTutor(node)}>进入智伴辅导</button>
              )}
              {onEditNode && (
                <button
                  onClick={() => {
                    setFull(false);
                    onEditNode(node);
                  }}
                >
                  编辑所选知识点
                </button>
              )}
              <button
                onClick={() => {
                  deselect();
                  reset();
                }}
              >
                返回全图
              </button>
            </footer>
          </aside>
        )}
      </div>
    </section>
  );
}
