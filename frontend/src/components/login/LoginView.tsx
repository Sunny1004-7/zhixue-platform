import BrandGlyph from "../BrandGlyph";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ArrowRight, Check, Eye, EyeOff, GraduationCap, KeyRound, LoaderCircle, NotebookPen, UserRound } from "lucide-react";
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
  student: { label: "学生", action: "进入学生空间", Icon: GraduationCap },
  teacher: { label: "教师", action: "进入教师空间", Icon: NotebookPen },
};

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
      <a className="zx-skip" href="#zx-login-form" onClick={(event) => {
        event.preventDefault(); document.getElementById("zx-login-form")?.focus();
      }}>跳到登录表单</a>
      <main className="zx-auth" aria-labelledby={`${id}-heading`}>
        <section className="zx-identity" aria-label="知学智教">
          <header className="zx-brand">
            <span className="zx-brand-glyph"><BrandGlyph /></span>
            <h1 id={`${id}-heading`}>知学智教</h1>
            <p>大模型驱动的个性化教学平台</p>
          </header>
          <svg className="zx-book-art" viewBox="0 0 500 360" aria-hidden="true">
            <ellipse cx="250" cy="304" rx="190" ry="20" fill="#dbe6f0" />
            <path d="M62 117L244 165L438 117V278L251 329L62 279Z" fill="#bfd2e4" />
            <path d="M52 105L242 155L448 105V264L251 316L52 265Z" fill="#2859c5" opacity=".84" />
            <path d="M250 122C187 79 107 74 61 94V250C119 232 195 247 250 285C305 247 381 232 439 250V94C393 74 313 79 250 122Z" fill="#fff" stroke="#90aac6" strokeWidth="2" />
            <path d="M250 122V285M83 119C139 105 190 121 224 140M83 145C139 131 190 147 224 166M83 171C139 157 190 173 224 192M83 197C139 183 190 199 224 218M277 140C319 116 372 108 415 119M277 166C319 142 372 134 415 145M277 192C319 168 372 160 415 171M277 218C319 194 372 186 415 197" fill="none" stroke="#d1dce8" strokeWidth="3" strokeLinecap="round" />
            <path d="M341 91V183L364 164L387 172V82" fill="#16847f" />
            <circle cx="112" cy="54" r="9" fill="#d4a84c" />
            <path d="M416 40V66M403 53H429" stroke="#91b8c4" strokeWidth="3" strokeLinecap="round" />
          </svg>
        </section>
        <section className="zx-signin" aria-labelledby={`${id}-signin`}>
          <h2 id={`${id}-signin`}>登录课程空间</h2>
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
            </form>
        </section>
      </main>
    </div>
  );
}
