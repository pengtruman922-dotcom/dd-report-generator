import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { getSettings, saveSettings } from "../api/client";
import type { AISettings, StepConfig, FastGPTConfig, IntakeAgentConfig } from "../types";
import ToolSettingsPanel from "./ToolSettingsPanel";

const DEFAULT_CONFIG: StepConfig = {
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  api_key: "",
  model: "qwen3-max",
};

const DEFAULT_FASTGPT: FastGPTConfig = {
  enabled: true,
  api_url: "",
  api_key: "",
  dataset_id: "",
};

const DEFAULT_INTAKE: IntakeAgentConfig = {
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  api_key: "",
  model: "qwen3.5-plus",
  max_crawl_depth: 3,
  default_mode: "auto",
  core_fields_trigger_research: ["description", "company_intro"],
  research_data_expire_days: 90,
};

const STEPS: { key: keyof AISettings; label: string; desc: string }[] = [
  { key: "extractor", label: "步骤1: 信息提取", desc: "从Excel和附件中提取结构化信息（普通模型即可）" },
  { key: "researcher", label: "步骤2: 联网研究", desc: "调用搜索工具补充公开信息（需支持function calling）" },
  { key: "writer", label: "步骤3: 报告生成", desc: "生成完整尽调报告（建议用最强模型）" },
  { key: "field_extractor", label: "步骤4: 字段回填", desc: "从报告中提取字段自动回填元数据（可选，不配置则跳过）" },
  { key: "chunker", label: "步骤5: 索引生成", desc: "生成报告分块与搜索索引标签（可选，不配置则仅生成分块不生成AI索引）" },
];

