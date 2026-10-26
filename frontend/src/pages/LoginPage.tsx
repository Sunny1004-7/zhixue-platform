import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../AuthContext";
import { ApiError } from "../errors";
import LoginView, {
  type LoginCredentials,
} from "../components/login/LoginView";

export default function LoginPage() {
  const navigate = useNavigate();
  const { user, loading, login } = useAuth();
  useEffect(() => {
    if (!loading && user)
      navigate(
        user.role === "student" ? "/student/courses" : "/teacher/overview",
        { replace: true },
      );
  }, [loading, navigate, user]);
  const authenticate = async ({
    account,
    password,
    role,
  }: LoginCredentials) => {
    try {
      const authenticated = await login(account, password, role);
      navigate(
        authenticated.role === "student"
          ? "/student/courses"
          : "/teacher/overview",
        { replace: true },
      );
    } catch (reason) {
      if (reason instanceof ApiError)
        throw new Error(
          reason.status === 401
            ? "账号、密码或身份不匹配，请检查后重试。"
            : reason.message,
        );
      throw new Error("暂时无法连接登录服务，请检查网络后重试。");
    }
  };
  return (
    <>
      {sessionStorage.getItem("zhixue-exit-message") && (
        <div className="session-notice" role="status">
          {sessionStorage.getItem("zhixue-exit-message")}
        </div>
      )}
      <LoginView onLogin={authenticate} restoringSession={loading} />
    </>
  );
}
