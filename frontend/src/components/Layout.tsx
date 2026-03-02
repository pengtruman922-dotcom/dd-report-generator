import { useState, useRef, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";
import ChangePasswordModal from "./ChangePasswordModal";

export default function Layout({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowUserMenu(false);
      }
    };
    if (showUserMenu) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showUserMenu]);

  const navLink = (to: string, label: string) => {
    const active =
      to === "/"
        ? pathname === "/"
        : pathname.startsWith(to);
    return (
      <Link
        to={to}
        className={
          active
            ? "text-blue-600 font-medium"
            : "text-gray-500 hover:text-gray-800"
        }
      >
        {label}
      </Link>
    );
  };

  const handleLogout = async () => {
    setShowUserMenu(false);
    await logout();
    navigate("/login", { replace: true });
  };

  const isAdmin = user?.role === "admin";

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b shadow-sm">
        <div className="mx-auto px-8 h-14 flex items-center justify-between">
          <Link to="/reports" className="text-lg font-bold text-blue-700">
            并购尽调分析推荐
          </Link>
          <div className="flex items-center gap-4">
            <nav className="flex gap-4 text-sm">
              {navLink("/reports", "首页")}
              {isAdmin && navLink("/settings", "设置")}
              {isAdmin && navLink("/accounts", "账号管理")}
            </nav>
            {/* User menu */}
            {user && (
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900 px-2 py-1 rounded hover:bg-gray-50"
                >
                  <span className={`inline-block w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center ${
                    isAdmin ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"
                  }`}>
                    {user.username[0].toUpperCase()}
                  </span>
                  <span className="max-w-[80px] truncate">{user.username}</span>
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
                {showUserMenu && (
                  <div className="absolute right-0 top-full mt-1 w-40 bg-white border rounded-lg shadow-lg z-50 py-1">
                    <div className="px-3 py-2 border-b text-xs text-gray-400">
                      {isAdmin ? "管理员" : "普通用户"}
                    </div>
                    <button
                      onClick={() => {
                        setShowUserMenu(false);
                        setShowChangePassword(true);
                      }}
                      className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50"
                    >
                      修改密码
                    </button>
                    <button
                      onClick={handleLogout}
                      className="w-full text-left px-3 py-2 text-sm text-red-600 hover:bg-red-50"
                    >
                      退出登录
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </header>
      <main className="flex-1 w-full px-8 py-6">{children}</main>
      <footer className="text-center text-xs text-gray-400 py-3 border-t">
        DD Report Generator v1.0
      </footer>

      {showChangePassword && (
        <ChangePasswordModal onClose={() => setShowChangePassword(false)} />
      )}
    </div>
  );
}
