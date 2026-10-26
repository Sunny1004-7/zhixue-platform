import { ReactNode } from 'react';

export function LoadingState({ label = '正在读取学习状态…' }: { label?: string }) {
  return <div className="loading-state"><span /><b>{label}</b></div>;
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="error-state"><b>暂时无法读取数据</b><p>{message}</p>{retry && <button onClick={retry}>重新加载</button>}</div>;
}

export function Surface({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`surface ${className}`}>{children}</section>;
}

export function ProgressRing({ value, label, color = '#6268f6', size = 110 }: { value: number; label: string; color?: string; size?: number }) {
  return (
    <div className="progress-ring" style={{ width: size, height: size, background: `conic-gradient(${color} ${value * 3.6}deg, #e9ebf3 0deg)` }}>
      <div><b>{Math.round(value)}%</b><span>{label}</span></div>
    </div>
  );
}

export function Sparkline({ values, color = '#6268f6' }: { values: number[]; color?: string }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const points = values.map((value, index) => {
    const x = values.length === 1 ? 60 : (index / (values.length - 1)) * 120;
    const y = 40 - ((value - min) / Math.max(1, max - min)) * 31;
    return `${x},${y}`;
  }).join(' ');
  return <svg className="sparkline" viewBox="0 0 120 44" aria-label="近七次变化趋势"><polyline points={points} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
