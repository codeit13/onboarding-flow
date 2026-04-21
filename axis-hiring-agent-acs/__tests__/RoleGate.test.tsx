import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { RoleGate } from "@/components/RoleGate";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: (...args: any[]) => replace(...args),
    refresh: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// Some Node + jsdom + vitest combinations expose a partial localStorage
// (no clear/removeItem). Substitute a tiny in-memory shim so the suite is
// hermetic.
function installLocalStorage() {
  const store = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
      setItem: (k: string, v: string) => void store.set(k, String(v)),
      removeItem: (k: string) => void store.delete(k),
      clear: () => store.clear(),
      key: (i: number) => Array.from(store.keys())[i] ?? null,
      get length() {
        return store.size;
      },
    },
  });
}

const seed = (role: "employee" | "hr_partner" | "panel") =>
  window.localStorage.setItem(
    "axis-hiring-persona",
    JSON.stringify({ role, identity: "x", displayName: "X" }),
  );

describe("RoleGate", () => {
  beforeEach(() => {
    installLocalStorage();
    replace.mockClear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("renders children when the active persona is allowed", async () => {
    seed("hr_partner");
    render(
      <RoleGate allow={["hr_partner"]}>
        <p>secret hr stuff</p>
      </RoleGate>,
    );
    await waitFor(() =>
      expect(screen.getByText("secret hr stuff")).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("blocks and renders the wrong-persona interstitial otherwise", async () => {
    seed("employee");
    render(
      <RoleGate allow={["hr_partner"]}>
        <p>secret hr stuff</p>
      </RoleGate>,
    );
    await waitFor(() =>
      expect(screen.queryByText("secret hr stuff")).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/Wrong persona/i)).toBeInTheDocument();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/thrive"));
  });

  it("supports multi-role allow lists", async () => {
    seed("panel");
    render(
      <RoleGate allow={["panel", "hr_partner"]}>
        <p>shared</p>
      </RoleGate>,
    );
    await waitFor(() => expect(screen.getByText("shared")).toBeInTheDocument());
  });
});
