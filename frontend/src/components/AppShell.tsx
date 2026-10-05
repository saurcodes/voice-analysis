import { useState, type ReactNode } from "react";
import { NavLink } from "react-router";
import { List, Monitor, Moon, Sun } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { UserMenu } from "@/auth/UserMenu";
import type { Theme } from "@/lib/theme";
import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Library" },
  { to: "/compare", label: "Compare" },
  { to: "/settings", label: "Settings" },
] as const;

const THEME_CYCLE: Record<Theme, Theme> = {
  system: "light",
  light: "dark",
  dark: "system",
};

const THEME_ICON: Record<Theme, typeof Sun> = {
  system: Monitor,
  light: Sun,
  dark: Moon,
};

/** Cycles system -> light -> dark -> system. Reused as-is in SettingsPage's Theme section. */
export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const Icon = THEME_ICON[theme];

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      aria-label={`Theme: ${theme}. Click to change.`}
      onClick={() => setTheme(THEME_CYCLE[theme])}
    >
      <Icon weight="regular" className="size-5" />
    </Button>
  );
}

/** The three nav links, shared between the desktop inline nav and the mobile Sheet's nav so
 * both stay in lockstep; `onNavigate` closes the Sheet after a link is followed (the inline
 * nav has nothing to close, so it passes none). */
function NavLinks({ onNavigate, className }: { onNavigate?: () => void; className?: string }) {
  return (
    <>
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "rounded-md text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
              className,
              isActive && "text-foreground",
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 h-14 border-b border-border bg-card">
        <div className="mx-auto flex h-full max-w-7xl items-center justify-between gap-2 px-4">
          <div className="flex items-center gap-3 md:gap-8">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Menu"
              className="md:hidden"
              onClick={() => setMobileNavOpen(true)}
            >
              <List weight="regular" className="size-5" />
            </Button>
            <span className="font-semibold tracking-tight">Vocal Coach</span>
            <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
              <NavLinks className="px-3 py-1.5" />
            </nav>
          </div>
          <div className="flex items-center gap-3">
            <div className="hidden md:block">
              <ThemeToggle />
            </div>
            <UserMenu />
          </div>
        </div>
      </header>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-64">
          <SheetHeader>
            <SheetTitle>Menu</SheetTitle>
            <SheetDescription>Browse pages and change the theme.</SheetDescription>
          </SheetHeader>
          <nav aria-label="Primary" className="flex flex-col gap-1 px-4">
            <NavLinks className="px-3 py-2" onNavigate={() => setMobileNavOpen(false)} />
          </nav>
          <SheetFooter>
            <ThemeToggle />
          </SheetFooter>
        </SheetContent>
      </Sheet>

      <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
    </div>
  );
}
