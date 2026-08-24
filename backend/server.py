"""Brand Memory OS — Hackathon vertical slice backend."""
from __future__ import annotations
import os, io, json, uuid, logging, asyncio, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Literal

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Form, Request, Response, BackgroundTasks
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, EmailStr, Field, field_validator
from security import (
    create_session, destroy_session, hash_password, limiter, require_user,
    utcnow, validate_public_url, verify_password,
)
from services.brand_research import BrandResearchReport, run_brand_research

# ------------------------------------------------------------------ setup
load_dotenv(Path(__file__).parent / '.env')
LOG = logging.getLogger('brand-memory')
logging.basicConfig(level=logging.INFO)

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
EMERGENT_KEY = os.environ.get('EMERGENT_LLM_KEY')
APP_NAME = 'brand-memory-os'
LLM_MODEL = os.environ.get('OPENAI_EXTRACTION_MODEL', 'gpt-5-mini')
EMBED_MODEL = 'sentence-transformers/all-MiniLM-L6-v2'
STORAGE_BASE = (os.environ.get('INTEGRATION_PROXY_URL') or '').strip() or 'https://integrations.emergentagent.com'
STORAGE_URL = STORAGE_BASE.rstrip('/') + '/objstore/api/v1/storage'

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# lazy-loaded singletons
_embedder = None
_storage_key: Optional[str] = None
LOCAL_STORAGE_DIR = Path(os.environ.get('LOCAL_STORAGE_DIR', '/tmp/brand-memory-os'))


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
        target = (LOCAL_STORAGE_DIR / path).resolve()
        if LOCAL_STORAGE_DIR.resolve() not in target.parents:
            raise RuntimeError('invalid storage path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path
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
    if not key:
        target = (LOCAL_STORAGE_DIR / path).resolve()
        if LOCAL_STORAGE_DIR.resolve() not in target.parents or not target.is_file():
            raise FileNotFoundError(path)
        suffix_types = {'.html': 'text/html', '.pdf': 'application/pdf', '.png': 'image/png',
                        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}
        return target.read_bytes(), suffix_types.get(target.suffix.lower(), 'application/octet-stream')
    r = requests.get(f'{STORAGE_URL}/objects/{path}', headers={'X-Storage-Key': key}, timeout=30)
    if r.status_code == 404:
        key = init_storage(force=True)
        r = requests.get(f'{STORAGE_URL}/objects/{path}', headers={'X-Storage-Key': key}, timeout=30)
    r.raise_for_status()
    return r.content, r.headers.get('Content-Type', 'application/octet-stream')


# --------------- LLM (extraction + rationale)
async def llm_json(system: str, user: str) -> dict:
    """Call OpenAI directly and return parsed JSON. Never fabricates on failure."""
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY is not configured')
    from openai import AsyncOpenAI
    resp = await AsyncOpenAI().responses.create(
        model=LLM_MODEL, instructions=system, input=user,
    )
    text = resp.output_text
    # extract first JSON blob
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise ValueError('non-json response')
    return json.loads(m.group(0))


async def llm_text(system: str, user: str) -> str:
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY is not configured')
    from openai import AsyncOpenAI
    resp = await AsyncOpenAI().responses.create(model=LLM_MODEL, instructions=system, input=user)
    return resp.output_text


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


# --------------- models
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class Guidelines(BaseModel):
    tone: list[str] = []
    approved_claims: list[str] = []
    prohibited_claims: list[str] = []
    colors: list[str] = []
    layout_rules: list[str] = []
    cta_style: str = Field(default='', max_length=500)

    @field_validator('tone', 'approved_claims', 'prohibited_claims', 'colors', 'layout_rules')
    @classmethod
    def bounded_rules(cls, value: list[str]) -> list[str]:
        if len(value) > 50 or any(len(item) > 240 for item in value):
            raise ValueError('Rule lists allow up to 50 items of 240 characters')
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: Literal['agency', 'brand', 'in-house'] = 'brand'
    role: str = Field(default='', max_length=120)
    managed_brands: int = Field(default=1, ge=1, le=1000)
    industry: str = Field(default='', max_length=120)


class BrandCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = ''
    industry: str = Field(default='', max_length=120)
    market: str = Field(default='', max_length=120)

    @field_validator('url')
    @classmethod
    def website_is_public(cls, value: str) -> str:
        return validate_public_url(value) if value else ''


class OnboardingPatch(BaseModel):
    step: int = Field(ge=1, le=5)
    complete: bool = False
    data_choice: Optional[Literal['upload', 'sample', 'skip']] = None


class ResearchIn(BaseModel):
    url: str = ''
    notes: str = Field(default='', max_length=4000)


class ApplyResearchIn(BaseModel):
    approved: bool


class BriefIn(BaseModel):
    objective: str = Field(min_length=2, max_length=500)
    audience: str = Field(min_length=2, max_length=500)
    offer: str = Field(min_length=2, max_length=1000)
    constraints: str = Field(default='', max_length=2000)


class OutcomeIn(BaseModel):
    sent_at: str = ''
    delivery: float = 0
    open: float = Field(ge=0, le=100)
    click: float = Field(ge=0, le=100)
    conversion: float = 0
    revenue: float = 0
    notes: str = ''


class ConnectIn(BaseModel):
    provider: Literal['klaviyo', 'mailchimp']
    api_key: str = Field(min_length=8, max_length=400)


# --------------- helpers
def now(): return datetime.now(timezone.utc).isoformat()


async def authorize_org(org_id: str, user_id: str, *, write: bool = False) -> dict:
    org = await db.organizations.find_one({'id': org_id}, {'_id': 0})
    if not org:
        raise HTTPException(404, 'organization not found')
    if org.get('is_demo'):
        if write:
            raise HTTPException(403, 'The sample workspace is read-only')
        return org
    member = await db.organization_members.find_one({'org_id': org_id, 'user_id': user_id})
    if not member:
        raise HTTPException(403, 'not your organization')
    return org


async def load_brand(brand_id: str, user_id: str, *, write: bool = False) -> dict:
    b = await db.brands.find_one({'id': brand_id}, {'_id': 0})
    if not b:
        raise HTTPException(404, 'brand not found')
    await authorize_org(b['org_id'], user_id, write=write)
    return b


async def require_viewer(request: Request) -> dict:
    """Permit an explicit, read-only demo viewer; private data still requires auth."""
    if request.headers.get('X-Demo-Access') == 'read-only':
        return {'id': '__demo__'}
    return await require_user(db, request)


async def active_guidelines(brand_id: str) -> dict:
    b = await db.brands.find_one({'id': brand_id}, {'_id': 0})
    if not b:
        return {}
    v = b.get('active_guideline_version') or 1
    g = await db.guideline_sets.find_one({'brand_id': brand_id, 'version': v}, {'_id': 0})
    return g or {}


def fetch_public_website(url: str) -> tuple[str, str]:
    """Fetch a bounded public page while re-validating every redirect target."""
    current = validate_public_url(url)
    for _ in range(4):
        response = requests.get(
            current, timeout=(5, 12), allow_redirects=False,
            headers={'User-Agent': 'BrandMemoryResearch/1.0'}, stream=True,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get('Location')
            if not location:
                raise ValueError('Website redirect was invalid')
            from urllib.parse import urljoin
            current = validate_public_url(urljoin(current, location))
            continue
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' not in content_type:
            raise ValueError('Brand research currently supports HTML websites')
        data = response.raw.read(1_000_001, decode_content=True)
        if len(data) > 1_000_000:
            raise ValueError('Website page is too large')
        return current, extract_html(data)[:50_000]
    raise ValueError('Website redirected too many times')


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
    await db.users.create_index('email', unique=True)
    await db.sessions.create_index('expires_at', expireAfterSeconds=0)
    await db.sessions.create_index('token_hash', unique=True)
    await db.organization_members.create_index([('org_id', 1), ('user_id', 1)], unique=True)
    await ensure_seed()


@app.on_event('shutdown')
async def shutdown():
    client.close()


# --------------- authentication
@api.post('/auth/register', status_code=201)
async def register(body: RegisterIn, request: Request, response: Response):
    await limiter.check(f"register:{request.client.host if request.client else 'unknown'}", limit=5, window_seconds=900)
    email = str(body.email).lower()
    if await db.users.find_one({'email': email}):
        raise HTTPException(409, 'An account already exists for this email')
    user = {'id': uuid.uuid4().hex, 'name': body.name.strip(), 'email': email,
            'password_hash': hash_password(body.password), 'created_at': utcnow()}
    await db.users.insert_one(user)
    csrf = await create_session(db, response, user['id'])
    return {'user': {k: v for k, v in user.items() if k not in {'_id', 'password_hash'}},
            'csrf_token': csrf, 'organizations': []}


@api.post('/auth/login')
async def login(body: LoginIn, request: Request, response: Response):
    await limiter.check(f"login:{request.client.host if request.client else 'unknown'}", limit=10, window_seconds=900)
    user = await db.users.find_one({'email': str(body.email).lower()})
    if not user or not verify_password(body.password, user.get('password_hash', '')):
        raise HTTPException(401, 'Invalid email or password')
    csrf = await create_session(db, response, user['id'])
    org_ids = [m['org_id'] async for m in db.organization_members.find({'user_id': user['id']})]
    orgs = [o async for o in db.organizations.find({'id': {'$in': org_ids}}, {'_id': 0})]
    return {'user': {k: v for k, v in user.items() if k not in {'_id', 'password_hash'}},
            'csrf_token': csrf, 'organizations': orgs}


@api.get('/auth/me')
async def me(request: Request):
    user = await require_user(db, request)
    org_ids = [m['org_id'] async for m in db.organization_members.find({'user_id': user['id']})]
    orgs = [o async for o in db.organizations.find({'id': {'$in': org_ids}}, {'_id': 0})]
    return {'user': {k: v for k, v in user.items() if k != 'csrf_token'},
            'csrf_token': user['csrf_token'], 'organizations': orgs}


@api.post('/auth/logout')
async def logout(request: Request, response: Response):
    await require_user(db, request, csrf=True)
    await destroy_session(db, request, response)
    return {'ok': True}


# --------------- organizations
@api.post('/organizations')
async def create_org(body: OrgCreate, request: Request, response: Response):
    user = await require_user(db, request, csrf=True)
    org = {
        'id': uuid.uuid4().hex, 'name': body.name, 'type': body.type, 'role': body.role,
        'managed_brands': body.managed_brands, 'industry': body.industry,
        'onboarding_step': 1, 'onboarding_complete': False,
        'is_demo': False, 'created_at': now(),
    }
    await db.organizations.insert_one(org)
    await db.organization_members.insert_one({
        'org_id': org['id'], 'user_id': user['id'], 'role': 'owner', 'created_at': utcnow(),
    })
    org.pop('_id', None)
    return org


@api.patch('/organizations/{org_id}/onboarding')
async def patch_onboarding(org_id: str, body: OnboardingPatch, request: Request):
    user = await require_user(db, request, csrf=True)
    await authorize_org(org_id, user['id'], write=True)
    upd = {'onboarding_step': body.step}
    if body.complete:
        upd['onboarding_complete'] = True
    if body.data_choice:
        upd['data_choice'] = body.data_choice
    await db.organizations.update_one({'id': org_id}, {'$set': upd})
    return {'ok': True, **upd}


@api.get('/organizations/{org_id}/onboarding')
async def get_onboarding(org_id: str, request: Request):
    user = await require_user(db, request)
    org = await authorize_org(org_id, user['id'])
    brand = await db.brands.find_one({'org_id': org_id}, {'_id': 0})
    guidelines = await active_guidelines(brand['id']) if brand else None
    research = await db.brand_research.find_one({'brand_id': brand['id']}, {'_id': 0}, sort=[('created_at', -1)]) if brand else None
    return {'organization': org, 'brand': brand, 'guidelines': guidelines, 'research': research}


# --------------- brands
@api.post('/organizations/{org_id}/brands')
async def create_brand(org_id: str, body: BrandCreate, request: Request):
    user = await require_user(db, request, csrf=True)
    await authorize_org(org_id, user['id'], write=True)
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
    user = await require_viewer(request)
    b = await load_brand(brand_id, user['id'])
    g = await active_guidelines(brand_id)
    org = await db.organizations.find_one({'id': b['org_id']}, {'_id': 0})
    return {'brand': b, 'guidelines': g, 'organization': org}


@api.patch('/brands/{brand_id}/guidelines')
async def update_guidelines(brand_id: str, body: Guidelines, request: Request):
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
    new_v = (b.get('active_guideline_version') or 0) + 1
    doc = {'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brand_id,
           'version': new_v, **body.model_dump(), 'created_at': now()}
    await db.guideline_sets.insert_one(doc)
    await db.brands.update_one({'id': brand_id}, {'$set': {'active_guideline_version': new_v}})
    doc.pop('_id', None)
    return doc


# --------------- controlled brand research
@api.post('/brands/{brand_id}/research', status_code=201)
async def create_brand_research(brand_id: str, body: ResearchIn, request: Request):
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
    await limiter.check(f"research:{user['id']}", limit=5, window_seconds=3600)
    source = body.url or b.get('url')
    if not source:
        raise HTTPException(422, 'Add a public brand website first')
    try:
        final_url, website_text = await asyncio.to_thread(fetch_public_website, source)
        if len(website_text.strip()) < 100:
            raise ValueError('Website did not contain enough readable evidence')
        report = await run_brand_research(
            brand_name=b['name'], source_url=final_url, website_text=website_text,
            notes=body.notes,
        )
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(422, 'Brand website could not be fetched safely') from exc
    except Exception as exc:
        LOG.exception('brand research failed')
        raise HTTPException(502, 'Brand research did not complete; no changes were applied') from exc
    doc = {
        'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brand_id,
        'source_url': final_url, 'status': 'awaiting_review',
        'model': os.environ.get('OPENAI_AGENT_MODEL', 'gpt-5-mini'),
        'workflow': ['Brand research director', 'Brand evidence collector',
                     'Brand strategy analyst', 'Brand safety and synthesis'],
        'report': report.model_dump(), 'created_by': user['id'], 'created_at': now(),
    }
    await db.brand_research.insert_one(doc)
    await db.brands.update_one({'id': brand_id}, {'$set': {'research_status': 'awaiting_review'}})
    doc.pop('_id', None)
    return doc


@api.get('/brands/{brand_id}/research/latest')
async def latest_brand_research(brand_id: str, request: Request):
    user = await require_user(db, request)
    await load_brand(brand_id, user['id'])
    result = await db.brand_research.find_one(
        {'brand_id': brand_id}, {'_id': 0}, sort=[('created_at', -1)])
    if not result:
        raise HTTPException(404, 'No brand research has been run')
    return result


@api.post('/brands/{brand_id}/research/{research_id}/apply')
async def apply_brand_research(brand_id: str, research_id: str, body: ApplyResearchIn, request: Request):
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
    if not body.approved:
        raise HTTPException(422, 'Explicit human approval is required')
    research = await db.brand_research.find_one({'id': research_id, 'brand_id': brand_id}, {'_id': 0})
    if not research or research.get('status') != 'awaiting_review':
        raise HTTPException(409, 'Research is unavailable or was already reviewed')
    report = BrandResearchReport.model_validate(research['report'])
    current = await active_guidelines(brand_id)
    proposed_approved = list(dict.fromkeys((current.get('approved_claims') or []) + report.approved_claim_candidates))
    proposed_prohibited = list(dict.fromkeys((current.get('prohibited_claims') or []) + report.prohibited_claim_candidates))
    if {x.casefold() for x in proposed_approved} & {x.casefold() for x in proposed_prohibited}:
        raise HTTPException(409, 'Research conflicts with an existing claim rule; edit manually')
    new_v = (b.get('active_guideline_version') or 0) + 1
    guideline = {
        'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brand_id, 'version': new_v,
        'tone': list(dict.fromkeys((current.get('tone') or []) + report.voice_traits)),
        'approved_claims': proposed_approved, 'prohibited_claims': proposed_prohibited,
        'colors': current.get('colors') or [],
        'layout_rules': list(dict.fromkeys((current.get('layout_rules') or []) + report.layout_recommendations)),
        'cta_style': current.get('cta_style') or '', 'source_research_id': research_id,
        'approved_by': user['id'], 'created_at': now(),
    }
    await db.guideline_sets.insert_one(guideline)
    await db.brands.update_one({'id': brand_id}, {'$set': {
        'active_guideline_version': new_v, 'research_status': 'approved',
    }})
    await db.brand_research.update_one({'id': research_id}, {'$set': {
        'status': 'approved', 'approved_by': user['id'], 'approved_at': now(),
    }})
    guideline.pop('_id', None)
    return guideline


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
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
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
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
    campaign_id = uuid.uuid4().hex
    await db.campaigns.insert_one({
        'id': campaign_id, 'org_id': b['org_id'], 'brand_id': brand_id,
        'name': body.name, 'source_type': body.source, 'file_path': None,
        'pasted_html': body.html[:200000],
        'status': 'processing', 'metrics': {}, 'created_at': now(),
    })
    background.add_task(process_pasted, campaign_id, body.html, body.name)
    return {'campaign_id': campaign_id, 'status': 'processing', 'source': body.source}


# --------------- provider connections (Klaviyo / Mailchimp)
def _fernet():
    """Derive a Fernet key from SESSION_SECRET for at-rest encryption of API keys."""
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    import base64
    secret = os.environ.get('SESSION_SECRET', 'brand-memory-dev-secret-2026').encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=b'bmos-conn', iterations=200000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(secret)))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def klaviyo_headers(key: str) -> dict:
    return {
        'Authorization': f'Klaviyo-API-Key {key}',
        'accept': 'application/vnd.api+json',
        'revision': '2024-10-15',
    }


