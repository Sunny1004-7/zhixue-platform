import type { GraphEdge, GraphNode, KnowledgeGraph } from "../types";

export type Camera = { x: number; y: number; zoom: number };
export type Point = { x: number; y: number };
export const relations = {
  prerequisite: "先修",
  contains: "包含",
  application: "应用",
  contrast: "对照",
};
export type Relation = keyof typeof relations;
export const relationTypes = Object.keys(relations) as Relation[];

export function zoomAt(camera: Camera, next: number, anchor: Point): Camera {
  const zoom = Math.max(0.08, Math.min(3, next));
  return {
    zoom,
    x: anchor.x - ((anchor.x - camera.x) * zoom) / camera.zoom,
    y: anchor.y - ((anchor.y - camera.y) * zoom) / camera.zoom,
  };
}

export function nodeBox(node: GraphNode) {
  const lines = Array.from(node.label)
    .join("")
    .match(/.{1,8}/gu) ?? ["未命名知识点"];
  return {
    x: node.position_x * 1.6,
    y: node.position_y * 1.6,
    width: 156,
    height: Math.max(64, lines.length * 21 + (node.mastery == null ? 20 : 39)),
    lines,
  };
}

export function fitCamera(
  nodes: GraphNode[],
  width: number,
  height: number,
): Camera {
  if (!nodes.length) return { x: width / 2, y: height / 2, zoom: 1 };
  const boxes = nodes.map(nodeBox);
  const left = Math.min(...boxes.map((b) => b.x - b.width / 2));
  const right = Math.max(...boxes.map((b) => b.x + b.width / 2));
  const top = Math.min(...boxes.map((b) => b.y - b.height / 2));
  const bottom = Math.max(...boxes.map((b) => b.y + b.height / 2));
  const zoom = Math.min(
    1.15,
    Math.max(1, width - 64) / Math.max(1, right - left),
    Math.max(1, height - 64) / Math.max(1, bottom - top),
  );
  return {
    zoom,
    x: width / 2 - ((left + right) / 2) * zoom,
    y: height / 2 - ((top + bottom) / 2) * zoom,
  };
}

export function filterGraph(
  graph: KnowledgeGraph,
  types: Relation[],
  mastery: string,
  selected: string | null,
  adjacent: boolean,
) {
  let nodes = graph.nodes.filter(
    (n) => mastery === "all" || n.mastery_state === mastery,
  );
  const ids = new Set(nodes.map((n) => n.id));
  const edges = graph.edges.filter(
    (e) =>
      types.includes(e.relation) &&
      ids.has(e.from_node_id) &&
      ids.has(e.to_node_id),
  );
  if (types.length !== relationTypes.length) {
    const endpoints = new Set(
      edges.flatMap((e) => [e.from_node_id, e.to_node_id]),
    );
    nodes = nodes.filter((n) => endpoints.has(n.id));
  }
  if (adjacent && selected) {
    const neighbors = new Set([selected]);
    edges.forEach((e) => {
      if (e.from_node_id === selected || e.to_node_id === selected) {
        neighbors.add(e.from_node_id);
        neighbors.add(e.to_node_id);
      }
    });
    nodes = nodes.filter((n) => neighbors.has(n.id));
  }
  const visible = new Set(nodes.map((n) => n.id));
  return {
    nodes,
    edges: edges.filter(
      (e) => visible.has(e.from_node_id) && visible.has(e.to_node_id),
    ),
  };
}

export function relationFrom(edge: GraphEdge, id: string): string {
  if (edge.relation === "prerequisite")
    return edge.from_node_id === id ? "后续知识" : "前置知识";
  if (edge.relation === "contains")
    return edge.from_node_id === id ? "包含" : "所属知识";
  if (edge.relation === "application")
    return edge.from_node_id === id ? "应用到" : "应用来源";
  return "对照知识";
}
