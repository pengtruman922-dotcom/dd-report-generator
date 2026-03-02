import { useNavigate } from "react-router-dom";
import { getDownloadUrl, getPdfDownloadUrl } from "../api/client";

interface Props {
  reportId: string;
  content: string;
}

export default function ReportActions({ reportId, content }: Props) {
  const navigate = useNavigate();

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
  };

  return (
    <div className="flex gap-3">
      <a
        href={getDownloadUrl(reportId)}
        download
        className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
      >
        下载 .md
      </a>
      <a
        href={getPdfDownloadUrl(reportId)}
        download
        className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
      >
        下载 PDF
      </a>
      <button
        onClick={handleCopy}
        className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
      >
        复制内容
      </button>
      <button
        onClick={() => navigate("/settings", { state: { tab: "fastgpt" } })}
        className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700"
      >
        推送到知识库
      </button>
    </div>
  );
}
