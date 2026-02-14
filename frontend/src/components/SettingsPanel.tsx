import { useEffect, useState } from "react";
import { getSettings, saveSettings } from "../api/client";
import type { AISettings, StepConfig, FastGPTConfig } from "../types";

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

const STEPS: { key: keyof AISettings; label: string; desc: string }[] = [
  { key: "extractor", label: "步骤1: 信息提取", desc: "从Excel和附件中提取结构化信息（普通模型即可）" },
  { key: "researcher", label: "步骤2: 联网研究", desc: "调用搜索工具补充公开信息（需支持function calling）" },
  { key: "writer", label: "步骤3: 报告生成", desc: "生成完整尽调报告（建议用最强模型）" },
  { key: "field_extractor", label: "步骤4: 字段回填", desc: "从报告中提取字段自动回填元数据（可选，不配置则跳过）" },
  { key: "chunker", label: "步骤5: 索引生成", desc: "生成报告分块与搜索索引标签（可选，不配置则仅生成分块不生成AI索引）" },
];

export default function SettingsPanel() {
  const [settings, setSettings] = useState<AISettings>({
    extractor: { ...DEFAULT_CONFIG },
    researcher: { ...DEFAULT_CONFIG },
    writer: { ...DEFAULT_CONFIG },
    field_extractor: { ...DEFAULT_CONFIG },
    chunker: { ...DEFAULT_CONFIG },
    fastgpt: { ...DEFAULT_FASTGPT },
  });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    getSettings()
      .then((data) => {
        setSettings({
          extractor: data.extractor ?? { ...DEFAULT_CONFIG },
          researcher: data.researcher ?? { ...DEFAULT_CONFIG },
          writer: data.writer ?? { ...DEFAULT_CONFIG },
          field_extractor: data.field_extractor ?? { ...DEFAULT_CONFIG },
          chunker: data.chunker ?? { ...DEFAULT_CONFIG },
          fastgpt: data.fastgpt ?? { ...DEFAULT_FASTGPT },
        });
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
      await saveSettings(settings);
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

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">AI 模型设置</h2>
      <p className="text-sm text-gray-500">
        每一步可以配置不同的AI模型。使用 OpenAI 兼容 API 格式。
      </p>

      {STEPS.map(({ key, label, desc }) => (
        <div key={key} className="bg-white rounded-lg shadow p-5 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-semibold">{label}</h3>
              <p className="text-xs text-gray-400">{desc}</p>
            </div>
            <button
              onClick={() => applyToAll(key)}
              className="text-xs text-blue-600 hover:underline"
            >
              应用到全部
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="text-xs text-gray-500">Base URL</label>
              <input
                type="text"
                value={(settings[key] as StepConfig).base_url}
                onChange={(e) => update(key, "base_url", e.target.value)}
                className="w-full border rounded px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500">API Key</label>
              <input
                type="password"
                value={(settings[key] as StepConfig).api_key}
                onChange={(e) => update(key, "api_key", e.target.value)}
                className="w-full border rounded px-3 py-1.5 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500">Model</label>
              <input
                type="text"
                value={(settings[key] as StepConfig).model}
                onChange={(e) => update(key, "model", e.target.value)}
                className="w-full border rounded px-3 py-1.5 text-sm"
              />
            </div>
          </div>
        </div>
      ))}

      {/* FastGPT Knowledge Base Config */}
      <h2 className="text-xl font-bold pt-4">FastGPT 知识库推送</h2>
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
            <input
              type="checkbox"
              checked={fastgpt.enabled}
              onChange={(e) => updateFastgpt("enabled", e.target.checked)}
              className="w-4 h-4 rounded"
            />
            <span className="text-sm text-gray-600">启用自动推送</span>
          </label>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="md:col-span-2">
            <label className="text-xs text-gray-500">API URL</label>
            <input
              type="text"
              value={fastgpt.api_url}
              onChange={(e) => updateFastgpt("api_url", e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm"
              placeholder="https://ai.mpgroup.cn:3100/api/core/dataset"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500">Dataset ID</label>
            <input
              type="text"
              value={fastgpt.dataset_id}
              onChange={(e) => updateFastgpt("dataset_id", e.target.value)}
              className="w-full border rounded px-3 py-1.5 text-sm"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-gray-500">API Key</label>
          <input
            type="password"
            value={fastgpt.api_key}
            onChange={(e) => updateFastgpt("api_key", e.target.value)}
            className="w-full border rounded px-3 py-1.5 text-sm"
            placeholder="Bearer openapi-..."
          />
        </div>
      </div>

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
    </div>
  );
}
