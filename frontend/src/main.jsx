import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Editor from '@monaco-editor/react';
import { Activity, AlertTriangle, ArrowRight, BarChart3, Bot, Check, CheckCircle2, ChevronDown, ChevronRight, Clock, Code2, Cpu, FilePlus, FileText, Folder, FolderPlus, Globe2, HardDrive, Loader2, Lock, MemoryStick, Menu, ShieldCheck, Users, Ban, KeyRound, Database, Moon, Pencil, Play, Plus, RefreshCw, RotateCw, Rocket, Save, ScrollText, Search, Send, Server, Sparkles, Square, Sun, Terminal, Trash2, Upload, Wand2, Wrench, X, XCircle, Zap } from 'lucide-react';
import './styles.css';

const tg = window.Telegram?.WebApp;
const initData = tg?.initData || '';
const tokenKey = 'vexhost_token';

function authHeaders(extra = {}) {
  const token = localStorage.getItem(tokenKey);
  return { ...(initData ? { 'X-Telegram-Init-Data': initData } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra };
}
async function api(path, options = {}) {
  const isForm = options.body instanceof FormData;
  const res = await fetch(path, { ...options, headers: authHeaders(isForm ? (options.headers || {}) : { 'Content-Type': 'application/json', ...(options.headers || {}) }) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed ${res.status}`);
  return data;
}
function Stat({ value, label }) { return <div className="stat"><b>{value}</b><span>{label}</span></div>; }

/* Reveal-on-scroll: reveal .reveal elements once, staggered, honoring reduced motion.
   Uses a MutationObserver so async-loaded content (dashboard/admin) is caught too. */
function useReveal() {
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const root = document.documentElement;
    root.classList.add('js-reveal');
    const io = new IntersectionObserver((entries, ob) => {
      for (const e of entries) if (e.isIntersecting) { e.target.classList.add('in'); ob.unobserve(e.target); }
    }, { rootMargin: '0px 0px -6% 0px', threshold: 0.08 });
    let raf = 0;
    const scan = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => document.querySelectorAll('.reveal:not(.in)').forEach(el => io.observe(el))); };
    scan();
    const mo = new MutationObserver(scan);
    mo.observe(document.body, { childList: true, subtree: true });
    return () => { cancelAnimationFrame(raf); io.disconnect(); mo.disconnect(); root.classList.remove('js-reveal'); };
  }, []);
}

function useTheme() {
  const [theme, setTheme] = useState(() => {
    if (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'light') return 'light';
    try { return localStorage.getItem('vexhost_theme') || 'dark'; } catch (_) { return 'dark'; }
  });
  useEffect(() => {
    if (theme === 'light') document.documentElement.setAttribute('data-theme', 'light');
    else document.documentElement.removeAttribute('data-theme');
    try { localStorage.setItem('vexhost_theme', theme); } catch (_) {}
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'light' ? '#ffffff' : '#000000');
  }, [theme]);
  return [theme, setTheme];
}
function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  const next = theme === 'light' ? 'dark' : 'light';
  return <button className="theme-toggle" onClick={() => setTheme(next)} aria-label={`Switch to ${next} theme`} title="Toggle theme">{theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}</button>;
}

function navAction(a, onNav) {
  const cls = a.variant === 'primary' ? 'primary' : a.variant === 'tg' ? 'btn-tg' : a.variant === 'ghost' ? 'secondary' : 'linkbtn';
  const handle = (e) => { a.onClick?.(e); onNav?.(); };
  const inner = <>{a.icon}{a.label}</>;
  return a.href
    ? <a className={cls} href={a.href} onClick={handle} {...(a.external ? { target: '_blank', rel: 'noreferrer' } : {})}>{inner}</a>
    : <button className={cls} onClick={handle}>{inner}</button>;
}

function NavBar({ brand = 'VexHost', links = [], actions = [] }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const close = () => setOpen(false);
    addEventListener('hashchange', close);
    return () => removeEventListener('hashchange', close);
  }, []);
  const linkEl = (l, cls) => <a key={l.label} className={`${cls}${l.cta ? ' nav-cta' : ''}`} href={l.href} onClick={() => setOpen(false)} {...(l.external ? { target: '_blank', rel: 'noreferrer' } : {})}>{l.cta && <Plus size={14} />}{l.label}</a>;
  return <nav className="nav">
    <div className="nav-inner">
      <a className="brand" href="/"><span>V</span> {brand}</a>
      <div className="nav-links">{links.map(l => linkEl(l, 'nav-link'))}</div>
      <div className="nav-actions">
        <div className="nav-actions-desk">{actions.map((a, i) => <React.Fragment key={i}>{navAction(a)}</React.Fragment>)}</div>
        <ThemeToggle />
        <button className="nav-burger" aria-label="Toggle menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>{open ? <X size={18} /> : <Menu size={18} />}</button>
      </div>
    </div>
    {open && <div className="nav-mobile">
      <div className="nav-mobile-links">{links.map(l => linkEl(l, 'nav-mobile-link'))}</div>
      {actions.length > 0 && <div className="nav-mobile-actions">{actions.map((a, i) => <React.Fragment key={i}>{navAction(a, () => setOpen(false))}</React.Fragment>)}</div>}
    </div>}
  </nav>;
}

function Login({ onLogin }) {
  const [form, setForm] = useState({ username: '', password: '' });
  const [status, setStatus] = useState('');
  async function submit(e) {
    e.preventDefault(); setStatus('Signing in…');
    try { const r = await api('/api/auth/login', { method: 'POST', body: JSON.stringify(form) }); localStorage.setItem(tokenKey, r.token); setStatus('Signed in.'); onLogin(); }
    catch (err) { setStatus(err.message); }
  }
  return <article className="panel login-panel"><h2>Browser login</h2><p>Open @VexHostBot once to receive username/password, then manage hosting from any browser.</p><form className="form" onSubmit={submit}><input placeholder="Username from bot" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /><input placeholder="Password from bot" type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /><button className="primary" disabled={!form.username || !form.password}><Lock size={18} /> Login</button></form>{status && <p className="notice">{status}</p>}</article>;
}

function fmtUptime(s) {
  if (!s || s < 1) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${s}s`;
}

const RUNTIME_TYPES = ['node_app', 'python_app', 'api', 'telegram_bot', 'mini_app'];
function entryFile(type) { return (type === 'node_app' || type === 'mini_app') ? 'server.js' : 'main.py'; }
function baseName(p) { return (p || '').split('/').pop(); }
function langFromPath(p) {
  const ext = (p.split('.').pop() || '').toLowerCase();
  const map = { js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript', ts: 'typescript', tsx: 'typescript', json: 'json', html: 'html', htm: 'html', css: 'css', scss: 'scss', less: 'less', md: 'markdown', py: 'python', yml: 'yaml', yaml: 'yaml', sh: 'shell', toml: 'ini', ini: 'ini', xml: 'xml', sql: 'sql' };
  return map[ext] || 'plaintext';
}
function prettierParser(p) {
  const ext = (p.split('.').pop() || '').toLowerCase();
  if (['js', 'jsx', 'mjs', 'cjs'].includes(ext)) return 'babel';
  if (['ts', 'tsx'].includes(ext)) return 'babel-ts';
  if (ext === 'json') return 'json';
  if (['css', 'scss', 'less'].includes(ext)) return 'css';
  if (['html', 'htm'].includes(ext)) return 'html';
  return null;
}

const PIPE_STAGES = [
  ['queued', 'Queued'],
  ['installing', 'Installing dependencies'],
  ['building', 'Building'],
  ['starting', 'Starting container'],
  ['health', 'Health checking'],
  ['live', 'Live'],
];

function DeployPipeline({ project, onChanged }) {
  const [phase, setPhase] = useState('idle');
  const [logs, setLogs] = useState('');
  const [busy, setBusy] = useState(false);
  const reached = useRef(0);
  const timer = useRef(null);
  const logRef = useRef(null);
  const isBot = project.type === 'telegram_bot';
  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [logs]);

  async function poll(started) {
    try {
      const lg = await api(`/api/projects/${project.id}/runtime/logs`).catch(() => ({ logs: '' }));
      const mt = await api(`/api/projects/${project.id}/runtime/metrics`).catch(() => null);
      const l = (lg.logs || '').toLowerCase();
      setLogs(lg.logs || '');
      if (mt && (mt.status === 'exited' || mt.status === 'dead' || mt.crash)) { setPhase('failed'); setBusy(false); onChanged?.(); return; }
      let idx = 0;
      if (/npm install|pip install|added \d+ packages|collecting |installing/.test(l)) idx = Math.max(idx, 1);
      if (/npm run build|vite build|tsc\b|webpack|compiled|build complete|built in/.test(l)) idx = Math.max(idx, 2);
      if (mt && mt.running) idx = Math.max(idx, 3);
      let live = false;
      if (mt && mt.running) {
        if (isBot) { if (/start_polling|bot is running|polling|run_polling/.test(l)) live = true; }
        else {
          idx = Math.max(idx, 4);
          const h = await api(`/api/projects/${project.id}/runtime/health`).catch(() => ({ ok: false }));
          if (h.ok) live = true;
        }
      }
      if (live) { reached.current = 5; setPhase('live'); setBusy(false); onChanged?.(); return; }
      reached.current = Math.max(reached.current, idx);
      setPhase(PIPE_STAGES[reached.current][0]);
      if (Date.now() - started > 90000) { setPhase('failed'); setBusy(false); return; }
      timer.current = setTimeout(() => poll(started), 1400);
    } catch (_) { timer.current = setTimeout(() => poll(started), 1600); }
  }
  async function deploy() {
    setBusy(true); setPhase('queued'); setLogs(''); reached.current = 0;
    try {
      await api(`/api/projects/${project.id}/runtime/start`, { method: 'POST', body: JSON.stringify({}) });
      const started = Date.now();
      timer.current = setTimeout(() => poll(started), 1200);
    } catch (e) { setPhase('failed'); setLogs(String(e.message || e)); setBusy(false); }
  }
  async function stop() {
    clearTimeout(timer.current); setBusy(false);
    await api(`/api/projects/${project.id}/runtime/stop`, { method: 'POST', body: JSON.stringify({}) }).catch(() => {});
    setPhase('idle'); onChanged?.();
  }

  const curIdx = phase === 'failed' ? reached.current : PIPE_STAGES.findIndex(s => s[0] === phase);
  return <section className="pipeline">
    <div className="pipeline-head">
      <h4><Rocket size={15} /> Build &amp; deploy</h4>
      <div className="actions">
        {phase === 'live' && <span className="pill pill-ok"><i /> live</span>}
        {phase === 'failed' && <span className="pill pill-down"><i /> failed</span>}
        <button className="primary" onClick={deploy} disabled={busy}>{busy ? <><Loader2 size={14} className="spin" /> Deploying</> : <><Play size={14} /> Deploy</>}</button>
        <button onClick={stop}><Square size={14} /> Stop</button>
      </div>
    </div>
    <ol className="stepper">
      {PIPE_STAGES.map((s, i) => {
        const st = phase === 'live' ? 'done'
          : phase === 'failed' ? (i < reached.current ? 'done' : i === reached.current ? 'failed' : 'todo')
          : phase === 'idle' ? 'todo'
          : i < curIdx ? 'done' : i === curIdx ? 'active' : 'todo';
        return <li key={s[0]} className={`step step-${st}`}>
          <span className="dot">{st === 'done' ? <CheckCircle2 size={16} /> : st === 'failed' ? <XCircle size={16} /> : st === 'active' ? <Loader2 size={13} className="spin" /> : <i />}</span>
          <span className="label">{s[1]}</span>
        </li>;
      })}
    </ol>
    <pre className="pipeline-logs" ref={logRef}>{logs || 'Press Deploy to build and start your container. Live logs stream here: npm install → build → docker run → healthcheck.'}</pre>
  </section>;
}

const POLICIES = [['always', 'Always'], ['on-failure', 'On failure'], ['manual', 'Manual']];

function RuntimeMetrics({ project, onOpenFile, onOpenLogs, onChanged }) {
  const [m, setM] = useState(null);
  const [err, setErr] = useState('');
  const [policy, setPolicy] = useState(project.restart_policy || 'always');
  const [acting, setActing] = useState(false);
  useEffect(() => {
    let alive = true;
    async function tick() {
      try { const r = await api(`/api/projects/${project.id}/runtime/metrics`); if (alive) { setM(r); setErr(''); } }
      catch (e) { if (alive) setErr(e.message); }
    }
    tick();
    const id = setInterval(tick, 4000);
    return () => { alive = false; clearInterval(id); };
  }, [project.id]);

  async function setPol(p) { setPolicy(p); try { await api(`/api/projects/${project.id}/runtime/policy`, { method: 'POST', body: JSON.stringify({ policy: p }) }); onChanged?.(); } catch (_) {} }
  async function restart() { setActing(true); try { await api(`/api/projects/${project.id}/runtime/restart`, { method: 'POST', body: JSON.stringify({}) }); } catch (_) {} setActing(false); onChanged?.(); }

  const running = m?.running;
  const state = m ? (m.status === 'not_created' ? 'not started' : m.status) : 'loading…';
  const dot = !m ? 'idle' : running ? 'ok' : m.status === 'not_created' ? 'idle' : 'down';
  const limit = m?.mem_limit_mb || 384;
  const memPct = m ? Math.min(100, m.mem_percent || (limit ? (m.mem_used_mb / limit) * 100 : 0)) : 0;
  const tiles = [
    ['CPU', <Cpu size={13} />, `${m ? m.cpu_percent : 0}%`, Math.min(100, m?.cpu_percent || 0)],
    ['Disk', <HardDrive size={13} />, <>{m ? m.disk_mb : 0}<u> MB</u></>, Math.min(100, ((m?.disk_mb || 0) / 1024) * 100)],
    ['Requests', <BarChart3 size={13} />, m ? m.requests : 0, Math.min(100, (m?.requests || 0) * 8)],
    ['Resp', <Activity size={13} />, <>{m ? m.response_time_ms : 0}<u> ms</u></>, Math.min(100, ((m?.response_time_ms || 0) / 1000) * 100)],
    ['Errors', <AlertTriangle size={13} />, m ? m.errors : 0, Math.min(100, (m?.errors || 0) * 20)],
    ['Bandwidth', <Globe2 size={13} />, <>{m ? m.bandwidth_mb : 0}<u> MB</u></>, Math.min(100, (m?.bandwidth_mb || 0) * 10)],
    ['Uptime', <Clock size={13} />, fmtUptime(m?.uptime_seconds), Math.min(100, ((m?.uptime_seconds || 0) / 3600) * 100)],
    ['Restarts', <RotateCw size={13} />, m ? m.restart_count : 0, Math.min(100, (m?.restart_count || 0) * 25)],
  ];

  return <section className="monitor">
    <div className="monitor-head">
      <h4><Activity size={15} /> Monitoring</h4>
      <span className={`pill pill-${dot}`}><i /> {state}</span>
    </div>

    {m?.crash && <div className="crash-banner">
      <AlertTriangle size={16} />
      <div className="crash-body">
        <b>Crashed</b>
        <div className="crash-meta"><span>Exit code: <code>{m.crash.exit_code}</code></span>{m.crash.oom_killed && <span>· out of memory</span>}</div>
        <span className="crash-reason">{m.crash.reason}</span>
        {m.crash.last_error && <div className="crash-err">Last error: <code>{m.crash.last_error}</code></div>}
        {m.crash.log_tail && <pre>{m.crash.log_tail}</pre>}
        <div className="crash-actions">
          <button className="primary" onClick={restart} disabled={acting}>{acting ? <Loader2 size={14} className="spin" /> : <RotateCw size={14} />} Restart</button>
          <button onClick={() => onOpenLogs?.()}><ScrollText size={14} /> Open logs</button>
          <button onClick={() => onOpenFile?.(entryFile(project.type))}><Wrench size={14} /> Fix in editor</button>
        </div>
      </div>
    </div>}

    <div className="metrics-grid">
      <div className="metric">
        <span className="k"><MemoryStick size={13} /> RAM</span>
        <b>{m ? m.mem_used_mb : 0}<u> / {limit} MB</u></b>
        <div className="bar"><i style={{ width: `${memPct}%` }} /></div>
      </div>
      {tiles.map(([k, icon, val, pct]) => (
        <div className={`metric metric-${String(k).toLowerCase()}`} key={k}>
          <span className="k">{icon} {k}</span><b>{val}</b>
          <div className="mini-chart"><i style={{ width: `${Math.max(4, pct || 0)}%` }} /></div>
        </div>
      ))}
    </div>

    <div className="policy-row">
      <span className="policy-label"><RotateCw size={13} /> Restart policy</span>
      <div className="segmented">
        {POLICIES.map(([v, lbl]) => <button key={v} className={policy === v ? 'on' : ''} onClick={() => setPol(v)}>{lbl}</button>)}
      </div>
    </div>
    {err && <p className="muted metrics-err">Metrics unavailable: {err}</p>}
  </section>;
}

function FileTree({ nodes, activePath, onOpen, onRename, onDelete, depth = 0 }) {
  return <ul className={`tree${depth ? ' tree-nested' : ''}`}>
    {nodes.map(n => n.type === 'dir'
      ? <TreeFolder key={n.path} node={n} activePath={activePath} onOpen={onOpen} onRename={onRename} onDelete={onDelete} depth={depth} />
      : <li key={n.path} className={`tree-row${activePath === n.path ? ' on' : ''}`}>
          <button className="tree-file" onClick={() => onOpen(n.path)}><FileText size={13} /> <span>{n.name}</span></button>
          <span className="tree-tools">
            <button title="Rename" onClick={() => onRename(n.path)}><Pencil size={12} /></button>
            <button title="Delete" className="icon-danger" onClick={() => onDelete(n.path)}><Trash2 size={12} /></button>
          </span>
        </li>)}
  </ul>;
}
function TreeFolder({ node, activePath, onOpen, onRename, onDelete, depth }) {
  const [open, setOpen] = useState(depth < 1);
  return <li className="tree-folder">
    <div className="tree-row">
      <button className="tree-file" onClick={() => setOpen(o => !o)}>{open ? <ChevronDown size={13} /> : <ChevronRight size={13} />} <Folder size={13} /> <span>{node.name}</span></button>
      <span className="tree-tools">
        <button title="Rename" onClick={() => onRename(node.path)}><Pencil size={12} /></button>
        <button title="Delete" className="icon-danger" onClick={() => onDelete(node.path)}><Trash2 size={12} /></button>
      </span>
    </div>
    {open && node.children && node.children.length > 0 && <FileTree nodes={node.children} activePath={activePath} onOpen={onOpen} onRename={onRename} onDelete={onDelete} depth={depth + 1} />}
  </li>;
}


function AddonCards({ items = [], compact = false }) {
  const icon = key => key.includes('postgres') ? <Database size={17} /> : key.includes('redis') ? <Zap size={17} /> : key.includes('cron') ? <Clock size={17} /> : key.includes('email') ? <Send size={17} /> : key.includes('ai') ? <Sparkles size={17} /> : key.includes('domain') ? <Globe2 size={17} /> : key.includes('ram') ? <MemoryStick size={17} /> : key.includes('disk') ? <HardDrive size={17} /> : <Folder size={17} />;
  return <div className={compact ? 'addons-grid project-addons-grid' : 'addons-grid'}>
    {items.map(a => <article className={`addon-card addon-${a.status}`} key={a.key}>
      <div className="addon-icon">{icon(a.key)}</div>
      <div><h3>{a.name}</h3><p>{a.description}</p></div>
      <div className="addon-foot"><span>{a.price}</span><button disabled={a.status !== 'available'}>{a.status === 'available' ? 'Enable' : 'Soon'}</button></div>
    </article>)}
  </div>;
}

function ProjectAddons({ items = [] }) {
  return <section className="project-tab-panel"><div className="tab-panel-head"><div><p className="eyebrow"><Zap size={14} /> Add-ons</p><h3>Attach services to this project</h3></div><span className="badge">{items.length} add-ons</span></div><AddonCards items={items} compact /></section>;
}

const HOSTING_IDEAS = [
  ['Deployments', 'Rollback button, deploy history, preview URLs for every build, GitHub webhook autodeploy.'],
  ['Secrets', 'Environment variables UI with masked values, per-project secrets, one-click .env template.'],
  ['Domains', 'Custom domains with DNS checker, TLS status, redirects, www/non-www toggle.'],
  ['Scaling', 'CPU/RAM presets, replicas, sleep mode, always-on mode, restart limits.'],
  ['Observability', 'Request log, error inbox, uptime checks, Telegram alerts, slow request tracing.'],
  ['Collaboration', 'Team members, read-only access, project transfer, audit log.'],
  ['Backups', 'Database backups, file snapshots, restore point before deploy.'],
  ['Templates', 'FastAPI, Express, Telegraf, aiogram, Discord bot, React Mini App starters.'],
];
function ProjectIdeas() {
  return <section className="project-tab-panel"><div className="tab-panel-head"><div><p className="eyebrow"><Sparkles size={14} /> Ideas</p><h3>Next hosting features</h3></div><span className="badge">roadmap</span></div><div className="ideas-board">{HOSTING_IDEAS.map(([k,v]) => <article key={k}><b>{k}</b><p>{v}</p></article>)}</div></section>;
}

function RuntimeGuide({ project }) {
  const isNode = project.type === 'node_app' || project.type === 'mini_app';
  const isPython = project.type === 'python_app' || project.type === 'api' || project.type === 'telegram_bot';
  return <section className="project-tab-panel"><div className="tab-panel-head"><div><p className="eyebrow"><Wrench size={14} /> Runtime</p><h3>{isNode ? 'Node.js hosting setup' : isPython ? 'Python hosting setup' : 'Static hosting setup'}</h3></div><span className="badge">{project.type}</span></div>
    <div className="runtime-guide-grid">
      <article><b>Entry file</b><code>{isNode ? 'server.js / index.js' : isPython ? 'main.py / app.py' : 'index.html'}</code><p>{isNode ? 'Listen on process.env.PORT.' : isPython ? 'Run FastAPI/Flask/bot from main.py. HTTP apps should listen on PORT.' : 'Upload/edit files and press Publish static.'}</p></article>
      <article><b>Dependencies</b><code>{isNode ? 'package.json' : isPython ? 'requirements.txt' : 'assets/'}</code><p>{isNode ? 'Use npm install during container start/build.' : isPython ? 'List packages in requirements.txt.' : 'CSS/JS/images are served from the public deployment folder.'}</p></article>
      <article><b>Console</b><code>{isNode ? 'npm run start' : isPython ? 'python main.py' : 'static'}</code><p>Use the Console tab for start/restart/logs/exec and monitoring.</p></article>
      <article><b>Production tips</b><code>health + logs</code><p>Add health endpoints, structured logs, env vars and avoid writing secrets into code.</p></article>
    </div>
  </section>;
}

function ProjectSideNav({ project, active, onChange, onNew }) {
  const runtime = RUNTIME_TYPES.includes(project.type);
  const tabs = [
    ['overview', <Server size={15} />, 'Overview'],
    ...(runtime ? [['console', <Terminal size={15} />, 'Console & monitoring']] : []),
    ['files', <Folder size={15} />, 'Files manager'],
    ['addons', <Zap size={15} />, 'Add-ons'],
    ['runtime', <Wrench size={15} />, project.type.includes('node') || project.type === 'mini_app' ? 'Node.js guide' : project.type.includes('python') || project.type === 'api' ? 'Python guide' : 'Hosting guide'],
    ...(project.type === 'telegram_bot' ? [['bot', <Bot size={15} />, 'Telegram bot']] : []),
    ['ideas', <Sparkles size={15} />, 'Ideas'],
  ];
  return <article className="panel project-side-nav">
    <div className="side-project-head"><span className="side-avatar">{project.name.slice(0,1).toUpperCase()}</span><div><h2>{project.name}</h2><p>{project.type} · {project.status}</p></div></div>
    <a className="side-open" href={project.live_url || `https://${project.subdomain}.vexory.xyz/`} target="_blank" rel="noreferrer"><Globe2 size={14} /> Open live site</a>
    <div className="side-tabs">{tabs.map(([id, icon, label]) => <button key={id} className={active === id ? 'on' : ''} onClick={() => onChange(id)}>{icon}<span>{label}</span></button>)}</div>
    <button className="side-new" onClick={onNew}><Plus size={14} /> New project</button>
  </article>;
}

function ProjectConsole({ project, onChanged, activeView = 'overview', setActiveView, addons = [] }) {
  const [tree, setTree] = useState([]);
  const [tabs, setTabs] = useState([]);
  const [activeTab, setActiveTab] = useState('');
  const [status, setStatus] = useState('');
  const [logs, setLogs] = useState('');
  const [commandOut, setCommandOut] = useState('');
  const [logsLive, setLogsLive] = useState(true);
  const [cmd, setCmd] = useState('pwd && ls -la');
  const [search, setSearch] = useState({ q: '', mode: 'name', results: null });
  const [dragOver, setDragOver] = useState(false);
  const [formatting, setFormatting] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const tabsRef = useRef([]);
  const saveTimers = useRef({});
  const editorRef = useRef(null);
  const termRef = useRef(null);
  const termPreRef = useRef(null);
  const gotoLineRef = useRef(0);

  const runtime = RUNTIME_TYPES.includes(project.type);
  const activeFile = tabs.find(t => t.path === activeTab);
  useEffect(() => { tabsRef.current = tabs; }, [tabs]);

  async function loadTree() { const r = await api(`/api/projects/${project.id}/files-tree`); setTree(r.tree || []); }
  useEffect(() => { setTabs([]); setActiveTab(''); setLogs(''); setCommandOut(''); setSearch({ q: '', mode: 'name', results: null }); loadTree().catch(e => setStatus(e.message)); }, [project.id]);
  useEffect(() => {
    if (!runtime || !logsLive) return;
    let alive = true;
    async function tick() {
      try { const r = await api(`/api/projects/${project.id}/runtime/logs`); if (alive) setLogs(r.logs || ''); }
      catch (_) {}
    }
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, [runtime, logsLive, project.id]);
  useEffect(() => { if (termPreRef.current) termPreRef.current.scrollTop = termPreRef.current.scrollHeight; }, [logs, commandOut]);

  async function openFile(path, gotoLine) {
    if (tabsRef.current.find(t => t.path === path)) { setActiveTab(path); if (gotoLine) jumpTo(gotoLine); return; }
    try {
      const r = await api(`/api/projects/${project.id}/file?path=${encodeURIComponent(path)}`);
      gotoLineRef.current = gotoLine || 0;
      setTabs(t => [...t, { path: r.path, content: r.content, dirty: false, saving: false, saved: true }]);
      setActiveTab(r.path);
    } catch (e) { setStatus(e.message); }
  }
  function jumpTo(line) { const ed = editorRef.current; if (ed && line) { ed.revealLineInCenter(line); ed.setPosition({ lineNumber: line, column: 1 }); ed.focus(); } }
  function closeTab(path, e) {
    e?.stopPropagation();
    const rest = tabsRef.current.filter(x => x.path !== path);
    setTabs(rest);
    if (activeTab === path) setActiveTab(rest.length ? rest[rest.length - 1].path : '');
  }
  function onEdit(val) {
    const v = val ?? '';
    setTabs(t => t.map(x => x.path === activeTab ? { ...x, content: v, dirty: true, saved: false } : x));
    clearTimeout(saveTimers.current[activeTab]);
    const path = activeTab;
    saveTimers.current[path] = setTimeout(() => saveTab(path), 800);
  }
  async function saveTab(path) {
    const tab = tabsRef.current.find(x => x.path === path);
    if (!tab) return;
    setTabs(t => t.map(x => x.path === path ? { ...x, saving: true } : x));
    try {
      await api(`/api/projects/${project.id}/file`, { method: 'POST', body: JSON.stringify({ path, content: tab.content }) });
      setTabs(t => t.map(x => x.path === path ? { ...x, dirty: false, saving: false, saved: true } : x));
    } catch (e) { setStatus(e.message); setTabs(t => t.map(x => x.path === path ? { ...x, saving: false } : x)); }
  }
  async function newFile() { const name = prompt('New file path, e.g. src/app.js'); if (!name) return; try { await api(`/api/projects/${project.id}/file`, { method: 'POST', body: JSON.stringify({ path: name, content: '' }) }); await loadTree(); openFile(name); } catch (e) { setStatus(e.message); } }
  async function newFolder() { const name = prompt('New folder path'); if (!name) return; try { await api(`/api/projects/${project.id}/mkdir`, { method: 'POST', body: JSON.stringify({ path: name }) }); await loadTree(); } catch (e) { setStatus(e.message); } }
  async function rename(path) { const to = prompt('Rename to:', path); if (!to || to === path) return; try { const r = await api(`/api/projects/${project.id}/rename`, { method: 'POST', body: JSON.stringify({ from: path, to }) }); await loadTree(); setTabs(t => t.map(x => x.path === path ? { ...x, path: r.path } : x)); if (activeTab === path) setActiveTab(r.path); } catch (e) { setStatus(e.message); } }
  async function del(path) { if (!confirm(`Delete ${path}?`)) return; try { await api(`/api/projects/${project.id}/delete-file`, { method: 'POST', body: JSON.stringify({ path }) }); await loadTree(); closeTab(path); } catch (e) { setStatus(e.message); } }
  async function upload(fileList) { const files = [...(fileList || [])]; if (!files.length) return; setStatus(`Uploading ${files.length} file(s)…`); for (const f of files) { const fd = new FormData(); fd.append('file', f); try { await api(`/api/projects/${project.id}/upload-file?path=`, { method: 'POST', body: fd }); } catch (e) { setStatus(e.message); } } await loadTree(); setStatus(`Uploaded ${files.length} file(s).`); }
  function onDrop(e) { e.preventDefault(); setDragOver(false); upload(e.dataTransfer.files); }
  async function runSearch() { const q = search.q.trim(); if (q.length < 2) { setSearch(s => ({ ...s, results: null })); return; } try { const r = await api(`/api/projects/${project.id}/search?q=${encodeURIComponent(q)}&mode=${search.mode}`); setSearch(s => ({ ...s, results: r.items || [] })); } catch (e) { setStatus(e.message); } }
  async function publishStatic() { try { const r = await api(`/api/projects/${project.id}/publish-static-files`, { method: 'POST', body: JSON.stringify({}) }); setStatus(`Published: ${r.live_url}`); onChanged?.(); } catch (e) { setStatus(e.message); } }
  async function refreshLogs() { if (!runtime) return; try { const r = await api(`/api/projects/${project.id}/runtime/logs`); setLogs(r.logs || ''); } catch (e) { setStatus(e.message); } }
  async function restartServer() { if (!runtime) { setStatus('Static sites do not have a runtime server. Use Publish static.'); return; } setRestarting(true); setStatus('Restarting server…'); try { const r = await api(`/api/projects/${project.id}/runtime/restart`, { method: 'POST', body: JSON.stringify({}) }); setStatus(r.queued ? 'Restart queued. Container will be back online shortly.' : 'Server restarted.'); refreshLogs(); onChanged?.(); } catch (e) { setStatus(e.message); } setRestarting(false); }
  async function execCmd() { try { const r = await api(`/api/projects/${project.id}/runtime/exec`, { method: 'POST', body: JSON.stringify({ command: cmd }) }); setCommandOut(prev => `${prev}\n$ ${cmd}\n${r.output}\n(exit ${r.exit_code})`); } catch (e) { setStatus(e.message); } }
  function openLogs() { refreshLogs(); termRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  async function format() {
    if (!activeFile) return;
    const parser = prettierParser(activeFile.path);
    if (!parser) { setStatus('No formatter for this file type.'); return; }
    setFormatting(true);
    try {
      const [pr, babel, estree, html, postcss] = await Promise.all([
        import('prettier/standalone'), import('prettier/plugins/babel'),
        import('prettier/plugins/estree'), import('prettier/plugins/html'), import('prettier/plugins/postcss'),
      ]);
      const plugins = [babel.default || babel, estree.default || estree, html.default || html, postcss.default || postcss];
      const out = await (pr.default || pr).format(activeFile.content, { parser, plugins, tabWidth: 2, semi: true });
      onEdit(out);
      setStatus('Formatted with Prettier.');
    } catch (e) { setStatus('Prettier: ' + (e.message || e)); }
    setFormatting(false);
  }

  const consoleView = <>
    {runtime ? <>
      <DeployPipeline project={project} onChanged={onChanged} />
      <RuntimeMetrics project={project} onOpenFile={openFile} onOpenLogs={openLogs} onChanged={onChanged} />
      <section className="terminal-box live-terminal" ref={termRef}>
        <div className="editor-top">
          <span className={`live-dot ${logsLive ? 'on' : ''}`}><i /> {logsLive ? 'Live logs' : 'Paused'}</span>
          <input value={cmd} onChange={e => setCmd(e.target.value)} placeholder="Command inside container" onKeyDown={e => e.key === 'Enter' && execCmd()} />
          <button onClick={execCmd}><Terminal size={15} /> Run</button>
          <button className="restart-server-btn" onClick={restartServer} disabled={restarting}>{restarting ? <Loader2 size={15} className="spin" /> : <RotateCw size={15} />} Restart server</button>
          <button onClick={() => setLogsLive(v => !v)}><Activity size={15} /> {logsLive ? 'Pause' : 'Live'}</button>
          <button onClick={refreshLogs}><ScrollText size={15} /> Refresh</button>
        </div>
        <pre ref={termPreRef}>{`${logs || 'Deploy the container to see live logs here.'}${commandOut ? '\n\n# command output' + commandOut : ''}`}</pre>
      </section>
    </> : <section className="project-tab-panel"><div className="tab-panel-head"><div><p className="eyebrow"><Globe2 size={14} /> Static project</p><h3>No runtime server required</h3></div></div><p className="muted">Edit files in Files manager, then press Publish static. Static websites do not need server restart.</p></section>}
  </>;

  const filesView = <div className="ide">
    <aside className={`ide-side${dragOver ? ' drag' : ''}`} onDragOver={e => { e.preventDefault(); setDragOver(true); }} onDragLeave={() => setDragOver(false)} onDrop={onDrop}>
      <div className="ide-search">
        <Search size={13} />
        <input value={search.q} placeholder={search.mode === 'name' ? 'Search files…' : 'Search in files…'} onChange={e => setSearch(s => ({ ...s, q: e.target.value }))} onKeyDown={e => e.key === 'Enter' && runSearch()} />
        <div className="seg-mini"><button className={search.mode === 'name' ? 'on' : ''} onClick={() => setSearch(s => ({ ...s, mode: 'name', results: null }))}>Name</button><button className={search.mode === 'content' ? 'on' : ''} onClick={() => setSearch(s => ({ ...s, mode: 'content', results: null }))}>Text</button></div>
      </div>
      <div className="ide-tools"><button title="New file" onClick={newFile}><FilePlus size={14} /></button><button title="New folder" onClick={newFolder}><FolderPlus size={14} /></button><label className="up" title="Upload files"><Upload size={14} /><input type="file" multiple onChange={e => { upload(e.target.files); e.target.value = ''; }} /></label></div>
      <div className="ide-tree">{search.results ? <div className="search-results"><div className="sr-head">{search.results.length} result(s)<button onClick={() => setSearch(s => ({ ...s, results: null }))}><X size={12} /></button></div>{search.results.map((r, i) => <button key={i} className="sr-item" onClick={() => openFile(r.path, r.line)}><span className="sr-path">{r.path}</span>{r.line && <span className="sr-line">:{r.line} · {r.text}</span>}</button>)}{!search.results.length && <p className="muted sr-empty">No matches.</p>}</div> : <FileTree nodes={tree} activePath={activeTab} onOpen={openFile} onRename={rename} onDelete={del} />}</div>
      {dragOver && <div className="drop-hint"><Upload size={16} /> Drop files to upload</div>}
    </aside>
    <section className="ide-main">
      <div className="tabs"><div className="tab-strip">{tabs.map(t => <button key={t.path} className={`tab${activeTab === t.path ? ' on' : ''}`} onClick={() => setActiveTab(t.path)} title={t.path}>{t.dirty ? <span className="dirty" /> : <FileText size={12} />}<span className="tab-name">{baseName(t.path)}</span><span className="tab-x" onClick={e => closeTab(t.path, e)}><X size={12} /></span></button>)}</div>{activeFile && <div className="tab-actions"><span className="save-state">{activeFile.saving ? 'Saving…' : activeFile.dirty ? 'Unsaved' : 'Saved'}</span><button className="fmt" onClick={format} disabled={formatting}>{formatting ? <Loader2 size={13} className="spin" /> : <Wand2 size={13} />} Format</button></div>}</div>
      <div className="editor-wrap">{activeFile ? <Editor height="100%" theme="vs-dark" path={activeFile.path} language={langFromPath(activeFile.path)} value={activeFile.content} onChange={onEdit} onMount={ed => { editorRef.current = ed; if (gotoLineRef.current) { jumpTo(gotoLineRef.current); gotoLineRef.current = 0; } }} options={{ fontSize: 13, minimap: { enabled: false }, automaticLayout: true, scrollBeyondLastLine: false, tabSize: 2, fontFamily: "'Geist Mono', ui-monospace, monospace", padding: { top: 14 } }} /> : <div className="editor-empty"><Code2 size={26} /><p>Open a file from the tree, or create one, to start editing.</p></div>}</div>
    </section>
  </div>;

  return <article className="panel hosting-console tabbed-console">
    <div className="console-head">
      <div><h3>{project.name}</h3><p>{project.type} · <a href={project.live_url || `https://${project.subdomain}.vexory.xyz/`} target="_blank" rel="noreferrer">{project.subdomain}.vexory.xyz</a></p></div>
      <div className="actions">
        <button onClick={loadTree}><RefreshCw size={15} /> Refresh</button>
        {runtime && <button className="primary restart-server-btn" onClick={restartServer} disabled={restarting}>{restarting ? <Loader2 size={15} className="spin" /> : <RotateCw size={15} />} Restart server</button>}
        {project.type === 'static_site' && <button className="primary" onClick={publishStatic}><Rocket size={15} /> Publish static</button>}
      </div>
    </div>
    <div className="mobile-console-tabs">
      {['overview','console','files','addons','runtime', project.type === 'telegram_bot' ? 'bot' : null,'ideas'].filter(Boolean).map(id => <button key={id} className={activeView === id ? 'on' : ''} onClick={() => setActiveView?.(id)}>{id}</button>)}
    </div>
    {status && <p className="notice">{status}</p>}
    {activeView === 'overview' && <section className="project-tab-panel overview-panel"><div className="tab-panel-head"><div><p className="eyebrow"><Server size={14} /> Overview</p><h3>Project control center</h3></div><span className={`badge badge-${project.status}`}>{project.status}</span></div><div className="overview-grid"><button onClick={() => setActiveView?.('console')}><Terminal size={18} /><b>Console</b><span>Start, restart, logs and commands</span></button><button onClick={() => setActiveView?.('files')}><Folder size={18} /><b>Files</b><span>Edit code and upload files</span></button><button onClick={() => setActiveView?.('addons')}><Zap size={18} /><b>Add-ons</b><span>Database, Redis, domains, storage</span></button><button onClick={() => setActiveView?.('runtime')}><Wrench size={18} /><b>Runtime guide</b><span>Python/Node.js production tips</span></button></div></section>}
    {activeView === 'console' && consoleView}
    {activeView === 'files' && filesView}
    {activeView === 'addons' && <ProjectAddons items={addons} />}
    {activeView === 'runtime' && <RuntimeGuide project={project} />}
    {activeView === 'bot' && project.type === 'telegram_bot' && <BotPanel project={project} />}
    {activeView === 'ideas' && <ProjectIdeas />}
  </article>;
}


function AddonsMarketplace({ items = [] }) {
  const icon = key => key.includes('postgres') ? <Database size={17} /> : key.includes('redis') ? <Zap size={17} /> : key.includes('cron') ? <Clock size={17} /> : key.includes('email') ? <Send size={17} /> : key.includes('ai') ? <Sparkles size={17} /> : key.includes('domain') ? <Globe2 size={17} /> : key.includes('ram') ? <MemoryStick size={17} /> : key.includes('disk') ? <HardDrive size={17} /> : <Folder size={17} />;
  return <section className="section addons-section">
    <div className="section-head"><div><p className="eyebrow">Add-ons marketplace</p><h2>Power-ups for your apps</h2></div><span className="badge">{items.length} add-ons</span></div>
    <div className="addons-grid">
      {items.map(a => <article className={`addon-card addon-${a.status}`} key={a.key}>
        <div className="addon-icon">{icon(a.key)}</div>
        <div><h3>{a.name}</h3><p>{a.description}</p></div>
        <div className="addon-foot"><span>{a.price}</span><button disabled={a.status !== 'available'}>{a.status === 'available' ? 'Enable' : 'Soon'}</button></div>
      </article>)}
    </div>
  </section>;
}

function BotPanel({ project }) {
  const defaults = [{ command: 'start', description: 'Start bot' }, { command: 'help', description: 'Help' }, { command: 'profile', description: 'My profile' }];
  const [data, setData] = useState(null);
  const [commands, setCommands] = useState(defaults);
  const [status, setStatus] = useState('');
  const [saving, setSaving] = useState(false);
  async function load() {
    try {
      const r = await api(`/api/projects/${project.id}/bot/status`);
      setData(r); setCommands((r.commands && r.commands.length) ? r.commands : defaults); setStatus('');
    } catch (e) { setStatus(e.message); }
  }
  useEffect(() => { load(); const id = setInterval(load, 7000); return () => clearInterval(id); }, [project.id]);
  function update(i, key, value) { setCommands(rows => rows.map((r, idx) => idx === i ? { ...r, [key]: value } : r)); }
  function add() { setCommands(rows => [...rows, { command: '', description: '' }]); }
  function remove(i) { setCommands(rows => rows.filter((_, idx) => idx !== i)); }
  async function save() {
    setSaving(true); setStatus('Syncing commands to Telegram…');
    try { const r = await api(`/api/projects/${project.id}/bot/commands`, { method: 'POST', body: JSON.stringify({ commands }) }); setCommands(r.commands); setStatus(r.applied_to_telegram ? 'Commands synced to Telegram.' : 'Commands saved. Add BOT_TOKEN in .env to sync them to Telegram.'); }
    catch (e) { setStatus(e.message); }
    setSaving(false);
  }
  const a = data?.analytics || {};
  return <section className="bot-panel">
    <div className="bot-head"><div><p className="eyebrow"><Bot size={14} /> Telegram bot mode</p><h3>Bot control panel</h3></div><button onClick={load}><RefreshCw size={14} /> Refresh</button></div>
    {status && <p className="notice">{status}</p>}
    <div className="bot-status-grid">
      <Stat value={data?.token_status || 'loading'} label="Bot token status" />
      <Stat value={data?.webhook_status || 'loading'} label="Webhook status" />
      <Stat value={data?.bot_username ? '@' + data.bot_username : '—'} label="Bot username" />
      <Stat value={data?.last_update ? new Date(data.last_update).toLocaleString() : '—'} label="Last update" />
      <Stat value={data?.users_count ?? 0} label="Users count" />
      <Stat value={data?.messages_today ?? 0} label="Messages today" />
      <Stat value={data?.errors ?? 0} label="Errors" />
    </div>
    <div className="bot-split">
      <article className="bot-card"><h4><BarChart3 size={15} /> Bot analytics</h4>
        <div className="analytics-grid">
          <span>Total users <b>{a.total_users ?? 0}</b></span><span>New users today <b>{a.new_users_today ?? 0}</b></span><span>Messages today <b>{a.messages_today ?? 0}</b></span><span>Active chats <b>{a.active_chats ?? 0}</b></span><span>Errors <b>{a.errors ?? 0}</b></span>
        </div>
        <h5>Top commands</h5>
        <div className="top-commands">{(a.top_commands || []).map(([cmd, count]) => <span key={cmd}><code>{cmd}</code><b>{count}</b></span>)}{!(a.top_commands || []).length && <p className="muted">No command data yet. Logs will populate analytics after users interact with the bot.</p>}</div>
      </article>
      <article className="bot-card commands-card"><h4><Terminal size={15} /> Bot commands editor</h4>
        <div className="commands-list">{commands.map((c, i) => <div className="command-row" key={i}><input value={'/' + (c.command || '').replace(/^\//,'')} onChange={e => update(i, 'command', e.target.value.replace(/^\//,''))} placeholder="/start" /><input value={c.description || ''} onChange={e => update(i, 'description', e.target.value)} placeholder="Start bot" /><button className="icon-danger" onClick={() => remove(i)}><Trash2 size={13} /></button></div>)}</div>
        <div className="command-actions"><button onClick={add}><Plus size={14} /> Add command</button><button className="primary" onClick={save} disabled={saving}>{saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Sync commands to Telegram</button></div>
      </article>
    </div>
  </section>;
}

function Dashboard() {
  const [dash, setDash] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [addons, setAddons] = useState([]);
  const [admin, setAdmin] = useState(null);
  const [selected, setSelected] = useState(null);
  const [manageView, setManageView] = useState('overview');
  const [form, setForm] = useState({ name: '', type: 'static_site', template_key: 'react-landing', repo_url: '', subdomain: '', build_command: 'auto', output_dir: 'auto' });
  const [status, setStatus] = useState('');

  async function load() {
    try { const t = await api('/api/templates'); setTemplates(t.items || []); } catch (_) {}
    try { const a = await api('/api/addons'); setAddons(a.items || []); } catch (_) {}
    try {
      const d = await api('/api/dashboard');
      setDash(d);
      if (selected) setSelected((d.projects || []).find(p => p.id === selected.id) || null);
      if (d.user?.is_admin) { try { setAdmin(await api('/api/admin/summary')); } catch (_) {} }
    } catch (err) {
      setStatus(initData ? 'Session error: ' + err.message : 'Login in browser or open from Telegram bot.');
    }
  }
  useEffect(() => { tg?.ready?.(); tg?.expand?.(); load(); }, []);

  function goCreate() {
    if (location.hash !== '#create') return;
    setSelected(null);
    setTimeout(() => document.getElementById('create')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80);
  }
  useEffect(() => { goCreate(); addEventListener('hashchange', goCreate); return () => removeEventListener('hashchange', goCreate); }, []);
  useEffect(() => { goCreate(); }, [dash]);

  async function createProject(e) {
    e.preventDefault();
    setStatus('Creating project…');
    try {
      await api('/api/projects', { method: 'POST', body: JSON.stringify(form) });
      const wasStatic = form.type === 'static_site';
      setForm({ ...form, name: '', repo_url: '', subdomain: '' });
      setStatus(wasStatic ? 'Static site created and published. Open the subdomain now.' : 'Project created with starter files. Open Manage, then Deploy/Start it.');
      await load();
    } catch (err) { setStatus(err.message); }
  }
  async function deleteProject(p) {
    if (!confirm(`Delete ${p.name}?`)) return;
    await api(`/api/projects/${p.id}/delete`, { method: 'POST', body: JSON.stringify({}) });
    if (selected?.id === p.id) setSelected(null);
    await load();
  }
  function logout() { localStorage.removeItem(tokenKey); location.reload(); }

  const user = dash?.user;
  const projects = dash?.projects || [];
  const activeTemplate = templates.find(t => t.key === form.template_key);

  return <main className="dashboard-page dashboard-polish">
    <NavBar
      links={[
        { label: 'Home', href: '/' },
        { label: 'Dashboard', href: '#dashboard' },
        { label: 'Create', href: '#create', cta: true },
        ...(user?.is_admin ? [{ label: 'Admin', href: '#admin' }] : []),
        { label: 'Telegram', href: 'https://t.me/VexHostBot', external: true },
      ]}
      actions={localStorage.getItem(tokenKey) ? [{ label: 'Log out', onClick: logout, variant: 'link' }] : []}
    />

    <section className="dashboard-hero">
      <p className="eyebrow reveal" style={{ '--i': 0 }}><Sparkles size={14} /> Dashboard</p>
      <h1 className="reveal" style={{ '--i': 1 }}>Control center for your apps.</h1>
      <p className="subtitle reveal" style={{ '--i': 2 }}>Fast polished dashboard: create projects, edit files, start containers, watch metrics and ship to *.vexory.xyz from browser or Telegram Mini App.</p>
      {status && <div className="notice">{status}</div>}
      {!dash && !initData && <Login onLogin={load} />}
      {user && <div className="stats reveal">
        <Stat value={user.login_username || ('@' + user.telegram_id)} label="browser login" />
        <Stat value={`${dash.limits.projects_used}/${dash.limits.projects_limit}`} label="projects" />
        <Stat value={user.is_admin ? 'admin' : 'user'} label="role" />
      </div>}
    </section>

    {dash && <section className="section dashboard-grid">
      {selected ? <ProjectSideNav project={selected} active={manageView} onChange={setManageView} onNew={() => { setSelected(null); setManageView('overview'); }} /> : <article className="panel create-panel" id="create">
        <h2>Create project</h2>
        <p>Choose runtime and subdomain. Static sites publish instantly; Node/Python servers run in Docker with live logs and metrics.</p>
        <form className="form" onSubmit={createProject}>
          <input placeholder="Project name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
          <input placeholder="subdomain, e.g. mybot" value={form.subdomain} onChange={e => setForm({ ...form, subdomain: e.target.value })} />
          <select value={form.type} onChange={e => setForm({ ...form, type: e.target.value })}>
            <option value="static_site">Static Website</option>
            <option value="node_app">Node.js App</option>
            <option value="python_app">Python App</option>
            <option value="api">Python API</option>
            <option value="telegram_bot">Telegram Bot</option>
            <option value="mini_app">Mini App / Node</option>
          </select>
          <select value={form.template_key} onChange={e => setForm({ ...form, template_key: e.target.value })}>
            {templates.map(t => <option key={t.key} value={t.key}>{t.name}</option>)}
          </select>
          <input placeholder="GitHub repo URL, optional" value={form.repo_url} onChange={e => setForm({ ...form, repo_url: e.target.value })} />
          <div className="upload-row"><input placeholder="Build command" value={form.build_command} onChange={e => setForm({ ...form, build_command: e.target.value })} /><input placeholder="Output dir" value={form.output_dir} onChange={e => setForm({ ...form, output_dir: e.target.value })} /></div>
          {activeTemplate && <p className="muted">Template: {activeTemplate.description}</p>}
          <button className="primary"><Plus size={15} /> Create live project</button>
        </form>
      </article>}

      <section className="projects-col">
        <div className="section-head"><div><p className="eyebrow">Projects</p><h2>Your servers and sites</h2></div><button onClick={load}><RefreshCw size={14} /> Refresh</button></div>
        <div className="project-list">
          {projects.map(p => <article className={`project-card ${selected?.id === p.id ? 'on' : ''}`} key={p.id}>
            <div><h3>{p.name}</h3><p>{p.type} · <a href={p.live_url || `https://${p.subdomain}.vexory.xyz/`} target="_blank" rel="noreferrer">{p.subdomain}.vexory.xyz</a></p></div>
            <span className={`badge badge-${p.status}`}>{p.status}</span>
            <div className="project-actions">
              <button className="primary manage-btn" onClick={() => { setSelected(p); setManageView('overview'); }}><Code2 size={14} /> Manage</button>
              <a className="button" href={p.live_url || `https://${p.subdomain}.vexory.xyz/`} target="_blank" rel="noreferrer"><Globe2 size={14} /> Open</a>
              <button className="danger" onClick={() => deleteProject(p)}><Trash2 size={14} /> Delete</button>
            </div>
          </article>)}
          {!projects.length && <article className="panel empty"><Server size={28} /><h3>No projects yet</h3><p>Create your first website, server or bot on the left.</p></article>}
        </div>
        {selected && <ProjectConsole project={selected} onChanged={load} activeView={manageView} setActiveView={setManageView} addons={addons} />}
      </section>
    </section>}

    {dash && !selected && <AddonsMarketplace items={addons} />}

    {admin && <section className="section admin-panel admin-teaser">
      <div className="section-head"><div><p className="eyebrow">Admin</p><h2>Platform overview</h2></div><a className="primary" href="#admin"><ShieldCheck size={14} /> Open admin dashboard</a></div>
      <div className="stats"><Stat value={admin.users} label="users" /><Stat value={admin.projects} label="projects" /><Stat value={admin.running_containers || 0} label="running" /></div>
    </section>}
  </main>;
}

function MiniStat({ icon, value, label, danger }) {
  return <div className={`admin-stat${danger ? ' danger' : ''}`}>{icon}<b>{value}</b><span>{label}</span></div>;
}
function flagClass(level) { return level === 'critical' ? 'critical' : level === 'high' ? 'high' : 'medium'; }
function AdminDashboard() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState('');
  async function load() {
    setStatus('');
    try { setData(await api('/api/admin/summary')); }
    catch (e) { setStatus(e.message); }
  }
  useEffect(() => { tg?.ready?.(); tg?.expand?.(); load(); const id = setInterval(load, 8000); return () => clearInterval(id); }, []);
  async function runAction(action, payload, label) {
    if (!confirm(`${label}? This is dangerous and will be sent with confirm=true.`)) return;
    setBusy(action);
    try {
      const r = await api('/api/admin/action', { method: 'POST', body: JSON.stringify({ action, confirm: true, ...payload }) });
      setStatus(r.new_password ? `Password reset: ${r.login_username} / ${r.new_password}` : `${label}: done`);
      await load();
    } catch (e) { setStatus(e.message); }
    setBusy('');
  }
  const projects = data?.recent_projects || [];
  const users = data?.recent_users || [];
  const flags = data?.abuse_flags || [];
  const queue = data?.queue || { queued: 0, processing: 0, failed: 0, items: [] };
  return <main className="dashboard-page admin-page">
    <NavBar
      brand="VexHost Admin"
      links={[
        { label: 'Dashboard', href: '#dashboard' },
        { label: 'Create', href: '#create', cta: true },
        { label: 'Admin', href: '#admin' },
        { label: 'Mini App', href: 'https://t.me/VexHostBot', external: true },
      ]}
      actions={[{ label: <>Refresh</>, onClick: load, variant: 'ghost', icon: <RefreshCw size={14} /> }]}
    />

    <section className="admin-hero">
      <p className="eyebrow reveal" style={{ '--i': 0 }}><ShieldCheck size={14} /> Admin dashboard</p>
      <h1 className="reveal" style={{ '--i': 1 }}>Operations, abuse and runtime control.</h1>
      <p className="subtitle reveal" style={{ '--i': 2 }}>Separate admin page for web and Telegram Mini App. Dangerous actions require <code>confirm=true</code> on the backend.</p>
      {status && <div className="notice">{status}</div>}
      <div className="admin-stats reveal">
        <MiniStat icon={<Users size={18} />} value={data?.users ?? '—'} label="Users" />
        <MiniStat icon={<Server size={18} />} value={data?.projects ?? '—'} label="Projects" />
        <MiniStat icon={<Activity size={18} />} value={data?.running_containers ?? '—'} label="Running containers" />
        <MiniStat icon={<Cpu size={18} />} value={`${data?.cpu_percent ?? 0}%`} label="CPU usage" />
        <MiniStat icon={<MemoryStick size={18} />} value={`${data?.ram_mb ?? 0} MB`} label="RAM usage" />
        <MiniStat icon={<HardDrive size={18} />} value={`${data?.disk_mb ?? 0} MB`} label="Disk usage" />
        <MiniStat icon={<AlertTriangle size={18} />} value={data?.errors ?? 0} label="Errors" danger={(data?.errors || 0) > 0} />
        <MiniStat icon={<Database size={18} />} value={data?.payments?.count ?? 0} label="Payments" />
      </div>
    </section>

    <section className="section admin-grid">
      <article className="panel admin-card wide">
        <div className="admin-card-head"><div><p className="eyebrow">Abuse detection</p><h2>Flags</h2></div><span className="badge">{flags.length} flags</span></div>
        <div className="flag-list">
          {flags.map((f, i) => <div className={`flag ${flagClass(f.level)}`} key={i}><AlertTriangle size={14} /><b>{f.label}</b><span>{f.project_name} · user #{f.user_id}</span></div>)}
          {!flags.length && <p className="muted">No active abuse flags. Checks: restarts, high CPU, mining keywords, port scanning/spam keywords, huge logs, suspicious packages.</p>}
        </div>
      </article>

      <article className="panel admin-card">
        <div className="admin-card-head"><div><p className="eyebrow">Queue system</p><h2>Build/start queue</h2></div></div>
        <div className="queue-row"><span>queued</span><b>{queue.queued}</b></div>
        <div className="queue-row"><span>processing</span><b>{queue.processing}</b></div>
        <div className="queue-row"><span>failed</span><b>{queue.failed}</b></div>
        <p className="muted">Build and runtime start/restart jobs use queued → processing → success/failed so API requests return quickly.</p>
      </article>

      <article className="panel admin-card wide">
        <div className="admin-card-head"><div><p className="eyebrow">Projects</p><h2>Kill / suspend / files</h2></div></div>
        <div className="admin-table">
          {projects.map(p => <div className="admin-row" key={p.id}>
            <div><b>{p.name}</b><span>#{p.id} · user #{p.user_id} · {p.type} · {p.status}</span><small>{p.subdomain}.vexory.xyz · CPU {p.runtime?.cpu_percent || 0}% · RAM {p.runtime?.mem_used_mb || 0} MB · Disk {p.runtime?.disk_mb || 0} MB</small></div>
            <div className="admin-actions">
              <button onClick={() => runAction('stop_project', { project_id: p.id }, 'Stop project')} disabled={busy}>Stop project</button>
              <button onClick={() => runAction('delete_runtime', { project_id: p.id }, 'Delete runtime')} disabled={busy}>Delete runtime</button>
              <button className="danger" onClick={() => runAction('delete_files', { project_id: p.id }, 'Delete files')} disabled={busy}>Delete files</button>
              <button className="danger" onClick={() => runAction('delete_project', { project_id: p.id }, 'Delete project')} disabled={busy}>Delete project</button>
            </div>
          </div>)}
        </div>
      </article>

      <article className="panel admin-card wide">
        <div className="admin-card-head"><div><p className="eyebrow">Users</p><h2>Accounts</h2></div></div>
        <div className="admin-table users-table">
          {users.map(u => <div className="admin-row" key={u.id}>
            <div><b>@{u.username || u.login_username || u.telegram_id}</b><span>#{u.id} · tg {u.telegram_id} · {u.plan} {u.is_admin ? '· admin' : ''} {u.is_suspended ? '· suspended' : ''}</span></div>
            <div className="admin-actions">
              <button onClick={() => runAction('reset_password', { user_id: u.id }, 'Reset password')} disabled={busy}><KeyRound size={13} /> Reset password</button>
              <button onClick={() => runAction('give_pro', { user_id: u.id }, 'Give Pro')} disabled={busy}><Sparkles size={13} /> Give Pro</button>
              <button className="danger" onClick={() => runAction('suspend_user', { user_id: u.id }, 'Suspend user')} disabled={busy}><Ban size={13} /> Suspend user</button>
            </div>
          </div>)}
        </div>
      </article>
    </section>
  </main>;
}
const DEPLOY_LINES = [
  { t: 'cmd', text: '~ vexhost deploy' },
  { t: 'tg', text: '● Command from Telegram   @you → /deploy my-site' },
  { t: 'dim', text: '→ git push vexhost main' },
  { t: 'row', text: '  Building project', ok: '✓ 3.1s' },
  { t: 'row', text: '  Publishing to edge', ok: '✓ 0.8s' },
  { t: 'row', text: '  Assigning subdomain', ok: '✓' },
  { t: 'live', text: '● Live', url: 'my-site.vexory.xyz' },
];

function DeployConsole() {
  const reduce = useMemo(() => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches, []);
  const [shown, setShown] = useState(reduce ? DEPLOY_LINES.length : 0);
  useEffect(() => {
    if (reduce || shown >= DEPLOY_LINES.length) return;
    const delay = shown === 0 ? 400 : DEPLOY_LINES[shown - 1].t === 'row' ? 520 : 380;
    const id = setTimeout(() => setShown(s => s + 1), delay);
    return () => clearTimeout(id);
  }, [shown, reduce]);
  const done = shown >= DEPLOY_LINES.length;
  return (
    <div className="console-shell">
      <div className="console-glow" aria-hidden="true" />
      <div className="console" role="img" aria-label="Example of deploying a project from Telegram: build, publish and go live on a subdomain.">
        <div className="console-bar">
          <div className="console-dots"><i /><i /><i /></div>
          <span className="console-title">vexhost — deploy</span>
        </div>
        <div className="console-body">
          {DEPLOY_LINES.slice(0, shown).map((l, i) => {
            if (l.t === 'row') return <div className="cl line-in" key={i}><span className="lbl cl-dim">{l.text}</span><span className="cl-ok">{l.ok}</span></div>;
            if (l.t === 'live') return <div className="cl-live line-in" key={i}><span className="dot" /><span>{l.text}</span><a href={`https://${l.url}`} target="_blank" rel="noreferrer">https://{l.url}</a></div>;
            if (l.t === 'cmd') return <div className={`cl-cmd line-in`} key={i}><span className="p">$</span> vexhost deploy</div>;
            return <div className={`line-in cl-${l.t}`} key={i}>{l.text}</div>;
          })}
          {!done && <span className="cursor" aria-hidden="true" />}
        </div>
      </div>
    </div>
  );
}

function Footer() {
  const cols = [
    ['Product', [['Features', '#features'], ['Telegram bot', 'https://t.me/VexHostBot'], ['Pricing', '#pricing'], ['Dashboard', '#dashboard']]],
    ['Resources', [['Docs', '#'], ['Status', '#'], ['Templates', '#'], ['API', '#']]],
    ['Company', [['About', '#'], ['Blog', '#'], ['Contact', 'https://t.me/VexHostBot']]],
  ];
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div>
          <a className="brand" href="/"><span>V</span> VexHost</a>
          <p className="footer-tag">Free hosting for websites, servers and Telegram bots. Deploy from chat in a single command.</p>
        </div>
        {cols.map(([title, links]) => (
          <div className="footer-col" key={title}>
            <h4>{title}</h4>
            {links.map(([label, href]) => <a href={href} key={label}>{label}</a>)}
          </div>
        ))}
      </div>
      <div className="footer-bar">
        <span>© 2026 VexHost</span>
        <span>Built for people who live in Telegram</span>
      </div>
    </footer>
  );
}

const SHIP_STEPS = [
  ['01', 'Message the bot', 'Send /new to @VexHostBot and pick a runtime. You get a project and access in seconds.', '/new my-site'],
  ['02', 'Build in a container', 'We install, build and boot your app inside an isolated Docker container — live logs the whole way.', 'docker run'],
  ['03', 'Live on a subdomain', 'Health check passes and your project is served at name.vexory.xyz, ready to share.', 'name.vexory.xyz'],
];

function Landing() {
  const features = [
    ['File manager', 'Upload files, create folders and edit code right in the browser.', FileText, false],
    ['Instant publishing', 'Change index.html and your static site ships to prod — no ZIP, no wait.', Globe2, false],
    ['Subdomains', 'Every project gets its own address at example.vexory.xyz.', Rocket, false],
    ['Console & logs', 'Start, stop, restart, live logs and commands inside the container.', Terminal, false],
    ['Metrics & monitoring', 'Live CPU, RAM, disk, requests and uptime for every running container.', Activity, false],
    ['Auto-restart', 'If a container crashes, VexHost restarts it and shows the crash reason.', RotateCw, false],
  ];
  return (
    <main>
      <NavBar
        links={[
          { label: 'Features', href: '#features' },
          { label: 'Telegram', href: '#telegram' },
          { label: 'Pricing', href: '#pricing' },
          { label: 'Dashboard', href: '#dashboard' },
          { label: 'Create', href: '#create', cta: true },
        ]}
        actions={[
          { label: 'Log in', href: '#dashboard', variant: 'link' },
          { label: <>Get started <ArrowRight size={16} /></>, href: '#dashboard', variant: 'primary' },
        ]}
      />

      <section className="hero">
        <p className="eyebrow reveal" style={{ '--i': 0 }}><Zap size={14} /> Free hosting · managed from Telegram</p>
        <h1 className="display reveal" style={{ '--i': 1 }}>Hosting for websites, servers<br /><span className="muted-word">and Telegram bots.</span></h1>
        <p className="lead reveal" style={{ '--i': 2 }}>Free. Deploy static sites, Node, Python and APIs in isolated containers — from a Telegram bot or your browser.</p>
        <div className="hero-actions reveal" style={{ '--i': 3 }}>
          <a className="primary btn-lg" href="#dashboard">Start for free <ArrowRight size={16} /></a>
          <a className="btn-tg btn-lg" href="https://t.me/VexHostBot"><Send size={16} /> Open in Telegram</a>
        </div>
        <div className="reveal" style={{ '--i': 4 }}><DeployConsole /></div>
      </section>

      <div className="trust">
        <div className="trust-inner">
          <span className="trust-label">Runs on</span>
          {['Docker', 'Nginx', 'FastAPI', 'aiogram', 'Node.js'].map(t => <span className="trust-item" key={t}>{t}</span>)}
        </div>
      </div>

      <section className="ship" id="how">
        <div className="section-head">
          <p className="eyebrow reveal">How it works</p>
          <h2 className="title reveal">From chat to production in three steps.</h2>
        </div>
        <div className="ship-rail">
          {SHIP_STEPS.map(([no, t, d, code], i) => (
            <div className="ship-step reveal" style={{ '--i': i }} key={no}>
              <span className="no">{no}</span>
              <h3>{t}</h3>
              <p>{d}</p>
              <p style={{ marginTop: '12px' }}><code>{code}</code></p>
            </div>
          ))}
        </div>
      </section>

      <section className="section" id="features">
        <div className="section-head">
          <p className="eyebrow reveal">Features</p>
          <h2 className="title reveal">Real hosting, not just ZIP uploads.</h2>
        </div>
        <div className="bento">
          <article className="card feat-lg reveal">
            <div className="card-copy">
              <div className="card-head"><div className="ico"><Server size={20} /></div><span className="kbd">docker</span></div>
              <h3>Real Docker runtimes</h3>
              <p>Node.js, Python, APIs and bots each run in their own isolated container — with CPU, RAM and disk you can actually watch, restart and scale.</p>
            </div>
            <div className="containers" role="img" aria-label="Three running containers: an API, a Telegram bot and a web app, each live with response time and memory usage.">
              <div className="crow"><span className="cdot" /><span className="cname">api · fastapi</span><span className="cmeta">42 ms · 128 MB</span><span className="cbar"><i /></span></div>
              <div className="crow"><span className="cdot" /><span className="cname">bot · aiogram</span><span className="cmeta">polling · 74 MB</span><span className="cbar"><i /></span></div>
              <div className="crow"><span className="cdot" /><span className="cname">web · node</span><span className="cmeta">28 ms · 96 MB</span><span className="cbar"><i /></span></div>
            </div>
          </article>
          {features.map(([t, d, I], i) => (
            <article className="card reveal" style={{ '--i': (i % 3) }} key={t}>
              <div className="ico"><I size={20} /></div>
              <h3>{t}</h3>
              <p>{d}</p>
            </article>
          ))}
          <article className="card feat-wide is-tg reveal">
            <div className="card-head"><div className="ico"><Bot size={20} /></div><span className="kbd">telegram + browser</span></div>
            <h3>Manage from wherever you are</h3>
            <p>The bot hands you access and pings you on every deploy; the dashboard gives you the full file manager, console and metrics. Same account, two front doors.</p>
          </article>
        </div>
      </section>

      <div className="section-tint" id="telegram">
        <section className="section">
          <div className="tg-split">
            <div className="tg-copy reveal">
              <p className="eyebrow"><Send size={14} /> Telegram-first</p>
              <h2 className="title">Manage your hosting right in the chat.</h2>
              <ul className="tg-list">
                <li><Check className="tick" size={18} /> Create projects and get access with a single command.</li>
                <li><Check className="tick" size={18} /> Deploy, restart and read logs without leaving Telegram.</li>
                <li><Check className="tick" size={18} /> Build and status notifications land in your chat.</li>
              </ul>
              <a className="btn-tg" href="https://t.me/VexHostBot"><Send size={16} /> Open @VexHostBot</a>
            </div>
            <div className="chat reveal" style={{ '--i': 1 }}>
              <div className="chat-head">
                <div className="chat-avatar"><Bot size={20} /></div>
                <div><b>VexHost Bot</b><span>@VexHostBot</span></div>
              </div>
              <div className="chat-log">
                <div className="bubble me"><span className="mono">/new my-site</span></div>
                <div className="bubble bot"><span className="l">Done. Project <b>my-site</b> created.</span><span className="l">Type: static site</span></div>
                <div className="bubble me"><span className="mono">/deploy</span></div>
                <div className="bubble bot"><span className="l">Building and publishing…</span><span className="l">✓ Live: <span className="url">my-site.vexory.xyz</span></span></div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <section className="section" id="pricing">
        <div className="section-head center">
          <p className="eyebrow reveal">Pricing</p>
          <h2 className="title reveal">Simply free.</h2>
          <p className="lead reveal">No card, no hidden limits to start. Deploy your first project right now.</p>
        </div>
        <div className="price-wrap">
          <div className="price reveal">
            <span className="plan">Starter</span>
            <div className="amount"><b>$0</b><span>/ forever</span></div>
            <p className="note">Everything you need to launch a site, API or bot.</p>
            <ul>
              <li><Check size={18} /> Up to 3 active projects</li>
              <li><Check size={18} /> Docker runtimes: Node, Python, API</li>
              <li><Check size={18} /> Subdomains on *.vexory.xyz</li>
              <li><Check size={18} /> File manager and code editor</li>
              <li><Check size={18} /> Console, logs and restarts</li>
              <li><Check size={18} /> Manage from Telegram and browser</li>
            </ul>
            <a className="primary" href="#dashboard">Start for free <ArrowRight size={16} /></a>
          </div>
        </div>
      </section>

      <div className="cta-band">
        <div className="wrap reveal">
          <h2>Deploy your first project in a minute.</h2>
          <p>Open the dashboard or message the bot — access is granted instantly.</p>
          <div className="hero-actions">
            <a className="primary btn-lg" href="#dashboard">Open dashboard <ArrowRight size={16} /></a>
            <a className="secondary btn-lg" href="https://t.me/VexHostBot"><Send size={16} /> Open in Telegram</a>
          </div>
        </div>
      </div>

      <Footer />
    </main>
  );
}
function App() {
  const readRoute = () => ({ hash: location.hash, view: new URLSearchParams(location.search).get('view'), path: location.pathname });
  const [route, setRoute] = useState(readRoute);
  useEffect(() => {
    const f = () => setRoute(readRoute());
    addEventListener('hashchange', f);
    addEventListener('popstate', f);
    return () => { removeEventListener('hashchange', f); removeEventListener('popstate', f); };
  }, []);
  useReveal();
  const hasSession = Boolean(initData || localStorage.getItem(tokenKey));
  if (route.hash === '#admin' || route.view === 'admin' || route.path === '/admin') return <AdminDashboard />;
  if (route.hash === '#dashboard' || route.hash === '#create' || route.view === 'dashboard' || route.path === '/dashboard' || hasSession) return <Dashboard />;
  return <Landing />;
}
createRoot(document.getElementById('root')).render(<App />);
