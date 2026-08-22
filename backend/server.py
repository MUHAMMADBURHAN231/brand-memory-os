"""Brand Memory OS — Hackathon vertical slice backend."""
from __future__ import annotations
import os, io, json, uuid, math, logging, asyncio, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Literal

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form, Request, Response, Cookie, BackgroundTasks
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from itsdangerous import URLSafeSerializer, BadSignature

# ------------------------------------------------------------------ setup
load_dotenv(Path(__file__).parent / '.env')
LOG = logging.getLogger('brand-memory')
logging.basicConfig(level=logging.INFO)

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
EMERGENT_KEY = os.environ.get('EMERGENT_LLM_KEY')
APP_NAME = 'brand-memory-os'
LLM_MODEL = 'gpt-5.4'
EMBED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
SESSION_SECRET = os.environ.get('SESSION_SECRET', 'brand-memory-dev-secret-2026')
STORAGE_BASE = (os.environ.get('INTEGRATION_PROXY_URL') or '').strip() or 'https://integrations.emergentagent.com'
STORAGE_URL = STORAGE_BASE.rstrip('/') + '/objstore/api/v1/storage'

signer = URLSafeSerializer(SESSION_SECRET, salt='bm-session')
client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# lazy-loaded singletons
_embedder = None
_storage_key: Optional[str] = None


def get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        LOG.info('Loading embedder %s', EMBED_MODEL)
        _embedder = SentenceTransformer(EMBED_MODEL, device='cpu')
    return _embedder


def embed(text: str) -> list[float]:
    text = (text or '').strip() or 'empty'
    v = get_embedder().encode(text, normalize_embeddings=True)
    return v.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return float(sum(x * y for x, y in zip(a, b)))


# --------------- object storage
def init_storage(force: bool = False) -> Optional[str]:
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    if not EMERGENT_KEY:
        return None
    try:
        r = requests.post(f'{STORAGE_URL}/init', json={'emergent_key': EMERGENT_KEY}, timeout=15)
        r.raise_for_status()
        _storage_key = r.json()['storage_key']
        LOG.info('Object storage ready')
        return _storage_key
    except Exception as e:
        LOG.warning('Storage init failed: %s', e)
        return None


def storage_put(path: str, data: bytes, content_type: str) -> str:
    key = init_storage()
    if not key:
        raise RuntimeError('storage unavailable')
    r = requests.put(f'{STORAGE_URL}/objects/{path}',
                     headers={'X-Storage-Key': key, 'Content-Type': content_type},
                     data=data, timeout=60)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = requests.put(f'{STORAGE_URL}/objects/{path}',
                         headers={'X-Storage-Key': key, 'Content-Type': content_type},
                         data=data, timeout=60)
    r.raise_for_status()
    return r.json()['path']


def storage_get(path: str) -> tuple[bytes, str]:
    key = init_storage()
    r = requests.get(f'{STORAGE_URL}/objects/{path}', headers={'X-Storage-Key': key}, timeout=30)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = requests.get(f'{STORAGE_URL}/objects/{path}', headers={'X-Storage-Key': key}, timeout=30)
    r.raise_for_status()
    return r.content, r.headers.get('Content-Type', 'application/octet-stream')


