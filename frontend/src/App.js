import { useEffect, useState, useCallback } from 'react';
import { BrowserRouter, Routes, Route, Link, useNavigate, useParams, Navigate } from 'react-router-dom';
import axios from 'axios';
import {
  ArrowRight, ArrowLeft, Check, ChevronRight, Download, Gauge, Lightbulb, LockKeyhole,
  Sparkles, ShieldCheck, BookOpen, Upload, FileText, Loader2, X, Plus, AlertTriangle,
  ExternalLink, ClipboardList, Zap, Link2,
} from 'lucide-react';
import { toast, Toaster } from 'sonner';
import './App.css';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const api = axios.create({ baseURL: API, withCredentials: true });

// Providers users can "connect" — paste-based today, OAuth on roadmap
const PROVIDERS = [
  { id: 'klaviyo',   name: 'Klaviyo',   hint: 'Paste an email preview HTML' },
  { id: 'mailchimp', name: 'Mailchimp', hint: 'Paste from campaign preview' },
  { id: 'figma',     name: 'Figma',     hint: 'Right-click frame → Copy as HTML' },
  { id: 'hubspot',   name: 'HubSpot',   hint: 'Paste from email preview' },
  { id: 'iterable',  name: 'Iterable',  hint: 'Paste HTML export' },
];

// ------------------------------------------------------------------ Landing
function Landing() {
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState([]);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    api.post('/session').then(r => setOrgs(r.data.organizations || [])).finally(() => setReady(true));
  }, []);
  const incomplete = orgs.find(o => !o.onboarding_complete);
  const complete = orgs.filter(o => o.onboarding_complete);
  return (
    <div className="landing">
      <div className="landing-art" />
      <div className="landing-copy">
        <div className="brand-mark dark">
          <span>BM</span>
          <div><b>Brand Memory</b><small>OS</small></div>
        </div>
        <h1>Every send<br/>inherits your best work.</h1>
        <p>Feed it your past emails. Every future brief pulls back grounded direction, cited to real campaigns, checked against your rules.</p>
        <div className="landing-actions">
          <button className="primary large" data-testid="cta-create-workspace" onClick={() => navigate('/onboarding')}>
            Create workspace <ArrowRight size={18} />
          </button>
          <button className="ghost large" data-testid="cta-view-demo" onClick={() => navigate('/demo')}>
            Try the demo <ExternalLink size={16} />
          </button>
        </div>
        {ready && incomplete && (
          <button className="link resume" data-testid="cta-continue-setup"
                  onClick={() => navigate(`/onboarding?org=${incomplete.id}`)}>
            Continue setup — {incomplete.name} <ChevronRight size={14} />
          </button>
        )}
        {ready && complete.length > 0 && (
          <div className="landing-existing">
            <small>OPEN A WORKSPACE</small>
            {complete.slice(0, 4).map(o => <ExistingOrgLink key={o.id} org={o} />)}
          </div>
        )}
      </div>
    </div>
  );
}

function ExistingOrgLink({ org }) {
  const navigate = useNavigate();
  const last = localStorage.getItem(`bmos:last-brand:${org.id}`);
  return (
    <button className="existing-org" data-testid={`open-org-${org.id}`}
            onClick={() => last ? navigate(`/app/${org.id}/${last}/dashboard`) : navigate(`/onboarding?org=${org.id}`)}>
      <span>{org.name}</span>
      <ChevronRight size={14} />
    </button>
  );
}

// ------------------------------------------------------------------ Onboarding (simplified to 3 steps)
const STEPS = [
  { k: 'workspace', title: 'Workspace', hint: 'Name & brand' },
  { k: 'rules',     title: 'Rules',     hint: 'What must never appear' },
  { k: 'memory',    title: 'Memory',    hint: 'Add past emails' },
];

