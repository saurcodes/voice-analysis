import { useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { UploadSimple, WarningCircle, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ACCEPTED_EXTENSIONS = [".m4a", ".mp3", ".wav", ".mov", ".mp4"];
const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.join(",");

function isAccepted(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/**
 * Multi-file drag/drop + click-to-browse picker. Controlled: the parent owns the accepted
 * file list (`files`); this component only ever adds to or removes from it, and tracks its
 * own transient drag-over and client-side-rejection state.
 */
export function UploadDropzone({
  files,
  onFilesChange,
  disabled,
}: {
  files: File[];
  onFilesChange: (files: File[]) => void;
  disabled?: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [rejectedNames, setRejectedNames] = useState<string[]>([]);

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    const accepted = incoming.filter(isAccepted);
    const rejected = incoming.filter((file) => !isAccepted(file));
    if (accepted.length > 0) onFilesChange([...files, ...accepted]);
    setRejectedNames(rejected.map((file) => file.name));
  }

  function openPicker() {
    if (!disabled) inputRef.current?.click();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragOver(false);
    if (disabled) return;
    addFiles(event.dataTransfer.files);
  }

  function removeFile(index: number) {
    onFilesChange(files.filter((_, i) => i !== index));
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        onClick={openPicker}
        onKeyDown={handleKeyDown}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center text-sm outline-none transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50",
          dragOver ? "border-primary bg-primary/5" : "border-border",
          disabled && "pointer-events-none opacity-50",
        )}
      >
        <UploadSimple weight="regular" className="size-6 text-muted-foreground" />
        <p className="text-muted-foreground">Drag and drop recordings here, or click to browse.</p>
        <p className="text-xs text-muted-foreground">.m4a, .mp3, .wav, .mov, .mp4</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT_ATTR}
          disabled={disabled}
          className="hidden"
          aria-label="Choose recordings"
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
        />
      </div>

      {rejectedNames.length > 0 && (
        <p role="alert" className="flex items-center gap-1.5 text-sm text-serious">
          <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
          Unsupported file type: {rejectedNames.join(", ")}
        </p>
      )}

      {files.length > 0 && (
        <ul className="flex flex-col gap-2">
          {files.map((file, index) => (
            <li
              key={`${file.name}-${file.lastModified}-${index}`}
              className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
            >
              <span className="truncate">{file.name}</span>
              <div className="flex items-center gap-2">
                <span className="num text-muted-foreground">{formatSize(file.size)}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`Remove ${file.name}`}
                  disabled={disabled}
                  onClick={() => removeFile(index)}
                >
                  <X weight="regular" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