# --------------- LLM (extraction + rationale)
async def llm_json(system: str, user: str) -> dict:
    """Call GPT-5.4 and return parsed JSON. Never fabricates on failure."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    session_id = f'extract-{uuid.uuid4().hex[:8]}'
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=session_id,
                   system_message=system).with_model('openai', LLM_MODEL)
    resp = await chat.send_message(UserMessage(text=user))
    text = resp if isinstance(resp, str) else str(resp)
    # extract first JSON blob
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError('non-json response')
    return json.loads(m.group(0))


async def llm_text(system: str, user: str) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    session_id = f'rationale-{uuid.uuid4().hex[:8]}'
    chat = LlmChat(api_key=EMERGENT_KEY, session_id=session_id,
                   system_message=system).with_model('openai', LLM_MODEL)
    resp = await chat.send_message(UserMessage(text=user))
    return resp if isinstance(resp, str) else str(resp)


EXTRACT_SYSTEM = (
    "You extract structured facts from marketing email assets. "
    "You never invent metrics or claims. If a field is not present in the input, "
    "return null. Respond with ONLY a JSON object, no prose."
)
EXTRACT_SCHEMA = (
    "Return this JSON exactly: "
    '{"subject":str|null,"preview":str|null,"objective":str|null,'
    '"audience":str|null,"offer":str|null,"cta":str|null,'
    '"module_order":[str],"copy_intent":str|null,"layout_pattern":str|null,'
    '"tone_hints":[str],"claims":[str],"summary":str}'
)


def extract_html(data: bytes) -> str:
    try:
        soup = BeautifulSoup(data.decode('utf-8', errors='ignore'), 'html.parser')
        for s in soup(['script', 'style']):
            s.decompose()
        return re.sub(r'\s+', ' ', soup.get_text(' ')).strip()
    except Exception:
        return ''


def extract_pdf(data: bytes) -> str:
    try:
        r = PdfReader(io.BytesIO(data))
        return ' '.join((p.extract_text() or '') for p in r.pages).strip()
    except Exception:
        return ''


def extract_text(data: bytes, content_type: str, filename: str) -> str:
    ct = (content_type or '').lower()
    if 'html' in ct or filename.endswith('.html'):
        return extract_html(data)
    if 'pdf' in ct or filename.endswith('.pdf'):
        return extract_pdf(data)
    return ''


# --------------- session identity
def owner_id(request: Request) -> str:
    raw = request.cookies.get('bmos_owner')
    if raw:
        try:
            return signer.loads(raw)
        except BadSignature:
            pass
    raise HTTPException(401, 'no session')


def ensure_owner(response: Response, request: Request) -> str:
    raw = request.cookies.get('bmos_owner')
    if raw:
        try:
            return signer.loads(raw)
        except BadSignature:
            pass
    new = uuid.uuid4().hex
    response.set_cookie('bmos_owner', signer.dumps(new), max_age=60 * 60 * 24 * 30,
                        httponly=True, samesite='none', secure=True)
    return new


# --------------- models
class Guidelines(BaseModel):
    tone: list[str] = []
    approved_claims: list[str] = []
    prohibited_claims: list[str] = []
    colors: list[str] = []
    layout_rules: list[str] = []
    cta_style: str = ''


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal['agency', 'brand', 'in-house'] = 'brand'
    role: str = ''
    managed_brands: int = 1
    industry: str = ''


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = ''
    industry: str = ''
    market: str = ''


class OnboardingPatch(BaseModel):
    step: int = Field(ge=1, le=5)
    complete: bool = False
    data_choice: Optional[Literal['upload', 'sample', 'skip']] = None


class BriefIn(BaseModel):
    objective: str = Field(min_length=2)
    audience: str = Field(min_length=2)
    offer: str = Field(min_length=2)
    constraints: str = ''


class OutcomeIn(BaseModel):
    sent_at: str = ''
    delivery: float = 0
    open: float = Field(ge=0, le=100)
    click: float = Field(ge=0, le=100)
    conversion: float = 0
    revenue: float = 0
    notes: str = ''


# --------------- helpers
def now(): return datetime.now(timezone.utc).isoformat()


async def load_brand(brand_id: str, owner: str) -> dict:
    b = await db.brands.find_one({'id': brand_id}, {'_id': 0})
    if not b:
        raise HTTPException(404, 'brand not found')
    org = await db.organizations.find_one({'id': b['org_id']}, {'_id': 0})
    if not org or (org['owner_session_id'] != owner and not org.get('is_demo')):
        raise HTTPException(403, 'not your brand')
    return b


async def active_guidelines(brand_id: str) -> dict:
    b = await db.brands.find_one({'id': brand_id}, {'_id': 0})
    if not b:
        return {}
    v = b.get('active_guideline_version') or 1
    g = await db.guideline_sets.find_one({'brand_id': brand_id, 'version': v}, {'_id': 0})
    return g or {}


def validate_rules(text: str, guidelines: dict) -> list[dict]:
    """Deterministic rule enforcement. Independent of any LLM."""
    text_l = (text or '').lower()
    violations = []
    for claim in guidelines.get('prohibited_claims', []) or []:
        if claim and claim.lower() in text_l:
            violations.append({
                'severity': 'blocked',
                'rule': claim,
                'remedy': f'Remove the phrase "{claim}" or replace with an approved claim.'
            })
    return violations


async def rank_recommendations(brief: dict, brand_id: str) -> list[dict]:
    """Semantic retrieval with score breakdown. Returns cited campaigns."""
    text = f"{brief['objective']}. {brief['audience']}. {brief['offer']}. {brief.get('constraints','')}"
    q = embed(text)
    candidates = [c async for c in db.campaigns.find(
        {'brand_id': brand_id, 'status': 'ready'}, {'_id': 0})]
    ranked = []
    for c in candidates:
        emb = c.get('embedding')
        if not emb:
            continue
        sem = cosine(q, emb)
        obj_match = 1.0 if brief['objective'].lower().split()[0] in (c.get('objective') or '').lower() else 0.0
        aud_match = 1.0 if any(w and w in (c.get('audience') or '').lower()
                               for w in brief['audience'].lower().split()) else 0.0
        ev_quality = 1.0 if (c.get('metrics') or {}).get('open') else 0.4
        score = 0.65 * sem + 0.15 * obj_match + 0.10 * aud_match + 0.10 * ev_quality
        ranked.append({
            'campaign_id': c['id'],
            'campaign': c,
            'semantic_similarity': round(sem, 4),
            'objective_match': obj_match,
            'audience_match': aud_match,
            'evidence_quality': ev_quality,
            'score': round(score, 4),
        })
    ranked.sort(key=lambda x: x['score'], reverse=True)
    return ranked


# --------------- app
app = FastAPI(title='Brand Memory OS')
api = APIRouter(prefix='/api')


@app.on_event('startup')
async def startup():
    init_storage()
    asyncio.create_task(asyncio.to_thread(get_embedder))  # warm
    await ensure_seed()


@app.on_event('shutdown')
async def shutdown():
    client.close()


# --------------- session
@api.post('/session')
async def session_endpoint(request: Request, response: Response):
    sid = ensure_owner(response, request)
    orgs = [o async for o in db.organizations.find(
        {'owner_session_id': sid}, {'_id': 0, 'owner_session_id': 0})]
    return {'session_id': sid, 'organizations': orgs}


# --------------- organizations
@api.post('/organizations')
async def create_org(body: OrgCreate, request: Request, response: Response):
    sid = ensure_owner(response, request)
    org = {
        'id': uuid.uuid4().hex, 'name': body.name, 'type': body.type, 'role': body.role,
        'managed_brands': body.managed_brands, 'industry': body.industry,
        'owner_session_id': sid, 'onboarding_step': 1, 'onboarding_complete': False,
        'is_demo': False, 'created_at': now(),
    }
    await db.organizations.insert_one(org)
    org.pop('_id', None); org.pop('owner_session_id', None)
    return org


@api.patch('/organizations/{org_id}/onboarding')
async def patch_onboarding(org_id: str, body: OnboardingPatch, request: Request):
    sid = owner_id(request)
    org = await db.organizations.find_one({'id': org_id})
    if not org or org['owner_session_id'] != sid:
        raise HTTPException(403, 'not your organization')
    upd = {'onboarding_step': body.step}
    if body.complete:
        upd['onboarding_complete'] = True
    if body.data_choice:
        upd['data_choice'] = body.data_choice
    await db.organizations.update_one({'id': org_id}, {'$set': upd})
    return {'ok': True, **upd}


# --------------- brands
@api.post('/organizations/{org_id}/brands')
async def create_brand(org_id: str, body: BrandCreate, request: Request):
    sid = owner_id(request)
    org = await db.organizations.find_one({'id': org_id})
    if not org or org['owner_session_id'] != sid:
        raise HTTPException(403, 'not your organization')
    brand = {
        'id': uuid.uuid4().hex, 'org_id': org_id, 'name': body.name, 'url': body.url,
        'industry': body.industry, 'market': body.market,
        'memory_status': 'empty', 'active_guideline_version': 1, 'created_at': now(),
    }
    await db.brands.insert_one(brand)
    # create empty guidelines v1
    await db.guideline_sets.insert_one({
        'id': uuid.uuid4().hex, 'org_id': org_id, 'brand_id': brand['id'], 'version': 1,
        **Guidelines().model_dump(), 'created_at': now(),
    })
    brand.pop('_id', None)
    return brand


@api.get('/brands/{brand_id}')
async def get_brand(brand_id: str, request: Request):
    sid = owner_id(request)
    b = await load_brand(brand_id, sid)
    g = await active_guidelines(brand_id)
    org = await db.organizations.find_one({'id': b['org_id']}, {'_id': 0, 'owner_session_id': 0})
    return {'brand': b, 'guidelines': g, 'organization': org}


@api.patch('/brands/{brand_id}/guidelines')
async def update_guidelines(brand_id: str, body: Guidelines, request: Request):
    sid = owner_id(request)
    b = await load_brand(brand_id, sid)
    new_v = (b.get('active_guideline_version') or 0) + 1
    doc = {'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brand_id,
           'version': new_v, **body.model_dump(), 'created_at': now()}
    await db.guideline_sets.insert_one(doc)
    await db.brands.update_one({'id': brand_id}, {'$set': {'active_guideline_version': new_v}})
    doc.pop('_id', None)
    return doc


# --------------- campaigns / ingestion
async def process_campaign(campaign_id: str, storage_path: str, content_type: str, filename: str):
    """Background: fetch file, extract text, LLM analyze, embed, mark ready."""
    try:
        data, ct = storage_get(storage_path)
        raw = extract_text(data, ct, filename)
        if not raw.strip() and not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            raise ValueError('no extractable text')
        text_sample = raw[:6000] if raw else f'[image asset: {filename}]'
        try:
            structured = await llm_json(EXTRACT_SYSTEM,
                                        f'{EXTRACT_SCHEMA}\n\nEmail asset text:\n{text_sample}')
        except Exception as e:
            LOG.warning('LLM extract failed: %s', e)
            structured = {'subject': None, 'summary': text_sample[:400], 'objective': None,
                          'audience': None, 'offer': None, 'module_order': [], 'tone_hints': [],
                          'claims': [], 'copy_intent': None, 'layout_pattern': None, 'cta': None}
        summary = structured.get('summary') or text_sample[:400]
        emb = await asyncio.to_thread(embed, summary)
        await db.campaigns.update_one(
            {'id': campaign_id},
            {'$set': {
                'status': 'ready', 'extracted': structured, 'embedding': emb,
                'embedding_model': EMBED_MODEL, 'llm_model': LLM_MODEL,
                'objective': structured.get('objective'),
                'audience': structured.get('audience'),
                'offer': structured.get('offer'),
                'subject': structured.get('subject'),
                'processed_at': now(),
            }}
        )
    except Exception as e:
        LOG.exception('process_campaign failed')
        await db.campaigns.update_one({'id': campaign_id},
                                      {'$set': {'status': 'failed', 'error': str(e)[:200]}})


@api.post('/brands/{brand_id}/campaigns/upload')
async def upload_campaign(brand_id: str, request: Request, background: BackgroundTasks,
                          file: UploadFile = File(...), name: str = Form(...)):
    sid = owner_id(request)
    b = await load_brand(brand_id, sid)
    ext = (file.filename or 'bin').rsplit('.', 1)[-1].lower()
    if ext not in {'html', 'htm', 'pdf', 'png', 'jpg', 'jpeg'}:
        raise HTTPException(400, 'unsupported file type')
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, 'file too large (10MB max)')
    path = f'{APP_NAME}/campaigns/{b["org_id"]}/{brand_id}/{uuid.uuid4().hex}.{ext}'
    try:
        storage_put(path, data, file.content_type or 'application/octet-stream')
    except Exception as e:
        LOG.warning('upload failed: %s', e)
        raise HTTPException(503, 'storage unavailable, try again')
    campaign_id = uuid.uuid4().hex
    await db.campaigns.insert_one({
        'id': campaign_id, 'org_id': b['org_id'], 'brand_id': brand_id,
        'name': name, 'source_type': ext, 'file_path': path,
        'content_type': file.content_type, 'original_filename': file.filename,
        'status': 'processing', 'metrics': {}, 'created_at': now(),
    })
    background.add_task(process_campaign, campaign_id, path, file.content_type or '', file.filename or '')
    return {'campaign_id': campaign_id, 'status': 'processing'}


class PasteIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source: str = 'paste'  # 'klaviyo' | 'figma' | 'mailchimp' | 'hubspot' | 'iterable' | 'paste'
    html: str = Field(min_length=1, max_length=200000)


async def process_pasted(campaign_id: str, html: str, filename: str):
    try:
        raw = extract_html(html.encode('utf-8'))
        text_sample = (raw or html)[:6000]
        try:
            structured = await llm_json(EXTRACT_SYSTEM,
                                        f'{EXTRACT_SCHEMA}\n\nEmail asset text:\n{text_sample}')
        except Exception as e:
            LOG.warning('LLM extract failed: %s', e)
            structured = {'subject': None, 'summary': text_sample[:400], 'objective': None,
                          'audience': None, 'offer': None, 'module_order': [], 'tone_hints': [],
                          'claims': [], 'copy_intent': None, 'layout_pattern': None, 'cta': None}
        summary = structured.get('summary') or text_sample[:400]
        emb = await asyncio.to_thread(embed, summary)
        await db.campaigns.update_one(
            {'id': campaign_id},
            {'$set': {
                'status': 'ready', 'extracted': structured, 'embedding': emb,
                'embedding_model': EMBED_MODEL, 'llm_model': LLM_MODEL,
                'objective': structured.get('objective'),
                'audience': structured.get('audience'),
                'offer': structured.get('offer'),
                'subject': structured.get('subject'),
                'processed_at': now(),
            }}
        )
    except Exception as e:
        LOG.exception('process_pasted failed')
        await db.campaigns.update_one({'id': campaign_id},
                                       {'$set': {'status': 'failed', 'error': str(e)[:200]}})


@api.post('/brands/{brand_id}/campaigns/paste')
async def paste_campaign(brand_id: str, body: PasteIn, request: Request, background: BackgroundTasks):
    """Accept pasted HTML from Klaviyo / Figma / Mailchimp / HubSpot / Iterable etc.
    Same analysis pipeline as upload — no file storage roundtrip."""
    sid = owner_id(request)
    b = await load_brand(brand_id, sid)
    campaign_id = uuid.uuid4().hex
    await db.campaigns.insert_one({
        'id': campaign_id, 'org_id': b['org_id'], 'brand_id': brand_id,
        'name': body.name, 'source_type': body.source, 'file_path': None,
        'pasted_html': body.html[:200000],
        'status': 'processing', 'metrics': {}, 'created_at': now(),
    })
    background.add_task(process_pasted, campaign_id, body.html, body.name)
    return {'campaign_id': campaign_id, 'status': 'processing', 'source': body.source}


@api.get('/brands/{brand_id}/campaigns')
async def list_campaigns(brand_id: str, request: Request):
    sid = owner_id(request)
    await load_brand(brand_id, sid)
    return [c async for c in db.campaigns.find(
        {'brand_id': brand_id}, {'_id': 0, 'embedding': 0}
    ).sort('created_at', -1)]


@api.get('/campaigns/{campaign_id}')
async def get_campaign(campaign_id: str, request: Request):
    sid = owner_id(request)
    c = await db.campaigns.find_one({'id': campaign_id}, {'_id': 0, 'embedding': 0})
    if not c:
        raise HTTPException(404, 'campaign not found')
    await load_brand(c['brand_id'], sid)
    return c


@api.get('/campaigns/{campaign_id}/file')
async def get_campaign_file(campaign_id: str, request: Request):
    sid = owner_id(request)
    c = await db.campaigns.find_one({'id': campaign_id}, {'_id': 0})
    if not c:
        raise HTTPException(404, 'campaign not found')
    await load_brand(c['brand_id'], sid)
    try:
        data, ct = storage_get(c['file_path'])
    except Exception:
        raise HTTPException(404, 'file unavailable')
    return Response(content=data, media_type=c.get('content_type') or ct)


# --------------- briefs & recommendations
@api.post('/brands/{brand_id}/briefs')
async def create_brief(brand_id: str, body: BriefIn, request: Request):
    sid = owner_id(request)
    b = await load_brand(brand_id, sid)
    g = await active_guidelines(brand_id)
    # deterministic pre-check on brief itself
    violations = validate_rules(body.offer + ' ' + body.constraints, g)
    brief = {
        'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brand_id,
        **body.model_dump(), 'guideline_version': b.get('active_guideline_version', 1),
        'status': 'ready' if not violations else 'needs_edit',
        'brief_violations': violations, 'created_at': now(),
    }
    await db.briefs.insert_one(brief)
    brief.pop('_id', None)
    return brief


@api.post('/briefs/{brief_id}/recommendations')
async def make_recommendations(brief_id: str, request: Request):
    sid = owner_id(request)
    brief = await db.briefs.find_one({'id': brief_id}, {'_id': 0})
    if not brief:
        raise HTTPException(404, 'brief not found')
    b = await load_brand(brief['brand_id'], sid)
    g = await active_guidelines(brief['brand_id'])
    ranked = await rank_recommendations(brief, brief['brand_id'])
    threshold = 0.35
    kept = [r for r in ranked if r['semantic_similarity'] >= threshold][:5]

    rationale = None
    if kept:
        try:
            src = '\n\n'.join(
                f"CAMPAIGN {r['campaign_id']}: subject='{r['campaign'].get('subject')}' "
                f"objective='{r['campaign'].get('objective')}' "
                f"audience='{r['campaign'].get('audience')}' "
                f"summary='{(r['campaign'].get('extracted') or {}).get('summary','')[:300]}' "
                f"metrics={r['campaign'].get('metrics') or {}}"
                for r in kept
            )
            prompt = (
                f"Brief: objective={brief['objective']}; audience={brief['audience']}; "
                f"offer={brief['offer']}; constraints={brief.get('constraints','')}\n\n"
                f"Retrieved evidence:\n{src}\n\n"
                "Write 2 short paragraphs: (1) why these campaigns are relevant, citing them by ID; "
                "(2) a recommended section structure for the new email, grounded ONLY in retrieved "
                "evidence and the brief. Do not invent metrics. If evidence is weak on any dimension, say so."
            )
            rationale = await llm_text(
                "You are a lifecycle marketing strategist. Ground every claim in the provided evidence.",
                prompt,
            )
        except Exception as e:
            LOG.warning('rationale failed: %s', e)
            rationale = None

    # deterministic rule violations against brief + top recommendation
    text_to_check = brief['offer'] + ' ' + brief.get('constraints', '')
    if kept:
        text_to_check += ' ' + ((kept[0]['campaign'].get('extracted') or {}).get('summary') or '')
    violations = validate_rules(text_to_check, g)

    rec = {
        'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brief['brand_id'],
        'brief_id': brief_id,
        'source_campaign_ids': [r['campaign_id'] for r in kept],
        'evidence': [
            {**r, 'campaign': {k: v for k, v in r['campaign'].items() if k != 'embedding'}}
            for r in kept
        ],
        'rationale': rationale,
        'rationale_model': LLM_MODEL if rationale else None,
        'rule_violations': violations,
        'guideline_version': b.get('active_guideline_version', 1),
        'evidence_strength': 'strong' if kept and kept[0]['score'] >= 0.6
                             else 'moderate' if kept else 'insufficient',
        'created_at': now(),
    }
    await db.recommendations.insert_one(rec)
    rec.pop('_id', None)
    return rec


@api.get('/recommendations/{rec_id}')
async def get_rec(rec_id: str, request: Request):
    sid = owner_id(request)
    r = await db.recommendations.find_one({'id': rec_id}, {'_id': 0})
    if not r:
        raise HTTPException(404)
    await load_brand(r['brand_id'], sid)
    return r


# --------------- blueprint
@api.post('/recommendations/{rec_id}/blueprint')
async def make_blueprint(rec_id: str, request: Request):
    sid = owner_id(request)
    rec = await db.recommendations.find_one({'id': rec_id}, {'_id': 0})
    if not rec:
        raise HTTPException(404, 'recommendation not found')
    await load_brand(rec['brand_id'], sid)
    if rec['rule_violations']:
        raise HTTPException(409, {
            'error': 'blocked',
            'violations': rec['rule_violations'],
        })
    if not rec['source_campaign_ids']:
        raise HTTPException(422, 'no evidence — cannot ground a blueprint')
    brief = await db.briefs.find_one({'id': rec['brief_id']}, {'_id': 0})
    g = await active_guidelines(rec['brand_id'])
    ev = rec['evidence'][0]['campaign']
    md = (
        f"# Campaign blueprint\n\n"
        f"## Objective\n{brief['objective']}\n\n"
        f"## Audience\n{brief['audience']}\n\n"
        f"## Offer\n{brief['offer']}\n\n"
        f"## Grounded in\n- {ev.get('name')} (campaign {ev.get('id')})\n\n"
        f"## Suggested structure\n"
        f"1. Hero — carry the tone from '{ev.get('subject','the source subject')}'\n"
        f"2. Proof — reuse the evidence pattern that worked for {ev.get('audience','this audience')}\n"
        f"3. Detail — one specific product or ritual detail (no unsupported claims)\n"
        f"4. CTA — one clear primary action; style: {g.get('cta_style') or 'brand default'}\n\n"
        f"## Guardrails applied\n"
        f"- Tone: {', '.join(g.get('tone') or []) or 'not set'}\n"
        f"- Prohibited: {', '.join(g.get('prohibited_claims') or []) or 'none'}\n\n"
        f"## Rationale\n{rec.get('rationale') or 'Rationale unavailable — grounded suggestion only.'}\n"
    )
    return {'markdown': md, 'grounded_in': [ev.get('id')], 'guideline_version': rec['guideline_version']}


# --------------- outcomes
@api.post('/campaigns/{campaign_id}/outcomes')
async def record_outcome(campaign_id: str, body: OutcomeIn, request: Request):
    sid = owner_id(request)
    c = await db.campaigns.find_one({'id': campaign_id}, {'_id': 0})
    if not c:
        raise HTTPException(404)
    await load_brand(c['brand_id'], sid)
    metrics = body.model_dump()
    await db.campaigns.update_one({'id': campaign_id},
                                  {'$set': {'metrics': metrics, 'memory_updated_at': now()}})
    await db.outcomes.insert_one({'id': uuid.uuid4().hex, 'org_id': c['org_id'],
                                   'brand_id': c['brand_id'], 'campaign_id': campaign_id,
                                   **metrics, 'created_at': now()})
    return {'saved': True, 'metrics': metrics}


# --------------- dashboard
@api.get('/brands/{brand_id}/dashboard')
async def dashboard(brand_id: str, request: Request):
    sid = owner_id(request)
    b = await load_brand(brand_id, sid)
    g = await active_guidelines(brand_id)
    campaigns = [c async for c in db.campaigns.find(
        {'brand_id': brand_id}, {'_id': 0, 'embedding': 0}
    ).sort('created_at', -1).limit(6)]
    ready = sum(1 for c in campaigns if c.get('status') == 'ready')
    processing = sum(1 for c in campaigns if c.get('status') == 'processing')
    outcomes = await db.outcomes.count_documents({'brand_id': brand_id})
    latest_rec = await db.recommendations.find_one({'brand_id': brand_id},
                                                    {'_id': 0}, sort=[('created_at', -1)])
    return {
        'brand': b, 'guidelines': g, 'recent_campaigns': campaigns,
        'readiness': {'analyzed': ready, 'processing': processing,
                       'guidelines_set': bool((g.get('tone') or []) or (g.get('prohibited_claims') or [])),
                       'outcomes_attached': outcomes},
        'latest_recommendation': latest_rec,
    }


# --------------- demo (public, read-only shortcut)
@api.get('/demo')
async def demo():
    org = await db.organizations.find_one({'is_demo': True}, {'_id': 0, 'owner_session_id': 0})
    if not org:
        raise HTTPException(503, 'demo not seeded')
    brand = await db.brands.find_one({'org_id': org['id']}, {'_id': 0})
    return {'org_id': org['id'], 'brand_id': brand['id'], 'is_demo': True}


# --------------- seed
DEMO_CAMPAIGNS = [
    {'name': 'The Monday Ritual',
     'summary': 'A warm ritual-led opener paired with one seasonal roast detail. Retention-focused editorial to active subscribers with a single product-education CTA. No discount mechanics.',
     'objective': 'retention', 'audience': 'Active subscribers',
     'offer': 'New seasonal roast', 'subject': 'Your Monday, roasted better',
     'metrics': {'open': 48.2, 'click': 7.8, 'conversion': 3.9}},
    {'name': 'Brew Guide: V60',
     'summary': 'Step-by-step brew guide teaching new subscribers a slower pour-over ritual. Engagement-focused editorial for new subscribers. No offer, purely educational.',
     'objective': 'engagement', 'audience': 'New subscribers',
     'offer': 'Brew education', 'subject': 'A slower cup, in 4 steps',
     'metrics': {'open': 44.7, 'click': 9.2, 'conversion': 2.1}},
    {'name': 'Roaster Notes',
     'summary': 'Founder note re-engagement for at-risk subscribers about a small-batch release. Retention format built as a personal letter, not a promotion.',
     'objective': 'retention', 'audience': 'At-risk subscribers',
     'offer': 'Re-engagement', 'subject': 'A note from the roastery',
     'metrics': {}},
]


async def ensure_seed():
    if await db.organizations.count_documents({'is_demo': True}):
        return
    org_id = uuid.uuid4().hex
    brand_id = uuid.uuid4().hex
    await db.organizations.insert_one({
        'id': org_id, 'name': 'Northstar Coffee Co. (Sample)', 'type': 'brand',
        'role': 'Lifecycle marketing', 'managed_brands': 1, 'industry': 'DTC coffee',
        'owner_session_id': '__demo__', 'is_demo': True,
        'onboarding_step': 5, 'onboarding_complete': True, 'created_at': now(),
    })
    await db.brands.insert_one({
        'id': brand_id, 'org_id': org_id, 'name': 'Northstar Coffee Co.',
        'url': 'https://northstar.coffee', 'industry': 'DTC coffee subscription',
        'market': 'US', 'memory_status': 'ready', 'active_guideline_version': 1,
        'created_at': now(),
    })
    await db.guideline_sets.insert_one({
        'id': uuid.uuid4().hex, 'org_id': org_id, 'brand_id': brand_id, 'version': 1,
        'tone': ['warm', 'specific', 'quietly confident'],
        'approved_claims': ['small-batch roasted', 'ships within 48 hours', 'flexible delivery'],
        'prohibited_claims': ['cures anxiety', 'guaranteed energy', 'detox', 'free forever'],
        'colors': ['#173F35', '#F4B860', '#F8F4EC'],
        'layout_rules': ['One clear hero', 'Short scannable sections', 'Single primary CTA'],
        'cta_style': 'Editorial, verb-led, no urgency shouting', 'created_at': now(),
    })
    # embed and insert seeded campaigns synchronously so demo is instant
    embedder_ready = get_embedder()
    for c in DEMO_CAMPAIGNS:
        cid = uuid.uuid4().hex
        emb = embed(c['summary'])
        await db.campaigns.insert_one({
            'id': cid, 'org_id': org_id, 'brand_id': brand_id,
            'name': c['name'], 'source_type': 'seed', 'file_path': None,
            'status': 'ready', 'objective': c['objective'], 'audience': c['audience'],
            'offer': c['offer'], 'subject': c['subject'],
            'metrics': c['metrics'], 'extracted': {'summary': c['summary'],
                                                    'subject': c['subject'],
                                                    'objective': c['objective'],
                                                    'audience': c['audience'],
                                                    'offer': c['offer']},
            'embedding': emb, 'embedding_model': EMBED_MODEL, 'llm_model': None,
            'is_sample': True, 'created_at': now(),
        })
    LOG.info('demo seed inserted org=%s brand=%s', org_id, brand_id)


# ------------------------------------------------------------------ mount
app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=['*'],
    allow_headers=['*'],
)