function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [orgId, setOrgId] = useState('');
  const [brandId, setBrandId] = useState('');
  const [form, setForm] = useState({
    orgName: '', orgType: 'brand', brandName: '', brandUrl: '',
  });
  const [rules, setRules] = useState({
    tone: ['warm', 'specific'],
    prohibited_claims: [],
    approved_claims: [], colors: [], layout_rules: [], cta_style: '',
  });
  const [busy, setBusy] = useState(false);

  const submitWorkspace = async () => {
    if (!form.orgName.trim() || !form.brandName.trim()) {
      toast.error('Give both a workspace and brand name'); return;
    }
    setBusy(true);
    try {
      const o = await api.post('/organizations', {
        name: form.orgName, type: form.orgType, role: '', managed_brands: 1, industry: '',
      });
      setOrgId(o.data.id);
      const b = await api.post(`/organizations/${o.data.id}/brands`, {
        name: form.brandName, url: form.brandUrl, industry: '', market: '',
      });
      setBrandId(b.data.id);
      localStorage.setItem(`bmos:last-brand:${o.data.id}`, b.data.id);
      await api.patch(`/organizations/${o.data.id}/onboarding`, { step: 2, complete: false });
      setStep(2);
    } catch (_e) { toast.error('Could not create workspace'); }
    finally { setBusy(false); }
  };

  const submitRules = async () => {
    setBusy(true);
    try {
      await api.patch(`/brands/${brandId}/guidelines`, rules);
      await api.patch(`/organizations/${orgId}/onboarding`, { step: 3, complete: false });
      setStep(3);
    } catch (_e) { toast.error('Could not save rules'); }
    finally { setBusy(false); }
  };

  const finish = async () => {
    setBusy(true);
    try {
      await api.patch(`/organizations/${orgId}/onboarding`, { step: 3, complete: true });
      navigate(`/app/${orgId}/${brandId}/dashboard`);
    } finally { setBusy(false); }
  };

  return (
    <div className="onboarding">
      <header className="onb-head">
        <div className="brand-mark small"><span>BM</span><b>Brand Memory</b></div>
        <div className="onb-steps">
          {STEPS.map((s, i) => (
            <div key={s.k} className={`onb-step ${step > i + 1 ? 'done' : step === i + 1 ? 'active' : ''}`} data-testid={`onb-step-${s.k}`}>
              <span>{step > i + 1 ? <Check size={12} /> : i + 1}</span>
              <div><b>{s.title}</b><small>{s.hint}</small></div>
            </div>
          ))}
        </div>
        <button className="link exit-onb" data-testid="onb-exit" onClick={() => navigate('/')}>Exit</button>
      </header>
      <main className="onb-body">
        {step === 1 && (
          <StepShell title="Name your workspace." sub="One workspace holds one brand's private memory. Agencies can add more brands later.">
            <label>Workspace / organization<input data-testid="onb-org-name" value={form.orgName} onChange={e => setForm({ ...form, orgName: e.target.value })} placeholder="Alpine Studio" autoFocus /></label>
            <div className="row">
              <label>Type
                <select data-testid="onb-org-type" value={form.orgType} onChange={e => setForm({ ...form, orgType: e.target.value })}>
                  <option value="brand">In-house brand</option>
                  <option value="agency">Agency</option>
                  <option value="in-house">In-house team</option>
                </select>
              </label>
              <label>Brand name<input data-testid="onb-brand-name" value={form.brandName} onChange={e => setForm({ ...form, brandName: e.target.value })} placeholder="Alpine Kettle Co." /></label>
            </div>
            <label>Brand website <small>optional</small><input data-testid="onb-brand-url" value={form.brandUrl} onChange={e => setForm({ ...form, brandUrl: e.target.value })} placeholder="https://alpinekettle.com" /></label>
            <div className="onb-actions">
              <button className="ghost" onClick={() => navigate('/')} data-testid="onb-back-1"><ArrowLeft size={16} /> Back</button>
              <button className="primary" data-testid="onb-continue-1" onClick={submitWorkspace} disabled={busy}>{busy ? 'Saving…' : 'Continue'} <ArrowRight size={16} /></button>
            </div>
          </StepShell>
        )}
        {step === 2 && (
          <StepShell title="What must the memory never say?" sub="These are the hard rules. If a recommendation hits one, export is blocked with a clear reason. Add tone words if you want — they help the AI stay on brand.">
            <ChipsField testid="onb-tone" label="Voice & tone" items={rules.tone} onChange={v => setRules({ ...rules, tone: v })} placeholder="warm, quietly confident…" />
            <ChipsField testid="onb-prohibited" label="Prohibited claims (the hard rules)" danger items={rules.prohibited_claims} onChange={v => setRules({ ...rules, prohibited_claims: v })} placeholder="detox, cures anxiety, free forever…" />
            <p className="micro-note"><ShieldCheck size={13} /> These check every recommendation and blueprint. Deterministic — not left to the AI.</p>
            <div className="onb-actions">
              <button className="ghost" onClick={() => setStep(1)} data-testid="onb-back-2"><ArrowLeft size={16} /> Back</button>
              <button className="primary" data-testid="onb-continue-2" onClick={submitRules} disabled={busy}>{busy ? 'Saving…' : 'Continue'} <ArrowRight size={16} /></button>
            </div>
          </StepShell>
        )}
        {step === 3 && (
          <StepShell title="Add some memory (or skip)." sub="You can also do this later. GPT-5.4 extracts structure; the embedder makes it searchable.">
            <div className="memory-add">
              <UploadBox brandId={brandId} inline onDone={() => toast.success('Uploaded — analysis running')} />
              <div className="or">or</div>
              <ConnectSourcesRow brandId={brandId} onDone={() => toast.success('Pasted — analysis running')} />
            </div>
            <div className="onb-actions">
              <button className="ghost" onClick={() => setStep(2)} data-testid="onb-back-3"><ArrowLeft size={16} /> Back</button>
              <button className="primary" data-testid="onb-finish" onClick={finish} disabled={busy}>{busy ? 'Opening…' : 'Open workspace'} <ArrowRight size={16} /></button>
            </div>
          </StepShell>
        )}
      </main>
    </div>
  );
}

