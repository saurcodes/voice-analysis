import { useState } from "react";
import { useNavigate } from "react-router";
import { AppShell } from "@/components/AppShell";
import { AnalyseDrawer } from "@/components/library/AnalyseDrawer";
import { AnalysesTable } from "@/components/library/AnalysesTable";
import { JobsPanel } from "@/components/library/JobsPanel";
import { Button } from "@/components/ui/button";

export function LibraryPage() {
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [trackedJobIds, setTrackedJobIds] = useState<string[]>([]);

  function toggleSelected(id: string) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function handleDrawerOpenChange(open: boolean) {
    setDrawerOpen(open);
    if (!open) setTrackedJobIds([]);
  }

  return (
    <AppShell>
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold tracking-tight">Library</h1>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={selectedIds.length < 2}
            onClick={() => navigate(`/compare?ids=${selectedIds.join(",")}`)}
          >
            Compare
          </Button>
          <Button type="button" onClick={() => setDrawerOpen(true)}>
            Analyse
          </Button>
        </div>
      </div>

      <div className="mt-6">
        <JobsPanel excludeIds={trackedJobIds} />
        <AnalysesTable
          selectedIds={selectedIds}
          onToggleSelected={toggleSelected}
          onAnalyseClick={() => setDrawerOpen(true)}
        />
      </div>

      <AnalyseDrawer
        open={drawerOpen}
        onOpenChange={handleDrawerOpenChange}
        onJobsCreated={(ids) => setTrackedJobIds((prev) => [...prev, ...ids])}
      />
    </AppShell>
  );
}
