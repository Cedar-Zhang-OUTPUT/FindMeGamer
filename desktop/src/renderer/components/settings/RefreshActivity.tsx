import { useEffect, useState } from 'react';
import type { DesktopBridge } from '../../../shared/bridge';
import type { ListPage, ProfileKind } from '../../../shared/library';

type Props = { api: Pick<DesktopBridge, 'library'>; connected: boolean };

function Category({ api, kind }: { api: Props['api']; kind: ProfileKind }) {
  const [page, setPage] = useState<ListPage | null>(null);
  const [pending, setPending] = useState(true);
  const [failed, setFailed] = useState(false);
  const [request, setRequest] = useState<{ cursor?: string; attempt: number }>({ attempt: 0 });
  useEffect(() => {
    let current = true;
    setPending(true);
    setFailed(false);
    void (async () => {
      try {
        const result = await api.library.list({ kind, limit: 100,
          ...(request.cursor ? { cursor: request.cursor } : {}) });
        if (!current) return;
        if (!result.ok) { setFailed(true); return; }
        setPage(previous => ({ nextCursor: result.data.nextCursor,
          items: [...new Map([...(request.cursor ? previous?.items ?? [] : []), ...result.data.items]
            .map(item => [item.id, item])).values()] }));
      } catch {
        if (current) setFailed(true);
      } finally {
        if (current) setPending(false);
      }
    })();
    return () => { current = false; };
  }, [api.library, kind, request]);

  const items = page?.items ?? [];
  const lastDates = items.map(item => item.updatedAt).filter((date): date is string => typeof date === 'string' && Number.isFinite(Date.parse(date)));
  const nextDates = items.map(item => item.nextAnalysisAt).filter((date): date is string => typeof date === 'string' && Number.isFinite(Date.parse(date)));
  const last = lastDates.sort((a,b) => Date.parse(b)-Date.parse(a))[0];
  const next = nextDates.sort((a,b) => Date.parse(a)-Date.parse(b))[0];
  const unscheduled = items.filter(item => item.nextAnalysisAt === null).length;
  const unknown = items.length - nextDates.length - unscheduled;
  const partial = Boolean(page?.nextCursor);
  return <section aria-label={kind === 'games' ? 'Steam-linked games' : 'YouTube creators'} className="refresh-activity-category">
    <h4>{kind === 'games' ? 'Steam-linked games' : 'YouTube creators'}</h4>
    {page && <dl>
      <dt>Loaded records</dt><dd>{partial ? `First ${items.length} records` : `${items.length} records`}</dd>
      <dt>Last analysis</dt><dd>{last ? <time dateTime={last}>{last}</time> : 'Unavailable'}</dd>
      <dt>Next refresh</dt><dd>{next ? <time dateTime={next}>{next}</time> : unknown ? 'Unavailable' : 'No scheduled refresh'}</dd>
      <dt>Scheduled</dt><dd>{nextDates.length}</dd>
      <dt>Not scheduled</dt><dd>{unscheduled}</dd>
      {unknown > 0 && <><dt>Schedule unavailable</dt><dd>{unknown}</dd></>}
    </dl>}
    {pending && <p role="status">Loading {kind} activity…</p>}
    {failed && <p role="alert">Could not load {kind} activity.</p>}
    {failed ? <button type="button" disabled={pending} onClick={() => setRequest(previous => ({ ...previous, attempt: previous.attempt + 1 }))}>Retry {kind}</button>
      : page?.nextCursor && <button type="button" disabled={pending} onClick={() => setRequest(previous => ({ cursor: page.nextCursor!, attempt: previous.attempt + 1 }))}>Load more {kind}</button>}
  </section>;
}

function ConnectedActivity({ api }: Pick<Props, 'api'>) {
  const [started, setStarted] = useState(false);
  return <details className="refresh-activity" onToggle={event => { if (event.currentTarget.open) setStarted(true); }}>
    <summary>Refresh activity</summary>
    {started && <><Category api={api} kind="games"/><Category api={api} kind="creators"/></>}
  </details>;
}

export function RefreshActivity({ api, connected }: Props) {
  return connected ? <ConnectedActivity api={api}/> : <p>Connect a workspace to view refresh activity.</p>;
}