function StepShell({ title, sub, children }) {
  return (
    <div className="step-shell">
      <h1>{title}</h1>
      <p className="step-sub">{sub}</p>
      <div className="step-form">{children}</div>
    </div>
  );
}

function ChipsField({ label, placeholder, items, onChange, danger, testid }) {
  const [v, setV] = useState('');
  const add = () => { if (v.trim()) { onChange([...items, v.trim()]); setV(''); } };
  return (
    <div className="chips-field">
      <label>{label}</label>
      <div className={`chips ${danger ? 'danger' : ''}`}>
        {items.map((x, i) => (
          <span key={i} data-testid={`${testid}-chip-${i}`}>{x}<button onClick={() => onChange(items.filter((_, j) => j !== i))}><X size={12} /></button></span>
        ))}
      </div>
      <div className="chip-input">
        <input data-testid={`${testid}-input`} value={v} onChange={e => setV(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} placeholder={placeholder} />
        <button className="ghost tiny" data-testid={`${testid}-add`} onClick={add}><Plus size={13} /> Add</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Upload box
function UploadBox({ brandId, onDone, inline }) {
  const [name, setName] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!name.trim() || !file) { toast.error('Give it a name and pick a file'); return; }
    const fd = new FormData();
    fd.append('name', name); fd.append('file', file);
    setBusy(true);
    try {
      await api.post(`/brands/${brandId}/campaigns/upload`, fd, { headers: { 'Content-Type': 'multipart/form-data' } });
      setName(''); setFile(null); onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Upload failed');
    } finally { setBusy(false); }
  };
  return (
    <div className={`upload-box ${inline ? 'inline' : ''}`}>
      <div className="upload-head">
        <Upload size={16} />
        <div><b>Upload a past email</b><small>HTML, PDF, PNG, JPG · under 10 MB</small></div>
      </div>
      <div className="upload-row">
        <input data-testid="upload-name" placeholder="Campaign name" value={name} onChange={e => setName(e.target.value)} />
        <label className="file-picker" data-testid="upload-file-label">
          <FileText size={13} /> {file ? file.name.slice(0, 22) : 'Choose file'}
          <input type="file" data-testid="upload-file" accept=".html,.htm,.pdf,.png,.jpg,.jpeg" onChange={e => setFile(e.target.files?.[0] || null)} hidden />
        </label>
        <button className="primary" data-testid="upload-submit" onClick={submit} disabled={busy}>{busy ? 'Uploading…' : 'Add'} <ArrowRight size={13} /></button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Connect sources
function ConnectSourcesRow({ brandId, onDone }) {
  const [openId, setOpenId] = useState(null);
  const opened = PROVIDERS.find(p => p.id === openId);
  return (
    <div className="connect-row">
      <div className="upload-head">
        <Link2 size={16} />
        <div><b>Connect from your tools</b><small>Paste HTML from any email or design tool</small></div>
      </div>
      <div className="provider-tiles">
        {PROVIDERS.map(p => (
          <button key={p.id} className="provider-tile" data-testid={`provider-${p.id}`} onClick={() => setOpenId(p.id)}>
            <span className="tile-logo">{p.name[0]}</span>
            <b>{p.name}</b>
            <small>{p.hint}</small>
          </button>
        ))}
      </div>
      {opened && <PasteModal brandId={brandId} provider={opened} onClose={() => setOpenId(null)} onDone={() => { setOpenId(null); onDone(); }} />}
    </div>
  );
}

function PasteModal({ brandId, provider, onClose, onDone }) {
  const [name, setName] = useState('');
  const [html, setHtml] = useState('');
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!name.trim() || !html.trim()) { toast.error('Name it and paste some HTML'); return; }
    setBusy(true);
    try {
      await api.post(`/brands/${brandId}/campaigns/paste`, { name, source: provider.id, html });
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not add');
    } finally { setBusy(false); }
  };
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} data-testid={`paste-modal-${provider.id}`}>
        <div className="modal-head">
          <div><b>Connect from {provider.name}</b><small>{provider.hint}</small></div>
          <button onClick={onClose} data-testid="paste-close"><X size={16} /></button>
        </div>
        <label>Campaign name<input data-testid="paste-name" value={name} onChange={e => setName(e.target.value)} placeholder={`${provider.name} — winter launch`} autoFocus /></label>
        <label>Paste email HTML
          <textarea data-testid="paste-html" value={html} onChange={e => setHtml(e.target.value)} rows={8} placeholder="<html>…paste from your tool…</html>" />
        </label>
        <div className="modal-foot">
          <small className="soon">OAuth sync from {provider.name} · on the roadmap</small>
          <button className="primary" data-testid="paste-submit" onClick={submit} disabled={busy}>{busy ? 'Adding…' : 'Add to memory'} <ArrowRight size={13} /></button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Workspace shell
function Shell({ children, active, brand, org, isDemo }) {
  const { orgId, brandId } = useParams();
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark"><span>BM</span><div><b>Brand Memory</b><small>OS</small></div></div>
        <div className="workspace-switch" data-testid="sidebar-brand">
          <span className="avatar">{brand?.name?.[0] || 'B'}</span>
          <div>
            <small>{org?.name || 'Loading'}</small>
            <strong>{brand?.name || '…'}</strong>
          </div>
          {isDemo && <span className="sample-badge" data-testid="sample-badge">SAMPLE</span>}
        </div>
        <nav>
          <button className={active === 'dashboard' ? 'active' : ''} data-testid="nav-dashboard" onClick={() => navigate(`/app/${orgId}/${brandId}/dashboard`)}><Sparkles size={16} /> Dashboard</button>
          <button className={active === 'campaigns' ? 'active' : ''} data-testid="nav-campaigns" onClick={() => navigate(`/app/${orgId}/${brandId}/campaigns`)}><BookOpen size={16} /> Memory</button>
          <button className={active === 'brief' ? 'active' : ''} data-testid="nav-brief" onClick={() => navigate(`/app/${orgId}/${brandId}/briefs/new`)}><ClipboardList size={16} /> New brief</button>
          <button className={active === 'guidelines' ? 'active' : ''} data-testid="nav-guidelines" onClick={() => navigate(`/app/${orgId}/${brandId}/guidelines`)}><ShieldCheck size={16} /> Rules</button>
        </nav>
        <div className="sidebar-foot">
          <div className="privacy"><LockKeyhole size={13} /><span>Private<br /><b>Only this brand</b></span></div>
          <button className="link exit" data-testid="exit-workspace" onClick={() => navigate('/')}>Exit workspace</button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

// ------------------------------------------------------------------ Dashboard
function Dashboard() {
  const { orgId, brandId } = useParams();
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    api.get(`/brands/${brandId}/dashboard`).then(r => setD(r.data)).catch(e => setErr(e.response?.status || 'error'));
  }, [brandId]);
  if (err === 403) return <Blocked />;
  if (!d) return <FullLoader />;
  const isDemo = d.brand.name?.includes('Northstar');
  const ready = d.readiness;
  return (
    <Shell active="dashboard" brand={d.brand} org={d.brand} isDemo={isDemo}>
      <Header eyebrow="DASHBOARD" title={d.brand.name} isDemo={isDemo} />
      <p className="page-sub">Everything the memory currently knows about {d.brand.name}.</p>
      <section className="readiness">
        <ReadinessCard icon={<BookOpen size={16} />} label="Emails in memory" value={ready.analyzed} testid="ready-analyzed" />
        <ReadinessCard icon={<Loader2 size={16} />} label="Processing now" value={ready.processing} testid="ready-processing" />
        <ReadinessCard icon={<ShieldCheck size={16} />} label="Brand rules" value={ready.guidelines_set ? 'Set' : 'Not yet'} testid="ready-guidelines" />
        <ReadinessCard icon={<Gauge size={16} />} label="Outcomes recorded" value={ready.outcomes_attached} testid="ready-outcomes" />
      </section>
      <div className="dash-actions">
        <Link className="primary" data-testid="dash-cta-brief" to={`/app/${orgId}/${brandId}/briefs/new`}><Zap size={14} /> Create a brief</Link>
        <Link className="ghost light" data-testid="dash-cta-upload" to={`/app/${orgId}/${brandId}/campaigns`}><Plus size={14} /> Add campaigns</Link>
      </div>
      <section className="section">
        <h2>Recent memory</h2>
        <div className="library-grid">
          {d.recent_campaigns.length === 0 && <EmptyPanel title="Nothing here yet" body="Add a couple of past emails to give the memory something to remember." />}
          {d.recent_campaigns.map(c => <CampaignCard key={c.id} c={c} />)}
        </div>
      </section>
      {d.latest_recommendation && (
        <section className="section">
          <h2>Latest recommendation</h2>
          <MiniRec rec={d.latest_recommendation} orgId={orgId} brandId={brandId} />
        </section>
      )}
    </Shell>
  );
}

