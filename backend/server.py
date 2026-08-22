from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
import os, logging, re

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')
client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]
app = FastAPI(title='Brand Memory OS')
api = APIRouter(prefix='/api')

WORKSPACE = {'id':'northstar','name':'Northstar Coffee Co.','type':'DTC coffee subscription','description':'A thoughtful coffee ritual for busy mornings.'}
RULES = {'workspace_id':'northstar','tone':['warm','specific','quietly confident'],'approved_claims':['small-batch roasted','ships within 48 hours','flexible delivery'], 'prohibited_claims':['cures anxiety','guaranteed energy','detox','free forever'], 'colors':['#173F35','#F4B860','#F8F4EC'],'layout_preferences':['One clear hero','Short scannable sections','Single primary CTA']}
CAMPAIGNS = [
 {'id':'cmp-104','workspace_id':'northstar','name':'The Monday Ritual','objective':'retention','audience':'Active subscribers','offer':'New seasonal roast','subject':'Your Monday, roasted better','format':'Editorial / product education','outcome':{'status':'complete','open_rate':48.2,'click_rate':7.8,'conversion_rate':3.9,'label':'Performance-backed'},'matched':['retention','active subscribers','seasonal roast'],'evidence':'A warm ritual-led opener paired with a single product detail lifted clicks without discounting.','color':'#D9E8D8'},
 {'id':'cmp-087','workspace_id':'northstar','name':'Brew Guide: V60','objective':'engagement','audience':'New subscribers','offer':'Brew education','subject':'A slower cup, in 4 steps','format':'How-to / editorial','outcome':{'status':'complete','open_rate':44.7,'click_rate':9.2,'conversion_rate':2.1,'label':'Performance-backed'},'matched':['engagement','new subscribers','education'],'evidence':'Step-by-step content earned the strongest click rate in the new-subscriber cohort.','color':'#F5DEC4'},
 {'id':'cmp-062','workspace_id':'northstar','name':'Roaster Notes','objective':'retention','audience':'At-risk subscribers','offer':'Re-engagement','subject':'A note from the roastery','format':'Founder note','outcome':{'status':'incomplete','open_rate':39.1,'click_rate':None,'conversion_rate':None,'label':'Incomplete metrics'},'matched':['retention','at-risk subscribers'],'evidence':'The founder-note format is directionally relevant, but click and conversion data are not attached.','color':'#DBE5F4'}
]

class Brief(BaseModel):
 objective: str = Field(min_length=2); audience: str = Field(min_length=2); offer: str = Field(min_length=2); constraints: str = ''
class Outcome(BaseModel):
 campaign_id: str; open_rate: float; click_rate: float; conversion_rate: float = 0

class Rules(BaseModel):
    workspace_id: str = 'northstar'
    tone: list[str] = []
    approved_claims: list[str] = []
    prohibited_claims: list[str] = []
    colors: list[str] = []
    layout_preferences: list[str] = []

async def ensure_seeded():
    if await db.workspaces.count_documents({}) == 0:
        await db.workspaces.insert_one(WORKSPACE)
    if await db.brand_rules.count_documents({'workspace_id':'northstar'}) == 0:
        await db.brand_rules.insert_one(RULES)
    if await db.campaigns.count_documents({'workspace_id':'northstar'}) == 0:
        await db.campaigns.insert_many(CAMPAIGNS)

def clean(doc):
    doc.pop('_id', None)
    return doc

@api.on_event('startup')
async def startup(): await ensure_seeded()

@api.get('/workspace')
async def get_workspace(): return WORKSPACE

@api.get('/rules')
async def get_rules():
    doc = await db.brand_rules.find_one({'workspace_id':'northstar'}, {'_id':0})
    return doc or RULES

@api.put('/rules')
async def update_rules(rules: Rules):
    validated = rules
    validated.workspace_id = 'northstar'
    output = validated.model_dump()
    await db.brand_rules.replace_one({'workspace_id':'northstar'}, output, upsert=True)
    return output

@api.get('/campaigns')
async def get_campaigns():
    return [clean(x) async for x in db.campaigns.find({'workspace_id':'northstar'}, {'_id':0})]

@api.post('/recommendations')
async def recommendations(brief: Brief):
    rules = await get_rules(); campaigns = await get_campaigns()
    terms = set(re.findall(r'[a-z]+', ' '.join([brief.objective,brief.audience,brief.offer]).lower()))
    ranked=[]
    for c in campaigns:
        matched=[m for m in c['matched'] if any(t in m.lower() for t in terms)]
        if not matched:
            continue
        score=min(96, 58 + len(matched)*12 + (12 if c['outcome']['status']=='complete' else 0))
        conflict=''
        for word in rules.get('prohibited_claims',[]):
            if word.lower() in (brief.constraints+' '+brief.offer).lower(): conflict=f'Conflicts with prohibited claim: “{word}”'
        ranked.append({**c,'score':score,'matched_attributes':matched,'status':'blocked' if conflict else ('supported' if c['outcome']['status']=='complete' else 'limited'),'warning':conflict,'why':f"Selected because it matches {', '.join(matched) if matched else 'the closest available audience and format'} and has {c['outcome']['label'].lower()}."})
    ranked.sort(key=lambda x:x['score'], reverse=True)
    return {'brief':brief.model_dump(),'recommendations':ranked,'rules_checked':True,'evidence_count':sum(1 for x in ranked if x['status']=='supported')}

@api.post('/blueprint')
async def blueprint(brief: Brief, recommendation_id: str):
    rules=await get_rules(); rec=await db.campaigns.find_one({'id':recommendation_id,'workspace_id':'northstar'},{'_id':0})
    if not rec: raise HTTPException(404,'Campaign not found')
    text=(brief.constraints+' '+brief.offer).lower()
    blocked=next((x for x in rules.get('prohibited_claims',[]) if x.lower() in text),None)
    if blocked: raise HTTPException(409,f'Blueprint blocked by brand rule: {blocked}')
    md=f"# Northstar campaign blueprint\n\n## Objective\n{brief.objective}\n\n## Audience\n{brief.audience}\n\n## Offer\n{brief.offer}\n\n## Recommended structure\n1. Hero: one clear, specific promise\n2. Proof: use the {rec['name']} evidence pattern\n3. Detail: one useful product or ritual detail\n4. CTA: one primary action\n\n## Brand guardrails\n{', '.join(rules['tone'])}; {', '.join(rules['layout_preferences'])}"
    return {'markdown':md,'source_campaign':rec['name']}

@api.post('/outcomes')
async def record_outcome(outcome: Outcome):
    result=await db.campaigns.update_one({'id':outcome.campaign_id,'workspace_id':'northstar'},{'$set':{'outcome':{'status':'complete','open_rate':outcome.open_rate,'click_rate':outcome.click_rate,'conversion_rate':outcome.conversion_rate,'label':'Performance-backed'}}})
    if not result.matched_count: raise HTTPException(404,'Campaign not found')
    return {'saved':True,'message':'Outcome added to brand memory'}

app.include_router(api)
app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=os.environ.get('CORS_ORIGINS','*').split(','), allow_methods=['*'], allow_headers=['*'])
@app.on_event('shutdown')
async def shutdown(): client.close()