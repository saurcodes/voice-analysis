import { StrictMode, type ErrorInfo } from "react";
import { createRoot, type Root } from "react-dom/client";
import App from "./App";
import { ConfigContext } from "./auth/ConfigContext";
import { ConfigErrorPanel } from "./ConfigErrorPanel";
import { ConfigError, loadConfig } from "./config";

// Surface every React error with its component stack in the console: uncaught ones unmount
// the tree, caught ones are handled by an error boundary, recoverable ones React retried.
function logReactError(kind: string) {
  return (error: unknown, info: ErrorInfo) => {
    console.error(`[react ${kind}]`, error, info.componentStack);
  };
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
