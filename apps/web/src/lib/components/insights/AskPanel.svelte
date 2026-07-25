<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import type {
    AskClarificationChoice,
    AskPlanV1,
    AskRequest,
    AskResponse,
    AskStatusResponse
  } from '@ledger/shared-types';

  export let market: 'ALL' | 'CA' | 'TZ' = 'ALL';
  export let currency = 'CAD';

  type JsonRecord = Record<string, unknown>;
  type HistoryEntry = { question: string; plan: AskPlanV1 };
  type TableColumn = {
    key: string;
    label: string;
    type: 'text' | 'money' | 'decimal' | 'number' | 'date' | 'percentage' | 'status';
    currency?: string;
  };
  type ChartPoint = {
    label: string;
    display: string;
    value: number;
    position: number;
    zero: number;
  };
  type ResolvedQueryView = {
    queryId: string;
    dataset: string;
    market: string;
    from: string;
    to: string;
    comparisonFrom?: string;
    comparisonTo?: string;
  };

  const examples = [
    'How much did I spend last month?',
    'Which categories drove spending this quarter?',
    'Show recurring charges that are overdue.',
    'What did foreign spending cost me this year?'
  ];

  const operationMessages: Record<number, string> = {
    400: 'Check the question, scope, and browser timezone, then try again.',
    429: 'Ask is already handling two questions. Try again when one finishes.',
    502: 'The provider could not create a safe query plan. Rephrase the question and try again.',
    503: 'Ask is temporarily unavailable. Deterministic Insights remain available in the other tabs.',
    504: 'The question took too long to answer. Try a narrower question.'
  };

  let status: AskStatusResponse | null = null;
  let statusLoading = true;
  let statusError = '';
  let question = '';
  let lastQuestion = '';
  let response: AskResponse | null = null;
  let requestError = '';
  let requestNotice = '';
  let submitting = false;
  let history: HistoryEntry[] = [];
  let statusController: AbortController | null = null;
  let requestController: AbortController | null = null;
  let questionInput: HTMLTextAreaElement;
  let resultHeading: HTMLElement;
  let mounted = false;
  let previousContext = `${market}:${currency}`;

  $: statusRecord = asRecord(status);
  $: askEnabled = statusRecord.enabled === true;
  $: askAvailable = statusRecord.available === true;
  $: statusReason = readableReason(asText(statusRecord.reason));
  $: outcome = response?.kind ?? '';
  $: answerBlocks = response ? blocksFrom(response) : [];
  $: evidenceItems = response ? evidenceFrom(response) : [];
  $: normalizedPlan = response ? planFrom(response) : null;
  $: responseWarnings = response ? warningsFrom(response) : [];
  $: clarification = response ? clarificationFrom(response) : null;
  $: unsupported = response ? unsupportedFrom(response) : null;
  $: responseMetadata = response ? metadataFrom(response) : [];
  $: resolvedQueries = response ? resolvedQueriesFrom(response) : [];
  $: nextContext = `${market}:${currency}`;
  $: if (mounted && nextContext !== previousContext) {
    const hadConversation = Boolean(question || lastQuestion || response || history.length || submitting);
    previousContext = nextContext;
    resetConversation(false);
    if (hadConversation) {
      requestNotice = 'Conversation cleared because the active scope or home currency changed.';
    }
  }

  function asRecord(value: unknown): JsonRecord {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
      ? value as JsonRecord
      : {};
  }

  function asList(value: unknown): unknown[] {
    return Array.isArray(value) ? value : [];
  }

  function asText(value: unknown): string {
    return typeof value === 'string' ? value : '';
  }

  function titleCase(value: string) {
    return value.replaceAll('_', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function readableReason(reason: string) {
    if (!reason) return '';
    const messages: Record<string, string> = {
      disabled: 'Ask is turned off for this Ledger installation.',
      provider_unavailable: 'The configured Ask provider is unavailable.',
      missing_configuration: 'Ask needs provider credentials and model configuration before it can answer questions.',
      invalid_configuration: 'Ask configuration needs attention.'
    };
    return messages[reason] ?? titleCase(reason);
  }

  function browserTimeZone() {
    try {
      const value = Intl.DateTimeFormat().resolvedOptions().timeZone;
      if (value) {
        new Intl.DateTimeFormat('en', { timeZone: value }).format(new Date());
        return value;
      }
    } catch {
      // UTC is a valid, deterministic fallback when the browser cannot identify its zone.
    }
    return 'UTC';
  }

  async function errorMessage(apiResponse: Response, fallback: string) {
    try {
      const body = asRecord(await apiResponse.json());
      const error = asRecord(body.error);
      return asText(error.message) || operationMessages[apiResponse.status] || fallback;
    } catch {
      return operationMessages[apiResponse.status] || fallback;
    }
  }

  async function loadStatus() {
    statusController?.abort();
    const controller = new AbortController();
    statusController = controller;
    statusLoading = true;
    statusError = '';
    try {
      const apiResponse = await fetch('/api/ask/status', {
        cache: 'no-store',
        headers: { accept: 'application/json' },
        signal: controller.signal
      });
      if (!apiResponse.ok) {
        throw new Error(await errorMessage(apiResponse, 'Ask status could not be checked.'));
      }
      status = await apiResponse.json() as AskStatusResponse;
    } catch (error) {
      if (!controller.signal.aborted) {
        statusError = error instanceof Error ? error.message : 'Ask status could not be checked.';
      }
    } finally {
      if (statusController === controller) {
        statusLoading = false;
        statusController = null;
      }
    }
  }

  async function submitQuestion(
    nextQuestion = question,
    localSelection?: AskRequest['localSelection']
  ) {
    const trimmed = nextQuestion.trim();
    if (!askAvailable || submitting || trimmed.length < 1 || trimmed.length > 500) return;

    requestController?.abort();
    const controller = new AbortController();
    requestController = controller;
    submitting = true;
    requestError = '';
    requestNotice = '';
    response = null;
    question = trimmed;
    lastQuestion = trimmed;

    const body: AskRequest = {
      question: trimmed,
      market,
      timeZone: browserTimeZone(),
      history,
      ...(localSelection ? { localSelection } : {})
    };

    try {
      const apiResponse = await fetch('/api/ask', {
        method: 'POST',
        cache: 'no-store',
        headers: { accept: 'application/json', 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: controller.signal
      });
      if (!apiResponse.ok) {
        throw new Error(await errorMessage(apiResponse, 'Ledger could not answer that question.'));
      }
      const result = await apiResponse.json() as AskResponse;
      if (requestController !== controller) return;
      response = result;
      const plan = planFrom(result);
      const awaitsLocalSelection = result.kind === 'clarification_required'
        && result.choices.some((choice) => choice.localSelection !== undefined);
      if (plan && !awaitsLocalSelection) {
        history = [...history, { question: trimmed, plan }].slice(-3);
      }
      await tick();
      resultHeading?.focus();
    } catch (error) {
      if (requestController !== controller) return;
      if (controller.signal.aborted) {
        requestNotice = 'Ask request cancelled.';
      } else {
        requestError = error instanceof Error ? error.message : 'Ledger could not answer that question.';
      }
      await tick();
      resultHeading?.focus();
    } finally {
      if (requestController === controller) {
        submitting = false;
        requestController = null;
      }
    }
  }

  function cancelRequest() {
    requestController?.abort();
  }

  async function useExample(example: string) {
    question = example;
    await tick();
    questionInput?.focus();
  }

  async function useClarification(choice: AskClarificationChoice) {
    if (choice.localSelection) {
      const plan = response?.kind === 'clarification_required' ? response.plan : undefined;
      if (plan?.disposition !== 'execute') {
        requestError = 'This local clarification choice is no longer valid. Ask the question again.';
        return;
      }
      await submitQuestion(lastQuestion || question, {
        plan,
        queryId: choice.localSelection.queryId,
        entityToken: choice.localSelection.entityToken
      });
      return;
    }
    question = lastQuestion ? `${lastQuestion} (${choice.label})`.slice(0, 500) : choice.label;
    response = null;
    await tick();
    questionInput?.focus();
  }

  async function resetConversation(restoreFocus = true) {
    const activeRequest = requestController;
    requestController = null;
    activeRequest?.abort();
    submitting = false;
    question = '';
    lastQuestion = '';
    response = null;
    requestError = '';
    requestNotice = '';
    history = [];
    if (restoreFocus) {
      await tick();
      questionInput?.focus();
    }
  }

  function blocksFrom(value: AskResponse): unknown[] {
    return value.kind === 'answered' ? value.answer : [];
  }

  function segmentText(segment: unknown) {
    if (typeof segment === 'string') return segment;
    const record = asRecord(segment);
    return asText(record.text) || asText(record.display) || asText(record.value) || asText(record.label);
  }

  function blockText(value: unknown) {
    if (typeof value === 'string') return value;
    const record = asRecord(value);
    const segments = asList(record.segments);
    if (segments.length) return segments.map(segmentText).join('');
    return asText(record.text) || asText(record.content) || asText(record.value) || asText(record.label);
  }

  function evidenceFrom(value: AskResponse): JsonRecord[] {
    return value.kind === 'answered' ? value.evidence.map(asRecord) : [];
  }

  function evidenceTitle(item: JsonRecord, index: number) {
    return asText(item.title) || `Evidence ${index + 1}`;
  }

  function metricItems(item: JsonRecord) {
    if (asText(item.kind) !== 'metric') return [];
    const columns = tableColumns(item);
    const firstRow = tableRows(item)[0];
    if (!firstRow) return [];
    return columns.map((column, index) => {
      const value = cellValue(firstRow, column, index);
      return {
        label: column.label,
        value: formatCell(value, column),
        detail: ''
      };
    }).filter((metric) => metric.label || metric.value);
  }

  function tableColumns(item: JsonRecord): TableColumn[] {
    const table = asRecord(item.table);
    const columns = asList(table.columns).length ? asList(table.columns) : asList(item.columns);
    return columns.map((column, index) => {
      if (typeof column === 'string') return { key: column, label: titleCase(column), type: 'text' as const };
      const record = asRecord(column);
      const key = asText(record.key) || asText(record.id) || `column_${index}`;
      const type = asText(record.type);
      return {
        key,
        label: asText(record.label) || titleCase(key),
        type: ['text', 'money', 'decimal', 'number', 'date', 'percentage', 'status'].includes(type)
          ? type as TableColumn['type']
          : 'text',
        currency: asText(record.currency) || undefined
      };
    });
  }

  function tableRows(item: JsonRecord): unknown[] {
    const table = asRecord(item.table);
    return asList(table.rows).length ? asList(table.rows) : asList(item.rows);
  }

  function cellValue(row: unknown, column: TableColumn, index: number) {
    if (Array.isArray(row)) return row[index];
    const record = asRecord(row);
    const cells = asList(record.cells);
    if (cells.length) {
      const keyed = cells.find((cell) => asText(asRecord(cell).key) === column.key);
      return keyed ?? cells[index];
    }
    return record[column.key];
  }

  function cellText(value: unknown) {
    if (value === null || value === undefined) return '—';
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    if (typeof value === 'boolean') return value ? 'Yes' : 'No';
    const record = asRecord(value);
    return asText(record.display) || asText(record.text) || asText(record.value) || asText(record.label) || '—';
  }

  function groupedDecimal(value: string) {
    const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value);
    if (!match) return value;
    const sign = match[1] === '-' ? '−' : match[1];
    return `${sign}${match[2]!.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${match[3] ?? ''}`;
  }

  function formatCell(value: unknown, column: TableColumn) {
    const raw = cellText(value);
    if (raw === '—') return raw;
    if (column.type === 'money') {
      return /^[+-]?\d+(?:\.\d+)?$/.test(raw)
        ? column.currency
          ? `${column.currency} ${groupedDecimal(raw)}`
          : groupedDecimal(raw)
        : raw;
    }
    if (column.type === 'decimal') return groupedDecimal(raw);
    if (column.type === 'percentage') return raw.endsWith('%') ? raw : `${groupedDecimal(raw)}%`;
    if (column.type === 'number') return groupedDecimal(raw);
    if (column.type === 'status') return titleCase(raw);
    if (column.type === 'date') {
      const date = new Date(`${raw}T00:00:00Z`);
      if (!Number.isNaN(date.getTime())) {
        return new Intl.DateTimeFormat(undefined, {
          month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
        }).format(date);
      }
    }
    return raw;
  }

  function safeHref(value: unknown) {
    const record = asRecord(value);
    const href = asText(record.href) || asText(record.drillDownHref);
    return href.startsWith('/') && !href.startsWith('//') ? href : '';
  }

  function chartConfig(item: JsonRecord) {
    return { kind: asText(item.kind), xKey: '', yKey: '' };
  }

  function chartPoints(item: JsonRecord): ChartPoint[] {
    const config = chartConfig(item);
    if (!['bar', 'line'].includes(config.kind)) return [];
    const columns = tableColumns(item);
    const labelColumn = columns.find((column) => ['text', 'date', 'status'].includes(column.type)) ?? columns[0];
    const valueColumn = columns.find((column) => ['money', 'decimal', 'number', 'percentage'].includes(column.type) && column.key !== labelColumn?.key) ?? columns[1];
    if (!labelColumn || !valueColumn) return [];
    const raw = tableRows(item).map((row) => {
      const cell = cellValue(row, valueColumn, columns.indexOf(valueColumn));
      const raw = cellText(cell);
      const display = formatCell(cell, valueColumn);
      const value = Number.parseFloat(raw.replace(/[^0-9+.-]/g, ''));
      return {
        label: formatCell(cellValue(row, labelColumn, columns.indexOf(labelColumn)), labelColumn),
        display,
        value: Number.isFinite(value) ? value : 0
      };
    });
    const minimum = Math.min(0, ...raw.map((point) => point.value));
    const maximum = Math.max(0, ...raw.map((point) => point.value));
    const span = Math.max(1, maximum - minimum);
    const zero = (0 - minimum) / span;
    return raw.map((point) => ({
      ...point,
      position: (point.value - minimum) / span,
      zero
    }));
  }

  function linePoint(point: ChartPoint, index: number, total: number) {
    const x = total <= 1 ? 320 : 18 + index * (604 / (total - 1));
    const y = 168 - point.position * 140;
    return { x, y };
  }

  function lineZero(points: ChartPoint[]) {
    return points.length ? 168 - points[0]!.zero * 140 : 168;
  }

  function barBottom(point: ChartPoint) {
    return Math.min(point.position, point.zero) * 100;
  }

  function barHeight(point: ChartPoint) {
    return Math.max(1.5, Math.abs(point.position - point.zero) * 100);
  }

  function linePath(points: ChartPoint[]) {
    return points.map((point, index) => {
      const position = linePoint(point, index, points.length);
      return `${index === 0 ? 'M' : 'L'} ${position.x} ${position.y}`;
    }).join(' ');
  }

  function planFrom(value: AskResponse): AskPlanV1 | null {
    return 'plan' in value ? value.plan ?? null : null;
  }

  function safePlanJson(plan: unknown) {
    const blocked = new Set(['sql', 'prompt', 'system', 'messages', 'providerpayload']);
    return JSON.stringify(plan, (key, value) => blocked.has(key.toLowerCase()) ? undefined : value, 2);
  }

  function warningsFrom(value: AskResponse) {
    const warnings = value.kind === 'answered' ? [...value.warnings] : [];
    const context = value.kind === 'answered' || value.kind === 'no_data' ? value.context : null;
    if (context?.sourceChangedSinceGeneration) {
      warnings.unshift('Newer ledger activity exists than this analytics generation. Refresh analytics before relying on the answer as current.');
    }
    if (context?.coverage.status === 'partial') {
      const primaryDataset = context.resolvedQueries[0]?.dataset;
      const count = `${context.coverage.pendingFxCount} transaction${context.coverage.pendingFxCount === 1 ? '' : 's'}`;
      warnings.unshift(primaryDataset === 'transactions'
        ? `${count} appear in the evidence with ${context.baseCurrency} reporting amounts pending.`
        : primaryDataset === 'fx'
          ? `${count} lack complete FX reference evidence, so cost estimates are incomplete.`
          : `${count} await ${context.baseCurrency} valuation and are excluded from monetary calculations.`);
    }
    return [...new Set(warnings)];
  }

  function clarificationFrom(value: AskResponse) {
    return value.kind === 'clarification_required'
      ? { prompt: value.prompt, choices: value.choices }
      : null;
  }

  function unsupportedFrom(value: AskResponse) {
    return value.kind === 'unsupported'
      ? {
          reason: titleCase(value.reasonCode),
          guidance: value.message,
          suggestions: value.suggestions
        }
      : null;
  }

  function metadataFrom(value: AskResponse) {
    const context = value.kind === 'answered' || value.kind === 'no_data' ? value.context : null;
    if (!context) return [];
    const entries = [
      ['Market', context.market],
      ['Home currency', context.baseCurrency],
      ['As of', context.asOfDate],
      ['Timezone', context.timeZone],
      ['Analytics generation', String(context.analyticsGeneration)],
      ['Threshold policy', context.thresholdPolicyVersion],
      ['Source watermark', context.sourceWatermark ?? 'No source watermark']
    ];
    return entries.filter((entry): entry is [string, string] => Boolean(entry[1]));
  }

  function resolvedQueriesFrom(value: AskResponse): ResolvedQueryView[] {
    return value.kind === 'answered' || value.kind === 'no_data'
      ? value.context.resolvedQueries
      : [];
  }

  onMount(() => {
    mounted = true;
    previousContext = `${market}:${currency}`;
    void loadStatus();
  });

  onDestroy(() => {
    statusController?.abort();
    requestController?.abort();
  });
</script>

<div class="ask-shell">
  <article class="panel ask-intro">
    <div class="ask-heading">
      <div>
        <p class="eyebrow">Grounded Ask</p>
        <h2>Ask your ledger a question</h2>
        <p>Ledger turns your question into a small, read-only query plan, then shows the answer with the evidence it used.</p>
      </div>
      <div class="scope-badges" aria-label="Active Ask scope">
        <span class="pill">{market === 'ALL' ? 'All markets' : market}</span>
        <span class="pill">{currency} home currency</span>
      </div>
    </div>
    <div class="provider-disclosure">
      <strong>External AI disclosure</strong>
      <p>Your question and prior validated query plans may be sent to the configured provider. Ledger values, dates, entity labels, transaction rows, and finding evidence stay local.</p>
    </div>
  </article>

  {#if statusLoading}
    <div class="panel status-card" role="status" aria-live="polite">
      <div class="status-copy"><strong>Checking Ask availability</strong><span>This does not load or block deterministic Insights.</span></div>
      <div class="status-spinner" aria-hidden="true"></div>
    </div>
  {:else if statusError}
    <div class="panel status-card attention" role="alert">
      <div class="status-copy"><strong>Ask status could not be checked</strong><span>{statusError}</span></div>
      <button class="button-secondary" type="button" on:click={loadStatus}>Try again</button>
    </div>
  {:else if !askAvailable}
    <div class="panel status-card" role="status">
      <div class="status-copy">
        <strong>{askEnabled ? 'Ask is temporarily unavailable' : 'Ask is off'}</strong>
        <span>{statusReason || 'Enable Ask in the local environment to use natural-language questions.'} The Overview and other deterministic views remain available.</span>
      </div>
    </div>
  {:else}
    <form class="panel ask-form" on:submit|preventDefault={() => submitQuestion()}>
      <div class="form-heading">
        <div>
          <h2>Your question</h2>
          <p>Ask about spending, cash flow, trends, recurring activity, findings, FX costs, or supporting transactions.</p>
        </div>
        {#if history.length > 0 || response}
          <button class="text-button" type="button" on:click={() => resetConversation()}>New conversation</button>
        {/if}
      </div>

      <div class="field question-field">
        <label for="ask-question">Question</label>
        <textarea
          id="ask-question"
          bind:this={questionInput}
          bind:value={question}
          maxlength="500"
          minlength="1"
          rows="4"
          disabled={submitting}
          aria-describedby="ask-question-help ask-question-count"
          placeholder="For example: How much did I spend last month?"
        ></textarea>
        <span class="question-meta"><small id="ask-question-help">Questions and answers are not saved.</small><small id="ask-question-count">{question.length}/500</small></span>
      </div>

      <div class="example-list" aria-label="Example questions">
        <span>Try an example</span>
        <div>
          {#each examples as example}
            <button type="button" disabled={submitting} on:click={() => useExample(example)}>{example}</button>
          {/each}
        </div>
      </div>

      <div class="ask-actions">
        <span>{history.length ? `${history.length} prior validated ${history.length === 1 ? 'plan' : 'plans'} in this tab` : 'No prior question context'}</span>
        {#if submitting}
          <button class="button-secondary" type="button" on:click={cancelRequest}>Cancel</button>
        {/if}
        <button class="button" type="submit" disabled={submitting || question.trim().length < 1 || question.trim().length > 500}>
          {submitting ? 'Answering…' : 'Ask Ledger'}
        </button>
      </div>
    </form>
  {/if}

  {#if submitting}
    <div class="panel answering" role="status" aria-live="polite">
      <div class="status-spinner" aria-hidden="true"></div>
      <div><strong>Building a grounded answer</strong><span>Planning and deterministic queries can take up to 45 seconds.</span></div>
    </div>
  {/if}

  {#if requestError || requestNotice}
    <div class:attention={Boolean(requestError)} class="panel status-card" role={requestError ? 'alert' : 'status'}>
      <div class="status-copy" bind:this={resultHeading} tabindex="-1">
        <strong>{requestError ? 'Ask could not answer' : 'Request stopped'}</strong>
        <span>{requestError || requestNotice}</span>
      </div>
      {#if requestError && lastQuestion}
        <button class="button-secondary" type="button" on:click={() => submitQuestion(lastQuestion)}>Retry</button>
      {/if}
    </div>
  {/if}

  {#if response}
    <section class="answer-shell" aria-live="polite" aria-busy={submitting}>
      {#if outcome === 'clarification_required' && clarification}
        <article class="panel result-card">
          <div class="result-heading" bind:this={resultHeading} tabindex="-1">
            <span class="pill attention">Clarification needed</span>
            <h2>{clarification.prompt}</h2>
            <p>Choose an option or edit the question before sending it again.</p>
          </div>
          {#if clarification.choices.length}
            <div class="clarification-choices" aria-label="Clarification choices">
              {#each clarification.choices as choice}
                <button class="button-secondary" type="button" on:click={() => useClarification(choice)}>{choice.label}</button>
              {/each}
            </div>
          {/if}
        </article>
      {:else if outcome === 'unsupported' && unsupported}
        <article class="panel result-card">
          <div class="result-heading" bind:this={resultHeading} tabindex="-1">
            <span class="pill attention">Outside Ask</span>
            <h2>{unsupported.reason}</h2>
            <p>{unsupported.guidance}</p>
          </div>
          {#if unsupported.suggestions.length}
            <div class="clarification-choices" aria-label="Supported alternatives">
              {#each unsupported.suggestions as suggestion}
                <button class="button-secondary" type="button" on:click={() => useExample(suggestion)}>{suggestion}</button>
              {/each}
            </div>
          {/if}
        </article>
      {:else if outcome === 'no_data'}
        <article class="panel result-card empty-result">
          <div class="result-heading" bind:this={resultHeading} tabindex="-1">
            <span class="pill">No data</span>
            <h2>No matching ledger evidence</h2>
            <p>{asText(asRecord(response).message) || 'Try a wider date range, another market, or a less specific question.'}</p>
          </div>
        </article>
      {:else}
        <article class="panel result-card answer-card">
          <div class="result-heading" bind:this={resultHeading} tabindex="-1">
            <span class="pill success-pill">Grounded answer</span>
            <h2>Answer</h2>
          </div>
          <div class="answer-copy">
            {#if answerBlocks.length === 0}
              <p>The deterministic evidence is shown below.</p>
            {/if}
            {#each answerBlocks as block}
              {#if asText(asRecord(block).heading)}<h3>{asText(asRecord(block).heading)}</h3>{/if}
              <p>{blockText(block)}</p>
            {/each}
          </div>
        </article>
      {/if}

      {#if responseWarnings.length}
        <div class="warning-stack" aria-label="Answer warnings">
          {#each responseWarnings as warning}
            <div class="coverage-warning" role="status"><strong>Check coverage</strong><span>{warning}</span></div>
          {/each}
        </div>
      {/if}

      {#if evidenceItems.length}
        <section class="evidence-section" aria-labelledby="ask-evidence-heading">
          <div class="section-heading"><div><p class="eyebrow">Auditable evidence</p><h2 id="ask-evidence-heading">What the answer used</h2></div><span>{evidenceItems.length} {evidenceItems.length === 1 ? 'result' : 'results'}</span></div>
          <div class="evidence-grid">
            {#each evidenceItems as item, evidenceIndex}
              {@const columns = tableColumns(item)}
              {@const rows = tableRows(item)}
              {@const metrics = metricItems(item)}
              {@const chart = chartConfig(item)}
              {@const points = chartPoints(item)}
              {@const evidenceCoverage = asRecord(item.coverage)}
              <article class="panel evidence-card">
                <div class="evidence-heading">
                  <div><span class="pill">{titleCase(asText(item.kind) || 'evidence')}</span><h3>{evidenceTitle(item, evidenceIndex)}</h3></div>
                  <div class="evidence-actions">
                    {#if item.truncated === true}<span class="truncated-pill">Truncated</span>{/if}
                    {#if safeHref({ href: item.drilldownPath })}<a class="text-button" href={safeHref({ href: item.drilldownPath })}>Open supporting records</a>{/if}
                  </div>
                </div>

                {#if metrics.length}
                  <dl class="ask-metrics">
                    {#each metrics as metric}<div><dt>{metric.label}</dt><dd>{metric.value}</dd>{#if metric.detail}<small>{metric.detail}</small>{/if}</div>{/each}
                  </dl>
                {/if}

                {#if points.length && chart.kind === 'bar'}
                  <div class="bar-chart" role="img" aria-label={`${evidenceTitle(item, evidenceIndex)} bar chart`}>
                    {#each points as point}
                      <div>
                        <span class="bar-plot">
                          <span class="bar-axis" style={`bottom: ${point.zero * 100}%`}></span>
                          <span
                            class:negative={point.value < 0}
                            class="bar-value"
                            style={`bottom: ${barBottom(point)}%; height: ${barHeight(point)}%`}
                            title={`${point.label}: ${point.display}`}
                          ></span>
                        </span>
                        <small>{point.label}</small>
                      </div>
                    {/each}
                  </div>
                {:else if points.length && chart.kind === 'line'}
                  <div class="line-chart">
                    <svg viewBox="0 0 640 190" role="img" aria-label={`${evidenceTitle(item, evidenceIndex)} line chart`}>
                      <line x1="18" x2="622" y1={lineZero(points)} y2={lineZero(points)}></line>
                      <path d={linePath(points)}></path>
                      {#each points as point, pointIndex}
                        {@const position = linePoint(point, pointIndex, points.length)}
                        <circle class:negative={point.value < 0} cx={position.x} cy={position.y} r="5"><title>{point.label}: {point.display}</title></circle>
                      {/each}
                    </svg>
                  </div>
                {/if}

                {#if asText(item.kind) !== 'metric' && columns.length && rows.length}
                  <div class="evidence-table-scroll">
                    <table>
                      <thead><tr>{#each columns as column}<th>{column.label}</th>{/each}</tr></thead>
                      <tbody>
                        {#each rows as row}
                          <tr>{#each columns as column, columnIndex}{@const cell = cellValue(row, column, columnIndex)}<td>{formatCell(cell, column)}</td>{/each}</tr>
                        {/each}
                      </tbody>
                    </table>
                  </div>
                {/if}

                {#if !metrics.length && (!columns.length || !rows.length)}
                  <p class="evidence-summary">{asText(item.summary) || asText(item.message) || 'The query completed with no tabular rows.'}</p>
                {/if}

                {#if asText(evidenceCoverage.status)}
                  <div class:partial={asText(evidenceCoverage.status) === 'partial'} class="evidence-coverage">
                    <span>{titleCase(asText(evidenceCoverage.status))} coverage</span>
                    <span>{String(evidenceCoverage.valuedTransactionCount ?? 0)} valued</span>
                    <span>{String(evidenceCoverage.pendingFxCount ?? 0)} pending FX</span>
                  </div>
                {/if}
              </article>
            {/each}
          </div>
        </section>
      {/if}

      {#if responseMetadata.length || normalizedPlan}
        <details class="panel query-inspection">
          <summary>Inspect normalized queries</summary>
          <p>This is the validated query description Ledger executed. SQL, prompts, and provider payloads are never shown.</p>
          {#if responseMetadata.length}
            <dl>{#each responseMetadata as entry}<div><dt>{entry[0]}</dt><dd>{entry[1]}</dd></div>{/each}</dl>
          {/if}
          {#if resolvedQueries.length}
            <div class="resolved-ranges">
              <strong>Resolved query ranges</strong>
              <ul>
                {#each resolvedQueries as query}
                  <li>
                    <span>{query.queryId}</span><strong>{titleCase(query.dataset)}</strong><span>{query.market}</span>
                    <time datetime={query.from}>{query.from}</time><span aria-hidden="true">→</span><time datetime={query.to}>{query.to}</time>
                    {#if query.comparisonFrom && query.comparisonTo}
                      <span>compared with</span><time datetime={query.comparisonFrom}>{query.comparisonFrom}</time><span aria-hidden="true">→</span><time datetime={query.comparisonTo}>{query.comparisonTo}</time>
                    {/if}
                  </li>
                {/each}
              </ul>
            </div>
          {:else if evidenceItems.length}
            <div class="resolved-ranges">
              <strong>Resolved evidence ranges</strong>
              <ul>{#each evidenceItems as item}<li><span>{asText(item.queryId)}</span>{evidenceTitle(item, 0)}</li>{/each}</ul>
            </div>
          {/if}
          {#if normalizedPlan}<pre>{safePlanJson(normalizedPlan)}</pre>{/if}
        </details>
      {/if}
    </section>
  {/if}
</div>

<style>
  .ask-shell, .answer-shell, .evidence-section { display: grid; min-width: 0; gap: 1rem; }
  .ask-intro { overflow: hidden; background: linear-gradient(135deg, var(--paper) 0%, #f1f7f4 100%); }
  .ask-heading, .form-heading, .section-heading, .evidence-heading { display: flex; align-items: start; justify-content: space-between; gap: 1rem; }
  .ask-heading h2, .ask-heading p, .form-heading h2, .form-heading p, .section-heading h2, .section-heading p, .evidence-heading h3 { margin: 0; }
  .ask-heading h2 { margin-top: 0.25rem; color: var(--forest); font-size: clamp(1.45rem, 3vw, 2.2rem); letter-spacing: -0.045em; }
  .ask-heading > div:first-child > p:last-child { max-width: 62ch; margin-top: 0.55rem; color: var(--muted); font-size: 0.76rem; line-height: 1.55; }
  .scope-badges { display: flex; flex: 0 0 auto; flex-wrap: wrap; justify-content: flex-end; gap: 0.4rem; }
  .provider-disclosure { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 0.75rem; margin-top: 1rem; padding: 0.8rem; color: #285049; border: 1px solid #bad3cb; border-radius: 12px; background: rgb(237 247 243 / 82%); }
  .provider-disclosure strong { font-size: 0.67rem; }
  .provider-disclosure p { margin: 0; font-size: 0.68rem; line-height: 1.5; }
  .status-card, .answering { display: flex; min-height: 92px; align-items: center; justify-content: space-between; gap: 1rem; }
  .status-card.attention { border-color: #e7b9ab; background: #fff8f4; }
  .status-copy, .answering > div:last-child { display: grid; gap: 0.25rem; }
  .status-copy span, .answering span { color: var(--muted); font-size: 0.7rem; line-height: 1.45; }
  .status-spinner { width: 22px; height: 22px; flex: 0 0 auto; border: 3px solid #cbd7d2; border-top-color: var(--forest); border-radius: 50%; animation: ask-spin 0.8s linear infinite; }
  @keyframes ask-spin { to { transform: rotate(360deg); } }
  .ask-form { display: grid; gap: 1rem; }
  .form-heading h2, .section-heading h2 { color: var(--forest); font-size: 1.25rem; letter-spacing: -0.035em; }
  .form-heading p { margin-top: 0.3rem; color: var(--muted); font-size: 0.7rem; line-height: 1.45; }
  .question-field textarea { min-height: 112px; font-size: 0.84rem; line-height: 1.55; }
  .question-meta { display: flex; justify-content: space-between; gap: 1rem; }
  .example-list { display: grid; gap: 0.45rem; }
  .example-list > span { color: var(--muted); font-size: 0.62rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; }
  .example-list > div { display: flex; flex-wrap: wrap; gap: 0.45rem; }
  .example-list button { min-height: 36px; padding: 0.45rem 0.65rem; color: var(--forest); border: 1px solid #cfd8d2; border-radius: 999px; background: #f8faf7; font-size: 0.65rem; font-weight: 700; text-align: left; }
  .example-list button:hover { border-color: var(--forest-mid); background: #edf5f1; }
  .example-list button:disabled { opacity: 0.5; }
  .ask-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 0.55rem; }
  .ask-actions > span { margin-right: auto; color: var(--muted); font-size: 0.63rem; }
  .answering { justify-content: flex-start; }
  .result-card { display: grid; gap: 1rem; }
  .result-heading { outline: none; }
  .result-heading h2, .result-heading p { margin: 0; }
  .result-heading h2 { margin-top: 0.5rem; color: var(--forest); font-size: 1.4rem; letter-spacing: -0.035em; }
  .result-heading p { max-width: 65ch; margin-top: 0.4rem; color: var(--muted); font-size: 0.74rem; line-height: 1.55; }
  .pill.attention { color: #7c5418; background: #f5e4b7; }
  .success-pill { color: #1e614d; background: #dcefe7; }
  .answer-copy { max-width: 76ch; }
  .answer-copy h3 { margin: 1rem 0 0.35rem; color: var(--forest); font-size: 1rem; }
  .answer-copy p { color: var(--ink); font-size: 0.82rem; line-height: 1.7; }
  .answer-copy p { margin: 0.45rem 0 0; }
  .clarification-choices { display: flex; flex-wrap: wrap; gap: 0.55rem; }
  .warning-stack { display: grid; gap: 0.55rem; }
  .coverage-warning { display: flex; align-items: start; gap: 0.65rem; padding: 0.75rem 0.9rem; color: #765c19; border: 1px solid #e2cf91; border-radius: 11px; background: #fbf4dc; font-size: 0.68rem; line-height: 1.45; }
  .coverage-warning strong { white-space: nowrap; }
  .section-heading { align-items: end; }
  .section-heading > span { color: var(--muted); font-size: 0.64rem; }
  .evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; align-items: start; }
  .evidence-card { display: grid; gap: 1rem; }
  .evidence-card:only-child { grid-column: 1 / -1; }
  .evidence-heading { align-items: center; }
  .evidence-heading h3 { margin-top: 0.4rem; color: var(--forest); font-size: 1.05rem; letter-spacing: -0.025em; }
  .evidence-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 0.45rem; }
  .truncated-pill { color: #7c5418; font-size: 0.61rem; font-weight: 800; }
  .ask-metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.55rem; margin: 0; }
  .ask-metrics > div { display: grid; min-height: 105px; padding: 0.75rem; align-content: space-between; gap: 0.25rem; border: 1px solid #e1e3dc; border-radius: 12px; background: #f8f7f2; }
  .ask-metrics dt { color: var(--muted); font-size: 0.6rem; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; }
  .ask-metrics dd { margin: 0; color: var(--forest); font-size: 1.15rem; font-weight: 850; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
  .ask-metrics small { color: var(--muted); font-size: 0.58rem; line-height: 1.35; }
  .evidence-table-scroll { max-width: 100%; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.68rem; }
  th, td { padding: 0.68rem 0.58rem; border-bottom: 1px solid #e5e7e1; text-align: left; white-space: nowrap; }
  th { color: var(--muted); font-size: 0.58rem; letter-spacing: 0.07em; text-transform: uppercase; }
  td { font-variant-numeric: tabular-nums; }
  .bar-chart { display: flex; height: 190px; padding: 1rem 0.25rem 0; align-items: stretch; gap: 0.45rem; overflow-x: auto; }
  .bar-chart > div { display: grid; min-width: 42px; height: 100%; flex: 1; grid-template-rows: minmax(0, 1fr) auto; align-items: stretch; justify-items: center; gap: 0.35rem; }
  .bar-plot { position: relative; display: block; width: 100%; height: 100%; }
  .bar-axis { position: absolute; right: 0; left: 0; height: 1px; background: #cfd4cd; }
  .bar-value { position: absolute; left: 50%; width: min(32px, 72%); min-height: 2px; border-radius: 5px; background: var(--forest-mid); transform: translateX(-50%); }
  .bar-value.negative { background: #a75543; }
  .bar-chart small { max-width: 70px; color: var(--muted); font-size: 0.54rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .line-chart { overflow-x: auto; }
  .line-chart svg { display: block; width: 100%; min-width: 560px; }
  .line-chart line { stroke: #cfd4cd; }
  .line-chart path { fill: none; stroke: var(--forest-mid); stroke-linecap: round; stroke-linejoin: round; stroke-width: 4; }
  .line-chart circle { fill: var(--paper); stroke: var(--forest-mid); stroke-width: 3; }
  .line-chart circle.negative { stroke: #a75543; }
  .evidence-summary { margin: 0; color: var(--muted); font-size: 0.72rem; line-height: 1.5; }
  .evidence-coverage { display: flex; padding-top: 0.7rem; align-items: center; flex-wrap: wrap; gap: 0.35rem 0.8rem; color: var(--muted); border-top: 1px solid #e5e7e1; font-size: 0.59rem; }
  .evidence-coverage > :first-child { margin-right: auto; color: #285049; font-weight: 850; }
  .evidence-coverage.partial > :first-child { color: #765c19; }
  .query-inspection { overflow: hidden; }
  .query-inspection summary { color: var(--forest); font-size: 0.72rem; font-weight: 850; cursor: pointer; }
  .query-inspection > p { color: var(--muted); font-size: 0.68rem; line-height: 1.45; }
  .query-inspection dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.45rem; margin: 0 0 1rem; }
  .query-inspection dl div { padding: 0.55rem; border-radius: 9px; background: #f3f4ef; }
  .query-inspection dt { color: var(--muted); font-size: 0.57rem; }
  .query-inspection dd { margin: 0.2rem 0 0; font-size: 0.66rem; font-weight: 800; overflow-wrap: anywhere; }
  .resolved-ranges { margin-bottom: 1rem; }
  .resolved-ranges > strong { color: var(--forest); font-size: 0.67rem; }
  .resolved-ranges ul { display: grid; padding: 0; margin: 0.45rem 0 0; gap: 0.3rem; list-style: none; }
  .resolved-ranges li { display: flex; align-items: baseline; flex-wrap: wrap; gap: 0.3rem 0.5rem; color: var(--muted); font-size: 0.64rem; }
  .resolved-ranges li > span:first-child { min-width: 24px; color: var(--forest); font-weight: 850; text-transform: uppercase; }
  .resolved-ranges li > strong { color: var(--ink); font-size: inherit; }
  .query-inspection pre { max-height: 360px; padding: 0.8rem; overflow: auto; color: #dce8e3; border-radius: 10px; background: #173832; font-size: 0.62rem; line-height: 1.5; }
  @media (max-width: 780px) {
    .ask-heading, .form-heading, .section-heading, .evidence-heading { display: grid; }
    .scope-badges { justify-content: flex-start; }
    .provider-disclosure { grid-template-columns: 1fr; }
    .evidence-grid { grid-template-columns: 1fr; }
    .evidence-card:only-child { grid-column: auto; }
  }
  @media (max-width: 520px) {
    .status-card { align-items: flex-start; flex-direction: column; }
    .status-card .button-secondary { width: 100%; }
    .ask-actions { display: grid; grid-template-columns: 1fr 1fr; }
    .ask-actions > span { grid-column: 1 / -1; }
    .ask-actions .button:only-of-type { grid-column: 1 / -1; }
    .example-list > div { display: grid; }
    .example-list button { border-radius: 10px; }
    .coverage-warning { display: grid; }
  }
  @media (prefers-reduced-motion: reduce) {
    .status-spinner { animation: none; border-top-color: #cbd7d2; }
  }
</style>
