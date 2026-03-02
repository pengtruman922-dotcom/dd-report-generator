import { useEffect, useState } from "react";
import { getToolProviders, getToolsConfig, saveToolsConfig } from "../api/client";
import type { ToolProviderInfo, ToolsConfig, ToolConfigField } from "../types";

const DEFAULT_TOOLS: ToolsConfig = {
  search: { active_provider: "duckduckgo", providers: {} },
  scraper: { active_provider: "jina_reader", providers: {} },
  datasource: { active_providers: [], providers: {} },
};

interface ProviderMap {
  search: ToolProviderInfo[];
  scraper: ToolProviderInfo[];
  datasource: ToolProviderInfo[];
}

function ConfigFields({
  schema,
  values,
  onChange,
}: {
  schema: ToolConfigField[];
  values: Record<string, any>;
  onChange: (key: string, val: any) => void;
}) {
  if (!schema.length) return <p className="text-xs text-gray-400">无需配置</p>;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">
      {schema.map((f) => (
        <div key={f.key}>
          <label className="text-xs text-gray-500">
            {f.label}
            {f.required && <span className="text-red-500 ml-0.5">*</span>}
          </label>
          <input
            type={f.type === "password" ? "password" : f.type === "number" ? "number" : "text"}
            value={values[f.key] ?? f.default ?? ""}
            onChange={(e) =>
              onChange(f.key, f.type === "number" ? Number(e.target.value) : e.target.value)
            }
            className="w-full border rounded px-3 py-1.5 text-sm"
            placeholder={f.description}
          />
        </div>
      ))}
    </div>
  );
}

