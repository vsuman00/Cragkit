// Executes the supplied scripts against a minimal DOM/timer model.
// This checks JavaScript behavior; it does not launch or emulate a browser renderer.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const htmlPath = path.join(root, 'interactive_visual_im_d2b565f3406507ed.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const results = [];

function boot(scriptTransform = s => s) {
  const elements = new Map();
  const listeners = new Map();
  const intervals = new Map();
  const timeouts = new Map();
  const messages = [];
  let timerId = 0;
  function element(attrs = {}) {
    const classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
    return {
      id: attrs.id || '', attrs: { ...attrs }, textContent: '', disabled: false,
      scrollHeight: 900, rect: null, parentElement: null,
      classList: {
        contains: c => classes.has(c),
        add: c => classes.add(c),
        remove: c => classes.delete(c),
        toggle(c, force) {
          const enabled = force === undefined ? !classes.has(c) : force;
          if (enabled) classes.add(c); else classes.delete(c);
          return enabled;
        }
      },
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return this.attrs[k] ?? null; },
      hasAttribute(k) { return Object.hasOwn(this.attrs, k); },
      querySelector(q) { return q === 'rect' ? this.rect : null; },
      getBoundingClientRect: () => ({ bottom: 900 }),
      style: { setProperty() {}, removeProperty() {} }
    };
  }
  for (const m of html.matchAll(/<[a-z][\w-]*\b([^<>]*)>/gi)) {
    const attrs = Object.fromEntries([...m[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(a => [a[1], a[2]]));
    if (attrs.id) elements.set(attrs.id, element(attrs));
  }
  const nodes = [...elements.values()].filter(e => e.classList.contains('flow-node'));
  const edges = [...elements.values()].filter(e => e.classList.contains('flow-edge'));
  for (const node of nodes) {
    node.rect = element();
    node.rect.parentElement = node;
  }
  const body = element();
  const documentElement = element();
  const container = element();
  const document = {
    body, documentElement, readyState: 'complete',
    getElementById: id => elements.get(id) || null,
    querySelector: q => q === '.widget-container' ? container : null,
    querySelectorAll(q) {
      if (q === '.flow-node rect') return nodes.map(n => n.rect);
      if (q === '.flow-edge') return edges;
      if (q === 'input[type="range"], .lumi-slider') return [];
      throw new Error('Unsupported DOM selector in analysis harness: ' + q);
    },
    addEventListener(type, fn) { listeners.set('document:' + type, [...(listeners.get('document:' + type) || []), fn]); }
  };
  const window = {
    matchMedia: () => ({ matches: false, addEventListener() {} }),
    addEventListener(type, fn) { listeners.set(type, [...(listeners.get(type) || []), fn]); },
    parent: { postMessage: (data, origin) => messages.push({ data, origin }) }
  };
  const context = vm.createContext({
    document, window,
    setInterval(fn, delay) { const id = ++timerId; intervals.set(id, { fn, delay }); return id; },
    clearInterval: id => intervals.delete(id),
    setTimeout(fn, delay) { const id = ++timerId; timeouts.set(id, { fn, delay }); return id; },
    MutationObserver: class { observe() {} },
    ResizeObserver: class { constructor(fn) { this.fn = fn; } observe() { this.fn(); } }
  }, { codeGeneration: { strings: false, wasm: false } });
  for (const [index, script] of scripts.entries()) {
    vm.runInContext(scriptTransform(script, index), context, { filename: 'explorer-script-' + index, timeout: 1000 });
  }
  return {
    run: code => vm.runInContext(code, context, { timeout: 1000 }),
    el: id => elements.get(id), nodes, edges, messages, intervals,
    emit(type, event) { for (const fn of listeners.get(type) || []) fn(event); },
    tick() { for (const { fn } of [...intervals.values()]) fn(); }
  };
}

function check(name, fn) {
  try { const detail = fn(); results.push({ name, status: 'PASS', detail }); }
  catch (error) { results.push({ name, status: 'FAIL', detail: error.message }); }
}

check('All three inline scripts execute with the supported DOM model', () => {
  assert.equal(scripts.length, 3); boot();
});
check('Initial inspector and navigation reflect first happy-path step', () => {
  const h = boot();
  assert.equal(h.el('insp-title').textContent, 'AgentToolCall');
  assert.equal(h.el('step-indicator').textContent, 'Step 1 / 5');
  assert.equal(h.el('btn-prev').disabled, true);
  assert.equal(h.el('btn-next').disabled, false);
  assert.equal(JSON.parse(h.el('insp-input').textContent).token_budget, 2000);
});
check('Every happy-path step updates inspector, active node, and active edge', () => {
  const h = boot();
  for (let i = 0; i < 5; i++) {
    const step = h.run(`SCENARIOS[0].steps[${i}]`);
    assert.equal(h.el('insp-title').textContent, step.nodeId);
    assert.equal(h.nodes.filter(n => n.rect.attrs['stroke-width'] === '2.5').length, 1);
    assert.equal(h.el('node-' + step.nodeId).rect.attrs['stroke-width'], '2.5');
    assert.equal(h.edges.filter(e => e.classList.contains('is-active')).length, i ? 1 : 0);
    if (step.edgeId) assert.equal(h.el(step.edgeId).classList.contains('is-active'), true);
    assert.deepEqual(JSON.parse(h.el('insp-output').textContent), JSON.parse(JSON.stringify(step.output)));
    h.run('nextStep()');
  }
  assert.equal(h.el('btn-next').disabled, true);
});
check('Prev and Next stay within scenario bounds', () => {
  const h = boot(); h.run('prevStep()'); assert.equal(h.run('currentStepIdx'), 0);
  for (let i = 0; i < 12; i++) h.run('nextStep()');
  assert.equal(h.run('currentStepIdx'), 4);
  for (let i = 0; i < 12; i++) h.run('prevStep()');
  assert.equal(h.run('currentStepIdx'), 0);
});
check('Scenario switching resets step, selection, and mode label', () => {
  const h = boot(); h.run('nextStep(); setScenario(1)');
  assert.equal(h.run('currentStepIdx'), 0);
  assert.equal(h.el('step-indicator').textContent, 'Step 1 / 8');
  assert.equal(h.el('mode-badge').textContent, 'Self-Correction Loop');
  assert.equal(h.el('btn-scenario-2').classList.contains('is-selected'), true);
  assert.equal(h.el('btn-scenario-1').classList.contains('is-selected'), false);
});
check('Retry trace executes all eight scripted steps and highlights recovery edges', () => {
  const h = boot(); h.run('setScenario(1)');
  const observed = [];
  for (let i = 0; i < 8; i++) {
    const step = h.run(`SCENARIOS[1].steps[${i}]`);
    observed.push(h.el('insp-title').textContent);
    assert.equal(h.el('insp-title').textContent, step.nodeId);
    if (i === 4 || i === 5) assert.equal(h.el(step.edgeId).attrs['marker-end'], 'url(#lumi-caret-retry)');
    h.run('nextStep()');
  }
  assert.equal(h.run('currentStepIdx'), 7);
  assert.equal(h.el('btn-next').disabled, true);
  return observed;
});
check('Ordinary node selection updates inspector', () => {
  const h = boot(); h.run("selectNode('CrossEncoderGrader')");
  assert.equal(h.run('currentStepIdx'), 3);
  assert.equal(h.el('insp-title').textContent, 'CrossEncoderGrader');
});
check('A retry-only node is ignored in the happy-path scenario', () => {
  const h = boot(); h.run("selectNode('QueryRewriterLoop')");
  assert.equal(h.run('currentStepIdx'), 0);
});
check('Playback advances, pauses, and clears its timer', () => {
  const h = boot(); h.run('togglePlay()');
  assert.equal(h.el('btn-play').textContent, 'Pause'); assert.equal(h.intervals.size, 1);
  h.tick(); assert.equal(h.run('currentStepIdx'), 1);
  h.run('togglePlay()'); assert.equal(h.intervals.size, 0);
  assert.equal(h.el('btn-play').textContent, 'Play');
});
check('Playback stops at the end and replay restarts at step one', () => {
  const h = boot(); h.run('togglePlay()');
  for (let i = 0; i < 8; i++) h.tick();
  assert.equal(h.run('currentStepIdx'), 4); assert.equal(h.intervals.size, 0);
  h.run('togglePlay()'); assert.equal(h.run('currentStepIdx'), 0);
  assert.equal(h.intervals.size, 1);
});
check('Changing scenario or selecting a node stops playback', () => {
  const h = boot(); h.run('togglePlay(); setScenario(1)'); assert.equal(h.intervals.size, 0);
  h.run("togglePlay(); selectNode('QueryRewriterLoop')"); assert.equal(h.intervals.size, 0);
});
check('Theme messages update the theme and resize notification is emitted', () => {
  const h = boot(); h.emit('message', { data: { type: 'set-theme', theme: 'dark' } });
  assert.equal(h.run("document.documentElement.getAttribute('data-theme')"), 'dark');
  assert.equal(h.messages.some(m => m.data.type === 'widget-resize'), true);
});
check('Changing a score does not recompute the branch: confirms scripted simulation', () => {
  const h = boot();
  h.run('SCENARIOS[0].steps[3].output.max_score = 0.10');
  for (let i = 0; i < 4; i++) h.run('nextStep()');
  assert.equal(h.el('insp-title').textContent, 'ContextCompressor');
  return 'A 0.10 score still proceeds to compression; branch decisions are supplied data.';
});
check('Selecting the active second retrieval occurrence preserves its attempt', () => {
  const h = boot(); h.run('setScenario(1)');
  for (let i = 0; i < 5; i++) h.run('nextStep()');
  assert.equal(h.run('currentStepIdx'), 5);
  h.run("selectNode('HybridSearchRRF')");
  assert.equal(h.run('currentStepIdx'), 5, 'Clicking Pass 2 should not jump to Pass 1 (index 2)');
});
check('Happy-path remaining-token figure reconciles with its preceding budget', () => {
  const h = boot(); const steps = h.run('SCENARIOS[0].steps');
  const expected = parseInt(steps[3].budget) - steps[4].output.token_count;
  assert.equal(parseInt(steps[4].budget), expected, `1850 - 620 = ${expected}, displayed ${steps[4].budget}`);
});
check('Retry-path remaining-token figure reconciles with its preceding budget', () => {
  const h = boot(); const steps = h.run('SCENARIOS[1].steps');
  const expected = parseInt(steps[6].budget) - steps[7].output.token_count;
  assert.equal(parseInt(steps[7].budget), expected, `1700 - 710 = ${expected}, displayed ${steps[7].budget}`);
});
check('Native HTML has no pasted Markdown fence delimiters', () => {
  assert.equal(/^```html\s*\n/.test(html), false, 'Opening ```html and closing ``` remain in the HTML file');
});
check('Clickable SVG nodes expose keyboard focus and activation', () => {
  const nodeTags = [...html.matchAll(/<g\b[^>]*class="flow-node"[^>]*>/g)].map(m => m[0]);
  assert.equal(nodeTags.length, 6);
  assert.equal(nodeTags.every(t => /tabindex=/.test(t) && /onkeydown=|onkeyup=/.test(t)), true,
    'All six clickable SVG groups lack tabindex and keyboard handlers');
});
check('A deliberately broken Next handler is detected without editing the source file', () => {
  const h = boot(s => s.replace('currentStepIdx++;', 'currentStepIdx--;'));
  assert.throws(() => h.run('nextStep()'));
  return 'The mutated handler hits an invalid step and throws; navigation assertions are sensitive to this defect.';
});

const scenarioInfo = boot().run('SCENARIOS.map(s => ({ id: s.id, steps: s.steps.length, illustrative_total_ms: s.steps.reduce((n, x) => n + Number(x.latency.match(/[0-9]+/)[0]), 0) }))');
const report = {
  html: htmlPath,
  verification_scope: 'Actual inline JavaScript executed in Node vm with minimal modeled DOM and controlled timers. No real browser, CSS layout, font loading, visual inspection, or retrieval backend execution.',
  inline_scripts: scripts.length,
  scenarios: JSON.parse(JSON.stringify(scenarioInfo)),
  passed: results.filter(r => r.status === 'PASS').length,
  failed: results.filter(r => r.status === 'FAIL').length,
  results
};
fs.writeFileSync(path.join(__dirname, 'explorer-analysis-results.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.failed ? 1 : 0;
