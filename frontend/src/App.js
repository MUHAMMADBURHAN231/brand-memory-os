import { useEffect, useState, useCallback } from 'react';
import { BrowserRouter, Routes, Route, Link, useNavigate, useParams, Navigate } from 'react-router-dom';
import axios from 'axios';
import {
  ArrowRight, ArrowLeft, Check, ChevronRight, Download, Gauge, Lightbulb, LockKeyhole,
  Sparkles, ShieldCheck, BookOpen, Upload, FileText, Loader2, X, Plus, AlertTriangle,
  ExternalLink, ClipboardList, Zap, Link2, LogOut, Search, UserRound, KeyRound, RefreshCw,
} from 'lucide-react';
import { toast, Toaster } from 'sonner';
import './App.css';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;
export const api = axios.create({ baseURL: API, withCredentials: true });
api.interceptors.request.use(config => {
  const csrf = localStorage.getItem('bmos:csrf');
  if (csrf && !['get', 'head', 'options'].includes((config.method || 'get').toLowerCase())) {
    config.headers['X-CSRF-Token'] = csrf;
  }
  if (localStorage.getItem('bmos:demo') === 'true') config.headers['X-Demo-Access'] = 'read-only';
  return config;
});

function setSession(data) {
  if (data?.csrf_token) localStorage.setItem('bmos:csrf', data.csrf_token);
  localStorage.removeItem('bmos:demo');
}

function isDemoWorkspace(d) {
  return Boolean(d?.is_demo || d?.organization?.is_demo);
}

// Providers: Klaviyo/Mailchimp support encrypted API-key sync; others remain paste-based.
const PROVIDERS = [
  { id: 'klaviyo',   name: 'Klaviyo',   hint: 'Sync campaigns or paste HTML', native: true },
  { id: 'mailchimp', name: 'Mailchimp', hint: 'Sync campaigns or paste HTML', native: true },
  { id: 'figma',     name: 'Figma',     hint: 'Right-click frame → Copy as HTML', native: false },
  { id: 'hubspot',   name: 'HubSpot',   hint: 'Paste from email preview', native: false },
  { id: 'iterable',  name: 'Iterable',  hint: 'Paste HTML export', native: false },
];

