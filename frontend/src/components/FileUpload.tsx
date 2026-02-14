import { useCallback, useState } from "react";

interface Props {
  label: string;
  accept: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export default function FileUpload({ label, accept, multiple, onFiles, disabled }: Props) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files);
      onFiles(files);
    },
    [onFiles, disabled],
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        onFiles(Array.from(e.target.files));
        e.target.value = "";
      }
    },
    [onFiles],
  );

  return (
    <label
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`
        block border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition
        ${dragging ? "border-blue-500 bg-blue-50" : "border-gray-300 hover:border-gray-400"}
        ${disabled ? "opacity-50 cursor-not-allowed" : ""}
      `}
    >
      <p className="text-gray-600 mb-1">{label}</p>
      <p className="text-xs text-gray-400">拖拽文件到此处，或点击选择</p>
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        onChange={handleChange}
        disabled={disabled}
        className="hidden"
      />
    </label>
  );
}
