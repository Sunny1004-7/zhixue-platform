import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Send } from "lucide-react";
import { useApi } from "../RuntimeContext";
import { ApiError } from "../errors";
import { Modal } from "./Dialogs";
import { LoadingState } from "./Primitives";
import type { AudienceDraft, StudentAttention } from "../types";
export type PublishResource = {
  id: string;
  type: "graph" | "question_set" | "video";
  version: number;
  title: string;
  concepts: Array<{ id: string; label: string }>;
};
export default function AudienceDialog({
  courseId,
  resource,
  onClose,
  onPublished,
}: {
  courseId: string;
  resource: PublishResource;
  onClose: () => void;
  onPublished: (message: string) => void;
}) {
  const api = useApi();
  const [mode, setMode] = useState<"class" | "concept_directed" | "single">(
    "class",
  );
  const [concepts, setConcepts] = useState(resource.concepts.map((x) => x.id));
  const [states, setStates] = useState<string[]>(["weak"]);
  const [students, setStudents] = useState<StudentAttention[] | null>(null);
  const [student, setStudent] = useState("");
  const [draft, setDraft] = useState<AudienceDraft | null>(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(crypto.randomUUID());
  const lock = useRef(false);
  useEffect(() => {
    let live = true;
    api
      .courseStudents(courseId, "name")
      .then((v) => {
        if (live) {
          setStudents(v.items);
          setStudent(v.items[0]?.student_id ?? "");
        }
      })
      .catch(() => {
        if (live) setError("无法读取班级学生，请重新打开后重试。");
      });
    return () => {
      live = false;
    };
  }, [api, courseId]);
  const invalidate = () => {
    setDraft(null);
    setError("");
    setAcknowledge(false);
    key.current = crypto.randomUUID();
  };
  const preview = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      setDraft(
        await api.previewAudience(courseId, resource.id, {
          resource_type: resource.type,
          resource_id: resource.id,
          resource_version: resource.version,
          audience_mode: mode,
          selected_concept_ids: mode === "concept_directed" ? concepts : [],
          selected_states: mode === "concept_directed" ? states : [],
          teacher_selected_student_ids: [],
          locked_student_id: mode === "single" ? student : null,
        }),
      );
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "接收者预览失败，选择内容已保留。",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  const publish = async () => {
    if (!draft || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.publishAudience(
        draft.id,
        draft.version,
        acknowledge,
        key.current,
      );
      onPublished(
        `《${resource.title}》已发布给 ${result.recipient_count} 名学生。`,
      );
      onClose();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "暂时无法确认发布结果，请恢复网络后重新核对。",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return (
    <Modal
      title="选择接收者并发布"
      onClose={() => {
        if (!busy) onClose();
      }}
      className="audience-dialog"
    >
      <div className="audience-body">
        <p>
          <b>{resource.title}</b>
          <span className="muted"> · 发布版本 {resource.version}</span>
        </p>
        <fieldset disabled={busy}>
          <legend>发布范围</legend>
          <div className="choice-group">
            {(
              [
                ["class", "全班学生"],
                ["concept_directed", "按知识状态"],
                ["single", "指定学生"],
              ] as const
            ).map(([v, label]) => (
              <label key={v}>
                <input
                  type="radio"
                  name="audience"
                  checked={mode === v}
                  onChange={() => {
                    invalidate();
                    setMode(v);
                  }}
                />
                {label}
              </label>
            ))}
          </div>
          {mode === "concept_directed" && (
            <>
              <h3>相关知识点</h3>
              <div className="choice-group">
                {resource.concepts.map((c) => (
                  <label key={c.id}>
                    <input
                      type="checkbox"
                      checked={concepts.includes(c.id)}
                      onChange={() => {
                        invalidate();
                        setConcepts((v) =>
                          v.includes(c.id)
                            ? v.filter((x) => x !== c.id)
                            : [...v, c.id],
                        );
                      }}
                    />
                    {c.label}
                  </label>
                ))}
              </div>
              <h3>学习状态</h3>
              <div className="choice-group">
                {[
                  ["weak", "需要巩固"],
                  ["mastered", "已掌握"],
                  ["unseen", "尚未学习 / 证据不足"],
                ].map(([v, label]) => (
                  <label key={v}>
                    <input
                      type="checkbox"
                      checked={states.includes(v)}
                      onChange={() => {
                        invalidate();
                        setStates((s) =>
                          s.includes(v) ? s.filter((x) => x !== v) : [...s, v],
                        );
                      }}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </>
          )}
          {mode === "single" && (
            <label>
              接收学生
              <select
                aria-label="接收学生"
                value={student}
                onChange={(e) => {
                  invalidate();
                  setStudent(e.target.value);
                }}
              >
                {students?.map((x) => (
                  <option key={x.student_id} value={x.student_id}>
                    {x.student_name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </fieldset>
        {!students && !error && <LoadingState label="正在读取班级学生…" />}
        {draft && (
          <section className="audience-preview">
            <h3>
              <CheckCircle2 size={17} />
              接收者预览 · {draft.final_student_ids.length} 人
            </h3>
            <div className="recipient-list">
              {draft.candidates
                .filter((x) => x.selected)
                .map((x) => (
                  <span key={x.student_id}>{x.student_name}</span>
                ))}
            </div>
            {!draft.final_student_ids.length && (
              <p>没有符合当前选择的学生，请调整发布范围。</p>
            )}
            {draft.warnings_require_confirmation && (
              <label className="warning-confirm">
                <input
                  type="checkbox"
                  checked={acknowledge}
                  onChange={(e) => setAcknowledge(e.target.checked)}
                />
                已核对重复推荐或发布频次提示，确认仍需发送。
              </label>
            )}
          </section>
        )}
        {busy && <p role="status">正在处理，请稍候…</p>}
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <footer>
        <button disabled={busy} onClick={onClose}>
          返回
        </button>
        {!draft ? (
          <button
            className="primary"
            disabled={
              busy ||
              !students ||
              (mode === "single" && !student) ||
              (mode === "concept_directed" &&
                (!concepts.length || !states.length))
            }
            onClick={() => void preview()}
          >
            预览接收者
          </button>
        ) : (
          <button
            className="primary"
            disabled={
              busy ||
              !draft.final_student_ids.length ||
              (draft.warnings_require_confirmation && !acknowledge)
            }
            onClick={() => void publish()}
          >
            <Send size={16} />
            确认发布
          </button>
        )}
      </footer>
    </Modal>
  );
}