function ReadinessCard({ icon, label, value, testid }) {
  return <div className="readiness-card" data-testid={testid}><span className="ri">{icon}</span><small>{label}</small><b>{value}</b></div>;
}

function MiniRec({ rec, orgId, brandId }) {
  const strengthLabel = rec.evidence_strength === 'strong' ? 'Strong match'
    : rec.evidence_strength === 'moderate' ? 'Moderate match' : 'Needs more evidence';
  return (
    <div className="mini-rec">
      <div>
        <span className={`tag ${rec.evidence_strength}`}>{strengthLabel}</span>
        <p>{rec.source_campaign_ids.length} campaign(s) cited · rules v{rec.guideline_version} · {rec.rule_violations.length ? 'BLOCKED by rule' : 'passes rules'}</p>
      </div>
      <Link className="ghost" to={`/app/${orgId}/${brandId}/recommendations/${rec.id}`} data-testid="mini-rec-open">Open <ArrowRight size={13} /></Link>
    </div>
  );
}

// ------------------------------------------------------------------ Campaigns
function Campaigns() {
  const { brandId } = useParams();
  const [list, setList] = useState([]);
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const reload = useCallback(() => {
    api.get(`/brands/${brandId}/dashboard`).then(r => setD(r.data)).catch(e => setErr(e.response?.status));
    api.get(`/brands/${brandId}/campaigns`).then(r => setList(r.data));
  }, [brandId]);
  useEffect(() => { reload(); const id = setInterval(reload, 3500); return () => clearInterval(id); }, [reload]);
  if (err === 403) return <Blocked />;
  if (!d) return <FullLoader />;
  const isDemo = d.brand.name?.includes('Northstar');
  return (
    <Shell active="campaigns" brand={d.brand} org={d.brand} isDemo={isDemo}>
      <Header eyebrow="MEMORY" title="Past work, kept in context." isDemo={isDemo} />
      <p className="page-sub">Every email keeps its objective, audience, and outcome attached. That&apos;s what makes recommendations trustworthy.</p>
      <div className="add-sources">
        <UploadBox brandId={brandId} onDone={reload} />
        <ConnectSourcesRow brandId={brandId} onDone={reload} />
      </div>
      <section className="library-grid">
        {list.length === 0 && <EmptyPanel title="No campaigns yet" body="Upload an email or paste one from your tool — the AI extracts structure and the memory becomes searchable." />}
        {list.map(c => <CampaignCard key={c.id} c={c} withOutcome onOutcome={reload} />)}
      </section>
    </Shell>
  );
}

