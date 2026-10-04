import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { RequireAuth } from "./RequireAuth";

test("renders children when authenticated", () => {
  renderWithProviders(
    <RequireAuth>
      <p>secret content</p>
    </RequireAuth>,
    { auth: { isAuthenticated: true, isLoading: false } },
  );
  expect(screen.getByText("secret content")).toBeInTheDocument();
});

test("keeps rendering children during a background renew on an already-authenticated session", () => {
  // react-oidc-context sets isLoading: true for the whole duration of ANY navigator call,
  // including signinSilent() triggered mid-session by getToken() or automaticSilentRenew.
  // Regression guard: this must not unmount the page / show the skeleton.
  const { container } = renderWithProviders(
    <RequireAuth>
      <p>secret content</p>
    </RequireAuth>,
    { auth: { isAuthenticated: true, isLoading: true, activeNavigator: "signinSilent" } },
  );
  expect(screen.getByText("secret content")).toBeInTheDocument();
  expect(container.querySelector('[aria-busy="true"]')).not.toBeInTheDocument();
});

test("shows a busy full-page skeleton while loading, without rendering children", () => {
  const { container } = renderWithProviders(
    <RequireAuth>
      <p>secret content</p>
    </RequireAuth>,
    { auth: { isAuthenticated: false, isLoading: true } },
  );
  expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  expect(screen.queryByText("secret content")).not.toBeInTheDocument();
});

test("calls signin with the current path and renders nothing when unauthenticated", () => {
  const signin = vi.fn();
  const { container } = renderWithProviders(
    <RequireAuth>
      <p>secret content</p>
    </RequireAuth>,
    { route: "/library?tab=recent", auth: { isAuthenticated: false, isLoading: false, signin } },
  );
  expect(signin).toHaveBeenCalledWith("/library?tab=recent");
  expect(screen.queryByText("secret content")).not.toBeInTheDocument();
  expect(container).toBeEmptyDOMElement();
});