export default function ToolSettingsPanel() {
  const [providers, setProviders] = useState<ProviderMap>({
    search: [],
    scraper: [],
    datasource: [],
  });
  const [config, setConfig] = useState<ToolsConfig>(DEFAULT_TOOLS);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    Promise.all([getToolProviders(), getToolsConfig()])
      .then(([prov, cfg]) => {
        setProviders(prov as unknown as ProviderMap);
        if (cfg && Object.keys(cfg).length > 0) {
          setConfig({
            search: { ...DEFAULT_TOOLS.search, ...cfg.search },
            scraper: { ...DEFAULT_TOOLS.scraper, ...cfg.scraper },
            datasource: { ...DEFAULT_TOOLS.datasource, ...cfg.datasource },
          });
        }
      })
      .catch(() => {});
  }, []);

  const updateProviderConfig = (
    toolType: keyof ToolsConfig,
    providerId: string,
    key: string,
    value: any,
  ) => {
    setConfig((prev) => ({
      ...prev,
      [toolType]: {
        ...prev[toolType],
        providers: {
          ...prev[toolType].providers,
          [providerId]: {
            ...(prev[toolType].providers[providerId] || {}),
            [key]: value,
          },
        },
      },
    }));
  };

  const setActiveProvider = (toolType: "search" | "scraper", providerId: string) => {
    setConfig((prev) => ({
      ...prev,
      [toolType]: { ...prev[toolType], active_provider: providerId },
    }));
  };

  const toggleDatasource = (providerId: string) => {
    setConfig((prev) => {
      const current = prev.datasource.active_providers || [];
      const next = current.includes(providerId)
        ? current.filter((id) => id !== providerId)
        : [...current, providerId];
      return {
        ...prev,
        datasource: { ...prev.datasource, active_providers: next },
      };
    });
  };

  const validateConfig = (): string[] => {
    const warnings: string[] = [];
    // Check search provider required fields
    const searchId = config.search.active_provider || "";
    const searchProv = providers.search.find((p) => p.provider_id === searchId);
    if (searchProv) {
      for (const f of searchProv.config_schema) {
        if (f.required && !config.search.providers[searchId]?.[f.key]) {
          warnings.push(`搜索引擎「${searchProv.display_name}」需要填写 ${f.label}`);
        }
      }
    }
    // Check scraper provider required fields
    const scraperId = config.scraper.active_provider || "";
    const scraperProv = providers.scraper.find((p) => p.provider_id === scraperId);
    if (scraperProv) {
      for (const f of scraperProv.config_schema) {
        if (f.required && !config.scraper.providers[scraperId]?.[f.key]) {
          warnings.push(`网页抓取器「${scraperProv.display_name}」需要填写 ${f.label}`);
        }
      }
    }
    // Check datasource providers
    for (const dsId of config.datasource.active_providers || []) {
      const dsProv = providers.datasource.find((p) => p.provider_id === dsId);
      if (dsProv) {
        for (const f of dsProv.config_schema) {
          if (f.required && !config.datasource.providers[dsId]?.[f.key]) {
            warnings.push(`数据源「${dsProv.display_name}」需要填写 ${f.label}`);
          }
        }
      }
    }
    return warnings;
  };

  const handleSave = async () => {
    const warnings = validateConfig();
    if (warnings.length > 0) {
      setMessage("⚠️ " + warnings.join("；"));
      // Still allow saving, but show warning — user might want to save partial config
      const proceed = window.confirm(
        "以下配置不完整，生成报告时会报错：\n\n" + warnings.join("\n") + "\n\n是否仍然保存？"
      );
      if (!proceed) return;
    }
    setSaving(true);
    setMessage("");
    try {
      await saveToolsConfig(config);
      setMessage("保存成功");
    } catch (e: any) {
      setMessage("保存失败: " + e.message);
    }
    setSaving(false);
  };

  const renderSingleSelect = (
    toolType: "search" | "scraper",
    label: string,
    desc: string,
  ) => {
    const items = providers[toolType];
    const active = config[toolType].active_provider || "";
    return (
      <div className="bg-white rounded-lg shadow p-5 space-y-3">
        <div>
          <h3 className="font-semibold">{label}</h3>
          <p className="text-xs text-gray-400">{desc}</p>
        </div>
        <div className="space-y-3">
          {items.map((p) => (
            <div
              key={p.provider_id}
              className={`border rounded-lg p-3 cursor-pointer transition ${
                active === p.provider_id
                  ? "border-blue-500 bg-blue-50"
                  : "border-gray-200 hover:border-gray-300"
              }`}
              onClick={() => setActiveProvider(toolType, p.provider_id)}
            >
              <div className="flex items-center gap-2">
                <input
                  type="radio"
                  name={toolType}
                  checked={active === p.provider_id}
                  onChange={() => setActiveProvider(toolType, p.provider_id)}
                  className="w-4 h-4"
                />
                <span className="font-medium text-sm">{p.display_name}</span>
                <span className="text-xs text-gray-400">{p.description}</span>
              </div>
              {active === p.provider_id && p.config_schema.length > 0 && (
                <ConfigFields
                  schema={p.config_schema}
                  values={config[toolType].providers[p.provider_id] || {}}
                  onChange={(k, v) => updateProviderConfig(toolType, p.provider_id, k, v)}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">搜索工具设置</h2>
      <p className="text-sm text-gray-500">
        配置研究步骤使用的搜索引擎、网页抓取器和数据源。
      </p>

      {renderSingleSelect("search", "搜索引擎", "选择联网研究使用的搜索引擎（单选）")}
      {renderSingleSelect("scraper", "网页抓取器", "选择网页内容抓取方式（单选）")}

      {/* Datasource: multi-select */}
      <div className="bg-white rounded-lg shadow p-5 space-y-3">
        <div>
          <h3 className="font-semibold">数据源</h3>
          <p className="text-xs text-gray-400">可同时启用多个数据源（多选）。标记「仅上市公司」的数据源在研究非上市公司时会自动跳过。</p>
        </div>
        <div className="space-y-3">
          {providers.datasource.map((p) => {
            const checked = (config.datasource.active_providers || []).includes(p.provider_id);
            return (
              <div
                key={p.provider_id}
                className={`border rounded-lg p-3 cursor-pointer transition ${
                  checked ? "border-green-500 bg-green-50" : "border-gray-200 hover:border-gray-300"
                }`}
                onClick={() => toggleDatasource(p.provider_id)}
              >
                <div className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleDatasource(p.provider_id)}
                    className="w-4 h-4 rounded"
                  />
                  <span className="font-medium text-sm">{p.display_name}</span>
                  {p.target_company_type === "listed" && (
                    <span className="text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded">
                      仅上市公司
                    </span>
                  )}
                  {p.target_company_type === "unlisted" && (
                    <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">
                      仅非上市公司
                    </span>
                  )}
                  <span className="text-xs text-gray-400">{p.description}</span>
                </div>
                {checked && p.config_schema.length > 0 && (
                  <ConfigFields
                    schema={p.config_schema}
                    values={config.datasource.providers[p.provider_id] || {}}
                    onChange={(k, v) => updateProviderConfig("datasource", p.provider_id, k, v)}
                  />
                )}
              </div>
            );
          })}
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
