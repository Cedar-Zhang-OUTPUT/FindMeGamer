// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import type { SettingsAPI, SMTPStatus } from "../src/shared/settings";
import { CloudSettings } from "../src/renderer/components/settings/CloudSettings";
import { collectionSettingsFixture } from './collection-fixtures';
const status = {
  configured: true,
  lastTestStatus: null,
  lastTestedAt: null,
} as const;
const smtp: SMTPStatus = {
  ...status,
  host: "smtp.example.com",
  port: 587,
  encryption: "starttls",
  username: "sender@example.com",
  fromName: "Studio",
  replyTo: "reply@example.com",
  emailsPerMinute: 10,
};
const ok = <T,>(data: T) => ({ ok: true as const, data });
function apiMock(): SettingsAPI {
  return {
    collection: vi.fn(async () => ok(collectionSettingsFixture())),
    setCollection: vi.fn(async () => ok(collectionSettingsFixture())),
    connection: vi.fn(async () => ok(status)),
    replaceConnection: vi.fn(async () => ok(status)),
    testConnection: vi.fn(async () =>
      ok({ ...status, lastTestStatus: "success" as const }),
    ),
    reanalysis: vi.fn(async () =>
      ok({ gameIntervalDays: 7, creatorIntervalDays: 3 }),
    ),
    saveReanalysis: vi.fn(async (value) => ok(value)),
    smtp: vi.fn(async () => ok(smtp)),
    saveSMTP: vi.fn(async () => ok(smtp)),
    testSMTP: vi.fn(async () =>
      ok({
        succeeded: true,
        lastTestStatus: "success" as const,
        lastTestedAt: "now",
      }),
    ),
    sendTestEmail: vi.fn(async () => {
      throw Error("sensitive detail");
    }),
  };
}
afterEach(cleanup);
it('groups each service status and its actions without repeating the service name visually',async()=>{
 const api=apiMock(),user=userEvent.setup();render(<CloudSettings api={api} connected section="services"/>);
 const controls=await screen.findByRole('group',{name:'YouTube connection controls'});
 expect(within(controls).getByRole('heading',{name:'YouTube'})).toBeVisible();
 expect(within(controls).getByText('Configured')).toBeVisible();
 expect(within(controls).getByRole('button',{name:'Test YouTube'})).toHaveTextContent('Test');
 const replace=within(controls).getByRole('button',{name:'Replace YouTube credential'});expect(replace).toHaveTextContent('Replace credential');
 await user.click(replace);await user.type(screen.getByLabelText('YouTube replacement credential'),'synthetic-only');
 expect(within(controls).getByRole('button',{name:'Test YouTube'})).toBeDisabled();
 await user.click(screen.getByRole('button',{name:'Save YouTube credential'}));expect(screen.getByRole('dialog')).toHaveTextContent('for everyone using this workspace');
 await user.click(screen.getByRole('button',{name:'Cancel'}));expect(screen.getByLabelText('YouTube replacement credential')).toHaveValue('synthetic-only');expect(api.replaceConnection).not.toHaveBeenCalled();
});
it("keeps service test limits discoverable without showing repeated explanatory text", async () => {
  const user = userEvent.setup();
  render(<CloudSettings api={apiMock()} connected section="services" />);
  const caveat = await screen.findByText("Search & analysis not verified");
  expect(caveat).not.toBeVisible();
  await user.click(screen.getByText("X test scope", { selector: "summary" }));
  expect(caveat).toBeVisible();
  expect(screen.getByText(/Checks usage access only/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Test usage access" })).toBeEnabled();
});
it("keeps saved SMTP connection details behind a named disclosure while showing the sender", async () => {
  const user = userEvent.setup();
  render(<CloudSettings api={apiMock()} connected section="email" />);
  expect(await screen.findByText("Studio <sender@example.com>")).toBeVisible();
  const host = screen.getByText(/smtp.example.com/);
  expect(host).not.toBeVisible();
  await user.click(screen.getByText("SMTP connection details", { selector: "summary" }));
  expect(host).toBeVisible();
  expect(screen.getByText(/STARTTLS/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Edit email settings" })).toBeEnabled();
});
it("reconciles an uncertain password save before enabling SMTP tests, preserving non-secret edits", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  api.saveSMTP = vi.fn(async () => ({
    ok: false as const,
    error: { code: "network_error", message: "hidden", retryable: true },
  }));
  render(<CloudSettings api={api} connected section="email" />);
  await user.click(
    await screen.findByRole("button", { name: "Edit email settings" }),
  );
  await user.type(
    screen.getByLabelText("Replacement password (optional)"),
    "replacement",
  );
  await user.click(screen.getByRole("button", { name: "Save email settings" }));
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await screen.findByText(/Operation could not be confirmed/);
  expect(
    screen.getByRole("button", { name: "Test connection" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Send test email…" }),
  ).toBeDisabled();
  await user.type(screen.getByLabelText("From name"), " edited");
  await user.click(
    screen.getByRole("button", { name: "Reload email settings" }),
  );
  await waitFor(() => expect(api.smtp).toHaveBeenCalledTimes(2));
  expect(screen.getByLabelText("From name")).toHaveValue("Studio edited");
  expect(
    screen.getByRole("button", { name: "Test connection" }),
  ).toBeDisabled();
  await user.clear(screen.getByLabelText("From name"));
  await user.type(screen.getByLabelText("From name"), "Studio");
  expect(screen.getByRole("button", { name: "Test connection" })).toBeEnabled();
});
it("offers read-only recovery after interval mutation failure without discarding edited values", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  api.saveReanalysis = vi.fn(async () => ({
    ok: false as const,
    error: { code: "network_error", message: "hidden", retryable: true },
  }));
  render(<CloudSettings api={api} connected section="refresh" />);
  const games = screen.getByLabelText("Games interval (days)");
  await waitFor(() => expect(games).toHaveValue(7));
  await user.clear(games);
  await user.type(games, "20");
  await user.click(screen.getByRole("button", { name: "Save intervals" }));
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await user.click(
    await screen.findByRole("button", { name: "Reload intervals" }),
  );
  await waitFor(() => expect(api.reanalysis).toHaveBeenCalledTimes(2));
  expect(games).toHaveValue(20);
  expect(api.saveReanalysis).toHaveBeenCalledTimes(1);
});
it("restores confirmed save focus to its stable panel when the save control disappears", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  render(<CloudSettings api={api} connected section="services" />);
  await user.click(
    await screen.findByRole("button", { name: "Replace Steam credential" }),
  );
  await user.type(
    screen.getByLabelText("Steam replacement credential"),
    "replacement",
  );
  await user.click(
    screen.getByRole("button", { name: "Save Steam credential" }),
  );
  await user.tab();
  await user.keyboard("{Enter}");
  await waitFor(() =>
    expect(document.getElementById("settings-panel-services")).toHaveFocus(),
  );
});
it("updates SMTP test metadata and treats recipient as transient input", async () => {
  const api = apiMock(),
    user = userEvent.setup(),
    report = vi.fn();
  render(
    <CloudSettings
      api={api}
      connected
      section="email"
      onDraftStateChange={report}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "Send test email…" }),
  );
  await user.type(
    screen.getByLabelText("Test recipient email"),
    "recipient@example.com",
  );
  expect(report.mock.lastCall?.[0].dirty).toBe(false);
  await user.click(screen.getByRole("button", { name: "Test connection" }));
  expect(
    await screen.findByText(/Last SMTP test: success/),
  ).toBeInTheDocument();
});
it("reconciles failed provider mutations through a read and restores confirmed send focus", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  api.replaceConnection = vi.fn(async () => ({
    ok: false as const,
    error: { code: "network_error", message: "hidden", retryable: true },
  }));
  api.sendTestEmail = vi.fn(async () =>
    ok({
      succeeded: true,
      lastTestStatus: "success" as const,
      lastTestedAt: "now",
    }),
  );
  const view = render(<CloudSettings api={api} connected section="services" />);
  await user.click(
    await screen.findByRole("button", { name: "Replace YouTube credential" }),
  );
  await user.type(
    screen.getByLabelText("YouTube replacement credential"),
    "replacement",
  );
  await user.click(
    screen.getByRole("button", { name: "Save YouTube credential" }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  expect(screen.getByRole("button", { name: "Test YouTube" })).toBeDisabled();
  await user.click(
    await screen.findByRole("button", { name: "Reload YouTube status" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Test YouTube" })).toBeEnabled(),
  );
  expect(api.replaceConnection).toHaveBeenCalledTimes(1);
  view.rerender(<CloudSettings api={api} connected section="email" />);
  await user.click(screen.getByRole("button", { name: "Send test email…" }));
  await user.type(
    screen.getByLabelText("Test recipient email"),
    "recipient@example.com",
  );
  const send = screen.getByRole("button", { name: "Send test email" });
  await user.click(send);
  await user.tab();
  await user.keyboard("{Enter}");
  await waitFor(() => expect(send).toHaveFocus());
});
it("does not read cloud settings while disconnected", () => {
  const api = apiMock();
  render(<CloudSettings api={api} connected={false} section="email" />);
  expect(api.connection).not.toHaveBeenCalled();
  expect(api.smtp).not.toHaveBeenCalled();
  expect(api.reanalysis).not.toHaveBeenCalled();
});
it("requires a first SMTP password and saves explicit secure defaults without sending", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  api.smtp = vi.fn(async () =>
    ok({
      ...smtp,
      configured: false,
      host: null,
      port: null,
      encryption: null,
      username: null,
      fromName: null,
      replyTo: null,
    }),
  );
  render(<CloudSettings api={api} connected section="email" />);
  const host = await screen.findByLabelText("SMTP host");
  await waitFor(() => expect(host).toBeEnabled());
  expect(screen.getByLabelText("Port")).toHaveValue(587);
  expect(screen.getByLabelText("Encryption")).toHaveValue("starttls");
  await user.type(host, "smtp.example.com");
  await user.type(
    screen.getByLabelText("Username email"),
    "sender@example.com",
  );
  await user.type(screen.getByLabelText("From name"), "Studio");
  await user.type(screen.getByLabelText("Reply-To email"), "reply@example.com");
  await user.click(screen.getByRole("button", { name: "Save email settings" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Password"), "new-password");
  await user.click(screen.getByRole("button", { name: "Save email settings" }));
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() =>
    expect(api.saveSMTP).toHaveBeenCalledWith({
      host: "smtp.example.com",
      port: 587,
      encryption: "starttls",
      username: "sender@example.com",
      password: "new-password",
      fromName: "Studio",
      replyTo: "reply@example.com",
      emailsPerMinute: 10,
    }),
  );
  expect(api.sendTestEmail).not.toHaveBeenCalled();
  expect(screen.queryByDisplayValue("new-password")).not.toBeInTheDocument();
});
it("keeps service secrets across sections but clears them when disconnected and never probes Steam", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  const view = render(<CloudSettings api={api} connected section="services" />);
  await user.click(
    await screen.findByRole("button", { name: "Replace Steam credential" }),
  );
  await user.type(
    screen.getByLabelText("Steam replacement credential"),
    "secret",
  );
  expect(
    screen.queryByRole("button", { name: "Test Steam" }),
  ).not.toBeInTheDocument();
  view.rerender(<CloudSettings api={api} connected section="refresh" />);
  view.rerender(<CloudSettings api={api} connected section="services" />);
  expect(screen.getByLabelText("Steam replacement credential")).toHaveValue(
    "secret",
  );
  view.rerender(
    <CloudSettings api={api} connected={false} section="services" />,
  );
  expect(screen.queryByDisplayValue("secret")).not.toBeInTheDocument();
  expect(api.testConnection).not.toHaveBeenCalled();
});
it("preserves edited intervals when a new settings read completes", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  const view = render(<CloudSettings api={api} connected section="refresh" />);
  const games = await screen.findByLabelText("Games interval (days)");
  await waitFor(() => expect(games).toHaveValue(7));
  await user.clear(games);
  await user.type(games, "20");
  const next = apiMock();
  view.rerender(<CloudSettings api={next} connected section="refresh" />);
  await waitFor(() => expect(next.reanalysis).toHaveBeenCalled());
  expect(games).toHaveValue(20);
});
it("reports confirmation as busy and blocks double send while pending", async () => {
  const api = apiMock(),
    user = userEvent.setup(),
    report = vi.fn();
  api.sendTestEmail = vi.fn(() => new Promise<never>(() => {}));
  render(
    <CloudSettings
      api={api}
      connected
      section="email"
      onDraftStateChange={report}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: "Send test email…" }),
  );
  await user.type(
    screen.getByLabelText("Test recipient email"),
    "recipient@example.com",
  );
  await user.click(screen.getByRole("button", { name: "Send test email" }));
  expect(report.mock.lastCall?.[0].busy).toBe(true);
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  expect(
    screen.getByRole("button", { name: "Send test email" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Send test email" }));
  expect(api.sendTestEmail).toHaveBeenCalledTimes(1);
});
it("confirms shared replacement, clears submitted secret and keeps X capability caveat", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  render(<CloudSettings api={api} connected section="services" />);
  await user.click(
    await screen.findByRole("button", { name: "Replace X credential" }),
  );
  await user.type(
    screen.getByLabelText("X replacement credential"),
    "new-secret",
  );
  expect(
    screen.getByRole("button", { name: "Test usage access" }),
  ).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Save X credential" }));
  expect(api.replaceConnection).not.toHaveBeenCalled();
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await waitFor(() =>
    expect(api.replaceConnection).toHaveBeenCalledWith({
      service: "x",
      secret: "new-secret",
    }),
  );
  expect(screen.queryByDisplayValue("new-secret")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Test usage access" }));
  expect(
    screen.getByText("Search & analysis not verified"),
  ).toBeInTheDocument();
});
it("requires recipient consent and prevents automatic resend after unknown delivery", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  render(<CloudSettings api={api} connected section="email" />);
  await user.click(
    await screen.findByRole("button", { name: "Send test email…" }),
  );
  await user.type(
    screen.getByLabelText("Test recipient email"),
    "recipient@example.com",
  );
  await user.click(screen.getByRole("button", { name: "Send test email" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("recipient@example.com");
  expect(screen.getByRole("dialog")).toHaveTextContent("sender@example.com");
  expect(api.sendTestEmail).not.toHaveBeenCalled();
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  expect(
    await screen.findByText(/Delivery may be unknown/),
  ).toBeInTheDocument();
  expect(api.sendTestEmail).toHaveBeenCalledTimes(1);
  expect(screen.queryByText("sensitive detail")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reload email settings" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Test connection" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Test connection" }));
  expect(api.testSMTP).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/Delivery may be unknown/)).toBeInTheDocument();
});
it("discloses saved email edits and preserves service drafts with only one editor visible", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  const view = render(<CloudSettings api={api} connected section="email" />);
  expect(
    await screen.findByText("Studio <sender@example.com>"),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText("SMTP host")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Edit email settings" }));
  expect(screen.getByLabelText("SMTP host")).toHaveValue("smtp.example.com");
  view.rerender(<CloudSettings api={api} connected section="services" />);
  await user.click(
    screen.getByRole("button", { name: "Replace Steam credential" }),
  );
  await user.type(
    screen.getByLabelText("Steam replacement credential"),
    "retained",
  );
  await user.click(
    screen.getByRole("button", { name: "Replace YouTube credential" }),
  );
  expect(
    screen.queryByLabelText("Steam replacement credential"),
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Replace Steam credential" }),
  );
  expect(screen.getByLabelText("Steam replacement credential")).toHaveValue(
    "retained",
  );
});
it("recovers failed reads through an explicit read-only reload", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  api.reanalysis = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      error: { code: "unauthorized", message: "private", retryable: false },
    })
    .mockResolvedValueOnce(ok({ gameIntervalDays: 7, creatorIntervalDays: 3 }));
  render(<CloudSettings api={api} connected section="refresh" />);
  await user.click(
    await screen.findByRole("button", { name: "Reload intervals" }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Games interval (days)")).toHaveValue(7),
  );
  expect(api.saveReanalysis).not.toHaveBeenCalled();
});
it("clears a secret on failed save and disables credential testing until replacement is clean", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  api.replaceConnection = vi.fn(async () => ({
    ok: false as const,
    error: { code: "network_error", message: "private", retryable: true },
  }));
  render(<CloudSettings api={api} connected section="services" />);
  await user.click(
    await screen.findByRole("button", { name: "Replace YouTube credential" }),
  );
  await user.type(
    screen.getByLabelText("YouTube replacement credential"),
    "secret",
  );
  await user.click(
    screen.getByRole("button", { name: "Save YouTube credential" }),
  );
  await user.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm" }),
  );
  await screen.findByText(/Operation failed/);
  expect(screen.getByLabelText("YouTube replacement credential")).toHaveValue(
    "",
  );
  expect(screen.queryByText("private")).not.toBeInTheDocument();
});
it("saves both interval values after keyboard confirmation and cancels without mutation", async () => {
  const api = apiMock(),
    user = userEvent.setup();
  render(<CloudSettings api={api} connected section="refresh" />);
  const games = await screen.findByLabelText("Games interval (days)");
  await waitFor(() => expect(games).toHaveValue(7));
  await user.clear(games);
  await user.type(games, "14");
  await user.click(screen.getByRole("button", { name: "Save intervals" }));
  await user.keyboard("{Escape}");
  expect(api.saveReanalysis).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Save intervals" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Save intervals" }));
  await user.tab();
  await user.keyboard("{Enter}");
  await waitFor(() =>
    expect(api.saveReanalysis).toHaveBeenCalledWith({
      gameIntervalDays: 14,
      creatorIntervalDays: 3,
    }),
  );
});
