import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  Eye,
  EyeOff,
  GraduationCap,
  KeyRound,
  Layers3,
  LoaderCircle,
  MessageSquareText,
  Network,
  NotebookPen,
  UserRound,
} from "lucide-react";
import "./LoginView.css";

export type LoginRole = "student" | "teacher";
export type LoginCredentials = {
  account: string;
  password: string;
  role: LoginRole;
};
type LoginViewProps = {
  onLogin: (credentials: LoginCredentials) => Promise<void>;
  restoringSession?: boolean;
};

const roleContent = {
  student: {
    label: "学生",
    title: ["看见知识的联系，", "找到学习的方向。"],
    description:
      "从课程知识图谱出发，用练习检验理解，在辅导中厘清思路。每次学习的反馈，都为下一步提供依据。",
    entry: "继续你的课程学习",
    tools: ["课程知识图谱", "个性化练习", "多策略辅导"],
    action: "进入学生空间",
    support: "练习与辅导",
    Icon: GraduationCap,
  },
  teacher: {
    label: "教师",
    title: ["看清学习的进展，", "安排合适的教学。"],
    description:
      "连接课程材料、知识结构与学生学情，组织有针对性的习题、视频和教学支持，由你审核并发布。",
    entry: "开始你的课程教学",
    tools: ["班级与个人学情", "课程知识图谱", "教学资源发布"],
    action: "进入教师空间",
    support: "资源与辅导",
    Icon: NotebookPen,
  },
};

function BrandGlyph() {
  return (
    <svg viewBox="0 0 48 48" fill="none" aria-hidden="true">
      <path
        d="M7 10h12c5 0 8 3 8 8v23c-3-4-7-6-12-6H7V10Z"
        fill="currentColor"
        opacity=".2"
      />
      <path
        d="M7 10h9c5 0 8 3 8 8v21c-3-3-6-4-11-4H7V10Zm34 0h-9c-5 0-8 3-8 8v21c3-3 6-4 11-4h6V10Z"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path
        d="m32 20 6 5-6 5"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="15" cy="22" r="3" fill="currentColor" />
    </svg>
  );
}

