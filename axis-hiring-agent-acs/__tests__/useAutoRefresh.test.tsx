import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { useAutoRefresh } from "@/lib/hooks/useAutoRefresh";

function Probe({
  loader,
  intervalMs,
  onState,
}: {
  loader: () => Promise<number>;
  intervalMs: number;
  onState: (data: number | null, err: string | null) => void;
}) {
  const { data, error } = useAutoRefresh<number>(loader, intervalMs);
  onState(data, error);
  return null;
}

describe("useAutoRefresh", () => {
  it("loads the initial value and exposes it via data", async () => {
    const loader = vi.fn().mockResolvedValue(42);
    const states: { data: number | null; err: string | null }[] = [];
    render(
      <Probe
        loader={loader}
        intervalMs={50}
        onState={(data, err) => states.push({ data, err })}
      />,
    );
    await waitFor(() => {
      expect(states.some((s) => s.data === 42)).toBe(true);
    });
    expect(loader).toHaveBeenCalled();
  });

  it("captures loader errors into the error field", async () => {
    const loader = vi.fn().mockRejectedValue(new Error("boom"));
    const states: { data: number | null; err: string | null }[] = [];
    render(
      <Probe
        loader={loader}
        intervalMs={50}
        onState={(data, err) => states.push({ data, err })}
      />,
    );
    await waitFor(() => {
      expect(states.some((s) => s.err === "boom")).toBe(true);
    });
  });

  it("re-polls on the interval", async () => {
    const loader = vi.fn().mockResolvedValue(1);
    render(
      <Probe loader={loader} intervalMs={30} onState={() => undefined} />,
    );
    await waitFor(() => {
      expect(loader.mock.calls.length).toBeGreaterThanOrEqual(2);
    });
  });
});
