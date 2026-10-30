/* ═══════════════════════════════════════════════════════════
   AutoRepro — dashboard client
   Hash routes:  #/new  ·  #/job/<id>
   All dynamic text goes through textContent (never innerHTML).
   ═══════════════════════════════════════════════════════════ */

const JOB_POLL_MS = 2000;
const LIST_POLL_MS = 4000;
const HEALTH_POLL_MS = 30000;

const DEMO = {
    report: "Login always shows 'Invalid credentials' even with the correct username and password.",
    url: 'http://host.docker.internal:8080/login',
};

const STAGES = [
    { id: 'analyze', name: 'Analyze', sub: 'LLM · parse report' },
    { id: 'inspect', name: 'Inspect', sub: 'HTTP · read DOM' },
    { id: 'generate', name: 'Generate', sub: 'LLM · write script' },
    { id: 'execute', name: 'Execute', sub: 'Docker · run' },
    { id: 'evaluate', name: 'Evaluate', sub: 'Logic · verdict' },
    { id: 'refine', name: 'Refine', sub: 'LLM · fix & retry' },
];

const STAGE_COPY = {
    analyze: 'Reading the bug report and planning the steps…',
    inspect: 'Fetching the target page and extracting real selectors…',
    generate: 'Writing the Selenium reproduction script…',
    execute: 'Running the script in the Docker sandbox…',
    evaluate: 'Checking the output for a verdict…',
    refine: 'Diagnosing the failure and rewriting the script…',
};

const VERDICT_LABEL = {
    running: 'Running',
    reproduced: 'Reproduced',
    'not-reproduced': 'Not reproduced',
    error: 'Error',
    unknown: 'Unknown',
};

const ICONS = {
    done: '<path d="m4 10 4 4 8-8" />',
    failed: '<path d="m5 5 10 10M15 5 5 15" />',
    warn: '<path d="M10 5v6M10 14.5v.5" />',
};

const state = {
    jobs: [],
    filter: 'all',
    query: '',
    currentId: null,
    current: null,
    tab: 'overview',
    shots: [],
    shotIndex: 0,
    jobTimer: null,
    listTimer: null,
    clockTimer: null,
    renderedScriptFor: null,
};

const $ = (id) => document.getElementById(id);

/* ── DOM helper ────────────────────────────────────────── */

function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'dataset') Object.assign(node.dataset, value);
        else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
        else node.setAttribute(key, value === true ? '' : value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
}

function icon(name, cls = '') {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 20 20');
    svg.setAttribute('aria-hidden', 'true');
    if (cls) svg.setAttribute('class', cls);
    svg.innerHTML = ICONS[name] || '';  // static, trusted markup only
    return svg;
}

/* ── API ───────────────────────────────────────────────── */

/* When the server runs with API_KEY set, every call needs the header. The key is a
   per-browser setting, so it lives in localStorage:
     localStorage.setItem('autorepro_api_key', '<the key>')  */
function apiKey() {
    try { return localStorage.getItem('autorepro_api_key') || ''; } catch { return ''; }
}

/* Mirror the key into a same-origin cookie so <img src> screenshot loads carry it too —
   a browser can't add a header to an image request. */
(function syncApiKeyCookie() {
    const key = apiKey();
    if (key) document.cookie = `autorepro_api_key=${encodeURIComponent(key)}; path=/; SameSite=Strict`;
})();

async function api(path, options) {
    const opts = { ...options };
    const key = apiKey();
    if (key) opts.headers = { ...(opts.headers || {}), 'X-API-Key': key };
    const res = await fetch(path, opts);
    let body = null;
    try { body = await res.json(); } catch { /* empty or non-JSON body */ }
    if (!res.ok) {
        const err = new Error(res.status === 401
            ? 'This server requires an API key. Set it with localStorage.setItem("autorepro_api_key", "<key>") and reload.'
            : describeError(body, res.status));
        err.status = res.status;
        throw err;
    }
    return body;
}

function describeError(body, status) {
    const detail = body && body.detail;
    if (!detail) return `Request failed (HTTP ${status})`;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        // FastAPI validation errors: [{loc: ['body', 'field'], msg: '...'}]
        return detail.map((d) => {
            const field = (d.loc || []).filter((p) => p !== 'body').join('.');
            return field ? `${humanField(field)}: ${d.msg}` : d.msg;
        }).join('\n');
    }
    return detail.message || JSON.stringify(detail);
}

function humanField(field) {
    return { bug_report: 'Bug description', target_url: 'Target URL' }[field] || field;
}

/* ── Formatting ────────────────────────────────────────── */