function KnowledgeScene({ role }: { role: LoginRole }) {
  return (
    <figure className="zx-knowledge">
      <figcaption>
        <Network size={17} aria-hidden="true" />
        <span>课程学习的脉络</span>
        <i />
      </figcaption>
      <div className="zx-network">
        <svg
          className="zx-connections"
          viewBox="0 0 800 340"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <path d="M178 156C240 156 220 78 310 78M490 78C555 78 530 156 600 156M600 175C545 175 550 275 490 275M310 275C225 275 245 175 178 175" />
          <path className="zx-connection-center" d="M402 118V235" />
          <circle cx="230" cy="127" r="5" />
          <circle cx="552" cy="127" r="5" />
          <circle cx="402" cy="176" r="5" />
        </svg>
        <div className="zx-node zx-node--course">
          <BookOpen size={27} aria-hidden="true" />
          <b>课程知识</b>
          <span>建立知识的联系</span>
        </div>
        <div className="zx-node zx-node--concept">
          <span className="zx-node-icon">
            <Layers3 size={20} aria-hidden="true" />
          </span>
          <div>
            <b>理解关联</b>
            <span>沿着先修关系学习</span>
          </div>
        </div>
        <div className="zx-node zx-node--practice">
          <MessageSquareText size={24} aria-hidden="true" />
          <b>{roleContent[role].support}</b>
          <span>围绕当前学习需要</span>
        </div>
        <div className="zx-node zx-node--feedback">
          <span className="zx-node-icon">
            <Check size={20} aria-hidden="true" />
          </span>
          <div>
            <b>学习反馈</b>
            <span>更新知识掌握情况</span>
          </div>
        </div>
        <span className="zx-network-label">知识结构与学习过程相连接</span>
      </div>
      <div className="zx-capabilities" aria-label="主要功能">
        {roleContent[role].tools.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
    </figure>
  );
}

/** Shared presentation. Authentication and navigation belong to each app's adapter. */
export default function LoginView({
  onLogin,
  restoringSession = false,
}: LoginViewProps) {
  const [role, setRole] = useState<LoginRole>("student");
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<{
    account?: string;
    password?: string;
    form?: string;
  }>({});
  const accountRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const formErrorRef = useRef<HTMLDivElement>(null);
  const inFlight = useRef(false);
  const id = useId();
  const active = roleContent[role];
  const busy = submitting || restoringSession;
  useEffect(() => {
    if (errors.form) formErrorRef.current?.focus();
  }, [errors.form]);

  const chooseRole = (next: LoginRole) => {
    setRole(next);
    setErrors({});
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (inFlight.current || restoringSession) return;
    const nextErrors = {
      account: account.trim() ? undefined : "请输入账号",
      password: password.length ? undefined : "请输入密码",
    };
    setErrors(nextErrors);
    if (nextErrors.account || nextErrors.password) {
      (nextErrors.account ? accountRef : passwordRef).current?.focus();
      return;
    }
    inFlight.current = true;
    setSubmitting(true);
    try {
      await onLogin({ account: account.trim(), password, role });
    } catch (reason) {
      setErrors({
        form:
          reason instanceof Error
            ? reason.message
            : "登录暂时不可用，请稍后重试。",
      });
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return (
    <div className={`zx-login zx-login--${role}`}>
      <a
        className="zx-skip"
        href="#zx-login-form"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("zx-login-form")?.focus();
        }}
      >
        跳到登录表单
      </a>
      <div className="zx-wrap">
        <header className="zx-header">
          <div className="zx-brand">
            <span className="zx-brand-glyph">
              <BrandGlyph />
            </span>
            <div>
              <b>知学智教</b>
              <span>大模型驱动的个性化教学平台</span>
            </div>
          </div>
          <span className="zx-header-note">
            <BookOpen size={17} aria-hidden="true" />
            连接课程、学习与教学
          </span>
        </header>
        <main className="zx-content">
          <section className="zx-story" aria-label="平台介绍">
            <div className="zx-story-copy">
              <span className="zx-entry">
                <i />
                {active.entry}
              </span>
              <h1>
                {active.title.map((line) => (
                  <span key={line}>{line}</span>
                ))}
              </h1>
              <p>{active.description}</p>
            </div>
            <KnowledgeScene role={role} />
          </section>
          <section className="zx-auth" aria-labelledby={`${id}-heading`}>
            <div className="zx-form-heading">
              <span>欢迎使用知学智教</span>
              <h2 id={`${id}-heading`}>{active.label}登录</h2>
              <p>选择身份，进入你的课程空间</p>
            </div>
            <form
              id="zx-login-form"
              className="zx-form"
              onSubmit={submit}
              noValidate
              aria-busy={busy}
              tabIndex={-1}
            >
              <fieldset className="zx-roles" disabled={busy}>
                <legend className="zx-sr-only">登录身份</legend>
                {(["student", "teacher"] as const).map((item) => {
                  const ItemIcon = roleContent[item].Icon;
                  return (
                    <label
                      className={`zx-role${role === item ? " zx-role--selected" : ""}`}
                      key={item}
                    >
                      <input
                        type="radio"
                        name="identity"
                        value={item}
                        checked={role === item}
                        onChange={() => chooseRole(item)}
                      />
                      <ItemIcon size={21} aria-hidden="true" />
                      <span>{roleContent[item].label}</span>
                      <Check
                        className="zx-role-check"
                        size={16}
                        aria-hidden="true"
                      />
                    </label>
                  );
                })}
              </fieldset>
              <div className="zx-field">
                <label htmlFor={`${id}-account`}>{active.label}账号</label>
                <div className="zx-input-shell">
                  <UserRound size={19} aria-hidden="true" />
                  <input
                    id={`${id}-account`}
                    ref={accountRef}
                    name="account"
                    type="text"
                    inputMode="email"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    placeholder="请输入账号…"
                    value={account}
                    disabled={busy}
                    required
                    aria-invalid={Boolean(errors.account)}
                    aria-describedby={
                      errors.account ? `${id}-account-error` : undefined
                    }
                    onChange={(event) => {
                      setAccount(event.target.value);
                      setErrors((value) => ({
                        ...value,
                        account: undefined,
                        form: undefined,
                      }));
                    }}
                  />
                </div>
                <span
                  id={`${id}-account-error`}
                  className="zx-field-error"
                  aria-live="polite"
                >
                  {errors.account}
                </span>
              </div>
              <div className="zx-field">
                <label htmlFor={`${id}-password`}>登录密码</label>
                <div className="zx-input-shell">
                  <KeyRound size={19} aria-hidden="true" />
                  <input
                    id={`${id}-password`}
                    ref={passwordRef}
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="请输入密码…"
                    value={password}
                    disabled={busy}
                    required
                    aria-invalid={Boolean(errors.password)}
                    aria-describedby={
                      errors.password ? `${id}-password-error` : undefined
                    }
                    onChange={(event) => {
                      setPassword(event.target.value);
                      setErrors((value) => ({
                        ...value,
                        password: undefined,
                        form: undefined,
                      }));
                    }}
                  />
                  <button
                    type="button"
                    className="zx-password-toggle"
                    aria-label={showPassword ? "隐藏密码" : "显示密码"}
                    aria-pressed={showPassword}
                    disabled={busy}
                    onClick={() => setShowPassword((value) => !value)}
                  >
                    {showPassword ? (
                      <EyeOff size={19} aria-hidden="true" />
                    ) : (
                      <Eye size={19} aria-hidden="true" />
                    )}
                  </button>
                </div>
                <span
                  id={`${id}-password-error`}
                  className="zx-field-error"
                  aria-live="polite"
                >
                  {errors.password}
                </span>
              </div>
              <div className="zx-feedback" aria-live="polite">
                {errors.form ? (
                  <div
                    ref={formErrorRef}
                    className="zx-form-error"
                    role="alert"
                    tabIndex={-1}
                  >
                    {errors.form}
                  </div>
                ) : (
                  <p>
                    {busy
                      ? restoringSession
                        ? "正在恢复登录状态…"
                        : "正在验证身份，请稍候…"
                      : "使用课程管理员分配的账号登录。"}
                  </p>
                )}
              </div>
              <button type="submit" className="zx-submit" disabled={busy}>
                {busy ? (
                  <>
                    <LoaderCircle
                      className="zx-spinner"
                      size={20}
                      aria-hidden="true"
                    />
                    {restoringSession ? "正在恢复会话…" : "正在验证身份…"}
                  </>
                ) : (
                  <>
                    {active.action}
                    <ArrowRight size={20} aria-hidden="true" />
                  </>
                )}
              </button>
              <p className="zx-access-note">账号仅可访问对应身份的课程空间</p>
            </form>
          </section>
        </main>
        <footer className="zx-footer">
          <span>知学智教——大模型驱动的个性化教学平台</span>
          <span>以课程为起点，让教与学相连接</span>
        </footer>
      </div>
    </div>
  );
}
