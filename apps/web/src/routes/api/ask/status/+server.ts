import { json } from '@sveltejs/kit';

import { privateReadHeaders } from '$lib/server/api.js';
import { askConfig } from '$lib/server/env.js';

export function GET() {
  const config = askConfig();
  return json(
    { enabled: config.enabled, available: config.available, reason: config.reason },
    { headers: privateReadHeaders }
  );
}