def mailchimp_server(key: str) -> str:
    # Mailchimp keys look like "abcdef-us14" — the dc after the dash is the server prefix.
    if '-' not in key:
        raise HTTPException(422, 'Mailchimp key must include the datacenter suffix, e.g. -us14')
    return key.rsplit('-', 1)[-1].strip()


def validate_provider_key(provider: str, key: str) -> dict:
    """Ping the provider to confirm the key works; returns a short account summary."""
    try:
        if provider == 'klaviyo':
            r = requests.get('https://a.klaviyo.com/api/accounts', headers=klaviyo_headers(key), timeout=10)
            if r.status_code == 401 or r.status_code == 403:
                raise HTTPException(422, 'Klaviyo rejected this API key')
            r.raise_for_status()
            data = r.json().get('data', [])
            account = (data[0].get('attributes') or {}) if data else {}
            return {'account': account.get('contact_information', {}).get('organization_name') or 'Klaviyo account'}
        if provider == 'mailchimp':
            dc = mailchimp_server(key)
            r = requests.get(f'https://{dc}.api.mailchimp.com/3.0/ping',
                             auth=('anystring', key), timeout=10)
            if r.status_code == 401:
                raise HTTPException(422, 'Mailchimp rejected this API key')
            r.raise_for_status()
            return {'account': 'Mailchimp account', 'dc': dc}
    except HTTPException:
        raise
    except requests.RequestException as e:
        raise HTTPException(502, f'Could not reach {provider}: {str(e)[:120]}')
    raise HTTPException(400, 'unsupported provider')


