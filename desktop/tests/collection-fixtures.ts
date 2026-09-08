import type { CollectionSettings } from '../src/shared/settings';

export function collectionSettingsFixture(): CollectionSettings {
  return {
    items: [
      { platform: 'youtube', enabled: true, implemented: true, credentials_configured: true, availability: 'configured_unverified' },
      { platform: 'x', enabled: true, implemented: true, credentials_configured: true, availability: 'configured_unverified' },
      { platform: 'twitch', enabled: false, implemented: false, credentials_configured: false, availability: 'disabled' },
      { platform: 'instagram', enabled: false, implemented: false, credentials_configured: false, availability: 'disabled' },
    ],
  };
}
