import { Children, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

/** Task views retain their local editor state while only one occupies the workspace. */
export function WorkspaceViews({ labels, children, selected, onSelect }: { labels: string[]; children: ReactNode; selected?: number; onSelect?: (index: number) => void }) {
  const [active, setActive] = useState(0);
  const current = selected ?? active;
  const panels = Children.toArray(children).filter(child => typeof child !== "string" || child.trim().length > 0);
  return <div className="work-views">
    <div className="work-view-tabs" role="tablist" aria-label="工作视图">
      {labels.map((label, i) => <button key={label} role="tab" aria-selected={current === i} onClick={() => { setActive(i); onSelect?.(i); }}>{label}</button>)}
    </div>
    {panels.map((child, i) => <div key={labels[i]} className="work-view-panel" role="tabpanel" hidden={i !== current}>{child}</div>)}
  </div>;
}

/** Pagination uses the actual reading area and measured row height, including wrapped titles. */
export function PagedList({ children, className = "", label = "列表", resetKey = "" }: {
  children: ReactNode; className?: string; label?: string; resetKey?: string;
}) {
  const items = Children.toArray(children);
  const [size, setSize] = useState(1);
  const [page, setPage] = useState(0);
  const area = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const measured = useRef(0);
  const count = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(page, count - 1);
  useEffect(() => { setPage(0); measured.current = 0; }, [resetKey]);
  useLayoutEffect(() => {
    const root = area.current, rows = list.current;
    if (!root || !rows) return;
    const measure = () => {
      if (!root.clientHeight || !root.getClientRects().length) return;
      const heights = [...rows.children].map(x => x.getBoundingClientRect().height).filter(Boolean);
      if (!heights.length) return;
      measured.current = Math.max(measured.current, ...heights);
      const gap = parseFloat(getComputedStyle(rows).rowGap) || 0;
      const next = Math.max(1, Math.floor((root.clientHeight + gap) / (measured.current + gap)));
      setSize(old => { if (old !== next) setPage(p => Math.floor(p * old / next)); return next; });
    };
    const observer = new ResizeObserver(measure);
    observer.observe(root); observer.observe(rows);
    measure();
    return () => observer.disconnect();
  }, [items.length, current, size, resetKey]);
  useEffect(() => { if (page >= count) setPage(count - 1); }, [page, count]);
  return <div className="paged-region" data-list={label}>
    <div className="paged-area" ref={area}><div className={className + " paged-items"} ref={list}>{items.slice(current * size, (current + 1) * size)}</div></div>
    <nav className="pagination" aria-label={label + "分页"}>
      <span>共 {items.length} 项 · {items.length ? current * size + 1 : 0}–{Math.min(items.length, (current + 1) * size)}</span>
      <button aria-label={label + "上一页"} disabled={!current} onClick={() => setPage(current - 1)}>上一页</button>
      <output>{current + 1} / {count}</output>
      <button aria-label={label + "下一页"} disabled={current >= count - 1} onClick={() => setPage(current + 1)}>下一页</button>
      <button aria-label={label + "末页"} disabled={current >= count - 1} onClick={() => setPage(count - 1)}>末页</button>
    </nav>
  </div>;
}