// ------------------------------------------------------------------ Landing
function Landing() {
  const navigate = useNavigate();
  const [orgs, setOrgs] = useState([]);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState(null);
  useEffect(() => {
    localStorage.removeItem('bmos:demo');
    api.get('/auth/me').then(r => {
      setSession(r.data); setUser(r.data.user); setOrgs(r.data.organizations || []);
    }).catch(() => {}).finally(() => setReady(true));
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
        <p>Agency lifecycle marketers paste or sync past emails. Every future brief comes back cited to real campaigns and blocked when a hard brand rule is hit.</p>
        <div className="landing-actions">
          <button className="primary large" data-testid="cta-create-workspace" onClick={() => navigate(user ? '/onboarding' : '/auth?mode=register')}>
            {user ? 'Create workspace' : 'Create account'} <ArrowRight size={18} />
          </button>
          <button className="ghost large" data-testid="cta-view-demo" onClick={() => navigate('/demo')}>
            Try the demo <ExternalLink size={16} />
          </button>
        </div>
        {ready && !user && <button className="link resume" onClick={() => navigate('/auth')}>Already have an account? Sign in</button>}
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

function AuthPage() {
  const navigate = useNavigate();
  const register = new URLSearchParams(window.location.search).get('mode') === 'register';
  const [mode, setMode] = useState(register ? 'register' : 'login');
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const submit = async e => {
    e.preventDefault(); setBusy(true);
    try {
      const r = await api.post(`/auth/${mode}`, form);
      setSession(r.data); navigate(r.data.organizations?.length ? '/' : '/onboarding');
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : (err.request && !err.response ? 'Backend is not running on http://localhost:8000' : 'Could not sign in'));
    }
    finally { setBusy(false); }
  };
  return <div className="auth-page">
    <Link className="brand-mark" to="/"><span>BM</span><div><b>Brand Memory</b><small>SECURE WORKSPACE</small></div></Link>
    <form className="auth-card" onSubmit={submit}>
      <div className="auth-icon"><UserRound size={20}/></div>
      <h1>{mode === 'register' ? 'Create your workspace account.' : 'Welcome back.'}</h1>
      <p>Private brand memory, isolated by organization.</p>
      {mode === 'register' && <label>Your name<input required minLength="2" value={form.name} onChange={e => setForm({...form, name:e.target.value})}/></label>}
      <label>Email<input required type="email" autoComplete="email" value={form.email} onChange={e => setForm({...form, email:e.target.value})}/></label>
      <label>Password<input required minLength="10" type="password" autoComplete={mode === 'register' ? 'new-password' : 'current-password'} value={form.password} onChange={e => setForm({...form, password:e.target.value})}/><small>At least 10 characters</small></label>
      <button className="primary full" disabled={busy}>{busy ? 'Please wait…' : mode === 'register' ? 'Create account' : 'Sign in'} <ArrowRight size={16}/></button>
      <button type="button" className="link" onClick={() => setMode(mode === 'register' ? 'login' : 'register')}>{mode === 'register' ? 'Have an account? Sign in' : 'New here? Create an account'}</button>
    </form>
  </div>;
}

function Protected({ children }) {
  const [state, setState] = useState('loading');
  useEffect(() => {
    if (localStorage.getItem('bmos:demo') === 'true') { setState('ready'); return; }
    api.get('/auth/me').then(r => { setSession(r.data); setState('ready'); }).catch(() => setState('blocked'));
  }, []);
  if (state === 'loading') return <FullLoader/>;
  return state === 'blocked' ? <Navigate to="/auth" replace/> : children;
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

// ------------------------------------------------------------------ Onboarding (five persisted steps)
const STEPS = [
  { k: 'organization', title: 'Organization', hint: 'Private boundary' },
  { k: 'brand', title: 'Brand', hint: 'Identity & market' },
  { k: 'research', title: 'Research', hint: 'Evidence first' },
  { k: 'guardrails', title: 'Guardrails', hint: 'Human controlled' },
  { k: 'memory', title: 'Memory', hint: 'Review & enter' },
];

function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [orgId, setOrgId] = useState('');
  const [brandId, setBrandId] = useState('');
  const [form, setForm] = useState({
    orgName: '', orgType: 'brand', brandName: '', brandUrl: '', industry: '', market: '',
  });
  const [rules, setRules] = useState({
    tone: ['warm', 'specific'],
    prohibited_claims: [],
    approved_claims: [], colors: [], layout_rules: [], cta_style: '',
  });
  const [busy, setBusy] = useState(false);
  const [research, setResearch] = useState(null);
  const [researchNotes, setResearchNotes] = useState('');

  useEffect(() => {
    const resumeId = new URLSearchParams(window.location.search).get('org');
    if (!resumeId) return;
    api.get(`/organizations/${resumeId}/onboarding`).then(r => {
      const { organization:o, brand:b, guidelines:g, research:rr } = r.data;
      setOrgId(o.id); setBrandId(b?.id || ''); setStep(Math.min(5, o.onboarding_step || 1));
      setForm(f => ({...f, orgName:o.name, orgType:o.type, brandName:b?.name || '', brandUrl:b?.url || '', industry:b?.industry || '', market:b?.market || ''}));
      if (g) setRules({tone:g.tone || [], prohibited_claims:g.prohibited_claims || [], approved_claims:g.approved_claims || [], colors:g.colors || [], layout_rules:g.layout_rules || [], cta_style:g.cta_style || ''});
      if (rr) setResearch(rr);
    }).catch(() => toast.error('Could not resume setup'));
  }, []);

  const submitOrganization = async () => {
    if (!form.orgName.trim()) { toast.error('Give the organization a name'); return; }
    setBusy(true);
    try {
      if (orgId) {
        await api.patch(`/organizations/${orgId}/onboarding`, { step: 2, complete: false });
        setStep(2); return;
      }
      const o = await api.post('/organizations', {
        name: form.orgName, type: form.orgType, role: '', managed_brands: 1, industry: '',
      });
      await api.patch(`/organizations/${o.data.id}/onboarding`, { step: 2, complete: false });
      setOrgId(o.data.id);
      setStep(2);
    } catch (_e) { toast.error('Could not create workspace'); }
    finally { setBusy(false); }
  };

  const submitBrand = async () => {
    if (!form.brandName.trim()) { toast.error('Give the brand a name'); return; }
    setBusy(true);
    try {
      if (brandId) {
        await api.patch(`/organizations/${orgId}/onboarding`, {step:3, complete:false});
        setStep(3); return;
      }
      const b = await api.post(`/organizations/${orgId}/brands`, {name:form.brandName, url:form.brandUrl, industry:form.industry, market:form.market});
      setBrandId(b.data.id); localStorage.setItem(`bmos:last-brand:${orgId}`, b.data.id);
      await api.patch(`/organizations/${orgId}/onboarding`, {step:3, complete:false}); setStep(3);
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not save brand'); }
    finally { setBusy(false); }
  };

  const runResearch = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/brands/${brandId}/research`, {url:form.brandUrl, notes:researchNotes});
      setResearch(r.data); toast.success('Research ready for your review');
    } catch (e) { toast.error(e.response?.data?.detail || 'Research could not run. You can continue manually.'); }
    finally { setBusy(false); }
  };

  const continueResearch = async () => {
    await api.patch(`/organizations/${orgId}/onboarding`, {step:4, complete:false}); setStep(4);
  };

  const submitRules = async () => {
    setBusy(true);
    try {
      await api.patch(`/brands/${brandId}/guidelines`, rules);
      await api.patch(`/organizations/${orgId}/onboarding`, { step: 5, complete: false });
      setStep(5);
    } catch (_e) { toast.error('Could not save rules'); }
    finally { setBusy(false); }
  };

  const finish = async () => {
    setBusy(true);
    try {
      await api.patch(`/organizations/${orgId}/onboarding`, { step: 5, complete: true, data_choice: 'skip' });
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
          <StepShell title="Create the organization boundary." sub="People and brands are isolated through organization membership. No workspace opens without an authenticated account.">
            <label>Workspace / organization<input data-testid="onb-org-name" value={form.orgName} onChange={e => setForm({ ...form, orgName: e.target.value })} placeholder="Alpine Studio" autoFocus /></label>
            <label>Type
                <select data-testid="onb-org-type" value={form.orgType} onChange={e => setForm({ ...form, orgType: e.target.value })}>
                  <option value="brand">In-house brand</option>
                  <option value="agency">Agency</option>
                  <option value="in-house">In-house team</option>
                </select>
            </label>
            <div className="onb-actions">
              <button className="ghost" onClick={() => navigate('/')} data-testid="onb-back-1"><ArrowLeft size={16} /> Back</button>
              <button className="primary" data-testid="onb-continue-1" onClick={submitOrganization} disabled={busy}>{busy ? 'Saving…' : 'Continue'} <ArrowRight size={16} /></button>
            </div>
          </StepShell>
        )}
        {step === 2 && (
          <StepShell title="Add the first brand." sub="The website must be public. Private-network and localhost URLs are rejected before research begins.">
            <label>Brand name<input value={form.brandName} onChange={e => setForm({...form,brandName:e.target.value})} placeholder="Alpine Kettle Co." autoFocus/></label>
            <label>Public website<input type="url" value={form.brandUrl} onChange={e => setForm({...form,brandUrl:e.target.value})} placeholder="https://alpinekettle.com"/></label>
            <div className="row"><label>Industry<input value={form.industry} onChange={e => setForm({...form,industry:e.target.value})} placeholder="Outdoor cookware"/></label><label>Market<input value={form.market} onChange={e => setForm({...form,market:e.target.value})} placeholder="US / UK"/></label></div>
            <div className="onb-actions"><button className="ghost" onClick={()=>setStep(1)}><ArrowLeft size={16}/> Back</button><button className="primary" onClick={submitBrand} disabled={busy}>{busy?'Saving…':'Continue'} <ArrowRight size={16}/></button></div>
          </StepShell>
        )}
        {step === 3 && (
          <StepShell title="Research before generating." sub="A controlled OpenAI agent handoff extracts evidence, analyzes strategy, then proposes conservative controls. Nothing is applied automatically.">
            <div className="research-callout"><Search size={20}/><div><b>Evidence → strategy → safety synthesis</b><p>Only the approved website is cited. Website text is treated as untrusted input.</p></div></div>
            <label>Optional research context<textarea value={researchNotes} onChange={e=>setResearchNotes(e.target.value)} placeholder="Known audience, positioning, or compliance context…"/></label>
            {research && <ResearchSummary research={research}/>}
            <div className="onb-actions"><button className="ghost" onClick={()=>setStep(2)}><ArrowLeft size={16}/> Back</button><div className="split-actions"><button className="outline" onClick={runResearch} disabled={busy || !form.brandUrl}>{busy?'Researching…':research?'Run again':'Run brand research'}</button><button className="primary" onClick={continueResearch}>Continue <ArrowRight size={16}/></button></div></div>
          </StepShell>
        )}
        {step === 4 && (
          <StepShell title="Set the hard guardrails." sub="These checks run deterministically. AI research is advisory; you remain the final approver.">
            <ChipsField testid="onb-tone" label="Voice & tone" items={rules.tone} onChange={v => setRules({ ...rules, tone: v })} placeholder="warm, quietly confident…" />
            <ChipsField testid="onb-prohibited" label="Prohibited claims (the hard rules)" danger items={rules.prohibited_claims} onChange={v => setRules({ ...rules, prohibited_claims: v })} placeholder="detox, cures anxiety, free forever…" />
            <p className="micro-note"><ShieldCheck size={13} /> These check every recommendation and blueprint. Deterministic — not left to the AI.</p>
            <div className="onb-actions">
              <button className="ghost" onClick={() => setStep(3)} data-testid="onb-back-2"><ArrowLeft size={16} /> Back</button>
              <button className="primary" data-testid="onb-continue-2" onClick={submitRules} disabled={busy}>{busy ? 'Saving…' : 'Continue'} <ArrowRight size={16} /></button>
            </div>
          </StepShell>
        )}
        {step === 5 && (
          <StepShell title="Add memory, then enter." sub="Upload past email evidence now or start with an empty, honest workspace. You can add more later.">
            <div className="memory-add">
              <UploadBox brandId={brandId} inline onDone={() => toast.success('Uploaded — analysis running')} />
              <div className="or">or</div>
              <ConnectSourcesRow brandId={brandId} onDone={() => toast.success('Pasted — analysis running')} />
            </div>
            <div className="onb-actions">
              <button className="ghost" onClick={() => setStep(4)} data-testid="onb-back-3"><ArrowLeft size={16} /> Back</button>
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

function ResearchSummary({ research }) {
  const report = research.report || {};
  return <div className="research-result">
    <div className="research-status"><ShieldCheck size={15}/><b>Awaiting your review</b><span>{research.model}</span></div>
    <p>{report.summary}</p>
    <div className="research-facts">
      <div><small>VOICE CANDIDATES</small><b>{(report.voice_traits || []).join(' · ') || 'None proposed'}</b></div>
      <div><small>EVIDENCE</small><b>{report.evidence?.length || 0} cited observations</b></div>
    </div>
    <small>Agent output is not active policy. Review it again in Rules before adding any proposal.</small>
  </div>;
}

function ChipsField({ label, placeholder, items, onChange, danger, testid, readOnly }) {
  const [v, setV] = useState('');
  const add = () => { if (v.trim()) { onChange([...items, v.trim()]); setV(''); } };
  return (
    <div className="chips-field">
      <label>{label}</label>
      <div className={`chips ${danger ? 'danger' : ''}`}>
        {items.map((x, i) => (
          <span key={i} data-testid={`${testid}-chip-${i}`}>{x}{!readOnly && <button onClick={() => onChange(items.filter((_, j) => j !== i))}><X size={12} /></button>}</span>
        ))}
      </div>
      {!readOnly && <div className="chip-input">
        <input data-testid={`${testid}-input`} value={v} onChange={e => setV(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }} placeholder={placeholder} />
        <button className="ghost tiny" data-testid={`${testid}-add`} onClick={add}><Plus size={13} /> Add</button>
      </div>}
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
  const [connections, setConnections] = useState([]);
  const load = useCallback(() => {
    api.get(`/brands/${brandId}/connections`).then(r => setConnections(r.data || [])).catch(() => setConnections([]));
  }, [brandId]);
  useEffect(() => { load(); }, [load]);
  const opened = PROVIDERS.find(p => p.id === openId);
  const connected = (id) => connections.find(c => c.provider === id);
  return (
    <div className="connect-row">
      <div className="upload-head">
        <Link2 size={16} />
        <div><b>Connect from your tools</b><small>Klaviyo and Mailchimp can sync. Everyone else pastes HTML.</small></div>
      </div>
      <div className="provider-tiles">
        {PROVIDERS.map(p => (
          <button key={p.id} className={`provider-tile ${connected(p.id) ? 'connected' : ''}`} data-testid={`provider-${p.id}`} onClick={() => setOpenId(p.id)}>
            <span className="tile-logo">{p.name[0]}</span>
            <b>{p.name}</b>
            <small>{connected(p.id) ? `Connected · ${connected(p.id).account_label || p.name}` : p.hint}</small>
          </button>
        ))}
      </div>
      {opened && (
        <ProviderModal
          brandId={brandId}
          provider={opened}
          connection={connected(opened.id)}
          onClose={() => setOpenId(null)}
          onRefresh={load}
          onDone={() => { setOpenId(null); load(); onDone(); }}
        />
      )}
    </div>
  );
}

function ProviderModal({ brandId, provider, connection, onClose, onDone, onRefresh }) {
  const native = provider.native;
  const [tab, setTab] = useState(native ? (connection ? 'sync' : 'key') : 'paste');
  const [name, setName] = useState('');
  const [html, setHtml] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const paste = async () => {
    if (!name.trim() || !html.trim()) { toast.error('Name it and paste some HTML'); return; }
    setBusy(true);
    try {
      await api.post(`/brands/${brandId}/campaigns/paste`, { name, source: provider.id, html });
      toast.success('Added to memory — analysis running');
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not add');
    } finally { setBusy(false); }
  };
  const connect = async () => {
    if (apiKey.trim().length < 8) { toast.error('Paste a private API key'); return; }
    setBusy(true);
    try {
      const r = await api.post(`/brands/${brandId}/connections`, { provider: provider.id, api_key: apiKey.trim() });
      toast.success(`Connected ${r.data.account || provider.name}`);
      setTab('sync'); setApiKey('');
      onRefresh?.();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not connect');
    } finally { setBusy(false); }
  };
  const sync = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/brands/${brandId}/connections/${provider.id}/sync`);
      toast.success(`Imported ${r.data.imported} campaign${r.data.imported === 1 ? '' : 's'}`);
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Sync failed');
    } finally { setBusy(false); }
  };
  const disconnect = async () => {
    setBusy(true);
    try {
      await api.delete(`/brands/${brandId}/connections/${provider.id}`);
      toast.success('Disconnected');
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not disconnect');
    } finally { setBusy(false); }
  };
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} data-testid={`paste-modal-${provider.id}`}>
        <div className="modal-head">
          <div><b>Connect from {provider.name}</b><small>{provider.hint}</small></div>
          <button onClick={onClose} data-testid="paste-close"><X size={16} /></button>
        </div>
        {native && (
          <div className="modal-tabs">
            <button className={tab !== 'paste' ? 'active' : ''} onClick={() => setTab(connection ? 'sync' : 'key')} data-testid="tab-sync">{connection ? 'API sync' : 'API key'}</button>
            <button className={tab === 'paste' ? 'active' : ''} onClick={() => setTab('paste')} data-testid="tab-paste">Paste HTML</button>
          </div>
        )}
        {tab === 'paste' && <>
          <label>Campaign name<input data-testid="paste-name" value={name} onChange={e => setName(e.target.value)} placeholder={`${provider.name} — winter launch`} autoFocus /></label>
          <label>Paste email HTML
            <textarea data-testid="paste-html" value={html} onChange={e => setHtml(e.target.value)} rows={8} placeholder="<html>…paste from your tool…</html>" />
          </label>
          <div className="modal-foot">
            <small className="soon">{native ? 'Private key is stored encrypted' : 'OAuth sync · on the roadmap'}</small>
            <button className="primary" data-testid="paste-submit" onClick={paste} disabled={busy}>{busy ? 'Adding…' : 'Add to memory'} <ArrowRight size={13} /></button>
          </div>
        </>}
        {native && tab !== 'paste' && !connection && <>
          <p className="modal-help">Private keys never appear in the browser after save. They are encrypted at rest and used only to import recent email campaigns.</p>
          <label>{provider.name} API key
            <input data-testid="connect-key" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={provider.id === 'mailchimp' ? 'xxxx-us14' : 'pk_live_…'} autoFocus />
          </label>
          <div className="modal-foot">
            <small className="soon"><KeyRound size={11} /> Encrypted · this brand only</small>
            <button className="primary" data-testid="connect-submit" onClick={connect} disabled={busy}>{busy ? 'Checking…' : 'Connect'} <ArrowRight size={13} /></button>
          </div>
        </>}
        {native && tab !== 'paste' && connection && <>
          <div className="connected-box">
            <b>{connection.account_label || provider.name}</b>
            <small>Last sync {connection.last_synced_at ? new Date(connection.last_synced_at).toLocaleString() : 'never'} · {connection.last_sync_count || 0} imported</small>
          </div>
          <div className="modal-foot">
            <button className="link" data-testid="disconnect-provider" onClick={disconnect} disabled={busy}>Disconnect</button>
            <button className="primary" data-testid="sync-provider" onClick={sync} disabled={busy}>{busy ? 'Syncing…' : 'Sync last 5 emails'} <RefreshCw size={13} /></button>
          </div>
        </>}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Workspace shell
