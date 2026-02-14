import { getDownloadUrl } from "../api/client";

interface Props {
  reportId: string;
  content: string;
}

export default function ReportActions({ reportId, content }: Props) {
  const handleCopy = () => {
    navigator.clipboard.writeText(content);
  };

  const handlePrint = () => {
    window.print();
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
      <button
        onClick={handleCopy}
        className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
      >
        复制内容
      </button>
      <button
        onClick={handlePrint}
        className="px-4 py-2 bg-gray-200 text-gray-700 text-sm rounded hover:bg-gray-300"
      >
        打印
      </button>
    </div>
  );
}
