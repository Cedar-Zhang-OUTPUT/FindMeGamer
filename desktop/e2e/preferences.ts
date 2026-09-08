import { PreferencesStore } from '../src/main/preferences-store';

/** Isolated test profiles never perform automatic public update requests. */
export async function isolatedPreferences(directory:string) {
  await new PreferencesStore(directory).update({automaticUpdates:false});
}
