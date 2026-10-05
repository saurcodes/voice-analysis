import { useState } from "react";
import { Link } from "react-router";
import { Folder, FolderOpen, WarningCircle } from "@phosphor-icons/react";
import { ApiError } from "@/api/client";
import { useDriveFiles } from "@/api/hooks";
import type { components } from "@/api/types";
import { formatDateTime } from "@/lib/dates";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

type DriveFileOut = components["schemas"]["DriveFileOut"];

interface Crumb {
  id: string;
  name: string;
}

const ROOT_CRUMB: Crumb = { id: "", name: "My Drive" };

const COLUMNS = ["Select", "Name", "Modified", "Size"] as const;

function formatSize(bytes: number | null): string {
  if (bytes === null) return "-";
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export interface DriveBrowserProps {
  selected: DriveFileOut[];
  onChange: (selected: DriveFileOut[]) => void;
  /** The parent controls when the list is actually fetched (e.g. only while the drawer and
   * the Drive tab are both open), so switching tabs or closing the drawer doesn't keep
   * polling Google in the background. */
  enabled?: boolean;
}

/** Shared header row for both the loading-skeleton table and the real results table. */
function DriveTableHeader() {
  return (
    <TableHeader>
      <TableRow>
        {COLUMNS.map((column) => (
          <TableHead key={column} className={column === "Select" ? "w-8" : undefined}>
            {column === "Select" ? <span className="sr-only">Select</span> : column}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  );
}

/**
 * Lists the signed-in user's Drive files in a folder (root by default) for multi-select in
 * the Analyse drawer. Selection is fully controlled: this component never holds its own copy
 * of the picked files, so it survives folder changes and tab switches without losing or
 * duplicating a selection made earlier.
 */
export function DriveBrowser({ selected, onChange, enabled = true }: DriveBrowserProps) {
  const [folderInput, setFolderInput] = useState("");
  const [breadcrumb, setBreadcrumb] = useState<Crumb[]>([ROOT_CRUMB]);
  const activeFolder = breadcrumb[breadcrumb.length - 1].id;
  const filesQuery = useDriveFiles(activeFolder || "root", { enabled });

  const selectedIds = new Set(selected.map((file) => file.id));
  const files: DriveFileOut[] = filesQuery.data ?? [];
  // Folders first, so the browsable structure reads before the selectable files.
  const orderedFiles = [...files.filter((f) => f.is_folder), ...files.filter((f) => !f.is_folder)];

  /** The manual "Folder id" input is a power-user override: it jumps straight to an arbitrary
   * folder id without knowing its name, so the breadcrumb after it can only show the id. */
  function browse() {
    const id = folderInput.trim();
    setBreadcrumb(id ? [ROOT_CRUMB, { id, name: id }] : [ROOT_CRUMB]);
  }

  function navigateIntoFolder(folder: DriveFileOut) {
    setBreadcrumb((prev) => [...prev, { id: folder.id, name: folder.name }]);
    setFolderInput("");
  }

  function navigateToCrumb(index: number) {
    setBreadcrumb((prev) => prev.slice(0, index + 1));
    setFolderInput("");
  }

  function toggle(file: DriveFileOut) {
    if (selectedIds.has(file.id)) {
      onChange(selected.filter((f) => f.id !== file.id));
    } else {
      onChange([...selected, file]);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <nav aria-label="Drive folder" className="flex flex-wrap items-center gap-1 text-sm">
        {breadcrumb.map((crumb, i) => {
          const isCurrent = i === breadcrumb.length - 1;
          return (
            <span key={`${crumb.id}-${i}`} className="flex items-center gap-1">
              {i > 0 && (
                <span className="text-muted-foreground" aria-hidden="true">
                  /
                </span>
              )}
              <button
                type="button"
                className={cn(
                  "rounded-sm",
                  isCurrent
                    ? "font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground hover:underline",
                )}
                onClick={() => navigateToCrumb(i)}
                disabled={isCurrent}
              >
                {crumb.name}
              </button>
            </span>
          );
        })}
      </nav>

      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="drive-folder-id">Folder id</Label>
          <Input
            id="drive-folder-id"
            value={folderInput}
            onChange={(event) => setFolderInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                browse();
              }
            }}
            placeholder="root"
          />
        </div>
        {selected.length > 0 && (
          <p className="pb-2 text-sm whitespace-nowrap text-muted-foreground">
            <span className="num">{selected.length}</span> selected
          </p>
        )}
        <Button type="button" variant="outline" onClick={browse}>
          <FolderOpen weight="regular" className="size-4" />
          Browse
        </Button>
      </div>

      {filesQuery.isLoading ? (
        <Table>
          <DriveTableHeader />
          <TableBody>
            {Array.from({ length: 3 }, (_, i) => (
              <TableRow key={i}>
                {COLUMNS.map((column) => (
                  <TableCell key={column}>
                    <Skeleton className="h-4 w-full max-w-24" />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : filesQuery.isError ? (
        <DriveBrowserError error={filesQuery.error} />
      ) : files.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No audio or video files in this folder
        </p>
      ) : (
        <Table>
          <DriveTableHeader />
          <TableBody>
            {orderedFiles.map((file) =>
              file.is_folder ? (
                <TableRow key={file.id}>
                  <TableCell />
                  <TableCell className="max-w-48 font-medium">
                    <button
                      type="button"
                      className="flex items-center gap-1.5 truncate hover:underline"
                      onClick={() => navigateIntoFolder(file)}
                    >
                      <Folder weight="regular" className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <span className="truncate">{file.name}</span>
                    </button>
                  </TableCell>
                  <TableCell>{formatDateTime(file.modified_time)}</TableCell>
                  <TableCell>
                    <span className="text-muted-foreground">-</span>
                  </TableCell>
                </TableRow>
              ) : (
                <TableRow key={file.id} data-state={selectedIds.has(file.id) ? "selected" : undefined}>
                  <TableCell>
                    <Checkbox
                      checked={selectedIds.has(file.id)}
                      onCheckedChange={() => toggle(file)}
                      aria-label={`Select ${file.name}`}
                    />
                  </TableCell>
                  <TableCell className="max-w-48 truncate font-medium">{file.name}</TableCell>
                  <TableCell>{formatDateTime(file.modified_time)}</TableCell>
                  <TableCell>
                    {file.size === null ? (
                      <span className="text-muted-foreground">{formatSize(file.size)}</span>
                    ) : (
                      <span className="num text-muted-foreground">{formatSize(file.size)}</span>
                    )}
                  </TableCell>
                </TableRow>
              ),
            )}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function DriveBrowserError({ error }: { error: unknown }) {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return (
        <p className="flex items-center justify-center gap-1.5 py-8 text-center text-sm text-muted-foreground">
          <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
          <Link to="/settings" className="font-medium text-primary hover:underline">
            Connect Google Drive in Settings
          </Link>
        </p>
      );
    }
    if (error.status === 503) {
      return (
        <p className="py-8 text-center text-sm text-muted-foreground">
          Google Drive is not configured on this server
        </p>
      );
    }
    if (error.status === 404) {
      return <p className="py-8 text-center text-sm text-muted-foreground">Folder not found</p>;
    }
    return (
      <p className="flex items-center justify-center gap-1.5 py-8 text-center text-sm text-serious">
        <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
        {typeof error.detail === "string" ? error.detail : error.message}
      </p>
    );
  }
  return (
    <p className="flex items-center justify-center gap-1.5 py-8 text-center text-sm text-serious">
      <WarningCircle weight="regular" className="size-4 shrink-0" aria-hidden="true" />
      Something went wrong. Try again.
    </p>
  );
}
