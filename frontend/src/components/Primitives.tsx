import { AlertCircle, LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";
import { clamp, finite, percent } from "../format";
export function Surface({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={"surface " + className}>{children}</section>;
}
export function LoadingState({
  label = "正在读取课程内容…",
}: {
  label?: string;
}) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={24} />
      <span>{label}</span>
    </div>
  );
}
export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <AlertCircle size={28} />
      <h2>暂时无法完成操作</h2>
      <p>{message || "请检查网络后重试。"}</p>
      {retry && <button onClick={retry}>重新加载</button>}
    </div>
  );
}
export function ProgressRing({
  value,
  label,
  color = "var(--accent)",
  size = 110,
}: {
  value: number | null;
  label: string;
  color?: string;
  size?: number;
}) {
  return (
    <div
      className="progress-ring"
      style={{
        width: size,
        height: size,
        background:
          "conic-gradient(" +
          color +
          " " +
          clamp(value) * 3.6 +
          "deg, #e6edf3 0deg)",
      }}
    >
      <div>
        <b>{percent(value)}</b>
        <span>{label}</span>
      </div>
    </div>
  );
}
export function Sparkline({
  values,
  color = "var(--accent)",
}: {
  values: number[];
  color?: string;
}) {
  const valid = values.filter(finite);
  if (!valid.length) return <span className="chart-empty">暂无趋势</span>;
  const min = Math.min(...valid),
    max = Math.max(...valid);
  const points = valid
    .map(
      (v, i) =>
        (valid.length === 1 ? 60 : (i / (valid.length - 1)) * 120) +
        "," +
        (38 - ((v - min) / Math.max(1, max - min)) * 29),
    )
    .join(" ");
  return (
    <svg
      className="sparkline"
      viewBox="0 0 120 44"
      role="img"
      aria-label="已有记录变化趋势"
    >
      <polyline points={points} fill="none" stroke={color} strokeWidth="2.5" />
    </svg>
  );
}
export function EmptyState({
  title = "暂无内容",
  detail,
  action,
}: {
  title?: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-result">
      <BookGlyph />
      <h3>{title}</h3>
      {detail && <p>{detail}</p>}
      {action}
    </div>
  );
}
function BookGlyph() {
  return (
    <svg
      width="30"
      height="30"
      viewBox="0 0 30 30"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M5 6H13L15 8L17 6H25V24H17L15 26L13 24H5Z"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}
export function Metric({
  label,
  value,
  note,
}: {
  label: string;
  value: ReactNode;
  note?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {note && <small>{note}</small>}
    </div>
  );
}
export function WeekChart({ values }: { values: number[] }) {
  const safe = Array.from({ length: 7 }, (_, i) =>
    finite(values[i]) ? Math.max(0, values[i]) : 0,
  );
  const max = Math.max(0, ...safe);
  return (
    <div
      className="week-chart"
      role="img"
      aria-label={"本周每日学习分钟：" + safe.join("、")}
    >
      <div>
        {safe.map((v, i) => (
          <div key={i}>
            <span>{v}</span>
            <i style={{ height: (max ? (v / max) * 100 : 0) + "%" }} />
            <small>{["一", "二", "三", "四", "五", "六", "日"][i]}</small>
          </div>
        ))}
      </div>
      {max === 0 && <p>本周还没有学习时长记录</p>}
    </div>
  );
}
