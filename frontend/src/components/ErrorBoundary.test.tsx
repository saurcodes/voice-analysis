import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom(): never {
  throw new Error("render exploded");
}

test("renders the fallback panel with a Reload button when a child throws", () => {
  // React and componentDidCatch both report the caught error; silence the expected noise.
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  try {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    expect(consoleError).toHaveBeenCalledWith(
      "[react ErrorBoundary]",
      expect.objectContaining({ message: "render exploded" }),
      expect.any(String),
    );
  } finally {
    consoleError.mockRestore();
  }
});

test("renders its children when nothing throws", () => {
  render(
    <ErrorBoundary>
      <p>all good</p>
    </ErrorBoundary>,
  );
  expect(screen.getByText("all good")).toBeInTheDocument();
  expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
});