function verdictOf(job) {
    if (!job) return 'unknown';
    if (job.status === 'processing') return 'running';
    if (job.status === 'failed') return 'error';
    if (job.status === 'done') return job.success ? 'reproduced' : 'not-reproduced';
    return 'unknown';
}

function relativeTime(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return '—';
    const mins = Math.floor((Date.now() - date.getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.floor(mins / 60)}h ago`;
    if (mins < 10080) return `${Math.floor(mins / 1440)}d ago`;
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function absoluteTime(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

function formatDuration(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
    if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${String(s).padStart(2, '0')}s`;
}

function jobDuration(job) {
    if (!job || !job.created_at) return null;
    const start = new Date(job.created_at).getTime();
    const end = job.completed_at ? new Date(job.completed_at).getTime() : Date.now();
    return (end - start) / 1000;
}

function hostOf(url) {
    try { return new URL(url).host; } catch { return url || ''; }
}

function plural(n, word) {
    return `${n} ${word}${n === 1 ? '' : 's'}`;
}

function screenshotLabel(filename) {
    const base = filename.replace(/\.png$/i, '');
    if (/^step_/i.test(base)) {
        const words = base.replace(/^step_\d+_?/i, '').replace(/_/g, ' ').trim();
        return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Step';
    }
    if (/^failure/i.test(base)) return 'Failure screenshot';
    return base.replace(/_/g, ' ');
}

/* ── Toasts & clipboard ────────────────────────────────── */

function toast(message, kind = 'info') {
    const node = el('div', { class: 'toast', dataset: { kind }, role: kind === 'error' ? 'alert' : 'status', text: message });
    $('toasts').append(node);
    setTimeout(() => node.remove(), kind === 'error' ? 6000 : 2600);
}

async function copyText(text, label = 'Copied') {
    try {
        await navigator.clipboard.writeText(text);
    } catch {
        const area = el('textarea', { style: 'position:fixed;opacity:0' });
        area.value = text;
        document.body.append(area);
        area.select();
        document.execCommand('copy');
        area.remove();
    }
    toast(label);
}

/* ── Theme ─────────────────────────────────────────────── */

function currentTheme() {
    const explicit = document.documentElement.dataset.theme;
    if (explicit) return explicit;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function toggleTheme() {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('autorepro-theme', next); } catch { /* storage unavailable */ }
}

/* ── Health ────────────────────────────────────────────── */

async function checkHealth() {
    const badge = $('health');
    try {
        await api('/health');
        badge.dataset.state = 'online';
        $('healthText').textContent = 'API online';
    } catch {
        badge.dataset.state = 'offline';
        $('healthText').textContent = 'API unreachable';
    }
}

/* ── Job list (sidebar) ────────────────────────────────── */

async function loadJobs() {
    try {
        state.jobs = await api('/jobs?summary=true');
    } catch {
        return;  // keep the last good list
    }
    renderJobList();
    renderStats();
    scheduleListPoll();
}

function scheduleListPoll() {
    clearTimeout(state.listTimer);
    if (state.jobs.some((j) => j.status === 'processing')) {
        state.listTimer = setTimeout(loadJobs, LIST_POLL_MS);
    }
}

function filteredJobs() {
    const q = state.query.trim().toLowerCase();
    return state.jobs.filter((job) => {
        if (state.filter !== 'all' && verdictOf(job) !== state.filter) return false;
        if (!q) return true;
        return [job.bug_report, job.target_url, job.job_id].some((v) => (v || '').toLowerCase().includes(q));
    });
}

function renderJobList() {
    const counts = { all: state.jobs.length, running: 0, reproduced: 0, 'not-reproduced': 0, error: 0 };
    state.jobs.forEach((job) => { const v = verdictOf(job); if (v in counts) counts[v] += 1; });
    document.querySelectorAll('[data-count]').forEach((node) => { node.textContent = counts[node.dataset.count] ?? 0; });

    const list = $('jobList');
    const jobs = filteredJobs();
    list.replaceChildren();

    if (jobs.length === 0) {
        const message = state.jobs.length === 0 ? 'No runs yet. Start one to see it here.' : 'No runs match this filter.';
        list.append(el('p', { class: 'list-empty', text: message }));
        return;
    }

    jobs.forEach((job) => {
        const verdict = verdictOf(job);
        const meta = [relativeTime(job.created_at)];
        if (job.attempt_count) meta.push(plural(job.attempt_count, 'attempt'));
        if (job.target_url) meta.push(hostOf(job.target_url));

        list.append(el('a', {
            href: `#/job/${encodeURIComponent(job.job_id)}`,
            class: `job-item${job.job_id === state.currentId ? ' is-active' : ''}`,
            title: VERDICT_LABEL[verdict],
            'aria-current': job.job_id === state.currentId ? 'page' : null,
        },
            el('span', { class: 'dot', dataset: { verdict }, 'aria-label': VERDICT_LABEL[verdict] }),
            el('span', { class: 'job-item-title', text: job.bug_report || 'Untitled run' }),
            el('span', { class: 'job-item-meta' }, meta.map((m) => el('span', { text: m }))),
        ));
    });
}

function renderStats() {
    const finished = state.jobs.filter((j) => j.status === 'done' || j.status === 'failed');
    const reproduced = state.jobs.filter((j) => verdictOf(j) === 'reproduced').length;
    const withAttempts = finished.filter((j) => j.attempt_count > 0);

    $('statTotal').textContent = state.jobs.length;
    $('statReproduced').textContent = reproduced;
    $('statRate').textContent = finished.length ? `${Math.round((reproduced / finished.length) * 100)}%` : '—';
    $('statAttempts').textContent = withAttempts.length
        ? (withAttempts.reduce((sum, j) => sum + j.attempt_count, 0) / withAttempts.length).toFixed(1)
        : '—';
}

/* ── Routing ───────────────────────────────────────────── */

function route() {
    closeSidebar();
    const match = location.hash.match(/^#\/job\/([^/?#]+)/);
    if (match) {
        showJob(decodeURIComponent(match[1]));
    } else {
        showNew();
    }
}

function showNew() {
    stopJobPolling();
    state.currentId = null;
    state.current = null;
    $('viewJob').hidden = true;
    $('viewNew').hidden = false;
    $('crumbCurrent').textContent = 'New reproduction';
    document.title = 'AutoRepro — AI Bug Reproducer';
    renderJobList();
}

function showJob(jobId) {
    if (state.currentId !== jobId) {
        state.currentId = jobId;
        state.current = null;
        state.renderedScriptFor = null;
        selectTab('overview', false);
    }
    $('viewNew').hidden = true;
    $('viewJob').hidden = false;
    $('crumbCurrent').textContent = jobId;
    renderJobList();
    fetchJob(jobId);
}

/* ── Job detail ────────────────────────────────────────── */

function stopJobPolling() {
    clearTimeout(state.jobTimer);
    clearInterval(state.clockTimer);
    state.jobTimer = null;
    state.clockTimer = null;
}

async function fetchJob(jobId) {
    stopJobPolling();
    let job;
    try {
        job = await api(`/result/${encodeURIComponent(jobId)}`);
    } catch (err) {
        if (state.currentId !== jobId) return;
        if (err.status === 404) {
            renderMissing(jobId);
            return;
        }
        // Transient failure: retry quietly
        state.jobTimer = setTimeout(() => fetchJob(jobId), JOB_POLL_MS * 2);
        return;
    }
    if (state.currentId !== jobId) return;  // user navigated away

    const wasRunning = state.current && state.current.status === 'processing';
    state.current = job;
    renderJob(job);

    if (job.status === 'processing') {
        state.jobTimer = setTimeout(() => fetchJob(jobId), JOB_POLL_MS);
        state.clockTimer = setInterval(() => { $('metaDuration').textContent = formatDuration(jobDuration(job)); }, 1000);
    } else if (wasRunning) {
        const verdict = verdictOf(job);
        toast(verdict === 'reproduced' ? 'Bug reproduced' : `Run finished: ${VERDICT_LABEL[verdict].toLowerCase()}`);
    }

    // Keep the sidebar row in sync with what we just learned
    const row = state.jobs.find((j) => j.job_id === jobId);
    if (row && (row.status !== job.status || row.attempt_count !== job.attempt_count)) loadJobs();
}

function renderMissing(jobId) {
    state.current = null;
    $('verdict').dataset.verdict = 'unknown';
    $('verdict').textContent = 'Not found';
    $('jobIdBtn').textContent = jobId;
    $('jobReport').textContent = 'No run exists with this ID. It may have been deleted, or the link is wrong.';
    ['metaStarted', 'metaDuration', 'metaAttempts'].forEach((id) => { $(id).textContent = '—'; });
    $('metaTarget').textContent = '—';
    $('metaTarget').removeAttribute('href');
    $('pipeline').replaceChildren();
    $('pipelineStatus').replaceChildren();
    $('errorBanner').hidden = true;
    $('downloadBtn').hidden = true;
    $('rerunBtn').hidden = true;
    ['overview', 'attempts', 'script', 'logs', 'evidence'].forEach((t) => $(`panel-${t}`).replaceChildren());
}

function renderJob(job) {
    const verdict = verdictOf(job);
    const attempts = job.attempts || [];

    document.title = `${VERDICT_LABEL[verdict]} · AutoRepro`;
    $('verdict').dataset.verdict = verdict;
    $('verdict').textContent = VERDICT_LABEL[verdict];
    $('jobIdBtn').textContent = `#${job.job_id.slice(0, 8)}`;
    $('jobReport').textContent = job.bug_report || '—';

    const target = $('metaTarget');
    target.textContent = job.target_url || '—';
    if (job.target_url) target.href = job.target_url; else target.removeAttribute('href');
    $('metaStarted').textContent = relativeTime(job.created_at);
    $('metaStarted').title = absoluteTime(job.created_at);
    $('metaDuration').textContent = formatDuration(jobDuration(job));
    $('metaAttempts').textContent = job.max_attempts
        ? `${job.attempt_count || 0} / ${job.max_attempts}`
        : String(job.attempt_count || 0);

    $('rerunBtn').hidden = !(job.bug_report && job.target_url);
    const download = $('downloadBtn');
    download.hidden = !(job.status !== 'processing' && job.final_script);
    download.href = `/result/${encodeURIComponent(job.job_id)}/script`;

    const banner = $('errorBanner');
    banner.hidden = job.status !== 'failed';
    $('errorText').textContent = job.error || 'The run failed without an error message.';

    renderPipeline(job);
    renderOverview(job);
    renderAttempts(job);
    renderScript(job);
    renderLogs(job);
    renderEvidence(job);

    $('countAttempts').textContent = attempts.length || '';
    $('countEvidence').textContent = (job.screenshot_urls || []).length || '';
}

/* Pipeline ------------------------------------------------ */

function stageStates(job) {
    const ids = STAGES.map((s) => s.id);
    const attempts = job.attempt_count || 0;
    const states = {};

    if (job.status === 'processing') {
        const current = job.stage || 'analyze';
        const idx = ids.indexOf(current);
        ids.forEach((id, i) => {
            if (id === current) states[id] = 'active';
            else if (i < idx || (attempts > 0 && i < 3)) states[id] = 'done';
            else if (id === 'execute' || id === 'evaluate') states[id] = attempts > 0 ? 'done' : 'pending';
            else if (id === 'refine') states[id] = attempts > 1 || (attempts > 0 && current === 'execute') ? 'done' : 'pending';
            else states[id] = 'pending';
        });
        return states;
    }

    if (job.status === 'failed') {
        const failedAt = job.stage && ids.includes(job.stage) ? job.stage : null;
        const idx = failedAt ? ids.indexOf(failedAt) : -1;
        ids.forEach((id, i) => {
            if (id === failedAt) states[id] = 'failed';
            else if (i < idx || (attempts > 0 && i < 5) || (id === 'refine' && attempts > 1)) states[id] = 'done';
            else states[id] = 'pending';
        });
        return states;
    }

    // done
    ids.forEach((id) => { states[id] = 'done'; });
    states.evaluate = job.success ? 'ok' : 'warn';
    states.refine = attempts > 1 ? 'done' : 'skipped';
    return states;
}

function renderPipeline(job) {
    const states = stageStates(job);
    const attempts = job.attempt_count || 0;
    const list = $('pipeline');
    list.replaceChildren();

    STAGES.forEach((stage) => {
        const st = states[stage.id];
        let sub = stage.sub;
        if (stage.id === 'execute') {
            // While execute is running, the attempt in flight is the next one
            const n = st === 'active' ? attempts + 1 : attempts;
            if (n > 0) sub = `attempt ${n}${job.max_attempts ? ` / ${job.max_attempts}` : ''}`;
        }
        if (stage.id === 'refine' && st === 'skipped') sub = 'not needed';

        const iconName = { done: 'done', ok: 'done', warn: 'warn', failed: 'failed' }[st];
        list.append(el('li', { class: 'stage', dataset: { state: st }, 'aria-label': `${stage.name}: ${st}` },
            el('span', { class: 'stage-bar' }),
            el('span', { class: 'stage-name' }, iconName ? icon(iconName, 'stage-icon') : null, stage.name),
            el('span', { class: 'stage-sub', text: sub }),
        ));
    });

    const status = $('pipelineStatus');
    status.replaceChildren();
    const last = (job.attempts || []).slice(-1)[0];

    if (job.status === 'processing') {
        const stage = job.stage || 'analyze';
        let text = STAGE_COPY[stage] || 'Working…';
        if (stage === 'execute' || stage === 'evaluate') {
            const n = stage === 'execute' ? attempts + 1 : attempts;
            text = `${stage === 'execute' ? 'Running' : 'Evaluating'} attempt ${n}${job.max_attempts ? ` of ${job.max_attempts}` : ''}…`;
        }
        status.append(el('span', { class: 'spinner', 'aria-hidden': 'true' }), text);
    } else if (job.status === 'failed') {
        status.append(job.stage ? `Stopped during the ${job.stage} stage.` : 'The run stopped with an error.');
    } else if (job.success) {
        status.append(`Bug reproduced on attempt ${attempts}${job.max_attempts ? ` of ${job.max_attempts}` : ''}.`);
    } else {
        const reason = last && last.error_type ? ` Last outcome: ${last.error_type}.` : '';
        status.append(`Not reproduced after ${plural(attempts, 'attempt')}.${reason}`);
    }
}

/* Overview ------------------------------------------------ */

function block(title, ...content) {
    return el('section', { class: 'ov-block' }, el('h3', { text: title }), ...content);
}

function renderOverview(job) {
    const panel = $('panel-overview');
    panel.replaceChildren();
    const a = job.analysis;

    if (!a || typeof a !== 'object' || Object.keys(a).length === 0) {
        panel.append(el('div', { class: 'empty' },
            el('strong', { text: job.status === 'processing' ? 'Analysing the report…' : 'No analysis available' }),
            job.status === 'processing' ? 'The structured analysis appears here once the analyze stage finishes.' : 'This run stopped before the bug report was analysed.',
        ));
        return;
    }

    const left = el('div');
    const right = el('div');

    if (Array.isArray(a.inferred_steps) && a.inferred_steps.length) {
        left.append(block('Reproduction steps', el('ol', { class: 'steps' }, a.inferred_steps.map((s) => el('li', { text: s })))));
    }
    if (a.success_condition) {
        left.append(block('Bug is confirmed when', el('p', { class: 'condition', text: a.success_condition })));
    }
    if (a.expected_behavior) {
        left.append(block('Expected behaviour', el('p', { text: a.expected_behavior })));
    }
    if (Array.isArray(a.bug_variants) && a.bug_variants.length) {
        right.append(block('Interpretations checked', el('ul', { class: 'variants' }, a.bug_variants.map((v) =>
            el('li', {}, el('strong', { text: v.interpretation || 'Variant' }), el('span', { text: v.success_condition || '' }))))));
    }
    if (Array.isArray(a.target_elements) && a.target_elements.length) {
        right.append(block('Target elements', el('div', { class: 'code-chips' }, a.target_elements.map((t) => el('code', { text: t })))));
    }
    if (Array.isArray(a.risk_factors) && a.risk_factors.length) {
        right.append(block('Risk factors', el('ul', { class: 'bullets' }, a.risk_factors.map((r) => el('li', { text: r })))));
    }

    const last = (job.attempts || []).slice(-1)[0];
    if (last) {
        right.append(block('Last attempt', el('dl', { class: 'kv' },
            el('dt', { text: 'Outcome' }), el('dd', { text: attemptOutcome(job, last, true).label }),
            el('dt', { text: 'Exit code' }), el('dd', { text: last.exit_code ?? '—' }),
            el('dt', { text: 'Duration' }), el('dd', { text: formatDuration(last.duration_seconds) }),
        )));
    }

    panel.append(el('div', { class: 'overview' }, left, right));
}

/* Attempts ------------------------------------------------ */

function attemptOutcome(job, attempt, isLast) {
    if (isLast && job.status === 'done' && job.success) return { label: 'Reproduced', kind: 'ok' };
    if (attempt.error_type === 'FalsePositive' || attempt.error_type === 'WrongVerification') return { label: attempt.error_type, kind: 'warn' };
    if (attempt.error_type) return { label: attempt.error_type, kind: 'bad' };
    if (isLast && job.status === 'processing') return { label: 'Evaluating', kind: 'run' };
    return { label: attempt.exit_code === 0 ? 'No verdict' : 'Failed', kind: attempt.exit_code === 0 ? 'warn' : 'bad' };
}

function codeBlock(text, language) {
    const code = el('code', { class: language ? `language-${language}` : null, text: text });
    if (language && window.Prism) window.Prism.highlightElement(code);
    return el('pre', { class: language ? 'code' : 'log' }, code);
}

function renderAttempts(job) {
    const panel = $('panel-attempts');
    // Don't rebuild while the user has a <details> open on a finished job
    const openKeys = new Set([...panel.querySelectorAll('details[open]')].map((d) => d.dataset.key));
    panel.replaceChildren();
    const attempts = job.attempts || [];

    if (!attempts.length) {
        panel.append(el('div', { class: 'empty' },
            el('strong', { text: 'No attempts yet' }),
            job.status === 'processing' ? 'Each sandbox run shows up here with its script, output and refinement note.' : 'The run stopped before any script was executed.',
        ));
        return;
    }

    const list = el('ol', { class: 'attempts' });
    attempts.forEach((attempt, i) => {
        const isLast = i === attempts.length - 1;
        const outcome = attemptOutcome(job, attempt, isLast);
        const key = (name) => `${attempt.attempt}-${name}`;
        const details = (name, label, content) => el('details', { dataset: { key: key(name) }, open: openKeys.has(key(name)) },
            el('summary', { text: label }), content);

        list.append(el('li', { class: 'attempt' },
            el('div', { class: 'attempt-head' },
                el('span', { class: 'attempt-num', text: `Attempt ${attempt.attempt}` }),
                el('span', { class: 'outcome', dataset: { kind: outcome.kind }, text: outcome.label }),
                el('span', { class: 'attempt-facts' },
                    el('span', { text: `exit ${attempt.exit_code ?? '—'}` }),
                    el('span', { text: formatDuration(attempt.duration_seconds) }),
                ),
            ),
            attempt.error_message ? el('p', { class: 'attempt-msg', text: attempt.error_message }) : null,
            attempt.refinement_note ? el('p', { class: 'attempt-note' }, el('b', { text: 'Refinement → ' }), attempt.refinement_note) : null,
            attempt.script ? details('script', 'Script', codeBlock(attempt.script, 'python')) : null,
            attempt.stdout ? details('stdout', 'stdout', codeBlock(attempt.stdout)) : null,
            attempt.stderr ? details('stderr', 'stderr', codeBlock(attempt.stderr)) : null,
        ));
    });
    panel.append(list);
}

/* Script -------------------------------------------------- */

function renderScript(job) {
    const panel = $('panel-script');
    const script = job.final_script || '';
    const key = `${job.job_id}:${job.status}:${script.length}`;
    if (state.renderedScriptFor === key) return;  // avoid re-highlighting on every poll
    state.renderedScriptFor = key;
    panel.replaceChildren();

    if (!script) {
        panel.append(el('div', { class: 'empty' },
            el('strong', { text: job.status === 'processing' ? 'Script not written yet' : 'No script was produced' }),
            job.status === 'processing' ? 'The final script appears here when the run finishes.' : 'The run ended before a script was generated.',
        ));
        return;
    }

    const lines = script.split('\n').length;
    panel.append(
        el('div', { class: 'code-toolbar' },
            el('span', { class: 'code-file', text: `reproduction.py · ${plural(lines, 'line')}` }),
            el('span', { class: 'spacer' }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Copy', onclick: () => copyText(script, 'Script copied') }),
            job.status !== 'processing'
                ? el('a', { class: 'btn btn-ghost btn-sm', href: `/result/${encodeURIComponent(job.job_id)}/script`, download: 'reproduction.py', text: 'Download' })
                : null,
        ),
        codeBlock(script, 'python'),
    );
}

/* Logs ---------------------------------------------------- */

function renderLogs(job) {
    const panel = $('panel-logs');
    panel.replaceChildren();
    const text = job.logs || (job.attempts || []).map((a) => a.stdout + (a.stderr ? `\n[stderr attempt ${a.attempt}]\n${a.stderr}\n` : '')).join('');

    if (!text.trim()) {
        panel.append(el('div', { class: 'empty' },
            el('strong', { text: 'No output yet' }),
            'Console output from each sandbox run is collected here.',
        ));
        return;
    }

    const pre = el('pre', { class: 'log' });
    let inErr = false;
    text.split('\n').forEach((line, i, all) => {
        let cls = null;
        if (/^\[stderr attempt/.test(line)) { inErr = true; cls = 'log-head'; }
        else if (/^Step \d+/i.test(line)) { inErr = false; }
        if (!cls && inErr) cls = 'log-err';
        if (!cls && /^\s*REPRODUCED\s*$/.test(line)) cls = 'log-hit';
        pre.append(cls ? el('span', { class: cls, text: line }) : line, i < all.length - 1 ? '\n' : '');
    });

    panel.append(
        el('div', { class: 'code-toolbar' },
            el('span', { class: 'code-file', text: `Combined output · ${plural((job.attempts || []).length, 'attempt')}` }),
            el('span', { class: 'spacer' }),
            el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: 'Copy', onclick: () => copyText(text, 'Logs copied') }),
        ),
        pre,
    );
}

/* Evidence ------------------------------------------------ */

function renderEvidence(job) {
    const panel = $('panel-evidence');
    const urls = [...(job.screenshot_urls || [])]
        .sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
    state.shots = urls.map((url) => {
        const filename = decodeURIComponent(url.split('/').pop() || '');
        const parts = url.split('/');
        parts[parts.length - 1] = encodeURIComponent(filename);
        return { url: parts.join('/'), label: screenshotLabel(filename), failure: /^failure/i.test(filename) };
    });

    const signature = state.shots.map((s) => s.url).join('|');
    if (panel.dataset.signature === signature && signature) return;  // unchanged, keep images loaded
    panel.dataset.signature = signature;
    panel.replaceChildren();

    if (!state.shots.length) {
        panel.append(el('div', { class: 'empty' },
            el('strong', { text: 'No screenshots captured' }),
            job.status === 'processing' ? 'Screenshots from the sandbox browser appear here as the script runs.' : 'The script did not save any screenshots.',
        ));
        return;
    }

    panel.append(el('div', { class: 'shots' }, state.shots.map((shot, i) =>
        el('button', { type: 'button', class: 'shot', dataset: { kind: shot.failure ? 'failure' : 'step' }, onclick: () => openLightbox(i), 'aria-label': `Open screenshot ${i + 1}: ${shot.label}` },
            el('img', { src: shot.url, alt: shot.label, loading: 'lazy' }),
            el('span', { class: 'shot-cap' }, el('span', { class: 'shot-num', text: String(i + 1).padStart(2, '0') }), shot.label),
        ))));
}

/* Tabs ---------------------------------------------------- */

function selectTab(name, focus = true) {
    state.tab = name;
    document.querySelectorAll('#tabs .tab').forEach((tab) => {
        const active = tab.dataset.tab === name;
        tab.setAttribute('aria-selected', String(active));
        tab.tabIndex = active ? 0 : -1;
        if (active && focus) tab.focus();
        $(tab.getAttribute('aria-controls')).hidden = !active;
    });
}

function setupTabs() {
    const tabs = [...document.querySelectorAll('#tabs .tab')];
    tabs.forEach((tab, i) => {
        tab.addEventListener('click', () => selectTab(tab.dataset.tab, false));
        tab.addEventListener('keydown', (e) => {
            let next = null;
            if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
            if (e.key === 'ArrowLeft') next = tabs[(i - 1 + tabs.length) % tabs.length];
            if (e.key === 'Home') next = tabs[0];
            if (e.key === 'End') next = tabs[tabs.length - 1];
            if (next) { e.preventDefault(); selectTab(next.dataset.tab); }
        });
    });
}

/* ── Lightbox ──────────────────────────────────────────── */

let lightboxReturnFocus = null;

function openLightbox(index) {
    if (!state.shots.length) return;
    lightboxReturnFocus = document.activeElement;
    state.shotIndex = index;
    $('lightbox').hidden = false;
    showShot();
    $('lightboxClose').focus();
}

function showShot() {
    const shot = state.shots[state.shotIndex];
    $('lightboxImg').src = shot.url;
    $('lightboxImg').alt = shot.label;
    $('lightboxCaption').textContent = shot.label;
    $('lightboxCount').textContent = `${state.shotIndex + 1} / ${state.shots.length}`;
    $('lightboxPrev').disabled = state.shotIndex === 0;
    $('lightboxNext').disabled = state.shotIndex === state.shots.length - 1;
}

function stepShot(delta) {
    const next = state.shotIndex + delta;
    if (next < 0 || next >= state.shots.length) return;
    state.shotIndex = next;
    showShot();
}

function closeLightbox() {
    if ($('lightbox').hidden) return;
    $('lightbox').hidden = true;
    $('lightboxImg').removeAttribute('src');
    if (lightboxReturnFocus) lightboxReturnFocus.focus();
}

/* ── New run form ──────────────────────────────────────── */

function updateCounter() {
    const len = $('bugReport').value.trim().length;
    const counter = $('charCount');
    counter.textContent = len >= 20 ? `${len} chars` : `${len} / 20 min`;
    counter.className = `counter${len > 0 && len < 20 ? ' is-warn' : ''}${len >= 20 ? ' is-ok' : ''}`;
}

function showFormError(message) {
    const node = $('formError');
    node.textContent = message;
    node.hidden = !message;
}

function validate(report, url) {
    const errors = [];
    $('bugReport').removeAttribute('aria-invalid');
    $('targetUrl').removeAttribute('aria-invalid');
    if (report.length < 20) {
        errors.push('Bug description: write at least 20 characters so the agent has enough to work with.');
        $('bugReport').setAttribute('aria-invalid', 'true');
    }
    let parsed = null;
    try { parsed = new URL(url); } catch { /* invalid */ }
    if (!parsed || !/^https?:$/.test(parsed.protocol)) {
        errors.push('Target URL: enter a full http:// or https:// address.');
        $('targetUrl').setAttribute('aria-invalid', 'true');
    }
    return errors;
}

async function startRun(report, url) {
    const job = await api('/reproduce', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bug_report: report, target_url: url }),
    });
    state.jobs.unshift({
        job_id: job.job_id, status: 'processing', bug_report: report, target_url: url,
        attempt_count: 0, created_at: new Date().toISOString(),
    });
    location.hash = `#/job/${encodeURIComponent(job.job_id)}`;
    loadJobs();
    return job;
}

