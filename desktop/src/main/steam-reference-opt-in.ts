// Narrow response-shape opt-in. Older installed clients keep their original DTOs.
// Only authenticated workspace API transports import this; never external media/links.
export const STEAM_REFERENCES_OPT_IN = { 'X-FMG-Steam-References': '1' } as const;
