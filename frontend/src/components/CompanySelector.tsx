import { useState } from "react";
import type { Company } from "../types";

interface Props {
  companies: Company[];
  selected: string | null;
  onSelect: (bdCode: string) => void;
}

export default function CompanySelector({ companies, selected, onSelect }: Props) {
  const [search, setSearch] = useState("");

  const filtered = companies.filter(
    (c) =>
      c.company_name.includes(search) ||
      c.project_name.includes(search) ||
      c.bd_code.includes(search),
  );

  return (
    <div>
      <input
        type="text"
        placeholder="搜索项目名称、主体或编码..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full border rounded px-3 py-2 mb-3 text-sm"
      />
      <div className="max-h-64 overflow-y-auto border rounded">
        {filtered.length === 0 && (
          <p className="text-gray-400 text-sm text-center py-4">无匹配结果</p>
        )}
        {filtered.map((c) => (
          <button
            key={c.bd_code}
            onClick={() => onSelect(c.bd_code)}
            className={`w-full text-left px-3 py-2 text-sm border-b last:border-b-0 transition
              ${selected === c.bd_code ? "bg-blue-50 text-blue-700 font-medium" : "hover:bg-gray-50"}`}
          >
            <span className="text-gray-400 mr-2">{c.bd_code}</span>
            <span className="font-medium">{c.project_name}</span>
            <span className="text-gray-400 ml-2 text-xs">({c.company_name})</span>
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-400 mt-1">共 {companies.length} 个项目</p>
    </div>
  );
}
