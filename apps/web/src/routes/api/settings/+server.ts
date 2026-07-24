import { json } from '@sveltejs/kit';

import { privateReadHeaders, unavailableOrInternal } from '$lib/server/api.js';
import { query } from '$lib/server/db.js';

type SettingsRow = { base_currency: string; updated_at: Date };

export async function GET() {
  try {
    const result = await query<SettingsRow>(
      `SELECT base_currency, updated_at
       FROM ledger_settings
       WHERE singleton`
    );
    const settings = result.rows[0];
    if (!settings) throw new Error('Ledger settings row is missing');
    return json(
      { baseCurrency: settings.base_currency, updatedAt: settings.updated_at.toISOString() },
      { headers: privateReadHeaders }
    );
  } catch (error) {
    return unavailableOrInternal(error, 'settings');
  }
}
