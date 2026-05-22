import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import {
  getModelWorkbench,
  getSettings,
  saveModelWorkbench,
  saveSettings,
  testModelWorkbenchNode,
} from "../api/client";
import type {
  FastGPTConfig,
  ModelBehaviorFieldView,
  ModelNodeView,
  ModelPromptView,
  ModelProviderFieldView,
  ModelWorkbenchResponse,
} from "../types";
import ToolSettingsPanel from "./ToolSettingsPanel";

const DEFAULT_FASTGPT: FastGPTConfig = {
  enabled: true,
  api_url: "",
  api_key: "",
  dataset_id: "",
};

const TABS = [
  { id: "models", label: "模型与提示词" },
  { id: "tools", label: "搜索工具" },
  { id: "fastgpt", label: "FastGPT" },
] as const;

const MODEL_GROUP_ORDER = ["录入链路", "写作链路", "附件更新链路"] as const;
const PROVIDER_FIELD_ORDER = ["base_url", "model", "api_key"] as const;

type TabId = (typeof TABS)[number]["id"];

type Notice = {
  type: "success" | "error" | "info";
  text: string;
} | null;

type NodeTestState = {
  status: "idle" | "testing" | "success" | "error";
  message: string;
} | null;

function cloneValue<T>(value: T): T {
  return JSON.parse(JSON.stringify(value));
}

function serializeWorkbench(workbench: ModelWorkbenchResponse | null): string {
  if (!workbench) return "";
  return JSON.stringify({
    ai_config: workbench.ai_config,
    prompt_overrides: workbench.prompt_overrides,
  });
}

function getProviderField(node: ModelNodeView, key: ModelProviderFieldView["key"]) {
  return node.provider?.fields.find((field) => field.key === key) ?? null;
}

function getBehaviorField(node: ModelNodeView, key: string) {
  return node.behavior?.fields.find((field) => field.key === key) ?? null;
}

function hasMeaningfulOverride(value: unknown, isProviderField: boolean): boolean {
  if (value === null || value === undefined) return false;
  if (typeof value === "string") {
    return isProviderField ? value.trim().length > 0 : true;
  }
  return true;
}

function isFallbackNode(node: ModelNodeView) {
  return node.node_kind !== "prompt_only" && node.reset_label === "恢复继承";
}

function getNodeMap(nodes: ModelNodeView[]) {
  return new Map(nodes.map((node) => [node.id, node]));
}

function resolveProviderFieldValue(
  nodesById: Map<string, ModelNodeView>,
  aiConfig: Record<string, any>,
  node: ModelNodeView,
  key: ModelProviderFieldView["key"],
): {
  value: string;
  mode: "custom" | "inherited" | "system_default";
  label: string;
  sourceNode?: string | null;
  configured: boolean;
} {
  const configKey = node.config_key;
  const rawConfig = configKey ? aiConfig[configKey] || {} : {};
  if (
    configKey &&
    Object.prototype.hasOwnProperty.call(rawConfig, key) &&
    hasMeaningfulOverride(rawConfig[key], true)
  ) {
    return {
      value: String(rawConfig[key] ?? ""),
      mode: "custom",
      label: "本节点",
      sourceNode: node.id,
      configured: Boolean(rawConfig[key]),
    };
  }

  if (node.inherits_from) {
    const parent = nodesById.get(node.inherits_from);
    if (parent) {
      const parentResolved = resolveProviderFieldValue(nodesById, aiConfig, parent, key);
      return {
        value: parentResolved.value,
        mode: "inherited",
        label: `继承自 ${parent.label}`,
        sourceNode: parent.id,
        configured: parentResolved.configured,
      };
    }
  }

  const field = getProviderField(node, key);
  const defaultValue = String(field?.default_value ?? "");
  return {
    value: defaultValue,
    mode: "system_default",
    label: "系统默认",
    sourceNode: null,
    configured: Boolean(defaultValue),
  };
}

function resolveBehaviorFieldValue(
  nodesById: Map<string, ModelNodeView>,
  aiConfig: Record<string, any>,
  node: ModelNodeView,
  key: string,
): {
  value: any;
  mode: "custom" | "inherited" | "system_default";
  label: string;
  sourceNode?: string | null;
} {
  const configKey = node.config_key;
  const rawConfig = configKey ? aiConfig[configKey] || {} : {};
  if (configKey && Object.prototype.hasOwnProperty.call(rawConfig, key)) {
    return {
      value: cloneValue(rawConfig[key]),
      mode: "custom",
      label: "本节点",
      sourceNode: node.id,
    };
  }

  if (node.inherits_from) {
    const parent = nodesById.get(node.inherits_from);
    if (parent) {
      const parentResolved = resolveBehaviorFieldValue(nodesById, aiConfig, parent, key);
      return {
        value: cloneValue(parentResolved.value),
        mode: "inherited",
        label: `继承自 ${parent.label}`,
        sourceNode: parent.id,
      };
    }
  }

  const field = getBehaviorField(node, key);
  return {
    value: cloneValue(field?.default_value ?? ""),
    mode: "system_default",
    label: "系统默认",
    sourceNode: null,
  };
}

