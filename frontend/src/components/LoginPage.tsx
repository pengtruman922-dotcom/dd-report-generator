import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

export default function LoginPage() {
  const { login, changePassword } = useAuth();
  const navigate = useNavigate();

  const [phase, setPhase] = useState<"login" | "force_change">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const user = await login(username, password);
      if (user.must_change_password) {
        setOldPassword(password);
        setPhase("force_change");
      } else {
        navigate("/reports", { replace: true });
      }
    } catch (err: any) {
      setError(err.message);
    }
    setLoading(false);
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (newPassword.length < 6) {
      setError("新密码长度至少6位");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("两次输入的密码不一致");
      return;
    }
    setLoading(true);
    try {
      await changePassword(oldPassword, newPassword);
      navigate("/reports", { replace: true });
    } catch (err: any) {
      setError(err.message);
    }
    setLoading(false);
  };

  const capabilities = [
    { title: "标的信息管理", desc: "高效录入与结构化管理卖方标的资产信息" },
    { title: "买卖智能匹配", desc: "基于多维度特征，精准连接买卖双方需求" },
    { title: "并购交易促成", desc: "全链路跟踪推进，助力交易高效达成" },
  ];

  return (
    <div className="min-h-screen flex flex-col lg:flex-row bg-white">
      {/* Left - Brand Showcase */}
      <div className="relative lg:w-[56%] w-full bg-gradient-to-br from-gray-50 to-gray-100 flex flex-col justify-center items-center px-8 py-12 lg:py-0 overflow-hidden">
        {/* Decorative elements */}
        <div className="absolute top-0 left-0 w-full h-full pointer-events-none">
          <div className="absolute top-[-10%] right-[-5%] w-[400px] h-[400px] rounded-full bg-red-50 opacity-60" />
          <div className="absolute bottom-[-15%] left-[-10%] w-[500px] h-[500px] rounded-full bg-red-50 opacity-40" />
          <div className="absolute top-[20%] left-[10%] w-[200px] h-[1px] bg-red-200 opacity-50 rotate-[30deg]" />
          <div className="absolute bottom-[30%] right-[15%] w-[150px] h-[1px] bg-red-200 opacity-50 rotate-[-20deg]" />
          <div className="absolute inset-0 opacity-[0.03]" style={{
            backgroundImage: 'linear-gradient(rgba(0,0,0,0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0,0,0,0.1) 1px, transparent 1px)',
            backgroundSize: '60px 60px'
          }} />
        </div>

        {/* Logo - top left */}
        <div className="absolute top-8 left-8 z-10">
          <img
            src="/image copy.png"
            alt="中大咨询集团"
            className="h-14 object-contain"
          />
        </div>

        <div className="relative z-10 max-w-md w-full">

          {/* Platform Name */}
          <div className="mb-10">
            <h1 className="text-3xl lg:text-4xl font-bold text-gray-900 tracking-tight mb-3">
              并购智联
            </h1>
            <p className="text-base text-gray-500 leading-relaxed">
              投资撮合智能服务平台
            </p>
          </div>

          {/* Capabilities */}
          <div className="space-y-5">
            {capabilities.map((cap, i) => (
              <div key={i} className="flex items-start gap-4">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-red-600 flex items-center justify-center mt-0.5">
                  <span className="text-white text-sm font-semibold">{i + 1}</span>
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 mb-0.5">{cap.title}</h3>
                  <p className="text-sm text-gray-500 leading-relaxed">{cap.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right - Login Form */}
      <div className="lg:w-[44%] w-full flex items-center justify-center px-6 py-12 lg:py-0">
        <div className="w-full max-w-sm">
          <h2 className="text-xl font-bold text-gray-900 mb-1">
            {phase === "login" ? "欢迎登录" : "首次登录 — 修改密码"}
          </h2>
          <p className="text-sm text-gray-400 mb-8">
            {phase === "login"
              ? "请输入您的账号信息"
              : "首次登录需要修改密码后才能使用系统"}
          </p>

          {error && (
            <div className="bg-red-50 border border-red-100 text-red-600 text-sm rounded-lg p-3 mb-5">
              {error}
            </div>
          )}

          {phase === "login" ? (
            <form onSubmit={handleLogin} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  用户名
                </label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-100 focus:border-red-400 transition-colors"
                  placeholder="请输入用户名"
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  密码
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-100 focus:border-red-400 transition-colors"
                  placeholder="请输入密码"
                  required
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 active:bg-red-800 disabled:opacity-50 text-sm font-medium transition-colors shadow-sm"
              >
                {loading ? "登录中..." : "登 录"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleChangePassword} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  新密码
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-100 focus:border-red-400 transition-colors"
                  placeholder="请输入新密码（至少6位）"
                  required
                  autoFocus
                  minLength={6}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5">
                  确认新密码
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-red-100 focus:border-red-400 transition-colors"
                  placeholder="请再次输入新密码"
                  required
                  minLength={6}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 active:bg-red-800 disabled:opacity-50 text-sm font-medium transition-colors shadow-sm"
              >
                {loading ? "修改中..." : "修改密码并进入"}
              </button>
            </form>
          )}

          {/* Footer */}
          <div className="mt-12 pt-6 border-t border-gray-100">
            <p className="text-xs text-gray-300 text-center">
              &copy; 中大咨询集团
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