@api.post('/brands/{brand_id}/connections', status_code=201)
async def create_connection(brand_id: str, body: ConnectIn, request: Request):
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
    await limiter.check(f'connect:{user["id"]}', limit=20, window_seconds=3600)
    summary = validate_provider_key(body.provider, body.api_key)
    doc = {
        'id': uuid.uuid4().hex, 'org_id': b['org_id'], 'brand_id': brand_id,
        'provider': body.provider, 'api_key_enc': encrypt_secret(body.api_key),
        'account_label': summary.get('account'), 'meta': {k: v for k, v in summary.items() if k != 'account'},
        'connected_by': user['id'], 'created_at': now(),
    }
    await db.connections.replace_one(
        {'brand_id': brand_id, 'provider': body.provider}, doc, upsert=True,
    )
    return {'provider': body.provider, 'account': summary.get('account'), 'connected_at': doc['created_at']}


@api.get('/brands/{brand_id}/connections')
async def list_connections(brand_id: str, request: Request):
    user = await require_viewer(request)
    await load_brand(brand_id, user['id'])
    conns = [c async for c in db.connections.find(
        {'brand_id': brand_id}, {'_id': 0, 'api_key_enc': 0}
    )]
    return conns


@api.delete('/brands/{brand_id}/connections/{provider}')
async def disconnect(brand_id: str, provider: str, request: Request):
    user = await require_user(db, request, csrf=True)
    await load_brand(brand_id, user['id'], write=True)
    r = await db.connections.delete_one({'brand_id': brand_id, 'provider': provider})
    if not r.deleted_count:
        raise HTTPException(404, 'connection not found')
    return {'deleted': True}


