import { useState } from 'react';
import type { DesktopBridge } from '../../shared/bridge';
import type { ReferenceWork, SteamRecommendations } from '../../shared/games';

export function SteamReferenceSource({ reference, api }: { reference?: ReferenceWork; api?: Pick<DesktopBridge, 'openExternal'> }) {
  const [failed, setFailed] = useState(false);
  if (reference?.source !== 'steam_more_like_this') return null;
  const source = reference.source_url;
  const canOpen = source && /^https:\/\//i.test(source) && api;
  async function open() {
    if (!source || !api) return;
    try { const result = await api.openExternal(source); setFailed(!result.ok); } catch { setFailed(true); }
  }
  return <div className="game-reference-provenance"><span className="game-source-badge">Steam recommendation</span>{canOpen && <button type="button" className="text-button" aria-label={`View Steam source for ${reference.name || reference.url}`} onClick={() => void open()}>View source ↗</button>}{failed && <span role="alert">Could not open Steam source.</span>}</div>;
}

export function SteamRecommendationsStatus({ state }: { state?: SteamRecommendations }) {
  if (state?.status !== 'partial' && state?.status !== 'unavailable') return null;
  return <p className="muted" role="status">{state.status === 'partial' ? 'Some Steam recommendations could not be loaded.' : 'Steam recommendations unavailable. Existing references are unchanged.'}</p>;
}
