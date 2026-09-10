import { useCallback, useEffect, useRef, useState } from "react";
import type { Result } from "../../../shared/bridge";
import {
  serviceNames,
  type SettingsAPI,
  type ServiceName,
  type ServiceStatus,
  type SMTPInput,
  type SMTPStatus,
} from "../../../shared/settings";
import "../../settings-cloud.css";
export interface CloudDraftState {
  dirty: boolean;
  busy: boolean;
  discard: () => void;
}
export interface CloudSettingsProps {
  api: SettingsAPI;
  connected: boolean;
  active?: boolean;
  section: "services" | "refresh" | "email";
  onDraftStateChange?: (state: CloudDraftState) => void;
}
type Report = (key: string, state: CloudDraftState | null) => void;
type Confirm = (message: string, action: () => void | Promise<unknown>) => void;
const noop = () => {};
function useDraft(
  key: string,
  dirty: boolean,
  busy: boolean,
  discard: () => void,
  report: Report,
) {
  const ref = useRef(discard);
  ref.current = discard;
  const reset = useCallback(() => ref.current(), []);
  useEffect(() => {
    report(key, { dirty, busy, discard: reset });
  }, [key, dirty, busy, reset, report]);
  useEffect(() => () => report(key, null), [key, report]);
}
function useOperation() {
  const [phase, setPhase] = useState<
    "idle" | "working" | "success" | "failure"
  >("idle");
  const [error, setError] = useState(
    "Check your connection and reload saved settings before trying again.",
  );
  const lock = useRef(false),
    alive = useRef(true),
    revision = useRef(0);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function run<T>(
    request: () => Promise<Result<T>>,
    accept: (data: T) => void,
  ) {
    if (lock.current) return;
    lock.current = true;
    revision.current++;
    setPhase("working");
    try {
      const result = await request();
      if (alive.current) {
        if (result.ok) {
          accept(result.data);
          setPhase("success");
        } else {
          setError(
            /auth|forbidden|key/i.test(result.error.code)
              ? "Open Workspace connection to repair your workspace key, then reload saved settings."
              : "Check your connection and reload saved settings before trying again.",
          );
          setPhase("failure");
        }
      }
      return result.ok;
    } catch {
      if (alive.current) setPhase("failure");
      return false;
    } finally {
      lock.current = false;
    }
  }
  const reconcile = useCallback(() => setPhase("idle"), []);
  return { phase, busy: phase === "working", run, revision, error, reconcile };
}
function Confirmation({
  message,
  action,
  cancel,
}: {
  message: string;
  action: () => void | Promise<unknown>;
  cancel: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const confirmed = useRef(false);
  useEffect(() => {
    origin.current = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      if (!confirmed.current) origin.current?.focus();
    };
  }, []);
  return (
    <div className="cloud-modal-backdrop">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cloud-confirm-title"
        className="cloud-modal"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
          if (e.key === "Tab") {
            const buttons = ref.current?.querySelectorAll("button");
            if (!buttons) return;
            const first = buttons[0],
              last = buttons[buttons.length - 1];
            if (e.shiftKey && document.activeElement === first) {
              e.preventDefault();
              last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <h3 id="cloud-confirm-title">Confirm change</h3>
        <p>{message}</p>
        <div className="cloud-actions">
          <button onClick={cancel}>Cancel</button>
          <button
            onClick={async () => {
              confirmed.current = true;
              const target = origin.current;
              const panel = target?.closest<HTMLElement>('[role="tabpanel"]');
              cancel();
              const completion = action();
              panel?.focus();
              await completion;
              setTimeout(() => {
                if (
                  target?.isConnected &&
                  !target.matches(":disabled") &&
                  !target.closest("[hidden]")
                )
                  target.focus();
                else if (panel?.isConnected && !panel.closest("[hidden]"))
                  panel.focus();
              }, 0);
            }}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}
const labels: Record<ServiceName, string> = {
  steam: "Steam",
  youtube: "YouTube",
  deepseek: "DeepSeek",
  google_ai: "Google AI",
  x: "X",
};
function Provider({
  api,
  name,
  report,
  confirm,
  expanded,
  onToggle,
  active,
}: {
  api: SettingsAPI;
  name: ServiceName;
  report: Report;
  confirm: Confirm;
  expanded: boolean;
  onToggle: () => void;
  active: boolean;
}) {
  const [saved, setSaved] = useState<ServiceStatus | null>(null),
    [loadFailed, setLoadFailed] = useState(false),
    [secret, setSecret] = useState(""),
    [reload, setReload] = useState(0);
  const op = useOperation();
  const label = labels[name];
  useEffect(() => {
    if (!active) return;
    let current = true;
    const version = op.revision.current;
    api.connection(name).then(
      (r) => {
        if (current && version === op.revision.current) {
          if (r.ok) {
            setSaved(r.data);
            setLoadFailed(false);
            op.reconcile();
          } else setLoadFailed(true);
        }
      },
      () => {
        if (current) setLoadFailed(true);
      },
    );
    return () => {
      current = false;
    };
  }, [active, api, name, op.revision, op.reconcile, reload]);
  useDraft(
    name,
    !!secret,
    op.busy,
    () => {
      setSecret("");
    },
    report,
  );
  return (
    <article className="cloud-provider">
      <div className="cloud-row" role="group" aria-label={`${label} connection controls`}>
        <div>
          <h3>{label}</h3>
          <span>
            {saved
              ? saved.configured
                ? "Configured"
                : "Not configured"
              : loadFailed
                ? "Unable to load status"
                : "Loading…"}
          </span>
        </div>
        <div className="cloud-provider-actions">
        {name !== "steam" && <button
          className="cloud-test-action"
          aria-label={name === "x" ? "Test usage access" : `Test ${label}`}
          disabled={!saved?.configured || !!secret || op.busy || op.phase === "failure"}
          onClick={() => void op.run(() => api.testConnection(name), setSaved)}
        >{name === "x" ? "Test usage access" : "Test"}</button>}
        <button
          disabled={op.busy || !saved}
          onClick={onToggle}
          aria-expanded={expanded}
          aria-label={`Replace ${label} credential`}
        >
          Replace credential
        </button>
        </div>
      </div>
      {(loadFailed || op.phase === "failure") && (
        <>
          <p>Check Workspace connection and your workspace key.</p>
          <button disabled={op.busy} onClick={() => setReload((n) => n + 1)}>
            Reload {label} status
          </button>
        </>
      )}
      {expanded && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            confirm(
              `Replace the shared ${label} credential for everyone using this workspace?`,
              () => {
                const value = secret;
                setSecret("");
                return op.run(
                  () => api.replaceConnection({ service: name, secret: value }),
                  (data) => {
                    setSaved(data);
                    onToggle();
                  },
                );
              },
            );
          }}
        >
          <label>
            {label} replacement credential
            <input
              type="password"
              autoComplete="new-password"
              value={secret}
              disabled={op.busy}
              onChange={(e) => setSecret(e.target.value)}
              required
            />
          </label>
          <button disabled={!secret.trim() || op.busy}>
            Save {label} credential
          </button>
        </form>
      )}
      <div className="cloud-actions cloud-provider-status">
        {name === "steam" && <span>Credential testing unavailable</span>}
        <span role="status">
          {op.busy
            ? "Working…"
            : op.phase === "failure"
              ? `Operation failed. ${op.error}`
              : saved?.lastTestStatus
                ? `Last test: ${saved.lastTestStatus}`
                : op.phase === "success"
                  ? "Saved"
                  : ""}
        </span>
      </div>
      {name === "x" && (
        <details>
          <summary>X test scope</summary>
          <p className="cloud-note">Search &amp; analysis not verified</p>
          <p>
            Checks usage access only. Account balance and recent search access
            are not verified.
          </p>
        </details>
      )}
    </article>
  );
}
function Refresh({
  api,
  report,
  confirm,
  active,
}: {
  api: SettingsAPI;
  report: Report;
  confirm: Confirm;
  active: boolean;
}) {
  const [saved, setSaved] = useState<{
      gameIntervalDays: number;
      creatorIntervalDays: number;
    } | null>(null),
    [games, setGames] = useState(""),
    [creators, setCreators] = useState(""),
    [loadFailed, setLoadFailed] = useState(false);
  const op = useOperation();
  const [reload, setReload] = useState(0);
  const dirty =
    !!saved &&
    (games !== String(saved.gameIntervalDays) ||
      creators !== String(saved.creatorIntervalDays));
  const edited = useRef(false);
  edited.current = dirty || op.busy;
  useEffect(() => {
    if (!active) return;
    let current = true;
    const version = op.revision.current;
    api.reanalysis().then(
      (r) => {
        if (current && version === op.revision.current) {
          if (r.ok) {
            setSaved(r.data);
            if (!edited.current) {
              setGames(String(r.data.gameIntervalDays));
              setCreators(String(r.data.creatorIntervalDays));
            }
            setLoadFailed(false);
            op.reconcile();
          } else setLoadFailed(true);
        }
      },
      () => {
        if (current) setLoadFailed(true);
      },
    );
    return () => {
      current = false;
    };
  }, [active, api, op.revision, op.reconcile, reload]);
  useDraft(
    "refresh",
    dirty,
    op.busy,
    () => {
      setGames(saved ? String(saved.gameIntervalDays) : "");
      setCreators(saved ? String(saved.creatorIntervalDays) : "");
    },
    report,
  );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        confirm(
          "Update shared refresh intervals for everyone using this workspace?",
          () =>
            op.run(
              () =>
                api.saveReanalysis({
                  gameIntervalDays: Number(games),
                  creatorIntervalDays: Number(creators),
                }),
              (value) => {
                setSaved(value);
                setGames(String(value.gameIntervalDays));
                setCreators(String(value.creatorIntervalDays));
              },
            ),
        );
      }}
    >
      <h2>Auto-refresh</h2>
      <div className="cloud-grid">
        <label>
          Games interval (days)
          <input
            aria-label="Games interval (days)"
            aria-describedby="games-refresh-scope"
            type="number"
            min="1"
            max="90"
            required
            value={games}
            disabled={!saved || op.busy}
            onChange={(e) => setGames(e.target.value)}
          />
          <small id="games-refresh-scope">Steam-linked games</small>
        </label>
        <label>
          Creators interval (days)
          <input
            aria-label="Creators interval (days)"
            aria-describedby="creators-refresh-scope"
            type="number"
            min="1"
            max="30"
            required
            value={creators}
            disabled={!saved || op.busy}
            onChange={(e) => setCreators(e.target.value)}
          />
          <small id="creators-refresh-scope">YouTube creators</small>
        </label>
      </div>
      <button disabled={!dirty || op.busy}>Save intervals</button>
      <p role="status">
        {loadFailed
          ? "Unable to load intervals. Check Workspace connection and your workspace key."
          : op.busy
            ? "Saving…"
            : op.phase === "failure"
              ? `Save could not be confirmed. ${op.error}`
              : op.phase === "success"
                ? "Intervals saved"
                : ""}
      </p>
      {(loadFailed || op.phase === "failure") && (
        <button
          type="button"
          disabled={op.busy}
          onClick={() => setReload((n) => n + 1)}
        >
          Reload intervals
        </button>
      )}
    </form>
  );
}
const initial: SMTPInput = {
  host: "",
  port: 587,
  encryption: "starttls",
  username: "",
  fromName: "",
  replyTo: "",
  emailsPerMinute: 10,
};
function smtpDraft(s: SMTPStatus): SMTPInput {
  return {
    host: s.host ?? "",
    port: s.port ?? 587,
    encryption: s.encryption ?? "starttls",
    username: s.username ?? "",
    fromName: s.fromName ?? "",
    replyTo: s.replyTo ?? "",
    emailsPerMinute: s.emailsPerMinute ?? 10,
  };
}
function Email({
  api,
  report,
  confirm,
  active,
}: {
  api: SettingsAPI;
  report: Report;
  confirm: Confirm;
  active: boolean;
}) {
  const [saved, setSaved] = useState<SMTPStatus | null>(null),
    [draft, setDraft] = useState<SMTPInput>(initial),
    [password, setPassword] = useState(""),
    [recipient, setRecipient] = useState(""),
    [loadFailed, setLoadFailed] = useState(false),
    [task, setTask] = useState<"save" | "test" | "send">("save"),
    [testPassed, setTestPassed] = useState(false);
  const op = useOperation();
  const [deliveryWarning, setDeliveryWarning] = useState(false);
  const [editing, setEditing] = useState(false),
    [sending, setSending] = useState(false),
    [reload, setReload] = useState(0);
  const dirty =
    !!password ||
    JSON.stringify(draft) !==
      JSON.stringify(saved ? smtpDraft(saved) : initial);
  const edited = useRef(false);
  edited.current = dirty || op.busy;
  useEffect(() => {
    if (!active) return;
    let current = true;
    const version = op.revision.current;
    api.smtp().then(
      (r) => {
        if (current && version === op.revision.current) {
          if (r.ok) {
            setSaved(r.data);
            if (!edited.current) setDraft(smtpDraft(r.data));
            setLoadFailed(false);
            op.reconcile();
          } else setLoadFailed(true);
        }
      },
      () => {
        if (current) setLoadFailed(true);
      },
    );
    return () => {
      current = false;
    };
  }, [active, api, op.revision, op.reconcile, reload]);
  useDraft(
    "email",
    dirty,
    op.busy,
    () => {
      setPassword("");
      setDraft(saved ? smtpDraft(saved) : initial);
      setRecipient("");
      setEditing(false);
      setSending(false);
    },
    report,
  );
  function field(
    key: keyof SMTPInput,
    label: string,
    type = "text",
    extra: Record<string, unknown> = {},
  ) {
    return (
      <label>
        {label}
        <input
          type={type}
          value={String(draft[key] ?? "")}
          disabled={!saved || op.busy}
          onChange={(e) =>
            setDraft({
              ...draft,
              [key]:
                type === "number" ? Number(e.target.value) : e.target.value,
            })
          }
          {...extra}
        />
      </label>
    );
  }
  const clean =
    !!saved?.configured && !dirty && !op.busy && op.phase !== "failure";
  return (
    <>
      <h2>Email delivery</h2>
      {saved?.configured && (
        <div className="cloud-row">
          <div>
            <p>{`${saved.fromName || ""} <${saved.username || ""}>`}</p>
            <span>
              {saved.lastTestStatus
                ? `Last SMTP test: ${saved.lastTestStatus}`
                : "Not tested"}
            </span>
            <details>
              <summary>SMTP connection details</summary>
              <p>{saved.host} · {saved.port} · {saved.encryption?.toUpperCase()}</p>
            </details>
            {saved.encryption === "none" && <p role="alert">Unencrypted SMTP exposes credentials and email in transit.</p>}
          </div>
          <button
            disabled={op.busy}
            onClick={() => setEditing(!editing)}
            aria-expanded={editing}
          >
            Edit email settings
          </button>
        </div>
      )}
      {(editing || !saved?.configured) && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            confirm(
              `Save shared email settings for everyone using this workspace?${draft.encryption === "none" ? " Warning: unencrypted SMTP exposes credentials and email in transit." : ""}`,
              () => {
                setTask("save");
                const input = { ...draft, ...(password ? { password } : {}) };
                setPassword("");
                return op.run(
                  () => api.saveSMTP(input),
                  (value) => {
                    setSaved(value);
                    setDraft(smtpDraft(value));
                    setEditing(false);
                  },
                );
              },
            );
          }}
        >
          <div className="cloud-grid">
            {field("host", "SMTP host", "text", { required: true })}
            {field("port", "Port", "number", {
              min: 1,
              max: 65535,
              required: true,
            })}
            <label>
              Encryption
              <select
                value={draft.encryption}
                disabled={!saved || op.busy}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    encryption: e.target.value as SMTPInput["encryption"],
                  })
                }
              >
                <option value="starttls">STARTTLS</option>
                <option value="tls">TLS</option>
                <option value="none">Unencrypted</option>
              </select>
            </label>
            {field("username", "Username email", "email", { required: true })}
            <label>
              {saved?.configured
                ? "Replacement password (optional)"
                : "Password"}
              <input
                type="password"
                autoComplete="new-password"
                disabled={!saved || op.busy}
                required={!saved?.configured}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {field("fromName", "From name", "text", { required: true })}
            {field("replyTo", "Reply-To email", "email", { required: true })}
          </div>
          <details>
            <summary>Rate limit</summary>
            {field("emailsPerMinute", "Emails per minute", "number", {
              min: 1,
              max: 60,
              required: true,
            })}
          </details>
          {draft.encryption === "none" && (
            <p role="alert">
              Unencrypted SMTP exposes credentials and email in transit.
            </p>
          )}
          <button disabled={!saved || !dirty || op.busy}>
            Save email settings
          </button>
        </form>
      )}
      <div className="cloud-actions">
        <button
          disabled={!clean}
          onClick={() => {
            setTask("test");
            void op.run(
              () => api.testSMTP(),
              (r) => {
                setTestPassed(r.succeeded);
                setSaved((current) =>
                  current
                    ? {
                        ...current,
                        lastTestStatus: r.lastTestStatus,
                        lastTestedAt: r.lastTestedAt,
                      }
                    : current,
                );
              },
            );
          }}
        >
          Test connection
        </button>
        <button
          disabled={!clean}
          onClick={() => setSending(!sending)}
          aria-expanded={sending}
        >
          Send test email…
        </button>
      </div>
      {sending && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            confirm(
              `Send one test email to ${recipient} from ${saved?.fromName || ""} <${saved?.username || ""}>?`,
              () => {
                setTask("send");
                return op
                  .run(
                    () => api.sendTestEmail({ recipient }),
                    (r) => {
                      setTestPassed(r.succeeded);
                      setSaved((current) =>
                        current
                          ? {
                              ...current,
                              lastTestStatus: r.lastTestStatus,
                              lastTestedAt: r.lastTestedAt,
                            }
                          : current,
                      );
                      if (!r.succeeded) setDeliveryWarning(true);
                    },
                  )
                  .then((success) => {
                    if (success === false) setDeliveryWarning(true);
                  });
              },
            );
          }}
        >
          <label>
            Test recipient email
            <input
              type="email"
              required
              value={recipient}
              disabled={!clean}
              onChange={(e) => setRecipient(e.target.value)}
            />
          </label>
          <button disabled={!clean || !recipient.trim()}>
            Send test email
          </button>
        </form>
      )}
      {deliveryWarning && (
        <p role="alert">
          Delivery may be unknown. Check the recipient inbox before sending
          again.
        </p>
      )}
      <p role="status">
        {loadFailed
          ? "Unable to load email settings. Check Workspace connection and your workspace key."
          : op.busy
            ? "Working…"
            : op.phase === "failure"
              ? task === "send"
                ? "Send could not be confirmed"
                : `Operation could not be confirmed. ${op.error}`
              : op.phase === "success"
                ? task === "save"
                  ? "Email settings saved"
                  : task === "test"
                    ? testPassed
                      ? "Connection test succeeded"
                      : "Connection test failed. Check SMTP host, encryption and saved credentials."
                    : testPassed
                      ? "Test email accepted"
                      : "Send could not be confirmed"
                : ""}
      </p>
      {(loadFailed || op.phase === "failure") && (
        <button disabled={op.busy} onClick={() => setReload((n) => n + 1)}>
          Reload email settings
        </button>
      )}
    </>
  );
}
function ConnectedCloud({
  api,
  section,
  active = true,
  onDraftStateChange,
}: CloudSettingsProps) {
  const states = useRef(new Map<string, CloudDraftState>()),
    callback = useRef(onDraftStateChange);
  callback.current = onDraftStateChange;
  const [confirmation, setConfirmation] = useState<{
    message: string;
    action: () => void | Promise<unknown>;
  } | null>(null);
  const [expanded, setExpanded] = useState<ServiceName | null>(null);
  const confirm = useCallback<Confirm>(
    (message, action) => setConfirmation({ message, action }),
    [],
  );
  const discard = useCallback(() => {
    for (const state of states.current.values()) state.discard();
    setConfirmation(null);
    setExpanded(null);
  }, []);
  const previous = useRef("");
  const report = useCallback<Report>(
    (key, state) => {
      if (state) states.current.set(key, state);
      else states.current.delete(key);
      const all = [...states.current.values()];
      const dirty = all.some((s) => s.dirty),
        busy = all.some((s) => s.busy);
      const signature = `${dirty}:${busy}`;
      if (signature !== previous.current) {
        previous.current = signature;
        callback.current?.({ dirty, busy, discard });
      }
    },
    [discard],
  );
  useDraft("confirmation", false, !!confirmation, noop, report);
  return (
    <div className="cloud-settings">
      <section
        role="tabpanel"
        tabIndex={-1}
        id="settings-panel-services"
        aria-labelledby="settings-tab-services"
        hidden={section !== "services"}
      >
        <h2>Services</h2>
        {serviceNames.map((name) => (
          <Provider
            key={name}
            name={name}
            api={api}
            report={report}
            confirm={confirm}
            expanded={expanded === name}
            active={active && section === "services"}
            onToggle={() =>
              setExpanded((current) => (current === name ? null : name))
            }
          />
        ))}
        {["Twitch", "Instagram"].map((name) => (
          <div className="cloud-row" key={name}>
            <h3>{name}</h3>
            <span>Unavailable</span>
          </div>
        ))}
      </section>
      <section
        role="tabpanel"
        tabIndex={-1}
        id="settings-panel-refresh"
        aria-labelledby="settings-tab-refresh"
        hidden={section !== "refresh"}
      >
        <Refresh api={api} report={report} confirm={confirm} active={active && section === "refresh"} />
      </section>
      <section
        role="tabpanel"
        tabIndex={-1}
        id="settings-panel-email"
        aria-labelledby="settings-tab-email"
        hidden={section !== "email"}
      >
        <Email api={api} report={report} confirm={confirm} active={active && section === "email"} />
      </section>
      {confirmation && (
        <Confirmation {...confirmation} cancel={() => setConfirmation(null)} />
      )}
    </div>
  );
}
export function CloudSettings(props: CloudSettingsProps) {
  const callback = useRef(props.onDraftStateChange);
  callback.current = props.onDraftStateChange;
  useEffect(() => {
    if (!props.connected)
      callback.current?.({ dirty: false, busy: false, discard: noop });
  }, [props.connected]);
  return props.connected ? (
    <ConnectedCloud {...props} />
  ) : (
    <p>Connect to your workspace to manage cloud settings.</p>
  );
}
