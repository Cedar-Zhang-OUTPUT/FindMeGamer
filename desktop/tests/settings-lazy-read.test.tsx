// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import type { DesktopBridge } from '../src/shared/bridge';
import type { AppearanceState } from '../src/renderer/hooks/useAppearance';
import { SettingsView } from '../src/renderer/components/settings/SettingsView';
import { settingsBridgeMock } from './settings-fixtures';

afterEach(cleanup);

function setup() {
  const local = settingsBridgeMock();
  const api = {
    ...local,
    connection: {} as DesktopBridge['connection'],
    library: { list: vi.fn(), detail: vi.fn() } as DesktopBridge['library'],
    games: {} as DesktopBridge['games'],
    openExternal: vi.fn(),
  } as DesktopBridge;
  const appearance = {
    preferences: { appearance: 'system' as const, fontSize: 'default' as const, automaticUpdates: true },
    error: null, busy: false, save: vi.fn(),
  } as AppearanceState;
  const props = {
    api, active: true, available: true, workspaceEpoch: 0, appearance,
    connection: {
      status: { serviceUrl: 'https://workspace.example.com', hasKey: true, storageAvailable: true },
      phase: 'connected' as const, error: null, route: 'direct' as const, recovering: false,
      onConnect: vi.fn(), onTest: vi.fn(), onDisconnect: vi.fn(), onLibrary: vi.fn(),
    },
    onNavigationGuardChange: vi.fn(),
  };
  return { api, props };
}

it('reads only the cloud section the user opens', async () => {
  const { api, props } = setup();
  const user = userEvent.setup();
  render(<SettingsView {...props} />);
  await act(async () => {});

  expect(api.settings.connection).not.toHaveBeenCalled();
  expect(api.settings.reanalysis).not.toHaveBeenCalled();
  expect(api.settings.smtp).not.toHaveBeenCalled();

  await user.click(screen.getByRole('tab', { name: 'Services' }));
  await waitFor(() => expect(api.settings.connection).toHaveBeenCalledTimes(5));
  expect(api.settings.reanalysis).not.toHaveBeenCalled();
  expect(api.settings.smtp).not.toHaveBeenCalled();

  await user.click(screen.getByRole('tab', { name: 'Auto-refresh' }));
  await waitFor(() => expect(api.settings.reanalysis).toHaveBeenCalledTimes(1));
  expect(api.settings.connection).toHaveBeenCalledTimes(5);
  expect(api.settings.smtp).not.toHaveBeenCalled();

  await user.click(screen.getByRole('tab', { name: 'Email' }));
  await waitFor(() => expect(api.settings.smtp).toHaveBeenCalledTimes(1));
  expect(api.settings.connection).toHaveBeenCalledTimes(5);
  expect(api.settings.reanalysis).toHaveBeenCalledTimes(1);
});

it('retains a cloud draft across sections but resets it lazily for a new workspace epoch', async () => {
  const { api, props } = setup();
  const user = userEvent.setup();
  const view = render(<SettingsView {...props} />);

  await user.click(screen.getByRole('tab', { name: 'Services' }));
  await user.click(await screen.findByRole('button', { name: 'Replace YouTube credential' }));
  await user.type(screen.getByLabelText('YouTube replacement credential'), 'retained-draft');
  await user.click(screen.getByRole('tab', { name: 'Auto-refresh' }));
  await user.click(screen.getByRole('tab', { name: 'Services' }));
  expect(screen.getByLabelText('YouTube replacement credential')).toHaveValue('retained-draft');

  await user.click(screen.getByRole('tab', { name: 'Workspace' }));
  expect(api.settings.connection).toHaveBeenCalledTimes(10);
  expect(api.settings.reanalysis).toHaveBeenCalledTimes(1);
  view.rerender(<SettingsView {...props} workspaceEpoch={1} />);
  await act(async () => {});
  expect(api.settings.connection).toHaveBeenCalledTimes(10);
  expect(api.settings.reanalysis).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole('tab', { name: 'Services' }));
  await waitFor(() => expect(api.settings.connection).toHaveBeenCalledTimes(15));
  expect(screen.queryByLabelText('YouTube replacement credential')).not.toBeInTheDocument();
});