function CampaignCard({ c, withOutcome, onOutcome }) {
  const [showOc, setShowOc] = useState(false);
  const sourceLabel = c.source_type === 'seed' ? 'SAMPLE'
    : ['klaviyo','mailchimp','figma','hubspot','iterable','paste'].includes(c.source_type) ? c.source_type.toUpperCase()
    : (c.source_type || 'file').toUpperCase();
  return (
    <article className="library-card" data-testid={`campaign-card-${c.id}`}>
      <div className="library-art" style={{ background: c.is_sample ? '#D9E8D8' : '#EEE9DF' }}>
        <span>{c.status === 'processing' ? 'Analyzing…' : c.status === 'failed' ? 'Failed' : sourceLabel}</span>
        <b>{c.subject || c.name}</b>
      </div>
      <div className="library-card-body">
        <span className="mini-label">{c.objective || 'objective TBD'} · {c.audience || 'audience TBD'}</span>
        <h3>{c.name}</h3>
        <p>{(c.extracted?.summary || '').slice(0, 150) || (c.status === 'processing' ? 'Extraction running — takes a few seconds.' : 'No summary yet.')}</p>
        <div className="metrics">
          {c.metrics?.open ? <>
            <b>{c.metrics.open}%<small>open</small></b>
            <b>{c.metrics.click}%<small>click</small></b>
          </> : <span className="warning" data-testid={`incomplete-${c.id}`}><AlertTriangle size={12} /> No outcome yet</span>}
        </div>
        {withOutcome && c.status === 'ready' && !showOc && (
          <button className="ghost tiny" data-testid={`open-outcome-${c.id}`} onClick={() => setShowOc(true)}><Gauge size={12} /> Record outcome</button>
        )}
        {showOc && <OutcomeForm campaignId={c.id} onDone={() => { setShowOc(false); onOutcome(); }} onCancel={() => setShowOc(false)} />}
      </div>
    </article>
  );
}