async def _sync_klaviyo(brand_id: str, org_id: str, key: str, background: BackgroundTasks) -> list[str]:
    """List recent Klaviyo email campaigns and enqueue each for extraction."""
    url = ('https://a.klaviyo.com/api/campaigns'
           '?filter=equals(messages.channel,%22email%22)'
           '&sort=-created_at&page[size]=5')
    r = requests.get(url, headers=klaviyo_headers(key), timeout=15)
    r.raise_for_status()
    ids = []
    for camp in r.json().get('data', [])[:5]:
        attrs = camp.get('attributes', {}) or {}
        cname = attrs.get('name') or f"Klaviyo {camp.get('id','')[:8]}"
        # fetch message html (campaigns endpoint doesn't include HTML directly)
        html = attrs.get('subject_line') or ''
        try:
            msgs = requests.get(
                f'https://a.klaviyo.com/api/campaign-messages'
                f'?filter=equals(campaign_id,%22{camp["id"]}%22)',
                headers=klaviyo_headers(key), timeout=15)
            if msgs.ok:
                for m in msgs.json().get('data', [])[:1]:
                    render = (m.get('attributes') or {}).get('render_options') or {}
                    tmpl = (m.get('attributes') or {}).get('definition') or {}
                    html = (tmpl.get('content') or {}).get('body') or html
        except Exception:
            pass
        campaign_id = uuid.uuid4().hex
        await db.campaigns.insert_one({
            'id': campaign_id, 'org_id': org_id, 'brand_id': brand_id,
            'name': cname, 'source_type': 'klaviyo', 'file_path': None,
            'pasted_html': (html or attrs.get('subject_line') or cname)[:200000],
            'external_id': camp.get('id'),
            'status': 'processing', 'metrics': {}, 'created_at': now(),
        })
        background.add_task(process_pasted, campaign_id,
                            html or attrs.get('subject_line') or cname, cname)
        ids.append(campaign_id)
    return ids


