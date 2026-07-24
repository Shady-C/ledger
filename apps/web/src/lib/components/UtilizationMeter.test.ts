/** @vitest-environment jsdom */

import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import UtilizationMeter from './UtilizationMeter.svelte';

afterEach(cleanup);

describe('UtilizationMeter', () => {
  it('renders the exact server values and keeps an over-limit meter accessible', () => {
    render(UtilizationMeter, {
      props: {
        label: 'Travel card utilization',
        value: '112.50',
        used: '6750.00',
        limit: '6000.00',
        available: '-750.00',
        currency: 'CAD'
      }
    });

    const meter = screen.getByRole('meter', { name: 'Travel card utilization' });
    expect(meter.getAttribute('aria-valuenow')).toBe('112.5');
    expect(meter.getAttribute('aria-valuetext')).toBe('112.5 percent');
    expect(screen.getByText('112.5%')).toBeTruthy();
    expect(screen.getByText(/6,750\.00 used/)).toBeTruthy();
    expect(screen.getByText(/750\.00 available/)).toBeTruthy();
  });

  it('explains why utilization is unavailable when no limit is supplied', () => {
    render(UtilizationMeter, {
      props: { label: 'Card utilization', value: null, used: '120.00', limit: null, currency: 'CAD' }
    });

    expect(screen.getByText('Not available')).toBeTruthy();
    expect(screen.getByText('Add a credit limit')).toBeTruthy();
    expect(screen.getByRole('meter').getAttribute('aria-valuenow')).toBeNull();
  });
});
