/** Shown instead of the app when /config.json could not be loaded (missing, malformed, or an
 * HTTP error from the server). Deliberately plain: it must render correctly even though the
 * app's own design tokens (src/index.css, ThemeProvider) never got a chance to apply. Only
 * ever rendered by renderApp() in src/bootstrap.tsx. */
export function ConfigErrorPanel({ message }: { message: string }) {
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
