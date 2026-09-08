import { useCallback, useEffect, useRef, useState } from "react";
import type {
  CollectionPlatform,
  CollectionPlatformState,
  CollectionSettings as SavedCollectionSettings,
  SettingsAPI,
} from "../../../shared/settings";
import type { CloudDraftState } from "./CloudSettings";
import "./collectionSettings.css";

export interface CollectionSettingsProps {
  api: SettingsAPI;
  connected: boolean;
  active: boolean;
  onDraftStateChange?: (state: CloudDraftState) => void;
}

const labels: Record<CollectionPlatform, string> = { youtube: "YouTube", x: "X", twitch: "Twitch", instagram: "Instagram" };
const availabilityLabels: Record<CollectionPlatformState["availability"], string> = {
  disabled: "Collection disabled",
  not_implemented: "Unavailable this release",
  missing_connection: "Connection required",
  configured_unverified: "Configured · Access not verified",
};
const noop = () => {};

function Confirmation({ platform, enabled, onCancel, onConfirm }: {
  platform: CollectionPlatform;
  enabled: boolean;
  onCancel: () => void;
  onConfirm: (origin: HTMLElement | null) => void;
}) {
  const dialog = useRef<HTMLDivElement>(null);
  const origin = useRef<HTMLElement | null>(null);
  const confirmed = useRef(false);
  useEffect(() => {
    origin.current = document.activeElement as HTMLElement | null;
    dialog.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => { if (!confirmed.current) origin.current?.focus(); };
  }, []);
  return <div className="collection-modal-backdrop"><div ref={dialog} className="collection-modal" role="dialog" aria-modal="true" aria-labelledby="collection-confirm-title" onKeyDown={event => {
    if (event.key === "Escape") { event.preventDefault(); onCancel(); }
    if (event.key === "Tab") {
      const buttons = dialog.current?.querySelectorAll("button");
      if (!buttons?.length) return;
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}>
    <h3 id="collection-confirm-title">Confirm collection change</h3>
    <p>This changes {labels[platform]} collection for everyone using this workspace. {enabled ? "Enabling collection does not resume paused work." : "Pause after the in-flight collection finishes. Enabling later does not resume paused work."}</p>
    <div className="collection-actions"><button type="button" onClick={onCancel}>Cancel</button><button type="button" onClick={() => { confirmed.current = true; onConfirm(origin.current); }}>Confirm</button></div>
  </div></div>;
}

export function CollectionSettings({ api, connected, active, onDraftStateChange }: CollectionSettingsProps) {
  const [saved, setSaved] = useState<SavedCollectionSettings | null>(null);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<"read" | "save" | null>(null);
  const [savedOnce, setSavedOnce] = useState(false);
  const [reload, setReload] = useState(0);
  const [confirmation, setConfirmation] = useState<{ platform: CollectionPlatform; enabled: boolean } | null>(null);
  const alive = useRef(true), revision = useRef(0), saveLock = useRef(false);
  const discard = useCallback(() => setConfirmation(null), []);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; revision.current++; };
  }, []);
  useEffect(() => {
    onDraftStateChange?.({ dirty: false, busy: !!confirmation || saving, discard });
  }, [confirmation, discard, onDraftStateChange, saving]);
  useEffect(() => () => onDraftStateChange?.({ dirty: false, busy: false, discard: noop }), [onDraftStateChange]);

  useEffect(() => {
    if (!connected || !active || saveLock.current) return;
    const version = ++revision.current;
    setReading(true);
    void api.collection().then(result => {
      if (!alive.current || version !== revision.current) return;
      if (result.ok) { setSaved(result.data); setFailure(null); setSavedOnce(false); } else setFailure("read");
      setReading(false);
    }, () => {
      if (!alive.current || version !== revision.current) return;
      setFailure("read"); setReading(false);
    });
  }, [active, api, connected, reload]);

  function save(platform: CollectionPlatform, enabled: boolean, focusTarget: HTMLElement | null) {
    if (saveLock.current) return;
    saveLock.current = true;
    setConfirmation(null); setReading(false); setSaving(true); setFailure(null);
    const version = ++revision.current;
    const restoreFocus = () => setTimeout(() => {
      const panel = document.getElementById("settings-panel-collection");
      if (focusTarget?.isConnected && !focusTarget.matches(":disabled") && !focusTarget.closest("[hidden]")) focusTarget.focus();
      else if (panel?.isConnected && !panel.closest("[hidden]")) panel.focus();
    }, 0);
    document.getElementById("settings-panel-collection")?.focus();
    void api.setCollection({ platform, enabled }).then(result => {
      if (alive.current && version === revision.current) {
        if (result.ok) { setSaved(result.data); setSavedOnce(true); } else setFailure("save");
        setSaving(false);
        restoreFocus();
      }
      saveLock.current = false;
    }, () => {
      if (alive.current && version === revision.current) { setFailure("save"); setSaving(false); restoreFocus(); }
      saveLock.current = false;
    });
  }

  return <section className="collection-settings" id="settings-panel-collection" role="tabpanel" tabIndex={-1} aria-labelledby="settings-tab-collection" hidden={!active}>
    <h2>Collection</h2>
    {!connected ? <div role="status">Connect to your workspace to manage collection settings.</div> : !saved ? <div role="status">{failure === "read" ? "Unable to load saved collection settings." : "Loading collection settings…"}</div> : <div className="collection-platforms">{saved.items.map(item => {
      const label = labels[item.platform];
      const unsupported = item.platform === "twitch" || item.platform === "instagram";
      return <fieldset className="collection-platform" key={item.platform} aria-label={label}>
        <legend>{label}</legend>
        <div className="collection-platform-state">
          <span>{item.implemented ? availabilityLabels[item.availability] : "Unavailable this release"}</span>
          <span>{item.credentials_configured ? "Credentials saved" : "No credentials"}</span>
        </div>
        <label><span>Collect from {label}</span><input type="checkbox" role="switch" aria-label={`Collect from ${label}`} checked={item.enabled} disabled={unsupported || saving || !!confirmation || failure !== null} onChange={() => setConfirmation({ platform: item.platform, enabled: !item.enabled })}/></label>
      </fieldset>;
    })}</div>}
    {connected && <div className="collection-footer"><button type="button" disabled={reading || saving || !!confirmation} onClick={() => setReload(value => value + 1)}>Reload saved settings</button><span role="status">{saving ? "Saving collection settings…" : failure === "save" ? "Save could not be confirmed. Reload saved settings before trying again." : failure === "read" ? "Read failed. Last known collection settings are retained." : savedOnce ? "Collection settings saved" : ""}</span></div>}
    {confirmation && <Confirmation
      {...confirmation}
      onCancel={() => setConfirmation(null)}
      onConfirm={origin => save(confirmation.platform, confirmation.enabled, origin)}
    />}
  </section>;
}
