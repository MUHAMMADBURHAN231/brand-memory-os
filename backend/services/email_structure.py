"""Deterministic email design-structure analysis.

Turns raw email HTML into an ordered sequence of layout modules, so the memory
stores *how a winning email was built*, not just what it said. Everything here is
rule-based on purpose: structure extraction must keep working when no LLM key is
configured, and it must return the same answer for the same input every time.

Module vocabulary follows the modular-email convention used by email design
systems: a small set of interchangeable blocks that covers most campaigns.
"""
from __future__ import annotations

import re
from typing import Optional

from bs4 import BeautifulSoup

# ------------------------------------------------------------------ vocabulary
# Ordered roughly the way a campaign reads top to bottom.
MODULE_LIBRARY: dict[str, dict[str, str]] = {
    'header':        {'label': 'Header',         'purpose': 'Logo and orientation. Confirms who is sending before anything else.'},
    'hero':          {'label': 'Hero',           'purpose': 'The single biggest promise. Carries the subject line into the body.'},
    'promo_banner':  {'label': 'Promo banner',   'purpose': 'States the offer plainly — discount, code, or deadline.'},
    'text':          {'label': 'Text block',     'purpose': 'Narrative or context that earns the click.'},
    'image_text':    {'label': 'Image + copy',   'purpose': 'One benefit shown and explained side by side.'},
    'product_grid':  {'label': 'Product grid',   'purpose': 'Several products at once. Widens the chance something lands.'},
    'product_card':  {'label': 'Product card',   'purpose': 'One product with image, name, and price.'},
    'testimonial':   {'label': 'Social proof',   'purpose': 'Review, rating, or quote that removes doubt before the CTA.'},
    'cta':           {'label': 'Call to action', 'purpose': 'One clear primary action.'},
    'social_row':    {'label': 'Social row',     'purpose': 'Channel links. Low priority, keeps brand presence.'},
    'footer':        {'label': 'Footer',         'purpose': 'Compliance, address, and unsubscribe.'},
}

VALID_MODULES = tuple(MODULE_LIBRARY)

# Category vocabulary — what kind of brand this design pattern came from.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    'activewear':    ('activewear', 'leggings', 'workout', 'gym', 'athleisure', 'training', 'performance wear'),
    'supplements':   ('supplement', 'protein', 'vitamin', 'creatine', 'collagen', 'capsule', 'serving', 'scoop'),
    'beauty':        ('skincare', 'serum', 'moisturizer', 'spf', 'cleanser', 'makeup', 'fragrance', 'haircare'),
    'food_beverage': ('roast', 'coffee', 'tea', 'snack', 'flavor', 'brew', 'drink', 'organic', 'recipe'),
    'apparel':       ('collection', 'fit', 'fabric', 'sizing', 'wardrobe', 'denim', 'outerwear'),
    'home':          ('bedding', 'kitchen', 'furniture', 'decor', 'mattress', 'cookware'),
    'electronics':   ('battery', 'charging', 'bluetooth', 'device', 'firmware', 'wireless'),
    'saas':          ('trial', 'onboarding', 'workspace', 'dashboard', 'integration', 'seat', 'plan'),
}

CATEGORIES = tuple(CATEGORY_KEYWORDS) + ('other',)

_CTA_VERBS = ('shop', 'buy', 'get', 'claim', 'start', 'try', 'order', 'grab',
              'discover', 'explore', 'save', 'redeem', 'join', 'unlock', 'view')
# A bare mention of "sale" or "discount" is not an offer — editorial copy says
# "no discount mechanics" all the time. Require a concrete offer signal, and skip
# the block when the phrase is negated.
_OFFER_PATTERN = re.compile(
    r'\b\d{1,3}\s*%\s*off\b|\b[$£€]\s?\d+\s*off\b|\bfree shipping\b|\buse code\b'
    r'|\bpromo code\b|\bbogo\b|\bends (tonight|today|soon|tomorrow)\b'
    r'|\blast chance\b|\bsale ends\b|\bsave [$£€]\s?\d+',
    re.I,
)
_NEGATED_OFFER = re.compile(r'\bno (discount|discounts|offer|offers|promo|promotion)', re.I)
_FOOTER_HINTS = ('unsubscribe', 'manage preferences', 'you are receiving this',
                 'update your preferences', 'privacy policy', 'all rights reserved')
