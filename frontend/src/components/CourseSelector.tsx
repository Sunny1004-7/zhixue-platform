import { BookOpenCheck, Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Course } from "../types";
import { useDialogs } from "./Dialogs";

export default function CourseSelector({ courses, value, onChange, student }: {
  courses: Course[]; value: string; onChange: (id: string) => void; student: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null);
  const navigate = useNavigate(), dialogs = useDialogs();
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => { if (!root.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", outside);
    root.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus();
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  return <div className="course-switcher" ref={root} onKeyDown={e => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); if (!open) { setOpen(true); return; }
      const choices = [...root.current!.querySelectorAll<HTMLElement>('[role="option"]')];
      const index = choices.indexOf(document.activeElement as HTMLElement);
      choices[(index + (e.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length]?.focus();
    }
  }}>
    <button ref={trigger} className="course-switch-trigger" aria-label="切换课程" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}><BookOpenCheck size={19}/><span>{courses.find(c => c.id === value)?.title ?? "选择课程"}</span><ChevronDown size={16}/></button>
    {open && <div className="course-switch-panel"><div role="listbox" aria-label="课程">
      {courses.map(c => <button key={c.id} role="option" aria-selected={c.id === value} onClick={async () => {
        if (c.id !== value && !(await dialogs.canLeave())) return;
        onChange(c.id); close();
      }}><span><b>{c.title}</b><small>{c.code} · {c.term}</small></span>{c.id === value && <Check size={17}/>}</button>)}
    </div>{student && <button className="course-catalog-link" onClick={async () => { if (await dialogs.canLeave()) { close(); navigate("/student/courses"); } }}>课程总览与学习汇总</button>}</div>}
  </div>;
}
