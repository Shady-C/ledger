/** @vitest-environment jsdom */

import { cleanup, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';

import TrendChart from './TrendChart.svelte';

afterEach(cleanup);

describe('TrendChart', () => {
  it('exposes the chart and exact monthly values to assistive technology', () => {
    render(TrendChart, {
      props: {
        points: [
          {
            period: '2026-06-01',
            dimensionType: 'ledger',
            dimensionId: null,
            dimensionName: 'Ledger',
            inflow: '4000.00',
            outflow: '1250.25',
            spending: '1100.25',
            netCashflow: '2749.75',
            trailingAverageSpending: null,
            trailingMedianSpending: null,
            monthOverMonth: null,
            yearOverYear: null,
            coverageStatus: 'partial',
            missingValuationCount: 1
          }
        ]
      }
    });

    expect(screen.getByRole('img', { name: /Monthly spending trend/ })).toBeTruthy();
    expect(screen.getByRole('list', { name: 'Trend values' }).textContent).toContain('1,100.25');
    expect(screen.getByRole('list', { name: 'Trend values' }).textContent).toContain('Partial');
  });

  it('renders an explicit empty state', () => {
    render(TrendChart, { props: { points: [] } });
    expect(screen.getByRole('status').textContent).toContain('No trend data yet');
  });
});