async def _sync_mailchimp(brand_id: str, org_id: str, key: str, background: BackgroundTasks) -> list[str]:
    dc = mailchimp_server(key)
    r = requests.get(
        f'https://{dc}.api.mailchimp.com/3.0/campaigns'
        '?count=5&status=sent&type=regular&sort_field=send_time&sort_dir=DESC',
        auth=('anystring', key), timeout=15)
    r.raise_for_status()
    ids = []
    for camp in r.json().get('campaigns', [])[:5]:
        cname = (camp.get('settings') or {}).get('title') or camp.get('id')
        html = ''
        try:
            content = requests.get(
                f'https://{dc}.api.mailchimp.com/3.0/campaigns/{camp["id"]}/content',
                auth=('anystring', key), timeout=15)
            if content.ok:
                html = content.json().get('html') or ''
        except Exception:
            pass
        campaign_id = uuid.uuid4().hex
        await db.campaigns.insert_one({
            'id': campaign_id, 'org_id': org_id, 'brand_id': brand_id,
            'name': cname, 'source_type': 'mailchimp', 'file_path': None,
            'pasted_html': (html or (camp.get('settings') or {}).get('subject_line') or cname)[:200000],
            'external_id': camp.get('id'),
            'status': 'processing', 'metrics': {}, 'created_at': now(),
        })
        background.add_task(process_pasted, campaign_id,
                            html or (camp.get('settings') or {}).get('subject_line') or cname, cname)
        ids.append(campaign_id)
    return ids