_SOCIAL_HINTS = ('instagram', 'facebook', 'twitter', 'tiktok', 'youtube', 'pinterest', 'linkedin')
_PROOF_HINTS = ('review', 'rated', 'stars', 'testimonial', 'loved by', 'customers say',
                'verified buyer', 'as seen in')
_PRICE = re.compile(r'[$£€]\s?\d')
_STARS = re.compile(r'[★⭐]{2,}|\b[45](\.\d)?\s*/\s*5\b')


# ------------------------------------------------------------------ signal pass
def _is_button(tag) -> bool:
    """An <a> that looks like a rendered button rather than an inline link."""
    attrs = ' '.join(filter(None, [
        ' '.join(tag.get('class', []) or []),
        tag.get('id', '') or '',
        tag.get('style', '') or '',
    ])).lower()
    if any(k in attrs for k in ('btn', 'button', 'cta')):
        return True
    if 'background' in attrs and 'padding' in attrs:
        return True
    text = tag.get_text(' ', strip=True).lower()
    return bool(text) and len(text) <= 40 and text.split()[0] in _CTA_VERBS


def _signals(soup: BeautifulSoup) -> list[dict]:
    """Flatten the document into an ordered stream of content signals.

    Email HTML is table soup, so container nesting is unreliable. Reading the
    leaf content in document order is far more stable than trying to guess which
    <table> is a "section".
    """
    out: list[dict] = []
    for tag in soup.find_all(['img', 'h1', 'h2', 'h3', 'h4', 'p', 'a', 'blockquote', 'li']):
        name = tag.name
        if name == 'img':
            out.append({'kind': 'image', 'text': (tag.get('alt') or '').strip(),
                        'src': (tag.get('src') or '')})
        elif name == 'a':
            text = tag.get_text(' ', strip=True)
            if not text:
                continue
            href = (tag.get('href') or '').lower()
            if any(s in href for s in _SOCIAL_HINTS):
                out.append({'kind': 'social', 'text': text})
            elif _is_button(tag):
                out.append({'kind': 'button', 'text': text})
            else:
                out.append({'kind': 'link', 'text': text})
        else:
            text = tag.get_text(' ', strip=True)
            if not text:
                continue
            kind = 'heading' if name in ('h1', 'h2', 'h3', 'h4') else 'text'
            if name == 'blockquote':
                kind = 'quote'
            out.append({'kind': kind, 'text': text})
    return out


def _classify(window: list[dict]) -> str:
    """Name the module a small run of signals most likely represents."""
    kinds = [s['kind'] for s in window]
    blob = ' '.join(s.get('text', '') for s in window).lower()
    images = kinds.count('image')
    has_button = 'button' in kinds
    has_heading = 'heading' in kinds
    words = len(blob.split())

    if any(h in blob for h in _FOOTER_HINTS):
        return 'footer'
    if kinds.count('social') >= 2:
        return 'social_row'
    if 'quote' in kinds or _STARS.search(blob) or any(h in blob for h in _PROOF_HINTS):
        return 'testimonial'
    prices = len(_PRICE.findall(blob))
    if images >= 3 and prices >= 2:
        return 'product_grid'
    if images >= 1 and prices >= 1:
        return 'product_card'
    if _OFFER_PATTERN.search(blob) and not _NEGATED_OFFER.search(blob) and words < 45:
        return 'promo_banner'
    if has_button and not has_heading and words < 25:
        return 'cta'
    if images >= 1 and words >= 15:
        return 'image_text'
    if has_heading or words >= 15:
        return 'text'
    if images:
        return 'image_text'
    return 'text'