function OutcomeForm({ campaignId, onDone, onCancel }) {
  const [f, setF] = useState({ open: '', click: '', conversion: '' });
  const submit = async () => {
    try {
      await api.post(`/campaigns/${campaignId}/outcomes`, {
        open: parseFloat(f.open || '0'), click: parseFloat(f.click || '0'),
        conversion: parseFloat(f.conversion || '0'),
      });
      toast.success('Outcome recorded — memory updated');
      onDone();
    } catch (e) { toast.error(e.response?.data?.detail?.[0]?.msg || 'Could not save'); }
  };
  return (
    <div className="outcome-form">
      <div className="row">
        <label>Open %<input data-testid="outcome-open" type="number" value={f.open} onChange={e => setF({ ...f, open: e.target.value })} /></label>
        <label>Click %<input data-testid="outcome-click" type="number" value={f.click} onChange={e => setF({ ...f, click: e.target.value })} /></label>
        <label>Conv %<input data-testid="outcome-conv" type="number" value={f.conversion} onChange={e => setF({ ...f, conversion: e.target.value })} /></label>
      </div>
      <div className="outcome-actions">
        <button className="ghost tiny" onClick={onCancel}>Cancel</button>
        <button className="primary tiny" data-testid="outcome-save" onClick={submit}>Save</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Brief
function BriefNew() {
  const { orgId, brandId } = useParams();
  const [d, setD] = useState(null);
  const [f, setF] = useState({ objective: '', audience: '', offer: '', constraints: '' });
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    api.get(`/brands/${brandId}/dashboard`).then(r => setD(r.data));
    try { const s = JSON.parse(localStorage.getItem(`bmos:brief:${brandId}`) || 'null'); if (s) setF(s); } catch (_e) { /* ignore */ }
  }, [brandId]);
  useEffect(() => { localStorage.setItem(`bmos:brief:${brandId}`, JSON.stringify(f)); }, [f, brandId]);
  const submit = async () => {
    if (!f.objective || !f.audience || !f.offer) { toast.error('Fill objective, audience, and offer'); return; }
    setBusy(true);
    try {
      const brief = await api.post(`/brands/${brandId}/briefs`, f);
      if (brief.data.brief_violations?.length) {
        toast.warning(`Your brief hits a hard rule: "${brief.data.brief_violations[0].rule}"`);
      }
      const rec = await api.post(`/briefs/${brief.data.id}/recommendations`);
      navigate(`/app/${orgId}/${brandId}/recommendations/${rec.data.id}`);
    } catch (_e) { toast.error('Could not process brief'); }
    finally { setBusy(false); }
  };
  if (!d) return <FullLoader />;
  const isDemo = d.brand.name?.includes('Northstar');
  return (
    <Shell active="brief" brand={d.brand} org={d.brand} isDemo={isDemo}>
      <Header eyebrow="NEW BRIEF" title="What are you making?" isDemo={isDemo} />
      <p className="page-sub">The memory finds real evidence from past sends. Nothing invented.</p>
      <div className="brief-page">
        <div className="brief-form">
          <label>Objective<input data-testid="brief-objective" value={f.objective} onChange={e => setF({ ...f, objective: e.target.value })} placeholder="Improve retention" /></label>
          <label>Audience<input data-testid="brief-audience" value={f.audience} onChange={e => setF({ ...f, audience: e.target.value })} placeholder="Active subscribers" /></label>
          <label>Offer / message<input data-testid="brief-offer" value={f.offer} onChange={e => setF({ ...f, offer: e.target.value })} placeholder="New seasonal roast" /></label>
          <label>Constraints <small>optional</small><textarea data-testid="brief-constraints" value={f.constraints} onChange={e => setF({ ...f, constraints: e.target.value })} placeholder="No discounts, keep it editorial" /></label>
          <button className="primary full" data-testid="brief-submit" onClick={submit} disabled={busy}>{busy ? 'Searching memory…' : 'Find evidence-backed direction'} <ArrowRight size={15} /></button>
          <div className="autosave"><span className="saved-dot" /> Draft autosaves in this browser</div>
        </div>
        <aside className="brief-side">
          <b>How this works</b>
          <ol>
            <li>Your brief is turned into a search vector.</li>
            <li>It finds the closest past emails from this brand only.</li>
            <li>GPT-5.4 writes a grounded rationale, citing them by name.</li>
            <li>Hard rules run last. If any hit, export is blocked.</li>
          </ol>
          <div className="rules-preview">
            <small>ACTIVE HARD RULES (v{d.brand.active_guideline_version})</small>
            {(d.guidelines?.prohibited_claims || []).length === 0 ? <p>None set — anything goes.</p>
              : d.guidelines.prohibited_claims.map((r, i) => <span key={i} className="danger-chip">{r}</span>)}
          </div>
        </aside>
      </div>
    </Shell>
  );
}

