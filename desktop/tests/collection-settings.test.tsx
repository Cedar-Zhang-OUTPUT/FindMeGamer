// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { DesktopBridge, Result } from "../src/shared/bridge";
import type { CollectionSettings as SavedCollectionSettings, SettingsAPI } from "../src/shared/settings";
import { CollectionSettings } from "../src/renderer/components/settings/CollectionSettings";
import { SettingsView } from "../src/renderer/components/settings/SettingsView";
import type { AppearanceState } from "../src/renderer/hooks/useAppearance";
import { settingsBridgeMock } from "./settings-fixtures";

const ok = <T,>(data: T) => ({ ok: true as const, data });
const literalStates = {
  items: [
    {
      platform: "youtube" as const,
      enabled: true,
      implemented: true,
      credentials_configured: true,
      availability: "configured_unverified" as const,
    },
    {
      platform: "x" as const,
      enabled: true,
      implemented: true,
      credentials_configured: false,
      availability: "missing_connection" as const,
    },
    {
      platform: "twitch" as const,
      enabled: false,
      implemented: false,
      credentials_configured: false,
      availability: "disabled" as const,
    },
    {
      platform: "instagram" as const,
      enabled: true,
      implemented: false,
      credentials_configured: true,
      availability: "not_implemented" as const,
    },
  ],
} satisfies SavedCollectionSettings;
type CollectionResult = Result<SavedCollectionSettings>;

function apiMock() {
  return {
    collection: vi.fn(async () => ok(literalStates)),
    setCollection: vi.fn(async () => ok(literalStates)),
  } as unknown as SettingsAPI;
}

afterEach(cleanup);

it("renders distinct collection availability and never enables unsupported controls", async () => {
  const api = apiMock();
  render(<CollectionSettings api={api} connected active />);

  const youtube = await screen.findByRole("group", { name: "YouTube" });
  expect(within(youtube).getByText("Configured · Access not verified")).toBeVisible();
  expect(within(youtube).getByText("Credentials saved")).toBeVisible();
  expect(within(youtube).getByRole("switch", { name: "Collect from YouTube" })).toBeEnabled();

  const x = screen.getByRole("group", { name: "X" });
  expect(within(x).getByText("Connection required")).toBeVisible();
  expect(within(x).getByText("No credentials")).toBeVisible();

  const twitch = screen.getByRole("group", { name: "Twitch" });
  expect(within(twitch).getByText("Unavailable this release")).toBeVisible();
  expect(within(twitch).getByText("No credentials")).toBeVisible();
  expect(within(twitch).getByRole("switch", { name: "Collect from Twitch" })).toBeDisabled();

  const instagram = screen.getByRole("group", { name: "Instagram" });
  expect(within(instagram).getByText("Unavailable this release")).toBeVisible();
  expect(within(instagram).getByText("Credentials saved")).toBeVisible();
  expect(within(instagram).getByRole("switch", { name: "Collect from Instagram" })).toBeDisabled();
  expect(within(instagram).getByRole("switch", { name: "Collect from Instagram" })).toBeChecked();
  expect(screen.queryByText(/connection verified/i)).not.toBeInTheDocument();
});