def _segment(signals: list[dict]) -> list[list[dict]]:
    """Group the signal stream into module-sized windows.

    A new module starts at a heading, at an image that follows body copy, or at a
    button that follows content — the three places a designer almost always begins
    a new block. Buttons matter especially: a call to action is its own module, and
    folding it into the copy above it loses the most important block in the email.
    """
    windows: list[list[dict]] = []
    current: list[dict] = []
    for sig in signals:
        starts_block = (
            sig['kind'] == 'heading'
            or (sig['kind'] == 'image' and any(s['kind'] in ('text', 'button') for s in current))
            or (sig['kind'] == 'button' and any(s['kind'] in ('text', 'image') for s in current))
        )
        if starts_block and current:
            windows.append(current)
            current = []
        current.append(sig)
    if current:
        windows.append(current)
    return windows


def parse_modules(html: str) -> list[str]:
    """Return the ordered module sequence for an email's HTML.

    Returns [] when the input has no usable structure — an empty list is an
    honest "unknown", never a guessed layout.
    """
    if not html or not html.strip():
        return []
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return []
    for junk in soup(['script', 'style', 'head']):
        junk.decompose()

    signals = _signals(soup)
    if not signals:
        return []

    # Find the footer boundary before segmenting. A trailing "unsubscribe" line
    # rarely starts its own block, so left in the stream it would be grouped with
    # the section above it and relabel that whole section as footer.
    footer_at = next(
        (i for i, s in enumerate(signals)
         if any(h in (s.get('text') or '').lower() for h in _FOOTER_HINTS)),
        None,
    )
    body = signals if footer_at is None else signals[:footer_at]

    windows = _segment(body)
    modules = [_classify(w) for w in windows]

    # A leading logo-only image is a header, not a hero.
    if modules and modules[0] in ('image_text', 'text'):
        first = windows[0]
        if len(first) <= 2 and all(s['kind'] == 'image' for s in first):
            modules[0] = 'header'
    # The first substantial block after the header is the hero by definition.
    for i, m in enumerate(modules):
        if m in ('image_text', 'text') and (i == 0 or modules[i - 1] == 'header'):
            modules[i] = 'hero'
            break
    # Everything from the footer marker down collapses into a single footer block.
    if footer_at is not None:
        modules = [m for m in modules if m != 'footer'] + ['footer']

    # Collapse immediate repeats — three text blocks in a row is one text block.
    collapsed: list[str] = []
    for m in modules:
        if not collapsed or collapsed[-1] != m:
            collapsed.append(m)
    return collapsed[:14]


def salient_parts(html: str) -> dict:
    """Pull the few lines of an email that carry its intent.

    An email's meaning lives in its subject, its hero heading, and its call to
    action. The rest is supporting copy. Grabbing only these keeps the retrieval
    text topical instead of drowning it in product names and prices.
    """
    empty = {'heading': '', 'cta': '', 'headings': [], 'excerpt': ''}
    if not html or not html.strip():
        return empty
    try:
        soup = BeautifulSoup(html, 'html.parser')
    except Exception:
        return empty
    for junk in soup(['script', 'style', 'head']):
        junk.decompose()

    headings = [h.get_text(' ', strip=True) for h in soup.find_all(['h1', 'h2', 'h3'])]
    headings = [h for h in headings if h][:4]

    cta = ''
    for a in soup.find_all('a'):
        if _is_button(a):
            cta = a.get_text(' ', strip=True)
            break

    paragraphs = [p.get_text(' ', strip=True) for p in soup.find_all('p')]
    excerpt = ' '.join(t for t in paragraphs if len(t.split()) >= 6)[:240]

    return {'heading': headings[0] if headings else '',
            'cta': cta, 'headings': headings, 'excerpt': excerpt}