function hasCustomNodeOverride(node: ModelNodeView, aiConfig: Record<string, any>) {
  if (!node.config_key) return false;
  const rawConfig = aiConfig[node.config_key] || {};
  return Object.entries(rawConfig).some(([key, value]) =>
    hasMeaningfulOverride(value, key === "base_url" || key === "api_key" || key === "model"),
  );
}

function rebuildWorkbenchView(
  workbench: ModelWorkbenchResponse,
  nextAiConfig: Record<string, any>,
  nextPromptOverrides: Record<string, string>,
): ModelWorkbenchResponse {
  const nodesById = getNodeMap(workbench.nodes);
  const nextNodes = workbench.nodes.map((node) => {
    const nextMode: ModelNodeView["config_mode"] =
      node.node_kind === "prompt_only"
        ? "prompt_only"
        : isFallbackNode(node)
          ? (hasCustomNodeOverride(node, nextAiConfig) ? "custom" : "inherited")
          : "custom";

    const providerFields =
      node.provider?.fields.map((field) => {
        const resolved = resolveProviderFieldValue(nodesById, nextAiConfig, node, field.key);
        return {
          ...field,
          value: field.key === "api_key" ? "" : resolved.value,
          editable: nextMode === "custom",
          configured: resolved.configured,
          display_value: field.key === "api_key" ? "" : resolved.value,
          status_text: resolved.configured ? "已配置" : "未配置",
          source: {
            mode: resolved.mode,
            label: resolved.label,
            source_node: resolved.sourceNode,
          },
        };
      }) ?? [];

    const behaviorFields =
      node.behavior?.fields.map((field) => {
        const resolved = resolveBehaviorFieldValue(nodesById, nextAiConfig, node, field.key);
        return {
          ...field,
          value: cloneValue(resolved.value),
          editable: nextMode === "custom",
          source: {
            mode: resolved.mode,
            label: resolved.label,
            source_node: resolved.sourceNode,
          },
        };
      }) ?? [];

    const nextPrompt = node.prompt
      ? {
          ...node.prompt,
          current: nextPromptOverrides[node.prompt.id] || node.prompt.default,
          overridden: Boolean(nextPromptOverrides[node.prompt.id]),
        }
      : undefined;

    const nextPromptVariants =
      node.prompt_variants?.map((prompt) => ({
        ...prompt,
        current: nextPromptOverrides[prompt.id] || prompt.default,
        overridden: Boolean(nextPromptOverrides[prompt.id]),
      })) ?? [];

    const promptOverrideCount =
      (nextPrompt?.overridden ? 1 : 0) +
      nextPromptVariants.filter((prompt) => prompt.overridden).length;

    const inheritedLabel = node.inherits_from
      ? nodesById.get(node.inherits_from)?.label || node.inherits_from
      : "";
    const nextSourceBadge =
      nextMode === "prompt_only"
        ? `模型继承 ${inheritedLabel}`.trim()
        : nextMode === "inherited" && inheritedLabel
          ? `继承 ${inheritedLabel}`
          : "独立配置";

    return {
      ...node,
      config_mode: nextMode,
      source_badge: nextSourceBadge,
      can_customize: nextMode === "inherited",
      can_reset: nextMode === "custom" && node.node_kind !== "prompt_only",
      prompt_override_count: promptOverrideCount,
      provider: node.provider
        ? {
            ...node.provider,
            fields: providerFields,
            summary: {
              model: providerFields.find((field) => field.key === "model")?.display_value || "",
              base_url:
                providerFields.find((field) => field.key === "base_url")?.display_value || "",
              api_key_configured: Boolean(
                providerFields.find((field) => field.key === "api_key")?.configured,
              ),
            },
          }
        : node.provider,
      behavior: node.behavior
        ? {
            ...node.behavior,
            fields: behaviorFields,
          }
        : node.behavior,
      prompt: nextPrompt,
      prompt_variants: nextPromptVariants,
    };
  });

  return {
    ...workbench,
    ai_config: nextAiConfig,
    prompt_overrides: nextPromptOverrides,
    nodes: nextNodes,
  };
}