async function submitForm(event) {
    event.preventDefault();
    const report = $('bugReport').value.trim();
    const url = $('targetUrl').value.trim();
    const errors = validate(report, url);
    showFormError(errors.join('\n'));
    if (errors.length) return;

    const button = $('submitBtn');
    const label = button.querySelector('.btn-label');
    button.disabled = true;
    label.textContent = 'Starting…';
    try {
        await startRun(report, url);
        $('submitForm').reset();
        updateCounter();
        toast('Run started');
    } catch (err) {
        showFormError(err.message);
    } finally {
        button.disabled = false;
        label.textContent = 'Start reproduction';
    }
}

async function rerun() {
    const job = state.current;
    if (!job) return;
    try {
        await startRun(job.bug_report, job.target_url);
        toast('Re-run started');
    } catch (err) {
        toast(err.message, 'error');
    }
}

/* ── Sidebar (mobile drawer) ───────────────────────────── */

function openSidebar() {
    $('sidebar').classList.add('is-open');
    $('scrim').hidden = false;
    $('menuBtn').setAttribute('aria-expanded', 'true');
}

function closeSidebar() {
    $('sidebar').classList.remove('is-open');
    $('scrim').hidden = true;
    $('menuBtn').setAttribute('aria-expanded', 'false');
}