@api.post('/brands/{brand_id}/connections/{provider}/sync')
async def sync_provider(brand_id: str, provider: str, request: Request, background: BackgroundTasks):
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
    await limiter.check(f'sync:{brand_id}:{provider}', limit=6, window_seconds=600)
    conn = await db.connections.find_one({'brand_id': brand_id, 'provider': provider})
    if not conn:
        raise HTTPException(404, 'not connected')
    try:
        key = decrypt_secret(conn['api_key_enc'])
    except Exception:
        raise HTTPException(500, 'stored key could not be decrypted; reconnect')
    try:
        if provider == 'klaviyo':
            ids = await _sync_klaviyo(brand_id, b['org_id'], key, background)
        elif provider == 'mailchimp':
            ids = await _sync_mailchimp(brand_id, b['org_id'], key, background)
        else:
            raise HTTPException(400, 'unsupported provider')
    except requests.HTTPError as e:
        status = e.response.status_code if getattr(e, 'response', None) is not None else 502
        raise HTTPException(502, f'{provider} sync failed ({status})')
    except requests.RequestException as e:
        raise HTTPException(502, f'{provider} sync failed: {str(e)[:120]}')
    await db.connections.update_one(
        {'brand_id': brand_id, 'provider': provider},
        {'$set': {'last_synced_at': now(), 'last_sync_count': len(ids)}}
    )
    return {'provider': provider, 'imported': len(ids), 'campaign_ids': ids}


