import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { X } from "lucide-react";
type Request = {
  title: string;
  message: string;
  initial?: string;
  danger?: boolean;
  resolve: (value: string | null) => void;
};
type Dialogs = {
  confirm: (
    title: string,
    message: string,
    danger?: boolean,
  ) => Promise<boolean>;
  prompt: (
    title: string,
    initial: string,
    message?: string,
  ) => Promise<string | null>;
  canLeave: () => Promise<boolean>;
};
const dirtyEditors = new Set<string>();
export function useUnsavedChanges(dirty: boolean) {
  const key = useId();
  useEffect(() => {
    if (dirty) dirtyEditors.add(key);
    else dirtyEditors.delete(key);
    return () => {
      dirtyEditors.delete(key);
    };
  }, [dirty, key]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (dirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}
const Context = createContext<Dialogs | null>(null);
const focusable =
  'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]';

/** Covers the retained domain dialogs as well as the shared confirmation dialog. */
function DialogLifecycle() {
  useEffect(() => {
    const states = new Map<
      HTMLElement,
      { previous: HTMLElement | null; dirty: boolean; busy: boolean }
    >();
    const scan = () => {
      for (const el of document.querySelectorAll<HTMLElement>(
        '[role="dialog"]',
      ))
        if (!states.has(el)) {
          states.set(el, {
            previous: document.activeElement as HTMLElement,
            dirty: false,
            busy: false,
          });
          el.tabIndex = -1;
          requestAnimationFrame(() =>
            (
              el.querySelector<HTMLElement>(
                "[autofocus], input, textarea, button",
              ) ?? el
            ).focus(),
          );
        }
      for (const [el, state] of states)
        if (!el.isConnected || !el.matches('[role="dialog"]')) {
          states.delete(el);
          if (state.previous?.isConnected) state.previous.focus();
        }
      document.body.classList.toggle("has-dialog", states.size > 0);
    };
    const observer = new MutationObserver(scan);
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["role"],
    });
    scan();
    const input = (event: Event) => {
      const dialog = (event.target as HTMLElement).closest<HTMLElement>(
        '[role="dialog"]',
      );
      if (dialog && states.has(dialog)) states.get(dialog)!.dirty = true;
    };
    const key = (event: KeyboardEvent) => {
      const el = [...states.keys()][states.size - 1];
      if (!el) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        el.querySelector<HTMLButtonElement>(
          'button[aria-label^="关闭"],button[title="关闭"]',
        )?.click();
      }
      if (event.key === "Tab") {
        const items = [...el.querySelectorAll<HTMLElement>(focusable)].filter(
          (x) => x.getClientRects().length > 0,
        );
        const first = items[0],
          last = items[items.length - 1];
        if (!first) {
          event.preventDefault();
          el.focus();
        } else if (
          event.shiftKey &&
          (document.activeElement === first || document.activeElement === el)
        ) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("input", input);
    document.addEventListener("change", input);
    document.addEventListener("keydown", key, true);
    return () => {
      observer.disconnect();
      document.body.classList.remove("has-dialog");
      document.removeEventListener("input", input);
      document.removeEventListener("change", input);
      document.removeEventListener("keydown", key, true);
    };
  }, []);
  return null;
}
export function Modal({
  title,
  children,
  onClose,
  className = "",
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
}) {
  return (
    <div
      className="dialog-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className={`common-dialog ${className}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button aria-label="关闭" onClick={onClose}>
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function DialogProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<Request | null>(null);
  const [value, setValue] = useState("");
  const pending = useRef(false);
  const ask = (
    title: string,
    message: string,
    initial?: string,
    danger?: boolean,
  ) =>
    new Promise<string | null>((resolve) => {
      if (pending.current) {
        resolve(null);
        return;
      }
      pending.current = true;
      setValue(initial ?? "");
      setRequest({ title, message, initial, danger, resolve });
    });
  const finish = (answer: string | null) => {
    request?.resolve(answer);
    pending.current = false;
    setRequest(null);
  };
  return (
    <Context.Provider
      value={{
        confirm: async (title, message, danger) =>
          (await ask(title, message, undefined, danger)) !== null,
        prompt: (title, initial, message = "") => ask(title, message, initial),
        canLeave: async () =>
          !dirtyEditors.size ||
          (await ask(
            "离开前确认",
            "当前还有未保存的修改。确认放弃这些修改并离开？",
            undefined,
            true,
          )) !== null,
      }}
    >
      {children}
      <DialogLifecycle />
      {request && (
        <Modal title={request.title} onClose={() => finish(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              finish(request.initial === undefined ? "yes" : value.trim());
            }}
          >
            <p>{request.message}</p>
            {request.initial !== undefined && (
              <label>
                内容
                <input
                  autoFocus
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  required
                  maxLength={2000}
                />
              </label>
            )}
            <footer>
              <button type="button" onClick={() => finish(null)}>
                保留并返回
              </button>
              <button
                className={request.danger ? "danger" : "primary"}
                disabled={request.initial !== undefined && !value.trim()}
              >
                确认
              </button>
            </footer>
          </form>
        </Modal>
      )}
    </Context.Provider>
  );
}
export function useDialogs() {
  const value = useContext(Context);
  if (!value) throw new Error("Missing dialogs provider");
  return value;
}