it("confirms a shared pause before one PUT and accepts only the returned state", async () => {
  const api = apiMock();
  let resolveSave!: (value: CollectionResult) => void;
  vi.mocked((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection)
    .mockReturnValueOnce(new Promise((resolve) => { resolveSave = resolve; }));
  const user = userEvent.setup();
  render(<CollectionSettings api={api} connected active />);
  const toggle = await screen.findByRole("switch", { name: "Collect from YouTube" });

  await user.click(toggle);
  const firstDialog = screen.getByRole("dialog", { name: "Confirm collection change" });
  expect(within(firstDialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
  expect(firstDialog).toHaveTextContent("everyone using this workspace");
  expect(firstDialog).toHaveTextContent("Pause after the in-flight collection finishes");
  expect(firstDialog).toHaveTextContent("Enabling later does not resume paused work");
  expect(toggle).toBeChecked();
  expect((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection).not.toHaveBeenCalled();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(toggle).toHaveFocus();
  expect(toggle).toBeChecked();

  await user.click(toggle);
  const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" });
  await user.dblClick(confirm);
  expect((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection).toHaveBeenCalledTimes(1);
  expect((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection).toHaveBeenCalledWith({
    platform: "youtube",
    enabled: false,
  });
  expect(toggle).toBeChecked();
  expect(screen.getByRole("switch", { name: "Collect from X" })).toBeDisabled();

  await act(async () => {
    resolveSave(ok({
      items: literalStates.items.map((item) =>
        item.platform === "youtube"
          ? { ...item, enabled: false, availability: "disabled" as const }
          : item,
      ),
    }));
  });
  await waitFor(() => expect(toggle).not.toBeChecked());
  expect(within(screen.getByRole("group", { name: "YouTube" })).getByText("Collection disabled")).toBeVisible();
  expect(screen.getByText("Collection settings saved")).toBeVisible();
  await waitFor(() => expect(toggle).toHaveFocus());

  await user.click(toggle);
  const enableDialog = screen.getByRole("dialog", { name: "Confirm collection change" });
  expect(enableDialog).toHaveTextContent("Enabling collection does not resume paused work");
  await user.click(within(enableDialog).getByRole("button", { name: "Cancel" }));
  expect(toggle).not.toBeChecked();
  expect((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection).toHaveBeenCalledTimes(1);
});

it("requires explicit readback after an uncertain PUT and retains last-known rows on read failure", async () => {
  const api = apiMock();
  const collection = vi.mocked((api as SettingsAPI & { collection: ReturnType<typeof vi.fn> }).collection);
  const setCollection = vi.mocked((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection);
  setCollection.mockRejectedValueOnce(new Error("lost response"));
  const user = userEvent.setup();
  render(<CollectionSettings api={api} connected active />);
  const xToggle = await screen.findByRole("switch", { name: "Collect from X" });

  await user.click(xToggle);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }));
  expect(await screen.findByText(/Save could not be confirmed/)).toBeVisible();
  expect(setCollection).toHaveBeenCalledTimes(1);
  expect(xToggle).toBeChecked();
  expect(xToggle).toBeDisabled();
  await user.click(xToggle);
  expect(setCollection).toHaveBeenCalledTimes(1);

  collection.mockResolvedValueOnce(ok({
    items: literalStates.items.map(item => item.platform === "x"
      ? { ...item, enabled: false, availability: "disabled" as const }
      : item),
  }));
  await user.click(screen.getByRole("button", { name: "Reload saved settings" }));
  await waitFor(() => expect(xToggle).not.toBeChecked());
  expect(setCollection).toHaveBeenCalledTimes(1);

  collection.mockRejectedValueOnce(new Error("read failed"));
  await user.click(screen.getByRole("button", { name: "Reload saved settings" }));
  expect(await screen.findByText("Read failed. Last known collection settings are retained.")).toBeVisible();
  expect(xToggle).not.toBeChecked();
});

it("ignores a stale read that resolves after a later successful save", async () => {
  const api = apiMock();
  const collection = vi.mocked((api as SettingsAPI & { collection: ReturnType<typeof vi.fn> }).collection);
  vi.mocked((api as SettingsAPI & { setCollection: ReturnType<typeof vi.fn> }).setCollection).mockResolvedValueOnce(ok({
    items: literalStates.items.map(item => item.platform === "youtube"
      ? { ...item, enabled: false, availability: "disabled" as const }
      : item),
  }));
  let resolveRead!: (value: CollectionResult) => void;
  const user = userEvent.setup();
  render(<CollectionSettings api={api} connected active />);
  const youtube = await screen.findByRole("switch", { name: "Collect from YouTube" });

  collection.mockReturnValueOnce(new Promise(resolve => { resolveRead = resolve; }));
  await user.click(screen.getByRole("button", { name: "Reload saved settings" }));
  await user.click(youtube);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(youtube).not.toBeChecked());

  await act(async () => { resolveRead(ok(literalStates)); });
  expect(youtube).not.toBeChecked();
  expect(screen.getByRole("button", { name: "Reload saved settings" })).toBeEnabled();
});

it("reads only on connected active entry or explicit reload", async () => {
  const api = apiMock();
  const collection = vi.mocked((api as SettingsAPI & { collection: ReturnType<typeof vi.fn> }).collection);
  const view = render(<CollectionSettings api={api} connected active={false} />);
  expect(collection).not.toHaveBeenCalled();

  view.rerender(<CollectionSettings api={api} connected active />);
  await waitFor(() => expect(collection).toHaveBeenCalledTimes(1));
  view.rerender(<CollectionSettings api={api} connected active />);
  expect(collection).toHaveBeenCalledTimes(1);
  view.rerender(<CollectionSettings api={api} connected active={false} />);
  view.rerender(<CollectionSettings api={api} connected active />);
  await waitFor(() => expect(collection).toHaveBeenCalledTimes(2));

  const disconnected = apiMock();
  view.rerender(<CollectionSettings api={disconnected} connected={false} active />);
  expect(screen.getByText("Connect to your workspace to manage collection settings.")).toBeVisible();
  expect((disconnected as SettingsAPI & { collection: ReturnType<typeof vi.fn> }).collection).not.toHaveBeenCalled();
});

function viewProps(collectionRequest: number, recovering = false) {
  const local = settingsBridgeMock();
  const api = {
    ...local,
    connection: {} as DesktopBridge["connection"],
    library: { list: vi.fn(), detail: vi.fn() } as DesktopBridge["library"],
    games: {} as DesktopBridge["games"],
    openExternal: vi.fn(),
  } as DesktopBridge;
  const appearance = {
    preferences: { appearance: "system" as const, fontSize: "default" as const, automaticUpdates: true },
    error: null,
    busy: false,
    save: vi.fn(),
  } as AppearanceState;
  return {
    api,
    active: true,
    available: true,
    workspaceEpoch: 0,
    appearance,
    collectionRequest,
    connection: {
      status: { serviceUrl: "https://workspace.example.com", hasKey: true, storageAvailable: true },
      phase: "connected" as const,
      error: null,
      route: "direct" as const,
      recovering,
      onConnect: vi.fn(),
      onTest: vi.fn(),
      onDisconnect: vi.fn(),
      onLibrary: vi.fn(),
    },
    onNavigationGuardChange: vi.fn(),
  };
}

it("integrates a keyboard-accessible shared category and honors request recovery priority", async () => {
  const initial = viewProps(0);
  const view = render(<SettingsView {...initial} />);
  const collectionTab = screen.getByRole("tab", { name: "Collection" });
  expect(collectionTab).toHaveTextContent("Shared");
  expect(collectionTab).toHaveAttribute("aria-selected", "false");

  view.rerender(<SettingsView {...initial} collectionRequest={1} />);
  await waitFor(() => expect(collectionTab).toHaveAttribute("aria-selected", "true"));
  expect(initial.api.settings.collection).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(collectionTab).toHaveFocus());
  await userEvent.setup().keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Auto-refresh" })).toHaveFocus();

  const recovery = { ...initial, collectionRequest: 2, connection: { ...initial.connection, recovering: true } };
  view.rerender(<SettingsView {...recovery} />);
  expect(screen.getByRole("tab", { name: "Workspace" })).toHaveAttribute("aria-selected", "true");
});

it("re-reads the preserved Collection panel when global Settings becomes active again", async () => {
  const props = viewProps(1);
  const view = render(<SettingsView {...props} />);
  await waitFor(() => expect(props.api.settings.collection).toHaveBeenCalledTimes(1));
  // Finish the explicit initial category navigation before testing a later return.
  await waitFor(() => expect(screen.getByRole('tab', {name:'Collection'})).toHaveFocus());
  const youtube = await screen.findByRole("switch", { name: "Collect from YouTube" });
  youtube.focus();

  view.rerender(<SettingsView {...props} active={false} />);
  view.rerender(<SettingsView {...props} active />);
  await waitFor(() => expect(props.api.settings.collection).toHaveBeenCalledTimes(2));
  expect(youtube).toHaveFocus();
});

it("keeps another shared draft guarded when collection confirmation is canceled", async () => {
  const props = viewProps(0);
  const user = userEvent.setup();
  render(<SettingsView {...props} />);

  await user.click(screen.getByRole("tab", { name: "Services" }));
  await user.click(await screen.findByRole("button", { name: "Replace YouTube credential" }));
  await user.type(screen.getByLabelText("YouTube replacement credential"), "retained-draft");
  await user.click(screen.getByRole("tab", { name: "Collection" }));
  await user.click(await screen.findByRole("switch", { name: "Collect from YouTube" }));
  await waitFor(() => expect(props.onNavigationGuardChange.mock.lastCall?.[0]).toEqual(expect.any(Function)));
  await user.keyboard("{Escape}");

  await user.click(screen.getByRole("tab", { name: "Workspace" }));
  expect(screen.getByLabelText("Service URL")).toBeDisabled();
  expect(screen.getByText("Unsaved shared settings")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Review settings" }));
  expect(screen.getByRole("tab", { name: "Services" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByLabelText("YouTube replacement credential")).toHaveValue("retained-draft");
});

it("preserves an upstream workspace block alongside shared settings guards", () => {
  const props = viewProps(0);
  render(<SettingsView {...props} connection={{ ...props.connection, blocked: true }} />);
  expect(screen.getByLabelText("Service URL")).toBeDisabled();
  expect(screen.getByRole("button", { name: "Disconnect" })).toBeDisabled();
});
