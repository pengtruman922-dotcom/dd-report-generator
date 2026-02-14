import { useState, useEffect, useCallback } from "react";
import { listUsers, createUser, deleteUser, resetUserPassword, updateUser } from "../api/client";
import { useAuth } from "../contexts/AuthContext";
import type { UserInfo } from "../types";

export default function AccountManager() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<"admin" | "user">("user");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  // Confirm dialogs
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [confirmResetId, setConfirmResetId] = useState<number | null>(null);

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listUsers();
      setUsers(data);
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreateError("");
    if (newPassword.length < 6) {
      setCreateError("密码长度至少6位");
      return;
    }
    setCreating(true);
    try {
      await createUser(newUsername, newPassword, newRole);
      setShowCreate(false);
      setNewUsername("");
      setNewPassword("");
      setNewRole("user");
      fetchUsers();
    } catch (err: any) {
      setCreateError(err.message);
    }
    setCreating(false);
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteUser(id);
      setConfirmDeleteId(null);
      fetchUsers();
    } catch (e: any) {
      alert("删除失败: " + e.message);
    }
  };

  const handleResetPassword = async (id: number) => {
    try {
      await resetUserPassword(id);
      setConfirmResetId(null);
      fetchUsers();
    } catch (e: any) {
      alert("重置失败: " + e.message);
    }
  };

  const handleToggleRole = async (u: UserInfo) => {
    const newRole = u.role === "admin" ? "user" : "admin";
    try {
      await updateUser(u.id, newRole);
      fetchUsers();
    } catch (e: any) {
      alert("修改失败: " + e.message);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20 text-gray-400">加载中...</div>;
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        加载失败: {error}
        <button onClick={fetchUsers} className="ml-3 underline">重试</button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">
          账号管理 <span className="text-sm font-normal text-gray-400">({users.length} 个用户)</span>
        </h1>
        <button
          onClick={() => setShowCreate(true)}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          + 创建用户
        </button>
      </div>

      {/* Users table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b text-left">
              <th className="px-4 py-3">用户名</th>
              <th className="px-4 py-3">角色</th>
              <th className="px-4 py-3">需改密</th>
              <th className="px-4 py-3">创建时间</th>
              <th className="px-4 py-3 text-center">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{u.username}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block px-2 py-0.5 rounded text-xs ${
                      u.role === "admin"
                        ? "bg-purple-100 text-purple-700"
                        : "bg-gray-100 text-gray-600"
                    }`}
                  >
                    {u.role === "admin" ? "管理员" : "普通用户"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {u.must_change_password ? (
                    <span className="text-orange-500 text-xs">是</span>
                  ) : (
                    <span className="text-gray-400 text-xs">否</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500">
                  {u.created_at?.slice(0, 19).replace("T", " ") ?? "--"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center justify-center gap-2">
                    <button
                      onClick={() => handleToggleRole(u)}
                      className="text-xs px-2 py-1 border rounded hover:bg-gray-50"
                      title={u.role === "admin" ? "设为普通用户" : "设为管理员"}
                    >
                      {u.role === "admin" ? "设为用户" : "设为管理员"}
                    </button>
                    <button
                      onClick={() => setConfirmResetId(u.id)}
                      className="text-xs px-2 py-1 border rounded text-orange-600 hover:bg-orange-50"
                    >
                      重置密码
                    </button>
                    {u.id !== currentUser?.id && (
                      <button
                        onClick={() => setConfirmDeleteId(u.id)}
                        className="text-xs px-2 py-1 border rounded text-red-600 hover:bg-red-50"
                      >
                        删除
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Create user modal */}
      {showCreate && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="font-bold text-lg mb-4">创建用户</h3>
            {createError && (
              <div className="bg-red-50 text-red-600 text-sm rounded-lg p-3 mb-4">
                {createError}
              </div>
            )}
            <form onSubmit={handleCreate} className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  用户名
                </label>
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  required
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  密码
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                  required
                  minLength={6}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  角色
                </label>
                <select
                  value={newRole}
                  onChange={(e) => setNewRole(e.target.value as "admin" | "user")}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
                >
                  <option value="user">普通用户</option>
                  <option value="admin">管理员</option>
                </select>
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setShowCreate(false);
                    setCreateError("");
                  }}
                  className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50"
                >
                  取消
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {creating ? "创建中..." : "创建"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Confirm delete modal */}
      {confirmDeleteId !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="font-bold text-lg mb-2">确认删除</h3>
            <p className="text-gray-600 text-sm mb-4">确定要删除该用户吗？该用户的会话将被清除。</p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmDeleteId(null)}
                className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={() => handleDelete(confirmDeleteId)}
                className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                删除
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm reset password modal */}
      {confirmResetId !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-sm w-full mx-4">
            <h3 className="font-bold text-lg mb-2">确认重置密码</h3>
            <p className="text-gray-600 text-sm mb-4">
              密码将被重置为 <code className="bg-gray-100 px-1 rounded">123456</code>，用户下次登录时需要修改密码。
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmResetId(null)}
                className="px-4 py-2 text-sm border rounded-lg hover:bg-gray-50"
              >
                取消
              </button>
              <button
                onClick={() => handleResetPassword(confirmResetId)}
                className="px-4 py-2 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600"
              >
                确认重置
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
