import { json } from '@sveltejs/kit';
import { settingsPatchSchema } from '@ledger/shared-types';

import { apiError, privateReadHeaders, unavailableOrInternal, validationError } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';

type SettingsRow = { base_currency: string; market_profile: 'CA' | 'TZ' | null; updated_at: Date };

export async function GET() {
  try {
    const result = await query<SettingsRow>(
      `SELECT base_currency, market_profile, updated_at
       FROM ledger_settings
       WHERE singleton`
    );
    const settings = result.rows[0];
    if (!settings) throw new Error('Ledger settings row is missing');
    return json(
      {
        baseCurrency: settings.base_currency,
        marketProfile: settings.market_profile,
        updatedAt: settings.updated_at.toISOString()
      },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'settings');
  }
}

export async function PATCH({ request }) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return apiError(400, 'invalid_json', 'Expected a JSON settings payload.');
  }
  const parsed = settingsPatchSchema.safeParse(body);
  if (!parsed.success) return validationError(parsed.error);

  try {
    const result = await query<SettingsRow>(
      `UPDATE ledger_settings
       SET market_profile = $1, updated_at = now()
       WHERE singleton
       RETURNING base_currency, market_profile, updated_at`,
      [parsed.data.marketProfile]
    );
    const settings = result.rows[0];
    if (!settings) throw new Error('Ledger settings row is missing');
    return json(
      {
        baseCurrency: settings.base_currency,
        marketProfile: settings.market_profile,
        updatedAt: settings.updated_at.toISOString()
      },
      { headers: { 'cache-control': 'no-store' } }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'update settings');
  }
}