def summarize_for_retrieval(html: str, modules: list[str], category: str = '') -> str:
    """Build an intent-style descriptor of an email for semantic retrieval.

    Briefs are written as intent ("introduce the winter roast to active
    subscribers"). Raw email HTML is written as marketing copy. Embedding those
    two directly compares different registers and scores far too low, so this
    rewrites the email into the same register the brief uses.
    """
    parts = salient_parts(html)
    blocks = ', '.join(MODULE_LIBRARY.get(m, {}).get('label', m).lower() for m in modules)

    pieces = []
    if parts['heading']:
        pieces.append(f"Email about {parts['heading']}.")
    for extra in parts['headings'][1:3]:
        pieces.append(f'{extra}.')
    if parts['cta']:
        pieces.append(f"Call to action: {parts['cta']}.")
    if category and category != 'other':
        pieces.append(f"{category.replace('_', ' ')} brand.")
    if blocks:
        pieces.append(f'Built from {blocks}.')
    if parts['excerpt']:
        pieces.append(parts['excerpt'])
    return ' '.join(pieces).strip()


def module_signature(modules: list[str]) -> str:
    """Compact, comparable form of a layout, e.g. 'header>hero>product_grid>cta'."""
    return '>'.join(modules)


def describe_modules(modules: list[str]) -> list[dict]:
    """Expand a module sequence into labelled, explained steps for display."""
    return [
        {
            'position': i + 1,
            'block': m,
            'label': MODULE_LIBRARY.get(m, {}).get('label', m.replace('_', ' ').title()),
            'purpose': MODULE_LIBRARY.get(m, {}).get('purpose', ''),
        }
        for i, m in enumerate(modules)
    ]


def structure_similarity(a: list[str], b: list[str]) -> float:
    """How alike two layouts are, from 0.0 to 1.0.

    Blends set overlap (which blocks are present) with order agreement (whether
    they appear in the same sequence), so 'hero then proof then CTA' scores
    higher against itself than against 'CTA then proof then hero'.
    """
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    jaccard = len(sa & sb) / len(sa | sb)

    # Longest common subsequence over the shared vocabulary captures ordering.
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = (table[i + 1][j + 1] + 1) if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    order = table[0][0] / max(n, m)
    return round(0.5 * jaccard + 0.5 * order, 4)


def infer_category(*texts: Optional[str]) -> str:
    """Best-guess brand category from any available text. 'other' when unclear."""
    blob = ' '.join(t for t in texts if t).lower()
    if not blob.strip():
        return 'other'
    best, best_hits = 'other', 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for k in keywords if k in blob)
        if hits > best_hits:
            best, best_hits = category, hits
    return best


def consensus_structure(sources: list[dict]) -> list[str]:
    """Derive one recommended layout from several past campaigns.

    `sources` are dicts with `modules` and a `weight` (higher = better evidence).
    A block is kept when the campaigns carrying the most weight actually used it,
    and blocks are ordered by their weighted average position — so the result is
    always a real pattern from real sends, never an invented one.
    """
    scored = [s for s in sources if s.get('modules')]
    if not scored:
        return []
    total = sum(max(s.get('weight', 0.0), 0.0) for s in scored) or 1.0

    weight_by_block: dict[str, float] = {}
    position_by_block: dict[str, float] = {}
    for s in scored:
        w = max(s.get('weight', 0.0), 0.0)
        mods = s['modules']
        for idx, block in enumerate(mods):
            weight_by_block[block] = weight_by_block.get(block, 0.0) + w
            # Normalised position so short and long emails compare fairly.
            rel = idx / max(len(mods) - 1, 1)
            position_by_block[block] = position_by_block.get(block, 0.0) + rel * w

    kept = [b for b, w in weight_by_block.items() if w / total >= 0.4]
    if not kept:  # fall back to the single strongest campaign's real layout
        return max(scored, key=lambda s: s.get('weight', 0.0))['modules']
    kept.sort(key=lambda b: position_by_block[b] / weight_by_block[b])
    return kept
