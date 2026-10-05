import { StrictMode, type ErrorInfo } from "react";
import { createRoot, type Root } from "react-dom/client";
import App from "./App";
import { ConfigContext } from "./auth/ConfigContext";
import { ConfigError, loadConfig } from "./config";

// Surface every React error with its component stack in the console: uncaught ones unmount
// the tree, caught ones are handled by an error boundary, recoverable ones React retried.
function logReactError(kind: string) {
  return (error: unknown, info: ErrorInfo) => {
    console.error(`[react ${kind}]`, error, info.componentStack);
  };
}

/** Shown instead of the app when /config.json could not be loaded (missing, malformed, or an
 * HTTP error from the server). Deliberately plain: it must render correctly even though the
 * app's own design tokens (src/index.css, ThemeProvider) never got a chance to apply.
 * Kept in this module (rather than its own file) since it is only ever rendered by
 * renderApp() below; this file is the bootstrap entry point, not a component library, so Fast
 * Refresh's "only export components" shape does not apply here. */
// eslint-disable-next-line react-refresh/only-export-components
function ConfigErrorPanel({ message }: { message: string }) {
  return (
    <div
      style={{
        display: "flex",
        minHeight: "100vh",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
        fontFamily: "system-ui, sans-serif",
        color: "#1a1a1a",
        background: "#f5f5f5",
        textAlign: "center",
      }}
    >
      <div style={{ maxWidth: "32rem" }}>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600, marginBottom: "0.75rem" }}>
          Configuration error
        </h1>
        <p style={{ marginBottom: "0.5rem" }}>{message}</p>
        <p>Check /config.json</p>
      </div>
    </div>
  );
}

/**
 * Loads the runtime config and renders the app into `root`, or a static error panel if the
 * config could not be loaded. Kept separate from main.tsx (which just calls this with the
 * real DOM root) so it can be unit tested with a stub loader and a detached container
 * (src/bootstrap.test.tsx).
 */
export async function renderApp(
  root: Element | DocumentFragment,
  loadConfigImpl: typeof loadConfig = loadConfig,
): Promise<Root> {
  const reactRoot = createRoot(root, {
    onUncaughtError: logReactError("uncaught"),
    onCaughtError: logReactError("caught"),
    onRecoverableError: logReactError("recoverable"),
  });

  try {
    const config = await loadConfigImpl();
    reactRoot.render(
      <StrictMode>
        <ConfigContext.Provider value={config}>
          <App />
        </ConfigContext.Provider>
      </StrictMode>,
    );
  } catch (error) {
    const message =
      error instanceof ConfigError ? error.message : "Could not load the application configuration.";
    reactRoot.render(
      <StrictMode>
        <ConfigErrorPanel message={message} />
      </StrictMode>,
    );
  }

  return reactRoot;
}