@api.get('/brands/{brand_id}/campaigns')
async def list_campaigns(brand_id: str, request: Request):
    user = await require_viewer(request)
    await load_brand(brand_id, user['id'])
    return [c async for c in db.campaigns.find(
        {'brand_id': brand_id}, {'_id': 0, 'embedding': 0}
    ).sort('created_at', -1)]


@api.get('/campaigns/{campaign_id}')
async def get_campaign(campaign_id: str, request: Request):
    user = await require_viewer(request)
    c = await db.campaigns.find_one({'id': campaign_id}, {'_id': 0, 'embedding': 0})
    if not c:
        raise HTTPException(404, 'campaign not found')
    await load_brand(c['brand_id'], user['id'])
    return c


@api.get('/campaigns/{campaign_id}/file')
async def get_campaign_file(campaign_id: str, request: Request):
    user = await require_viewer(request)
    c = await db.campaigns.find_one({'id': campaign_id}, {'_id': 0})
    if not c:
        raise HTTPException(404, 'campaign not found')
    await load_brand(c['brand_id'], user['id'])
    try:
        data, ct = storage_get(c['file_path'])
    except Exception:
        raise HTTPException(404, 'file unavailable')
    return Response(content=data, media_type=c.get('content_type') or ct)


# --------------- briefs & recommendations
@api.post('/brands/{brand_id}/briefs')
async def create_brief(brand_id: str, body: BriefIn, request: Request):
    user = await require_user(db, request, csrf=True)
    b = await load_brand(brand_id, user['id'], write=True)
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
    user = await require_user(db, request, csrf=True)
    brief = await db.briefs.find_one({'id': brief_id}, {'_id': 0})
    if not brief:
        raise HTTPException(404, 'brief not found')
    b = await load_brand(brief['brand_id'], user['id'], write=True)
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
    user = await require_viewer(request)
    r = await db.recommendations.find_one({'id': rec_id}, {'_id': 0})
    if not r:
        raise HTTPException(404)
    await load_brand(r['brand_id'], user['id'])
    return r


# --------------- blueprint
@api.post('/recommendations/{rec_id}/blueprint')
async def make_blueprint(rec_id: str, request: Request):
    user = await require_user(db, request, csrf=True)
    rec = await db.recommendations.find_one({'id': rec_id}, {'_id': 0})
    if not rec:
        raise HTTPException(404, 'recommendation not found')
    await load_brand(rec['brand_id'], user['id'], write=True)
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
    user = await require_user(db, request, csrf=True)
    c = await db.campaigns.find_one({'id': campaign_id}, {'_id': 0})
    if not c:
        raise HTTPException(404)
    await load_brand(c['brand_id'], user['id'], write=True)
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
    user = await require_viewer(request)
    b = await load_brand(brand_id, user['id'])
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
        'is_demo': True,
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
@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )
    response.headers['Cache-Control'] = 'no-store'
    if os.environ.get('ENVIRONMENT') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


cors_origins = [x.strip() for x in os.environ.get(
    'CORS_ORIGINS', 'http://localhost:3000').split(',') if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
    allow_methods=['GET', 'POST', 'PATCH', 'OPTIONS'],
    allow_headers=['Content-Type', 'X-CSRF-Token', 'X-Demo-Access'],
)
