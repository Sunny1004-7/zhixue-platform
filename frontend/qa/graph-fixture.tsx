import React from "react";
import { createRoot } from "react-dom/client";
import KnowledgeGraphView from "../src/components/KnowledgeGraphView";
import type { KnowledgeGraph } from "../src/types";

/** Mount a graph component for isolated interaction tests. */
export function mountGraphFixture(graph: KnowledgeGraph) {
  const application = document.getElementById("root");
  if (application) application.style.display = "none";
  const element = document.createElement("main");
  element.className = "app-shell";
  element.style.cssText = "display:block;padding:24px";
  document.body.append(element);
  const root = createRoot(element);
  const events: string[] = [];
  const actions: string[] = [];
  function render(next: KnowledgeGraph) {
    root.render(
      <KnowledgeGraphView
        graph={next}
        onNodeClick={(node) => events.push(node.id)}
        onPractice={(node) => actions.push(node.concept_id)}
      />,
    );
  }
  render(graph);
  return { render, events, actions, unmount: () => root.unmount() };
}