// ------------------------------------------------------------------ Recommendation
function matchQualityLabel(sem) {
  if (sem >= 0.60) return 'Strong match';
  if (sem >= 0.45) return 'Close match';
  if (sem >= 0.30) return 'Loose match';
  return 'Weak match';
}

function Recommendation() {
  const { orgId, brandId, recId } = useParams();
  const [rec, setRec] = useState(null);
  const [d, setD] = useState(null);
  const [exporting, setExporting] = useState(false);
  useEffect(() => {
    api.get(`/recommendations/${recId}`).then(r => setRec(r.data));
    api.get(`/brands/${brandId}/dashboard`).then(r => setD(r.data));
  }, [recId, brandId]);
  const exportBp = async () => {
    setExporting(true);
    try {
      const r = await api.post(`/recommendations/${recId}/blueprint`);
      const blob = new Blob([r.data.markdown], { type: 'text/markdown' });
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
      a.download = 'campaign-blueprint.md'; a.click();
      toast.success('Blueprint downloaded');
    } catch (e) {
      const detail = e.response?.data?.detail;
      if (detail?.violations) toast.error(`Blocked: ${detail.violations[0].rule} — ${detail.violations[0].remedy}`);
      else toast.error(typeof detail === 'string' ? detail : 'Export blocked');
    } finally { setExporting(false); }
  };
  if (!rec || !d) return <FullLoader />;
  const isDemo = d.brand.name?.includes('Northstar');
  const hasEvidence = rec.source_campaign_ids.length > 0;
  const strength = rec.evidence_strength;
  const strengthLabel = strength === 'strong' ? 'Strong evidence'
    : strength === 'moderate' ? 'Moderate evidence' : 'Needs more evidence';
  return (
    <Shell active="brief" brand={d.brand} org={d.brand} isDemo={isDemo}>
      <Header eyebrow="RECOMMENDATION" title="Evidence-backed direction." isDemo={isDemo} />
      <div className="rec-page">
        <div className="rec-summary">
          <span className={`tag ${strength}`}>{strengthLabel}</span>
          <span>Using rules v{rec.guideline_version}</span>
          <span>{rec.source_campaign_ids.length} campaign(s) cited</span>
          <span>Rationale by <b>{rec.rationale_model || 'deterministic only'}</b></span>
          <button className="primary" data-testid="rec-export" onClick={exportBp} disabled={exporting || rec.rule_violations.length > 0 || !hasEvidence}>
            {exporting ? 'Preparing…' : rec.rule_violations.length ? 'Blocked' : !hasEvidence ? 'No evidence yet' : 'Export blueprint'} <Download size={14} />
          </button>
        </div>
        {rec.rule_violations.length > 0 && (
          <div className="conflict-panel" data-testid="conflict-panel">
            <AlertTriangle size={16} />
            <div>
              <b>Blocked by a brand rule — export unavailable.</b>
              {rec.rule_violations.map((v, i) => (
                <p key={i}>&ldquo;{v.rule}&rdquo; — {v.remedy}</p>
              ))}
            </div>
          </div>
        )}
        {!hasEvidence && (
          <div className="empty-panel" data-testid="rec-empty">
            <Lightbulb size={22} />
            <h2>Nothing close enough in the memory.</h2>
            <p>Rather than invent direction, we&apos;re showing nothing. Try a different audience or add a similar past campaign first.</p>
          </div>
        )}
        {rec.rationale && (
          <div className="rationale">
            <b>Grounded rationale</b>
            <pre>{rec.rationale}</pre>
          </div>
        )}
        {rec.evidence.map((e, i) => (
          <article className="evidence-card" key={e.campaign_id} data-testid={`evidence-${e.campaign_id}`}>
            <div className="rec-top">
              <span className="rank">0{i + 1}</span>
              <div className="rec-title">
                <div>
                  <h2>{e.campaign.name}</h2>
                  <span className="mini-label">{matchQualityLabel(e.semantic_similarity)} · {e.objective_match ? 'same objective' : 'different objective'} · {e.audience_match ? 'same audience' : 'different audience'}</span>
                </div>
                <span className="score">{Math.round(e.score * 100)}<small>SCORE</small></span>
              </div>
            </div>
            <div className="evidence">
              <div className="evidence-preview" style={{ background: e.campaign.is_sample ? '#D9E8D8' : '#EEE9DF' }}>
                <span>{(e.campaign.subject || e.campaign.name).slice(0, 30)}</span>
                <b>{e.campaign.objective}</b>
              </div>
              <div className="evidence-copy">
                <span className="mini-label">Audience: {e.campaign.audience || 'TBD'}</span>
                <p>{(e.campaign.extracted?.summary || '').slice(0, 260)}</p>
                <div className="metrics">
                  {e.campaign.metrics?.open ? (
                    <>
                      <span><b>{e.campaign.metrics.open}%</b> opens</span>
                      <span><b>{e.campaign.metrics.click}%</b> clicks</span>
                    </>
                  ) : <span className="warning"><AlertTriangle size={12} /> No metrics attached</span>}
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
    </Shell>
  );
}

// ------------------------------------------------------------------ Guidelines
function GuidelinesPage() {
  const { brandId } = useParams();
  const [d, setD] = useState(null);
  const [g, setG] = useState(null);
  useEffect(() => {
    api.get(`/brands/${brandId}`).then(r => { setD(r.data); setG(r.data.guidelines || {}); });
  }, [brandId]);
  const save = async () => {
    try {
      await api.patch(`/brands/${brandId}/guidelines`, {
        tone: g.tone || [], approved_claims: g.approved_claims || [],
        prohibited_claims: g.prohibited_claims || [], colors: g.colors || [],
        layout_rules: g.layout_rules || [], cta_style: g.cta_style || '',
      });
      toast.success('New rules version saved');
    } catch (_e) { toast.error('Could not save'); }
  };
  if (!d || !g) return <FullLoader />;
  const isDemo = d.brand.name?.includes('Northstar');
  return (
    <Shell active="guidelines" brand={d.brand} org={d.organization} isDemo={isDemo}>
      <Header eyebrow="RULES" title="The guardrails behind every recommendation." isDemo={isDemo} />
      <p className="page-sub">Prohibited claims are hard rules — they block export. Everything else is guidance.</p>
      <div className="memory-grid">
        <ChipsField label="Voice & tone" testid="g-tone" items={g.tone || []} onChange={v => setG({ ...g, tone: v })} placeholder="warm, quietly confident…" />
        <ChipsField label="Approved claims" testid="g-approved" items={g.approved_claims || []} onChange={v => setG({ ...g, approved_claims: v })} placeholder="small-batch roasted…" />
        <ChipsField label="Prohibited claims" testid="g-prohibited" danger items={g.prohibited_claims || []} onChange={v => setG({ ...g, prohibited_claims: v })} placeholder="detox, cures anxiety…" />
        <ChipsField label="Layout rules" testid="g-layout" items={g.layout_rules || []} onChange={v => setG({ ...g, layout_rules: v })} placeholder="single primary CTA…" />
      </div>
      <label className="wide">CTA style<input data-testid="g-cta" value={g.cta_style || ''} onChange={e => setG({ ...g, cta_style: e.target.value })} /></label>
      <button className="primary" data-testid="g-save" onClick={save}>Save new version <Check size={14} /></button>
    </Shell>
  );
}

// ------------------------------------------------------------------ Misc
function DemoRedirect() {
  const [target, setTarget] = useState(null);
  useEffect(() => { api.get('/demo').then(r => setTarget(r.data)).catch(() => setTarget(false)); }, []);
  if (target === null) return <FullLoader />;
  if (target === false) return <div className="landing"><div className="landing-copy"><h1>Demo unavailable</h1><Link to="/">Back</Link></div></div>;
  return <Navigate to={`/app/${target.org_id}/${target.brand_id}/dashboard`} replace />;
}

function Header({ eyebrow, title, isDemo }) {
  return (
    <header>
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
      </div>
      <div className="header-meta">
        {isDemo && <span className="sample-pill" data-testid="header-sample-pill">SAMPLE · Northstar Coffee</span>}
      </div>
    </header>
  );
}

function EmptyPanel({ title, body }) {
  return (
    <div className="empty-panel wide" data-testid="empty-panel">
      <Lightbulb size={22} />
      <h2>{title}</h2>
      <p>{body}</p>
    </div>
  );
}

function FullLoader() {
  return <div className="full-loader" data-testid="full-loader"><Loader2 size={28} className="spin" /><span>Loading…</span></div>;
}

function Blocked() {
  return (
    <div className="landing">
      <div className="landing-copy">
        <div className="brand-mark dark"><span>BM</span><b>Brand Memory</b></div>
        <h1>Not your workspace.</h1>
        <p>This URL belongs to a different organization. Every workspace is isolated by design.</p>
        <Link className="primary large" to="/">Back to start <ArrowLeft size={14} /></Link>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ root
export default function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-right" richColors />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/demo" element={<DemoRedirect />} />
        <Route path="/app/:orgId/:brandId/dashboard" element={<Dashboard />} />
        <Route path="/app/:orgId/:brandId/campaigns" element={<Campaigns />} />
        <Route path="/app/:orgId/:brandId/briefs/new" element={<BriefNew />} />
        <Route path="/app/:orgId/:brandId/recommendations/:recId" element={<Recommendation />} />
        <Route path="/app/:orgId/:brandId/guidelines" element={<GuidelinesPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
