import { useCallback, useState } from "react";

interface Props {
  label: string;
  accept: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  hint?: string;
}

export default function FileUpload({ label, accept, multiple, onFiles, disabled, hint }: Props) {
  const [dragging, setDragging] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files);
      setSelectedFiles(files);
      onFiles(files);
    },
    [onFiles, disabled],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        const files = Array.from(e.target.files);
        setSelectedFiles(files);
        onFiles(files);
        e.target.value = "";
      }
    },
    [onFiles],
  );

  const handleClear = useCallback(() => {
    setSelectedFiles([]);
  }, []);

  return (
    <div>
      <label
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`
          block border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all
          ${dragging ? "border-blue-500 bg-blue-50 scale-[1.02]" : "border-gray-300 hover:border-gray-400"}
          ${disabled ? "opacity-50 cursor-not-allowed" : ""}
        `}
      >
        {/* Upload Icon */}
        <svg className="w-12 h-12 mx-auto mb-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
        </svg>

        <p className="text-gray-600 mb-1 font-medium">{label}</p>
        <p className="text-xs text-gray-400 mb-1">拖拽文件到此处，或点击选择</p>
        {hint && <p className="text-xs text-gray-500 mt-2">{hint}</p>}

        <input
          type="file"
          accept={accept}
          multiple={multiple}
          onChange={handleChange}
          disabled={disabled}
          className="hidden"
        />
      </label>

      {/* Selected files display */}
      {selectedFiles.length > 0 && (
        <div className="mt-3 space-y-2">
          {selectedFiles.map((file, i) => (
            <div key={i} className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <svg className="w-4 h-4 text-blue-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span className="truncate text-gray-700">{file.name}</span>
                <span className="text-gray-400 text-xs flex-shrink-0">
                  ({(file.size / 1024).toFixed(1)} KB)
                </span>
              </div>
              <button
                onClick={handleClear}
                className="ml-2 text-gray-400 hover:text-red-500 transition flex-shrink-0"
                title="清除"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