function Shell({ children, active, brand, org, isDemo, sampleRecId }) {
  const { orgId, brandId } = useParams();
  const navigate = useNavigate();
  const leave = async () => {
    if (!isDemo) {
      try { await api.post('/auth/logout'); } catch (_e) { /* ignore */ }
      localStorage.removeItem('bmos:csrf');
    }
    localStorage.removeItem('bmos:demo'); navigate('/');
  };
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
          {!isDemo && <button className={active === 'brief' ? 'active' : ''} data-testid="nav-brief" onClick={() => navigate(`/app/${orgId}/${brandId}/briefs/new`)}><ClipboardList size={16} /> New brief</button>}
          {isDemo && sampleRecId && <button className={active === 'brief' ? 'active' : ''} data-testid="nav-sample-brief" onClick={() => navigate(`/app/${orgId}/${brandId}/recommendations/${sampleRecId}`)}><ClipboardList size={16} /> Sample brief</button>}
          <button className={active === 'guidelines' ? 'active' : ''} data-testid="nav-guidelines" onClick={() => navigate(`/app/${orgId}/${brandId}/guidelines`)}><ShieldCheck size={16} /> Rules</button>
        </nav>
        <div className="sidebar-foot">
          <div className="privacy"><LockKeyhole size={13} /><span>Private<br /><b>Only this brand</b></span></div>
          <button className="link exit" data-testid="exit-workspace" onClick={leave}><LogOut size={13}/> {isDemo ? 'Exit demo' : 'Sign out'}</button>
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
  const isDemo = isDemoWorkspace(d);
  const ready = d.readiness;
  const org = d.organization || d.brand;
  const sampleRecId = d.latest_recommendation?.id;
  return (
    <Shell active="dashboard" brand={d.brand} org={org} isDemo={isDemo} sampleRecId={sampleRecId}>
      <Header eyebrow="DASHBOARD" title={d.brand.name} isDemo={isDemo} />
      <p className="page-sub">Everything the memory currently knows about {d.brand.name}.</p>
      <section className="readiness">
        <ReadinessCard icon={<BookOpen size={16} />} label="Emails in memory" value={ready.analyzed} testid="ready-analyzed" />
        <ReadinessCard icon={<Loader2 size={16} />} label="Processing now" value={ready.processing} testid="ready-processing" />
        <ReadinessCard icon={<ShieldCheck size={16} />} label="Brand rules" value={ready.guidelines_set ? 'Set' : 'Not yet'} testid="ready-guidelines" />
        <ReadinessCard icon={<Gauge size={16} />} label="Outcomes recorded" value={ready.outcomes_attached} testid="ready-outcomes" />
      </section>
      {!isDemo ? <div className="dash-actions">
        <Link className="primary" data-testid="dash-cta-brief" to={`/app/${orgId}/${brandId}/briefs/new`}><Zap size={14} /> Create a brief</Link>
        <Link className="ghost light" data-testid="dash-cta-upload" to={`/app/${orgId}/${brandId}/campaigns`}><Plus size={14} /> Add campaigns</Link>
      </div> : <div className="demo-notice"><LockKeyhole size={15}/><span>This sample is read-only. Open the sample brief to see cited evidence, then create an account for a private workspace.</span>{sampleRecId && <Link className="primary" data-testid="dash-cta-sample" to={`/app/${orgId}/${brandId}/recommendations/${sampleRecId}`}>See sample recommendation <ArrowRight size={14}/></Link>}</div>}
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
  const reload = useCallback(async () => {
    try {
      const [dash, camps] = await Promise.all([
        api.get(`/brands/${brandId}/dashboard`),
        api.get(`/brands/${brandId}/campaigns`),
      ]);
      setD(dash.data);
      setList(camps.data);
      // Polling exists only to watch uploads finish. Once nothing is being
      // processed there is nothing to wait for.
      return (dash.data.readiness?.processing || 0) > 0;
    } catch (e) {
      setErr(e.response?.status || 0);
      return false;  // a failing brand will not start working on retry
    }
  }, [brandId]);
  useEffect(() => {
    let id;
    let cancelled = false;
    const tick = async () => {
      const keepPolling = await reload();
      if (!cancelled && keepPolling) id = setTimeout(tick, 3500);
    };
    tick();
    return () => { cancelled = true; clearTimeout(id); };
  }, [reload]);
  if (err === 403) return <Blocked />;
  if (err) return <BrandGone status={err} />;
  if (!d) return <FullLoader />;
  const isDemo = isDemoWorkspace(d);
  return (
    <Shell active="campaigns" brand={d.brand} org={d.organization || d.brand} isDemo={isDemo} sampleRecId={d.latest_recommendation?.id}>
      <Header eyebrow="MEMORY" title="Past work, kept in context." isDemo={isDemo} />
      <p className="page-sub">Every email keeps its objective, audience, and outcome attached. That&apos;s what makes recommendations trustworthy.</p>
      {!isDemo && <div className="add-sources">
        <UploadBox brandId={brandId} onDone={reload} />
        <ConnectSourcesRow brandId={brandId} onDone={reload} />
      </div>}
      <section className="library-grid">
        {list.length === 0 && <EmptyPanel title="No campaigns yet" body="Upload an email or paste one from your tool — the AI extracts structure and the memory becomes searchable." />}
        {list.map(c => <CampaignCard key={c.id} c={c} withOutcome={!isDemo} onOutcome={reload} />)}
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
// Mirrors CATEGORIES in backend/services/email_structure.py.
const CATEGORY_OPTIONS = [
  { value: 'activewear', label: 'Activewear' },
  { value: 'supplements', label: 'Supplements' },
  { value: 'beauty', label: 'Beauty & skincare' },
  { value: 'food_beverage', label: 'Food & beverage' },
  { value: 'apparel', label: 'Apparel' },
  { value: 'home', label: 'Home' },
  { value: 'electronics', label: 'Electronics' },
  { value: 'saas', label: 'SaaS' },
  { value: 'other', label: 'Other' },
];

const RUN_STEPS = [
  { title: 'Read your description', detail: 'Objective, audience, and offer are pulled out of what you wrote.' },
  { title: 'Search this brand’s memory', detail: 'Finds past sends with the closest copy, layout, and category.' },
  { title: 'Assemble the structure', detail: 'Builds a block-by-block layout from patterns this brand already used.' },
  { title: 'Run the hard rules', detail: 'Prohibited claims block the export. No exceptions.' },
];

const STAGE_LABELS = ['Build the structure', 'Reading your description…',
  'Searching memory…', 'Assembling structure…'];

function BriefNew() {
  const { orgId, brandId } = useParams();
  const [d, setD] = useState(null);
  const [f, setF] = useState({ name: '', title: '', description: '', category: '' });
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const navigate = useNavigate();
  useEffect(() => {
    api.get(`/brands/${brandId}/dashboard`).then(r => setD(r.data));
    try { const s = JSON.parse(localStorage.getItem(`bmos:brief:${brandId}`) || 'null'); if (s) setF(s); } catch (_e) { /* ignore */ }
  }, [brandId]);
  useEffect(() => { localStorage.setItem(`bmos:brief:${brandId}`, JSON.stringify(f)); }, [f, brandId]);
  const ready = f.name.trim().length >= 2 && f.title.trim().length >= 2 && f.description.trim().length >= 10;
  const submit = async () => {
    if (!ready) { toast.error('Add a name, a title, and a description of at least 10 characters'); return; }
    setBusy(true);
    try {
      setStage(1);
      const brief = await api.post(`/brands/${brandId}/briefs`, f);
      if (brief.data.brief_violations?.length) {
        toast.warning(`Your description hits a hard rule: "${brief.data.brief_violations[0].rule}"`);
      }
      setStage(2);
      const rec = await api.post(`/briefs/${brief.data.id}/recommendations`);
      setStage(3);
      navigate(`/app/${orgId}/${brandId}/recommendations/${rec.data.id}`);
    } catch (_e) { toast.error('Could not process this campaign'); setStage(0); }
    finally { setBusy(false); }
  };
  if (!d) return <FullLoader />;
  const isDemo = isDemoWorkspace(d);
  return (
    <Shell active="brief" brand={d.brand} org={d.organization || d.brand} isDemo={isDemo} sampleRecId={d.latest_recommendation?.id}>
      <Header eyebrow="NEW CAMPAIGN" title="Name it, title it, describe it." isDemo={isDemo} />
      <p className="page-sub">Three fields. Everything else is worked out from your description and this brand&apos;s own past sends.</p>
      <div className="brief-page">
        <div className="brief-form">
          <label>
            <span className="field-step">1</span> Campaign name
            <small>Internal label so you can find it later</small>
            <input data-testid="brief-name" value={f.name} maxLength={120}
              onChange={e => setF({ ...f, name: e.target.value })} placeholder="Autumn Roast Launch" />
          </label>
          <label>
            <span className="field-step">2</span> Title
            <small>One line on what this email is</small>
            <input data-testid="brief-title" value={f.title} maxLength={200}
              onChange={e => setF({ ...f, title: e.target.value })}
              placeholder="Introduce the new seasonal roast to active subscribers" />
          </label>
          <label>
            <span className="field-step">3</span> What do you want?
            <small>Plain language. Say the goal, who it&apos;s for, and anything to avoid.</small>
            <textarea data-testid="brief-description" value={f.description} rows={5} maxLength={2000}
              onChange={e => setF({ ...f, description: e.target.value })}
              placeholder="We're launching the autumn seasonal roast. I want an editorial email for active subscribers that teaches the flavour profile and drives one click to the product page. No discounts." />
            <span className="char-count">{f.description.length}/2000</span>
          </label>
          <label>
            Category <small>optional — sharpens which past designs get matched</small>
            <select data-testid="brief-category" value={f.category}
              onChange={e => setF({ ...f, category: e.target.value })}>
              <option value="">Detect automatically</option>
              {CATEGORY_OPTIONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <button className="primary full" data-testid="brief-submit" onClick={submit} disabled={busy || !ready}>
            {busy ? STAGE_LABELS[stage] : 'Build the structure'} <ArrowRight size={15} />
          </button>
          <div className="autosave"><span className="saved-dot" /> Draft autosaves in this browser</div>
        </div>
        <aside className="brief-side">
          <b>What happens when you hit build</b>
          <ol className="run-steps">
            {RUN_STEPS.map((s, i) => (
              <li key={i} className={busy && stage > i ? 'done' : busy && stage === i ? 'active' : ''}>
                <b>{s.title}</b>
                <span>{s.detail}</span>
              </li>
            ))}
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
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    api.get(`/recommendations/${recId}`).then(r => setRec(r.data));
    api.get(`/brands/${brandId}/dashboard`).then(r => setD(r.data));
  }, [recId, brandId]);
  const copyStructure = async () => {
    const text = (rec.recommended_structure || [])
      .map(s => `${s.position}. ${s.label} — ${s.purpose}`)
      .join('\n');
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (_e) { toast.error('Could not copy — select the blocks manually'); }
  };
  const exportBp = async () => {
    setExporting(true);
    try {
      const r = await api.get(`/recommendations/${recId}/blueprint`);
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
  const isDemo = isDemoWorkspace(d);
  const hasEvidence = rec.source_campaign_ids.length > 0;
  const strength = rec.evidence_strength;
  const strengthLabel = strength === 'strong' ? 'Strong evidence'
    : strength === 'moderate' ? 'Moderate evidence' : 'Needs more evidence';
  return (
    <Shell active="brief" brand={d.brand} org={d.organization || d.brand} isDemo={isDemo} sampleRecId={d.latest_recommendation?.id || rec.id}>
      <Header eyebrow="RECOMMENDATION" title="Evidence-backed direction." isDemo={isDemo} />
      <div className="rec-page">
        <div className="rec-summary">
          <span className={`tag ${strength}`}>{strengthLabel}</span>
          <span>Built from <b>{rec.source_campaign_ids.length}</b> of this brand&apos;s past emails</span>
          <span>Checked against brand rules v{rec.guideline_version}</span>
          <span>{rec.rationale_model && rec.rationale_model !== 'seeded-demo'
            ? <>Explanation written by <b>{rec.rationale_model}</b></>
            : <>Layout from your own sends — <b>no AI writing involved</b></>}</span>
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
            <h2>No past email was close enough to build from.</h2>
            <p>
              This brand&apos;s memory has nothing similar enough to this campaign, so rather
              than invent a layout, we&apos;re showing you nothing. That&apos;s deliberate.
            </p>
            <div className="fix-list">
              <b>Two ways to fix it:</b>
              <ol>
                <li>
                  <b>Add more past emails.</b> Structure is read from HTML, so paste or sync
                  real emails rather than screenshots — a handful is usually enough.
                  <Link to={`/app/${orgId}/${brandId}/campaigns`}>Go to Memory <ArrowRight size={12} /></Link>
                </li>
                <li>
                  <b>Describe it closer to something you&apos;ve sent.</b> Mention the product,
                  the audience, and the goal in the same words your past emails use.
                  <Link to={`/app/${orgId}/${brandId}/briefs/new`}>Rewrite the campaign <ArrowRight size={12} /></Link>
                </li>
              </ol>
            </div>
          </div>
        )}
        {(rec.recommended_structure || []).length > 0 && (
          <div className="structure-panel" data-testid="rec-structure">
            <div className="structure-head">
              <div>
                <b>Build this, top to bottom</b>
                <p>
                  Each block is a section of the email, in order. Every one of them comes from
                  a real email this brand already sent — the names underneath say which.
                  Recreate them in Figma, Klaviyo, or whatever you design in.
                </p>
              </div>
              <div className="structure-actions">
                <code className="signature">{rec.structure_signature}</code>
                <button className="ghost tiny" data-testid="rec-copy-structure" onClick={copyStructure}>
                  {copied ? <><Check size={12} /> Copied</> : <><ClipboardList size={12} /> Copy structure</>}
                </button>
              </div>
            </div>
            <ol className="structure-list">
              {rec.recommended_structure.map(s => (
                <li key={s.position} data-testid={`block-${s.block}`}>
                  <span className="block-num">{String(s.position).padStart(2, '0')}</span>
                  <div className="block-body">
                    <b>{s.label}</b>
                    <p>{s.purpose}</p>
                    <span className="mini-label">
                      Used in {s.evidence_count} cited send{s.evidence_count === 1 ? '' : 's'}
                      {(s.grounded_in || []).length > 0 && `: ${s.grounded_in.map(g => g.name).join(', ')}`}
                    </span>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}
        {hasEvidence && (rec.recommended_structure || []).length === 0 && (
          <div className="conflict-panel" data-testid="rec-no-structure">
            <AlertTriangle size={16} />
            <div>
              <b>No layout could be grounded in past sends.</b>
              <p>The cited campaigns have no readable HTML structure. Sync or paste a few emails with their HTML, then re-run this campaign.</p>
            </div>
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
                {e.campaign.module_signature && (
                  <span className="mini-label">Layout: <code>{e.campaign.module_signature}</code></span>
                )}
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
  const [research, setResearch] = useState(null);
  useEffect(() => {
    api.get(`/brands/${brandId}`).then(r => { setD(r.data); setG(r.data.guidelines || {}); });
    api.get(`/brands/${brandId}/research/latest`).then(r => setResearch(r.data)).catch(() => {});
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
  const approveResearch = async () => {
    if (!window.confirm('Apply these reviewed research candidates as a new rules version?')) return;
    try {
      const r = await api.post(`/brands/${brandId}/research/${research.id}/apply`, {approved:true});
      setG(r.data); setResearch({...research,status:'approved'}); toast.success('Research approved as a new rules version');
    } catch (e) { toast.error(e.response?.data?.detail || 'Research could not be applied'); }
  };
  if (!d || !g) return <FullLoader />;
  const isDemo = isDemoWorkspace(d);
  return (
    <Shell active="guidelines" brand={d.brand} org={d.organization} isDemo={isDemo}>
      <Header eyebrow="RULES" title="The guardrails behind every recommendation." isDemo={isDemo} />
      <p className="page-sub">Prohibited claims are hard rules — they block export. Everything else is guidance.</p>
      {isDemo && <div className="demo-notice"><LockKeyhole size={15}/><span>Sample rules are read-only. Create an account to set your own immutable versions.</span></div>}
      {research?.status === 'awaiting_review' && !isDemo && <div className="research-review"><ResearchSummary research={research}/><div><b>Human approval required</b><p>Review the cited report before merging its voice, claim, and layout candidates into a new immutable rules version.</p><button className="outline" onClick={approveResearch}>Approve reviewed candidates</button></div></div>}
      <div className="memory-grid">
        <ChipsField label="Voice & tone" testid="g-tone" items={g.tone || []} onChange={v => setG({ ...g, tone: v })} placeholder="warm, quietly confident…" readOnly={isDemo} />
        <ChipsField label="Approved claims" testid="g-approved" items={g.approved_claims || []} onChange={v => setG({ ...g, approved_claims: v })} placeholder="small-batch roasted…" readOnly={isDemo} />
        <ChipsField label="Prohibited claims" testid="g-prohibited" danger items={g.prohibited_claims || []} onChange={v => setG({ ...g, prohibited_claims: v })} placeholder="detox, cures anxiety…" readOnly={isDemo} />
        <ChipsField label="Layout rules" testid="g-layout" items={g.layout_rules || []} onChange={v => setG({ ...g, layout_rules: v })} placeholder="single primary CTA…" readOnly={isDemo} />
      </div>
      <label className="wide">CTA style<input data-testid="g-cta" value={g.cta_style || ''} onChange={e => setG({ ...g, cta_style: e.target.value })} disabled={isDemo} /></label>
      {!isDemo && <button className="primary" data-testid="g-save" onClick={save}>Save new version <Check size={14} /></button>}
    </Shell>
  );
}

// ------------------------------------------------------------------ Misc
function DemoRedirect() {
  const [target, setTarget] = useState(null);
  useEffect(() => { api.get('/demo').then(r => { localStorage.setItem('bmos:demo', 'true'); setTarget(r.data); }).catch(() => setTarget(false)); }, []);
  if (target === null) return <FullLoader />;
  if (target === false) return <div className="landing"><div className="landing-copy"><h1>Demo unavailable</h1><p>The API on port 8000 is down or Mongo has not seeded yet. Start the backend, then retry.</p><Link className="primary large" to="/">Back</Link></div></div>;
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

function BrandGone({ status }) {
  return (
    <div className="landing">
      <div className="landing-copy">
        <div className="brand-mark dark"><span>BM</span><b>Brand Memory</b></div>
        <h1>{status === 404 ? 'This brand no longer exists.' : 'We could not load this brand.'}</h1>
        <p>
          {status === 404
            ? 'The link points at a brand that has been removed, or belongs to a workspace you left.'
            : 'The API did not respond. Check that the backend is running, then try again.'}
        </p>
        <Link className="primary large" to="/">Back to start <ArrowLeft size={14} /></Link>
      </div>
    </div>
  );
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
        <Route path="/auth" element={<AuthPage />} />
        <Route path="/onboarding" element={<Protected><Onboarding /></Protected>} />
        <Route path="/demo" element={<DemoRedirect />} />
        <Route path="/app/:orgId/:brandId/dashboard" element={<Protected><Dashboard /></Protected>} />
        <Route path="/app/:orgId/:brandId/campaigns" element={<Protected><Campaigns /></Protected>} />
        <Route path="/app/:orgId/:brandId/briefs/new" element={<Protected><BriefNew /></Protected>} />
        <Route path="/app/:orgId/:brandId/recommendations/:recId" element={<Protected><Recommendation /></Protected>} />
        <Route path="/app/:orgId/:brandId/guidelines" element={<Protected><GuidelinesPage /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