const TABS = [
  { id: "ai", label: "AI 模型" },
  { id: "intake", label: "录入 Agent" },
  { id: "tools", label: "搜索工具" },
  { id: "fastgpt", label: "FastGPT" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function SettingsPanel() {
  const location = useLocation();
  const initTab = (location.state as any)?.tab;
  const [activeTab, setActiveTab] = useState<TabId>(
    initTab && TABS.some((t) => t.id === initTab) ? initTab : "ai",
  );
  const [settings, setSettings] = useState<AISettings>({
    extractor: { ...DEFAULT_CONFIG },
    researcher: { ...DEFAULT_CONFIG },
    writer: { ...DEFAULT_CONFIG },
    field_extractor: { ...DEFAULT_CONFIG },
    chunker: { ...DEFAULT_CONFIG },
    fastgpt: { ...DEFAULT_FASTGPT },
  });
  const [intake, setIntake] = useState<IntakeAgentConfig>({ ...DEFAULT_INTAKE });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    getSettings()
      .then((data: any) => {
        setSettings({
          extractor: data.extractor ?? { ...DEFAULT_CONFIG },
          researcher: data.researcher ?? { ...DEFAULT_CONFIG },
          writer: data.writer ?? { ...DEFAULT_CONFIG },
          field_extractor: data.field_extractor ?? { ...DEFAULT_CONFIG },
          chunker: data.chunker ?? { ...DEFAULT_CONFIG },
          fastgpt: data.fastgpt ?? { ...DEFAULT_FASTGPT },
        });
        if (data.intake_agent) {
          setIntake({ ...DEFAULT_INTAKE, ...data.intake_agent });
        }
      })
      .catch(() => {});
  }, []);

  const update = (step: keyof AISettings, field: string, value: string) => {
    setSettings((prev) => ({
      ...prev,
      [step]: { ...(prev[step] as any), [field]: value },
    }));
  };

  const handleSave = async () => {
    setSaving(true);
    setMessage("");
    try {
      await saveSettings({ ...settings, intake_agent: intake } as any);
      setMessage("保存成功");
    } catch (e: any) {
      setMessage("保存失败: " + e.message);
    }
    setSaving(false);
  };

  const applyToAll = (step: keyof AISettings) => {
    const src = settings[step] as StepConfig;
    setSettings((prev) => ({
      ...prev,
      extractor: { ...src },
      researcher: { ...src },
      writer: { ...src },
      field_extractor: { ...src },
      chunker: { ...src },
    }));
  };

  const fastgpt = settings.fastgpt ?? { ...DEFAULT_FASTGPT };

  const updateFastgpt = (field: keyof FastGPTConfig, value: string | boolean) => {
    setSettings((prev) => ({
      ...prev,
      fastgpt: { ...(prev.fastgpt ?? DEFAULT_FASTGPT), [field]: value },
    }));
  };

  const SaveBar = () => (
    <div className="flex items-center gap-4">
      <button
        onClick={handleSave}
        disabled={saving}
        className="px-6 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
      >
        {saving ? "保存中..." : "保存设置"}
      </button>
      {message && (
        <span className={`text-sm ${message.includes("失败") ? "text-red-600" : "text-green-600"}`}>
          {message}
        </span>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex border-b">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition ${
              activeTab === tab.id
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "ai" && (
        <div className="space-y-6">
          <h2 className="text-xl font-bold">AI 模型设置</h2>
          <p className="text-sm text-gray-500">每一步可以配置不同的AI模型。使用 OpenAI 兼容 API 格式。</p>
          {STEPS.map(({ key, label, desc }) => (
            <div key={key} className="bg-white rounded-lg shadow p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold">{label}</h3>
                  <p className="text-xs text-gray-400">{desc}</p>
                </div>
                <button onClick={() => applyToAll(key)} className="text-xs text-blue-600 hover:underline">
                  应用到全部
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div>
                  <label className="text-xs text-gray-500">Base URL</label>
                  <input type="text" value={(settings[key] as StepConfig).base_url}
                    onChange={(e) => update(key, "base_url", e.target.value)}
                    className="w-full border rounded px-3 py-1.5 text-sm" />
                </div>
                <div>
                  <label className="text-xs text-gray-500">API Key</label>
                  <input type="password" value={(settings[key] as StepConfig).api_key}
                    onChange={(e) => update(key, "api_key", e.target.value)}
                    className="w-full border rounded px-3 py-1.5 text-sm" />
                </div>
                <div>
                  <label className="text-xs text-gray-500">Model</label>
                  <input type="text" value={(settings[key] as StepConfig).model}
                    onChange={(e) => update(key, "model", e.target.value)}
                    className="w-full border rounded px-3 py-1.5 text-sm" />
                </div>
              </div>
            </div>
          ))}
          <SaveBar />
        </div>
      )}

      {activeTab === "intake" && (
        <div className="space-y-6">
          <h2 className="text-xl font-bold">录入 Agent 设置</h2>
          <p className="text-sm text-gray-500">配置智能录入功能的 AI 模型和行为参数。</p>
          <div className="bg-white rounded-lg shadow p-5 space-y-4">
            <h3 className="font-semibold">模型配置</h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-gray-500">Base URL</label>
                <input type="text" value={intake.base_url}
                  onChange={(e) => setIntake((p) => ({ ...p, base_url: e.target.value }))}
                  className="w-full border rounded px-3 py-1.5 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500">API Key（留空则继承全局）</label>
                <input type="password" value={intake.api_key}
                  onChange={(e) => setIntake((p) => ({ ...p, api_key: e.target.value }))}
                  className="w-full border rounded px-3 py-1.5 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500">Model（需支持视觉）</label>
                <input type="text" value={intake.model}
                  onChange={(e) => setIntake((p) => ({ ...p, model: e.target.value }))}
                  className="w-full border rounded px-3 py-1.5 text-sm"
                  placeholder="qwen3.5-plus" />
              </div>
            </div>

            <h3 className="font-semibold pt-2">行为配置</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500">网页下钻最大次数</label>
                <input type="number" min={1} max={10} value={intake.max_crawl_depth}
                  onChange={(e) => setIntake((p) => ({ ...p, max_crawl_depth: Number(e.target.value) }))}
                  className="w-full border rounded px-3 py-1.5 text-sm" />
                <p className="text-xs text-gray-400 mt-0.5">每个链接最多追踪的子页面数，默认 3</p>
              </div>
              <div>
                <label className="text-xs text-gray-500">默认执行模式</label>
                <select value={intake.default_mode}
                  onChange={(e) => setIntake((p) => ({ ...p, default_mode: e.target.value as "auto" | "manual" }))}
                  className="w-full border rounded px-3 py-1.5 text-sm">
                  <option value="auto">自动（解析完直接执行）</option>
                  <option value="manual">手动确认（展示预览卡后执行）</option>
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500">调研数据有效期（天）</label>
                <input type="number" min={1} value={intake.research_data_expire_days}
                  onChange={(e) => setIntake((p) => ({ ...p, research_data_expire_days: Number(e.target.value) }))}
                  className="w-full border rounded px-3 py-1.5 text-sm" />
                <p className="text-xs text-gray-400 mt-0.5">超过此天数时，轻量更新会提示重新调研</p>
              </div>
              <div>
                <label className="text-xs text-gray-500">触发完整调研的核心字段（逗号分隔）</label>
                <input type="text"
                  value={intake.core_fields_trigger_research.join(", ")}
                  onChange={(e) => setIntake((p) => ({
                    ...p,
                    core_fields_trigger_research: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                  }))}
                  className="w-full border rounded px-3 py-1.5 text-sm"
                  placeholder="description, company_intro" />
                <p className="text-xs text-gray-400 mt-0.5">这些字段变化时，会提示是否需要完整重调研</p>
              </div>
            </div>
          </div>
          <SaveBar />
        </div>
      )}

      {activeTab === "tools" && <ToolSettingsPanel />}

      {activeTab === "fastgpt" && (
        <div className="space-y-6">
          <h2 className="text-xl font-bold">FastGPT 知识库推送</h2>
          <p className="text-sm text-gray-500">
            生成索引后自动推送到 FastGPT 知识库。启用后将在 pipeline 最后一步自动执行。
          </p>
          <div className="bg-white rounded-lg shadow p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="font-semibold">FastGPT 配置</h3>
                <p className="text-xs text-gray-400">配置 FastGPT API 连接参数和目标知识库</p>
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={fastgpt.enabled}
                  onChange={(e) => updateFastgpt("enabled", e.target.checked)}
                  className="w-4 h-4 rounded" />
                <span className="text-sm text-gray-600">启用自动推送</span>
              </label>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div className="md:col-span-2">
                <label className="text-xs text-gray-500">API URL</label>
                <input type="text" value={fastgpt.api_url}
                  onChange={(e) => updateFastgpt("api_url", e.target.value)}
                  className="w-full border rounded px-3 py-1.5 text-sm"
                  placeholder="https://your-fastgpt-server/api/core/dataset" />
              </div>
              <div>
                <label className="text-xs text-gray-500">Dataset ID</label>
                <input type="text" value={fastgpt.dataset_id}
                  onChange={(e) => updateFastgpt("dataset_id", e.target.value)}
                  className="w-full border rounded px-3 py-1.5 text-sm" />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500">API Key</label>
              <input type="password" value={fastgpt.api_key}
                onChange={(e) => updateFastgpt("api_key", e.target.value)}
                className="w-full border rounded px-3 py-1.5 text-sm"
                placeholder="Bearer openapi-..." />
            </div>
          </div>
          <SaveBar />
        </div>
      )}
    </div>
  );
}
