import { useState } from "react";
import type { Company } from "../types";

interface Props {
  companies: Company[];
  selected: Set<string>;
  onToggle: (bdCode: string) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
}

export default function CompanySelectorMulti({
  companies,
  selected,
  onToggle,
  onSelectAll,
  onClearAll,
}: Props) {
  const [search, setSearch] = useState("");

  const filtered = companies.filter(
    (c) =>
      c.company_name.includes(search) ||
      c.project_name.includes(search) ||
      c.bd_code.includes(search),
  );

  const allFilteredSelected = filtered.length > 0 && filtered.every((c) => selected.has(c.bd_code));

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <input
          type="text"
          placeholder="搜索项目名称、主体或编码..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 border rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-300"
        />
        <button
          onClick={allFilteredSelected ? onClearAll : onSelectAll}
          className="px-3 py-2 text-sm border rounded hover:bg-gray-50"
        >
          {allFilteredSelected ? "取消全选" : "全选"}
        </button>
      </div>
      <div className="max-h-64 overflow-y-auto border rounded">
        {filtered.length === 0 && (
          <p className="text-gray-400 text-sm text-center py-4">无匹配结果</p>
        )}
        {filtered.map((c) => {
          const isSelected = selected.has(c.bd_code);
          return (
            <button
              key={c.bd_code}
              onClick={() => onToggle(c.bd_code)}
              className={`w-full text-left px-3 py-2 text-sm border-b last:border-b-0 transition flex items-center gap-2
                ${isSelected ? "bg-blue-50" : "hover:bg-gray-50"}`}
            >
              <input
                type="checkbox"
                checked={isSelected}
                onChange={() => {}}
                className="rounded"
              />
              <span className="text-gray-400">{c.bd_code}</span>
              <span className={`font-medium ${isSelected ? "text-blue-700" : ""}`}>
                {c.project_name}
              </span>
              <span className="text-gray-400 text-xs">({c.company_name})</span>
            </button>
          );
        })}
      </div>
      <p className="text-xs text-gray-400 mt-1">
        已选 {selected.size} / {companies.length} 个项目
      </p>
    </div>
  );
}