/* ── Wiring ────────────────────────────────────────────── */

function init() {
    $('submitForm').addEventListener('submit', submitForm);
    $('bugReport').addEventListener('input', updateCounter);
    $('bugReport').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('submitForm').requestSubmit();
    });
    $('targetUrl').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('submitForm').requestSubmit();
    });
    document.querySelectorAll('[data-example]').forEach((chip) => chip.addEventListener('click', () => {
        $('bugReport').value = chip.dataset.example;
        updateCounter();
        $('bugReport').focus();
    }));
    $('demoBtn').addEventListener('click', () => {
        $('bugReport').value = DEMO.report;
        $('targetUrl').value = DEMO.url;
        updateCounter();
        showFormError('');
        toast('Demo filled in. Start tests/demo_server.py on port 8080 first.');
    });

    $('jobSearch').addEventListener('input', (e) => { state.query = e.target.value; renderJobList(); });
    document.querySelectorAll('#filters .filter').forEach((button) => button.addEventListener('click', () => {
        state.filter = button.dataset.filter;
        document.querySelectorAll('#filters .filter').forEach((b) => b.classList.toggle('is-active', b === button));
        renderJobList();
    }));

    $('jobIdBtn').addEventListener('click', () => { if (state.currentId) copyText(state.currentId, 'Job ID copied'); });
    $('rerunBtn').addEventListener('click', rerun);
    $('themeBtn').addEventListener('click', toggleTheme);
    $('menuBtn').addEventListener('click', openSidebar);
    $('scrim').addEventListener('click', closeSidebar);

    $('lightboxClose').addEventListener('click', closeLightbox);
    $('lightboxPrev').addEventListener('click', () => stepShot(-1));
    $('lightboxNext').addEventListener('click', () => stepShot(1));
    $('lightbox').addEventListener('click', (e) => { if (e.target.id === 'lightbox') closeLightbox(); });
    document.addEventListener('keydown', (e) => {
        if (!$('lightbox').hidden) {
            if (e.key === 'Escape') closeLightbox();
            if (e.key === 'ArrowLeft') stepShot(-1);
            if (e.key === 'ArrowRight') stepShot(1);
            return;
        }
        if (e.key === 'Escape') closeSidebar();
    });

    setupTabs();
    window.addEventListener('hashchange', route);

    checkHealth();
    setInterval(checkHealth, HEALTH_POLL_MS);
    loadJobs();
    route();
}

document.addEventListener('DOMContentLoaded', init);