function Tag({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "primary" | "warning" | "success";
}) {
  const styles = {
    default: "bg-gray-100 text-gray-700",
    primary: "bg-blue-50 text-blue-700",
    warning: "bg-amber-50 text-amber-700",
    success: "bg-emerald-50 text-emerald-700",
  }[tone];
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${styles}`}>{children}</span>
  );
}

function NoticeBanner({ notice }: { notice: Notice }) {
  if (!notice) return null;
  const classes =
    notice.type === "error"
      ? "border-red-200 bg-red-50 text-red-700"
      : notice.type === "success"
        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
        : "border-blue-200 bg-blue-50 text-blue-700";
  return <div className={`rounded-lg border px-4 py-3 text-sm ${classes}`}>{notice.text}</div>;
}

function PromptEditor({
  prompt,
  onChange,
  onReset,
}: {
  prompt: ModelPromptView;
  onChange: (value: string) => void;
  onReset: () => void;
}) {
  const [showDefault, setShowDefault] = useState(false);

  return (
    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold text-gray-900">{prompt.label || prompt.id}</div>
            <Tag tone={prompt.overridden ? "primary" : "default"}>
              {prompt.overridden ? "已覆盖默认" : "使用默认"}
            </Tag>
          </div>
          <div className="text-xs text-gray-500">
            {prompt.overridden ? "当前内容来自自定义覆盖" : "当前内容来自系统默认提示词"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowDefault((prev) => !prev)}
            className="rounded border px-3 py-1.5 text-xs text-gray-700 hover:bg-white"
          >
            {showDefault ? "隐藏默认" : "查看默认"}
          </button>
          <button
            onClick={onReset}
            className="rounded border px-3 py-1.5 text-xs text-gray-700 hover:bg-white"
          >
            恢复默认
          </button>
        </div>
      </div>

      <textarea
        value={prompt.current}
        onChange={(e) => onChange(e.target.value)}
        rows={12}
        className="mt-3 w-full rounded-lg border bg-white px-3 py-2 font-mono text-xs leading-6 focus:outline-none focus:ring-2 focus:ring-blue-300"
      />

      {showDefault ? (
        <div className="mt-3 rounded-lg border bg-white p-3">
          <div className="mb-2 text-xs font-medium text-gray-500">默认提示词</div>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs leading-6 text-gray-700">
            {prompt.default}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

function BehaviorInput({
  field,
  disabled,
  onChange,
}: {
  field: ModelBehaviorFieldView;
  disabled: boolean;
  onChange: (value: any) => void;
}) {
  if (field.input_type === "select") {
    return (
      <select
        value={String(field.value ?? "")}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border bg-white px-3 py-2 text-sm disabled:bg-gray-100"
      >
        {(field.options || []).map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (field.input_type === "number") {
    return (
      <input
        type="number"
        value={field.value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
        className="w-full rounded-lg border bg-white px-3 py-2 text-sm disabled:bg-gray-100"
      />
    );
  }

  if (field.input_type === "tags") {
    const value = Array.isArray(field.value) ? field.value.join(", ") : "";
    return (
      <input
        value={value}
        disabled={disabled}
        onChange={(e) =>
          onChange(
            e.target.value
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean),
          )
        }
        placeholder="多个值请用逗号分隔"
        className="w-full rounded-lg border bg-white px-3 py-2 text-sm disabled:bg-gray-100"
      />
    );
  }

  return (
    <input
      value={String(field.value ?? "")}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border bg-white px-3 py-2 text-sm disabled:bg-gray-100"
    />
  );
}

function NodePanel({
  node,
  apiKeyDraft,
  testState,
  onApiKeyDraftChange,
  onProviderChange,
  onClearApiKey,
  onBehaviorChange,
  onPromptChange,
  onPromptReset,
  onEnableCustomConfig,
  onResetNodeConfig,
  onTestConnection,
}: {
  node: ModelNodeView;
  apiKeyDraft: string;
  testState: NodeTestState;
  onApiKeyDraftChange: (value: string) => void;
  onProviderChange: (field: ModelProviderFieldView["key"], value: string) => void;
  onClearApiKey: () => void;
  onBehaviorChange: (key: string, value: any) => void;
  onPromptChange: (promptId: string, value: string) => void;
  onPromptReset: (promptId: string) => void;
  onEnableCustomConfig: () => void;
  onResetNodeConfig: () => void;
  onTestConnection: () => void;
}) {
  const sortedProviderFields =
    node.provider?.fields
      .slice()
      .sort(
        (left, right) =>
          PROVIDER_FIELD_ORDER.indexOf(left.key) - PROVIDER_FIELD_ORDER.indexOf(right.key),
      ) ?? [];

  return (
    <div className="space-y-4">
      <section className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold text-gray-900">{node.label}</h2>
              <Tag tone={node.is_primary ? "primary" : "default"}>
                {node.is_primary ? "主链路" : "辅助节点"}
              </Tag>
              <Tag tone={node.config_mode === "inherited" ? "warning" : "success"}>
                {node.config_mode === "prompt_only"
                  ? "仅提示词节点"
                  : node.config_mode === "inherited"
                    ? "继承配置"
                    : "独立配置"}
              </Tag>
              {node.prompt_override_count ? (
                <Tag tone="primary">已覆盖 {node.prompt_override_count} 处提示词</Tag>
              ) : null}
            </div>
            <p className="text-sm text-gray-600">{node.description}</p>
          </div>
          <div className="flex items-center gap-2">
            {node.can_customize ? (
              <button
                onClick={onEnableCustomConfig}
                className="rounded-lg border px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                启用独立模型配置
              </button>
            ) : null}
            {node.can_reset ? (
              <button
                onClick={onResetNodeConfig}
                className="rounded-lg border px-3 py-2 text-sm text-gray-700 hover:bg-gray-50"
              >
                {node.reset_label || "恢复默认"}
              </button>
            ) : null}
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-500">当前生效模型</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">
              {node.provider?.summary.model || "--"}
            </div>
          </div>
          <div className="rounded-lg border bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-500">当前配置来源</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">
              {node.source_badge || "--"}
            </div>
          </div>
          <div className="rounded-lg border bg-gray-50 p-3">
            <div className="text-xs font-medium text-gray-500">API Key 状态</div>
            <div className="mt-1 text-sm font-semibold text-gray-900">
              {node.provider?.summary.api_key_configured ? "已配置" : "未配置"}
            </div>
          </div>
        </div>

        <details className="mt-4 rounded-lg border bg-gray-50 p-3">
          <summary className="cursor-pointer text-sm font-medium text-gray-700">开发信息</summary>
          <div className="mt-3 space-y-2 text-xs text-gray-500">
            <div>运行文件：{node.runtime_file}</div>
            <div>提示词文件：{node.prompt_file}</div>
          </div>
        </details>
      </section>

      <section className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-gray-900">模型配置</h3>
            <p className="mt-1 text-sm text-gray-500">
              展示当前实际生效的模型参数与来源，不再在页面直接暴露默认密钥。
            </p>
          </div>
          <button
            onClick={onTestConnection}
            disabled={testState?.status === "testing"}
            className="rounded-lg border px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            {testState?.status === "testing" ? "测试中..." : "连接测试"}
          </button>
        </div>

        {testState?.status && testState.status !== "idle" ? (
          <div
            className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
              testState.status === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : testState.status === "error"
                  ? "border-red-200 bg-red-50 text-red-700"
                  : "border-blue-200 bg-blue-50 text-blue-700"
            }`}
          >
            {testState.message}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-3">
          {sortedProviderFields.map((field) => (
            <div key={field.key} className="space-y-2 rounded-lg border bg-gray-50 p-4">
              <div className="flex items-center justify-between gap-2">
                <label className="text-sm font-medium text-gray-700">{field.label}</label>
                <Tag tone={field.source.mode === "custom" ? "success" : "warning"}>
                  {field.source.label}
                </Tag>
              </div>

              {field.key === "api_key" ? (
                node.config_mode === "custom" ? (
                  <div className="space-y-2">
                    <input
                      type="password"
                      value={apiKeyDraft}
                      placeholder={
                        field.configured
                          ? "已配置，留空表示保持当前密钥"
                          : "请输入新的 API Key"
                      }
                      onChange={(e) => {
                        onApiKeyDraftChange(e.target.value);
                        onProviderChange(field.key, e.target.value);
                      }}
                      className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
                    />
                    <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
                      <span>{field.status_text}</span>
                      <button
                        onClick={onClearApiKey}
                        className="rounded border px-2 py-1 text-xs text-gray-600 hover:bg-white"
                      >
                        清空密钥
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border bg-white px-3 py-2 text-sm text-gray-700">
                    {field.status_text}
                  </div>
                )
              ) : field.editable ? (
                <input
                  value={field.display_value || ""}
                  onChange={(e) => onProviderChange(field.key, e.target.value)}
                  className="w-full rounded-lg border bg-white px-3 py-2 text-sm"
                />
              ) : (
                <div className="rounded-lg border bg-white px-3 py-2 text-sm text-gray-700 break-all">
                  {field.display_value || "--"}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {node.behavior?.fields.length ? (
        <section className="rounded-xl border bg-white p-5 shadow-sm">
          <div className="mb-4">
            <h3 className="text-base font-semibold text-gray-900">行为配置</h3>
            <p className="mt-1 text-sm text-gray-500">
              字段按类型展示，避免所有配置都混在普通文本框里。
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {node.behavior.fields.map((field) => (
              <div key={field.key} className="space-y-2 rounded-lg border bg-gray-50 p-4">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <label className="text-sm font-medium text-gray-700">{field.label}</label>
                    {field.description ? (
                      <div className="mt-1 text-xs text-gray-500">{field.description}</div>
                    ) : null}
                  </div>
                  <Tag tone={field.source.mode === "custom" ? "success" : "warning"}>
                    {field.source.label}
                  </Tag>
                </div>
                <BehaviorInput
                  field={field}
                  disabled={!field.editable}
                  onChange={(value) => onBehaviorChange(field.key, value)}
                />
                <div className="text-[11px] text-gray-400">字段键：{field.key}</div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rounded-xl border bg-white p-5 shadow-sm">
        <div className="mb-4">
          <h3 className="text-base font-semibold text-gray-900">提示词配置</h3>
          <p className="mt-1 text-sm text-gray-500">
            可查看当前覆盖状态，并按节点或产物粒度管理提示词。
          </p>
        </div>

        <div className="space-y-4">
          {node.prompt ? (
            <PromptEditor
              prompt={node.prompt}
              onChange={(value) => onPromptChange(node.prompt!.id, value)}
              onReset={() => onPromptReset(node.prompt!.id)}
            />
          ) : null}

          {node.prompt_variants?.length ? (
            <div className="space-y-3">
              {node.prompt_variants.map((prompt) => (
                <details key={prompt.id} className="rounded-xl border bg-gray-50 p-4">
                  <summary className="cursor-pointer list-none">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <div className="text-sm font-semibold text-gray-900">
                          {prompt.label || prompt.id}
                        </div>
                        <Tag tone={prompt.overridden ? "primary" : "default"}>
                          {prompt.overridden ? "已覆盖默认" : "使用默认"}
                        </Tag>
                      </div>
                      <div className="text-xs text-gray-500">展开编辑</div>
                    </div>
                  </summary>
                  <div className="mt-4">
                    <PromptEditor
                      prompt={prompt}
                      onChange={(value) => onPromptChange(prompt.id, value)}
                      onReset={() => onPromptReset(prompt.id)}
                    />
                  </div>
                </details>
              ))}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

export default function SettingsPanel() {
  const location = useLocation();
  const initTab = (location.state as { tab?: TabId } | null)?.tab;
  const [activeTab, setActiveTab] = useState<TabId>(
    initTab && TABS.some((tab) => tab.id === initTab) ? initTab : "models",
  );
  const [workbench, setWorkbench] = useState<ModelWorkbenchResponse | null>(null);
  const [fastgpt, setFastgpt] = useState<FastGPTConfig>({ ...DEFAULT_FASTGPT });
  const [selectedNodeId, setSelectedNodeId] = useState("tracking_processor");
  const [modelNotice, setModelNotice] = useState<Notice>(null);
  const [fastgptNotice, setFastgptNotice] = useState<Notice>(null);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [fastgptLoading, setFastgptLoading] = useState(true);
  const [modelsSaving, setModelsSaving] = useState(false);
  const [fastgptSaving, setFastgptSaving] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [fastgptError, setFastgptError] = useState("");
  const [initialWorkbenchSnapshot, setInitialWorkbenchSnapshot] = useState("");
  const [initialFastgptSnapshot, setInitialFastgptSnapshot] = useState("");
  const [apiKeyDrafts, setApiKeyDrafts] = useState<Record<string, string>>({});
  const [nodeTestStates, setNodeTestStates] = useState<Record<string, NodeTestState>>({});

  const loadWorkbench = async () => {
    setModelsLoading(true);
    setModelsError("");
    try {
      const data = await getModelWorkbench();
      setWorkbench(data);
      setInitialWorkbenchSnapshot(serializeWorkbench(data));
      setApiKeyDrafts({});
      setNodeTestStates({});
      if (data.nodes.length > 0 && !data.nodes.some((node) => node.id === selectedNodeId)) {
        setSelectedNodeId(data.nodes[0].id);
      }
    } catch (e: any) {
      setModelsError(e.message || "加载失败");
    } finally {
      setModelsLoading(false);
    }
  };

  const loadFastgpt = async () => {
    setFastgptLoading(true);
    setFastgptError("");
    try {
      const data: any = await getSettings();
      const nextFastgpt = data.fastgpt ?? { ...DEFAULT_FASTGPT };
      setFastgpt(nextFastgpt);
      setInitialFastgptSnapshot(JSON.stringify(nextFastgpt));
    } catch (e: any) {
      setFastgptError(e.message || "加载失败");
    } finally {
      setFastgptLoading(false);
    }
  };

  useEffect(() => {
    loadWorkbench();
    loadFastgpt();
  }, []);

  const modelDirty = useMemo(
    () => serializeWorkbench(workbench) !== initialWorkbenchSnapshot,
    [workbench, initialWorkbenchSnapshot],
  );
  const fastgptDirty = useMemo(
    () => JSON.stringify(fastgpt) !== initialFastgptSnapshot,
    [fastgpt, initialFastgptSnapshot],
  );

  const groupedNodes = useMemo(() => {
    const groups = new Map<string, ModelNodeView[]>();
    for (const group of MODEL_GROUP_ORDER) groups.set(group, []);
    for (const node of workbench?.nodes ?? []) {
      const list = groups.get(node.group) ?? [];
      list.push(node);
      groups.set(node.group, list);
    }
    return MODEL_GROUP_ORDER.map((group) => [group, groups.get(group) ?? []] as const).filter(
      ([, nodes]) => nodes.length > 0,
    );
  }, [workbench]);

  const selectedNode = workbench?.nodes.find((node) => node.id === selectedNodeId) ?? null;

  const applyWorkbenchUpdate = (
    aiConfigUpdater: (current: Record<string, any>) => Record<string, any>,
    promptUpdater?: (current: Record<string, string>) => Record<string, string>,
  ) => {
    setWorkbench((prev) => {
      if (!prev) return prev;
      const nextAiConfig = aiConfigUpdater(cloneValue(prev.ai_config));
      const nextPromptOverrides = promptUpdater
        ? promptUpdater(cloneValue(prev.prompt_overrides))
        : cloneValue(prev.prompt_overrides);
      return rebuildWorkbenchView(prev, nextAiConfig, nextPromptOverrides);
    });
  };

  const resetNodeTestState = (nodeId: string) => {
    setNodeTestStates((prev) => {
      if (!prev[nodeId]) return prev;
      return { ...prev, [nodeId]: null };
    });
  };

  const handleProviderChange = (node: ModelNodeView, field: ModelProviderFieldView["key"], value: string) => {
    if (!node.config_key) return;
    resetNodeTestState(node.id);

    applyWorkbenchUpdate((currentAiConfig) => {
      const nextNodeConfig = { ...(currentAiConfig[node.config_key!] || {}) };
      if (field === "api_key") {
        if (!value && isFallbackNode(node)) {
          delete nextNodeConfig[field];
        } else {
          nextNodeConfig[field] = value;
        }
      } else if (value.trim()) {
        nextNodeConfig[field] = value.trim();
      } else {
        delete nextNodeConfig[field];
      }
      currentAiConfig[node.config_key!] = nextNodeConfig;
      return currentAiConfig;
    });
  };

  const handleClearApiKey = (node: ModelNodeView) => {
    if (!node.config_key) return;
    setApiKeyDrafts((prev) => ({ ...prev, [node.id]: "" }));
    resetNodeTestState(node.id);
    handleProviderChange(node, "api_key", "");
  };

  const handleBehaviorChange = (node: ModelNodeView, key: string, value: any) => {
    if (!node.config_key) return;
    resetNodeTestState(node.id);

    applyWorkbenchUpdate((currentAiConfig) => {
      const nextNodeConfig = { ...(currentAiConfig[node.config_key!] || {}) };
      if (value === "" || value === undefined) {
        delete nextNodeConfig[key];
      } else {
        nextNodeConfig[key] = value;
      }
      currentAiConfig[node.config_key!] = nextNodeConfig;
      return currentAiConfig;
    });
  };

  const handleEnableCustomConfig = (node: ModelNodeView) => {
    if (!workbench || !node.config_key) return;
    resetNodeTestState(node.id);
    const nodesById = getNodeMap(workbench.nodes);
    const nextNodeConfig: Record<string, any> = {
      base_url: resolveProviderFieldValue(nodesById, workbench.ai_config, node, "base_url").value,
      model: resolveProviderFieldValue(nodesById, workbench.ai_config, node, "model").value,
      api_key: resolveProviderFieldValue(nodesById, workbench.ai_config, node, "api_key").value,
    };

    for (const field of node.behavior?.fields ?? []) {
      nextNodeConfig[field.key] = resolveBehaviorFieldValue(
        nodesById,
        workbench.ai_config,
        node,
        field.key,
      ).value;
    }

    setApiKeyDrafts((prev) => ({ ...prev, [node.id]: "" }));
    applyWorkbenchUpdate((currentAiConfig) => ({
      ...currentAiConfig,
      [node.config_key!]: nextNodeConfig,
    }));
  };

  const handleResetNodeConfig = (node: ModelNodeView) => {
    if (!node.config_key) return;
    resetNodeTestState(node.id);
    setApiKeyDrafts((prev) => ({ ...prev, [node.id]: "" }));
    applyWorkbenchUpdate((currentAiConfig) => {
      if (isFallbackNode(node)) {
        currentAiConfig[node.config_key!] = {};
        return currentAiConfig;
      }

      const nextNodeConfig: Record<string, any> = {};
      for (const field of node.provider?.fields ?? []) {
        if (field.key === "api_key") {
          nextNodeConfig[field.key] = field.default_value || "";
        } else if (field.default_value) {
          nextNodeConfig[field.key] = field.default_value;
        }
      }
      for (const field of node.behavior?.fields ?? []) {
        if (field.default_value !== undefined) {
          nextNodeConfig[field.key] = cloneValue(field.default_value);
        }
      }
      currentAiConfig[node.config_key!] = nextNodeConfig;
      return currentAiConfig;
    });
  };

  const handlePromptChange = (promptId: string, value: string, defaultValue: string) => {
    applyWorkbenchUpdate(
      (currentAiConfig) => currentAiConfig,
      (currentPromptOverrides) => {
        const nextPromptOverrides = { ...currentPromptOverrides };
        if (!value.trim() || value === defaultValue) {
          delete nextPromptOverrides[promptId];
        } else {
          nextPromptOverrides[promptId] = value;
        }
        return nextPromptOverrides;
      },
    );
  };

  const handleTestNodeConnection = async (node: ModelNodeView) => {
    if (!workbench) return;
    setNodeTestStates((prev) => ({
      ...prev,
      [node.id]: { status: "testing", message: "正在测试当前节点的模型连接..." },
    }));
    try {
      const result = await testModelWorkbenchNode({
        node_id: node.id,
        ai_config: workbench.ai_config,
      });
      const modelName = result.provider?.model || "--";
      setNodeTestStates((prev) => ({
        ...prev,
        [node.id]: {
          status: "success",
          message: `${result.message}（模型：${modelName}）`,
        },
      }));
    } catch (e: any) {
      setNodeTestStates((prev) => ({
        ...prev,
        [node.id]: {
          status: "error",
          message: e.message || "连接测试失败",
        },
      }));
    }
  };

  const handleSaveModels = async () => {
    if (!workbench) return;
    setModelsSaving(true);
    setModelNotice(null);
    try {
      await saveModelWorkbench({
        ai_config: workbench.ai_config,
        prompt_overrides: workbench.prompt_overrides,
      });
      await loadWorkbench();
      setModelNotice({ type: "success", text: "模型与提示词设置已保存。" });
    } catch (e: any) {
      setModelNotice({ type: "error", text: `保存失败: ${e.message}` });
    } finally {
      setModelsSaving(false);
    }
  };

  const handleSaveFastgpt = async () => {
    setFastgptSaving(true);
    setFastgptNotice(null);
    try {
      const current = await getSettings();
      await saveSettings({ ...current, fastgpt } as any);
      setInitialFastgptSnapshot(JSON.stringify(fastgpt));
      setFastgptNotice({ type: "success", text: "FastGPT 设置已保存。" });
    } catch (e: any) {
      setFastgptNotice({ type: "error", text: `保存失败: ${e.message}` });
    } finally {
      setFastgptSaving(false);
    }
  };

  const summary = useMemo(() => {
    const nodes = workbench?.nodes ?? [];
    return {
      primaryCount: nodes.filter((node) => node.is_primary).length,
      customCount: nodes.filter((node) => node.config_mode === "custom").length,
      promptOverrideCount: nodes.reduce(
        (total, node) => total + (node.prompt_override_count || 0),
        0,
      ),
    };
  }, [workbench]);

  return (
    <div className="space-y-6">
      <div className="flex border-b">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`border-b-2 px-4 py-2 text-sm font-medium transition ${
              activeTab === tab.id
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "models" ? (
        <div className="space-y-5">
          <div className="rounded-xl border bg-white p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-xl font-bold text-gray-900">模型与提示词</h1>
                <p className="mt-1 text-sm text-gray-500">
                  统一查看节点的生效配置来源、行为参数与提示词覆盖状态。
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-lg border bg-gray-50 px-4 py-3">
                  <div className="text-xs font-medium text-gray-500">主链路节点</div>
                  <div className="mt-1 text-lg font-semibold text-gray-900">
                    {summary.primaryCount}
                  </div>
                </div>
                <div className="rounded-lg border bg-gray-50 px-4 py-3">
                  <div className="text-xs font-medium text-gray-500">独立配置节点</div>
                  <div className="mt-1 text-lg font-semibold text-gray-900">
                    {summary.customCount}
                  </div>
                </div>
                <div className="rounded-lg border bg-gray-50 px-4 py-3">
                  <div className="text-xs font-medium text-gray-500">已覆盖提示词</div>
                  <div className="mt-1 text-lg font-semibold text-gray-900">
                    {summary.promptOverrideCount}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <NoticeBanner notice={modelNotice} />

          {modelsLoading ? (
            <div className="rounded-xl border bg-white p-8 text-sm text-gray-500 shadow-sm">
              模型设置加载中...
            </div>
          ) : modelsError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
              <div>加载失败：{modelsError}</div>
              <button
                onClick={loadWorkbench}
                className="mt-3 rounded border border-red-200 bg-white px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
              >
                重试
              </button>
            </div>
          ) : (
            <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
              <aside className="sticky top-6 h-fit rounded-xl border bg-white p-4 shadow-sm">
                <div className="mb-4 border-b pb-3">
                  <div className="text-sm font-semibold text-gray-900">节点导航</div>
                  <div className="mt-1 text-xs text-gray-500">
                    按业务链路分组展示当前仍在使用的节点。
                  </div>
                </div>

                <div className="space-y-4">
                  {groupedNodes.map(([group, nodes]) => {
                    return (
                      <div key={group} className="space-y-2">
                        <div className="flex items-center justify-between gap-2 px-1">
                          <div className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                            {group}
                          </div>
                        </div>

                        <div className="space-y-2">
                          {nodes.map((node) => (
                            <button
                              key={node.id}
                              onClick={() => setSelectedNodeId(node.id)}
                              className={`w-full rounded-xl border px-3 py-3 text-left transition ${
                                selectedNodeId === node.id
                                  ? "border-blue-200 bg-blue-50 text-blue-700 shadow-sm"
                                  : "border-gray-100 bg-gray-50 text-gray-700 hover:border-gray-200 hover:bg-gray-100"
                              }`}
                            >
                              <div className="flex items-start justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="truncate text-sm font-medium">{node.label}</div>
                                  <div className="mt-1 text-[11px] text-gray-500">
                                    {node.source_badge || "--"}
                                  </div>
                                </div>
                                {node.prompt_override_count ? (
                                  <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-blue-700">
                                    {node.prompt_override_count}
                                  </span>
                                ) : null}
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </aside>

              <section className="min-w-0">
                {selectedNode ? (
                  <NodePanel
                    node={selectedNode}
                    apiKeyDraft={apiKeyDrafts[selectedNode.id] || ""}
                    testState={nodeTestStates[selectedNode.id] || null}
                    onApiKeyDraftChange={(value) =>
                      setApiKeyDrafts((prev) => ({ ...prev, [selectedNode.id]: value }))
                    }
                    onProviderChange={(field, value) => handleProviderChange(selectedNode, field, value)}
                    onClearApiKey={() => handleClearApiKey(selectedNode)}
                    onBehaviorChange={(key, value) => handleBehaviorChange(selectedNode, key, value)}
                    onPromptChange={(promptId, value) => {
                      const prompt =
                        selectedNode.prompt?.id === promptId
                          ? selectedNode.prompt
                          : selectedNode.prompt_variants?.find((item) => item.id === promptId);
                      if (!prompt) return;
                      handlePromptChange(promptId, value, prompt.default);
                    }}
                    onPromptReset={(promptId) => {
                      const prompt =
                        selectedNode.prompt?.id === promptId
                          ? selectedNode.prompt
                          : selectedNode.prompt_variants?.find((item) => item.id === promptId);
                      if (!prompt) return;
                      handlePromptChange(promptId, prompt.default, prompt.default);
                    }}
                    onEnableCustomConfig={() => handleEnableCustomConfig(selectedNode)}
                    onResetNodeConfig={() => handleResetNodeConfig(selectedNode)}
                    onTestConnection={() => handleTestNodeConnection(selectedNode)}
                  />
                ) : null}
              </section>
            </div>
          )}

          <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-white/95 px-5 py-4 shadow-lg backdrop-blur">
            <div className="text-sm text-gray-500">
              {modelDirty ? "当前模型配置有未保存修改" : "当前模型配置已保存"}
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={loadWorkbench}
                disabled={modelsLoading || modelsSaving}
                className="rounded-lg border px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                放弃未保存修改
              </button>
              <button
                onClick={handleSaveModels}
                disabled={modelsSaving || !workbench || !modelDirty}
                className="rounded-lg bg-blue-600 px-5 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {modelsSaving ? "保存中..." : "保存模型与提示词"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {activeTab === "tools" ? <ToolSettingsPanel /> : null}

      {activeTab === "fastgpt" ? (
        <div className="space-y-6">
          <div>
            <h2 className="text-xl font-bold">FastGPT</h2>
            <p className="mt-1 text-sm text-gray-500">管理知识库推送开关与连接参数。</p>
          </div>

          <NoticeBanner notice={fastgptNotice} />

          {fastgptLoading ? (
            <div className="rounded-xl border bg-white p-8 text-sm text-gray-500 shadow-sm">
              FastGPT 设置加载中...
            </div>
          ) : fastgptError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-700">
              <div>加载失败：{fastgptError}</div>
              <button
                onClick={loadFastgpt}
                className="mt-3 rounded border border-red-200 bg-white px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
              >
                重试
              </button>
            </div>
          ) : (
            <>
              <div className="space-y-4 rounded-xl border bg-white p-5 shadow-sm">
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={fastgpt.enabled}
                    onChange={(e) => setFastgpt((prev) => ({ ...prev, enabled: e.target.checked }))}
                  />
                  启用自动推送
                </label>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-1 md:col-span-2">
                    <label className="text-xs text-gray-500">API URL</label>
                    <input
                      value={fastgpt.api_url}
                      onChange={(e) => setFastgpt((prev) => ({ ...prev, api_url: e.target.value }))}
                      className="w-full rounded border px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-gray-500">API Key</label>
                    <input
                      type="password"
                      value={fastgpt.api_key}
                      onChange={(e) => setFastgpt((prev) => ({ ...prev, api_key: e.target.value }))}
                      className="w-full rounded border px-3 py-2 text-sm"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-xs text-gray-500">Dataset ID</label>
                    <input
                      value={fastgpt.dataset_id}
                      onChange={(e) =>
                        setFastgpt((prev) => ({ ...prev, dataset_id: e.target.value }))
                      }
                      className="w-full rounded border px-3 py-2 text-sm"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-3 rounded-xl border bg-white px-5 py-4 shadow-sm">
                <div className="text-sm text-gray-500">
                  {fastgptDirty ? "FastGPT 配置有未保存修改" : "FastGPT 配置已保存"}
                </div>
                <button
                  onClick={handleSaveFastgpt}
                  disabled={fastgptSaving || !fastgptDirty}
                  className="rounded-lg bg-blue-600 px-5 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {fastgptSaving ? "保存中..." : "保存 FastGPT 设置"}
                </button>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
