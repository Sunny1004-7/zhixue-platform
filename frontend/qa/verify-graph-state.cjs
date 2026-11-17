const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const file = path.join(__dirname, "../src/components/graph-view-state.ts");
const compiled = ts.transpileModule(fs.readFileSync(file, "utf8"), {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const exportsObject = {};
vm.runInNewContext(compiled, { exports: exportsObject });
const { zoomAt, fitCamera, nodeBox, filterGraph, relationFrom, relationTypes } =
  exportsObject;

test("large-course packing separates node boxes and preserves every source value", () => {
  const course = {nodes: Array.from({length: 30}, (_, i) => ({id: String(i), label: "课程知识点" + i, position_x: 0, position_y: 0, mastery: i})), edges: [{id:"e",from_node_id:"0",to_node_id:"1",relation:"prerequisite"}]};
  const before = JSON.stringify(course);
  const view = exportsObject.layoutNetwork(course);
  const boxes = view.nodes.map(nodeBox);
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a=boxes[i],b=boxes[j];
    assert(Math.abs(a.x-b.x) >= (a.width+b.width)/2 || Math.abs(a.y-b.y) >= (a.height+b.height)/2);
  }
  assert.equal(JSON.stringify(course), before);
  assert.deepEqual(view.edges, course.edges);
  assert.deepEqual(view.nodes.map(n=>n.mastery), course.nodes.map(n=>n.mastery));
});
const nodes = [
  {
    id: "a",
    label: "概率基础",
    position_x: 50,
    position_y: 80,
    mastery: 80,
    mastery_state: "mastered",
  },
  {
    id: "b",
    label: "包含长中文名称的知识节点用于换行检查",
    position_x: 350,
    position_y: 250,
    mastery: 40,
    mastery_state: "weak",
  },
  {
    id: "c",
    label: "独立知识点",
    position_x: 650,
    position_y: 80,
    mastery: null,
    mastery_state: null,
  },
];
const edges = [
  { id: "ab", from_node_id: "a", to_node_id: "b", relation: "prerequisite" },
  { id: "bc", from_node_id: "b", to_node_id: "c", relation: "application" },
  {
    id: "missing",
    from_node_id: "a",
    to_node_id: "absent",
    relation: "contains",
  },
];
const graph = { nodes, edges };
test("zoom preserves the world point underneath a non-central anchor", () => {
  const before = { x: 40, y: -25, zoom: 0.7 };
  const anchor = { x: 220, y: 160 };
  const after = zoomAt(before, 1.8, anchor);
  assert(
    Math.abs(
      (anchor.x - before.x) / before.zoom - (anchor.x - after.x) / after.zoom,
    ) < 1e-9,
  );
  assert(
    Math.abs(
      (anchor.y - before.y) / before.zoom - (anchor.y - after.y) / after.zoom,
    ) < 1e-9,
  );
});
test("fit includes long labels and mastery within all four viewport bounds", () => {
  for (const [width, height] of [
    [1600, 800],
    [600, 350],
    [320, 300],
  ]) {
    const camera = fitCamera(nodes, width, height);
    for (const n of nodes) {
      const b = nodeBox(n);
      assert((b.x - b.width / 2) * camera.zoom + camera.x >= 0);
      assert((b.x + b.width / 2) * camera.zoom + camera.x <= width);
      assert((b.y - b.height / 2) * camera.zoom + camera.y >= 0);
      assert((b.y + b.height / 2) * camera.zoom + camera.y <= height);
    }
  }
  assert.equal(nodeBox(nodes[1]).lines.join(""), nodes[1].label);
});
test("relationship filter keeps only existing endpoints and never mutates input", () => {
  const snapshot = JSON.stringify(graph);
  const result = filterGraph(graph, ["prerequisite"], "all", null, false);
  assert.equal(result.nodes.map((n) => n.id).join(","), "a,b");
  assert.equal(result.edges.length, 1);
  assert.equal(JSON.stringify(graph), snapshot);
});
test("mastery filters cannot leave dangling edges", () => {
  const result = filterGraph(graph, relationTypes, "weak", null, false);
  assert.equal(result.nodes.length, 1);
  assert.equal(result.edges.length, 0);
});
test("neighbors include incoming and outgoing relationships", () => {
  const result = filterGraph(graph, relationTypes, "all", "b", true);
  assert.equal(result.nodes.length, 3);
  assert.equal(result.edges.length, 2);
  assert.equal(relationFrom(edges[0], "b"), "前置知识");
  assert.equal(relationFrom(edges[0], "a"), "后续知识");
  assert.equal(relationFrom(edges[1], "b"), "应用到");
  assert.equal(relationFrom(edges[1], "c"), "应用来源");
});
test("empty graph and zero relationship selection return valid states", () => {
  assert(Number.isFinite(fitCamera([], 320, 200).zoom));
  assert.equal(filterGraph(graph, [], "all", null, false).nodes.length, 0);
});
test("single-node fit is centered without changing course coordinates", () => {
  const before = JSON.stringify(nodes[0]);
  const box = nodeBox(nodes[0]);
  const c = fitCamera([nodes[0]], 800, 400);
  assert.equal(box.x * c.zoom + c.x, 400);
  assert.equal(box.y * c.zoom + c.y, 200);
  assert.equal(JSON.stringify(nodes[0]), before);
});
