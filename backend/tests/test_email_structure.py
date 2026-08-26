"""Unit tests for deterministic email design-structure analysis."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.email_structure import (  # noqa: E402
    CATEGORIES, consensus_structure, describe_modules, infer_category,
    module_signature, parse_modules, salient_parts, structure_similarity,
    summarize_for_retrieval,
)

PROMO_EMAIL = """
<html><body>
  <table><tr><td><img src="logo.png" alt="Acme"></td></tr></table>
  <h1>The new season drop is here</h1>
  <p>We spent eight months reworking the fit on our best selling leggings and the
     result is the most comfortable pair we have ever made.</p>
  <a href="#" class="btn">Shop the drop</a>
  <h2>Loved by 12,000 runners</h2>
  <blockquote>These are the only leggings I train in now.</blockquote>
  <h2>Best sellers</h2>
  <img src="a.png"><img src="b.png"><img src="c.png">
  <p>Contour Legging $88 and Base Tank $42 and Train Short $56</p>
  <p>You are receiving this because you signed up. Unsubscribe here.</p>
</body></html>
"""


def test_parses_a_realistic_email_into_ordered_modules():
    modules = parse_modules(PROMO_EMAIL)
    assert modules[0] == 'header', 'a leading logo-only image is the header'
    assert modules[1] == 'hero', 'the first substantial block is the hero'
    assert 'testimonial' in modules
    assert 'product_grid' in modules
    assert modules[-1] == 'footer', 'the unsubscribe block closes the email'


def test_module_order_is_preserved():
    modules = parse_modules(PROMO_EMAIL)
    assert modules.index('hero') < modules.index('product_grid') < modules.index('footer')


def test_unusable_input_returns_empty_not_a_guess():
    for junk in ('', '   ', '<html></html>', '<html><body></body></html>'):
        assert parse_modules(junk) == [], f'{junk!r} should yield no structure'


def test_parsing_is_deterministic():
    assert parse_modules(PROMO_EMAIL) == parse_modules(PROMO_EMAIL)


def test_repeated_blocks_collapse():
    html = '<body><p>' + '</p><p>'.join(['a long paragraph of body copy here'] * 5) + '</p></body>'
    assert parse_modules(html).count('text') <= 1


def test_footer_absorbs_everything_below_it():
    html = PROMO_EMAIL.replace(
        'Unsubscribe here.', 'Unsubscribe here.</p><h2>More</h2><p>Trailing content block</p>')
    assert parse_modules(html)[-1] == 'footer'
    assert parse_modules(html).count('footer') == 1


class TestCallToActionIsItsOwnBlock:
    """A button used to be folded into the copy above it, losing the CTA entirely."""

    def test_button_after_copy_starts_its_own_block(self):
        html = ('<body><h1>The drop is here</h1>'
                '<p>A long enough paragraph of body copy to count as real content.</p>'
                '<a class="btn" href="#">Shop the drop</a></body>')
        assert 'cta' in parse_modules(html)

    def test_cta_appears_in_a_full_email(self):
        assert 'cta' in parse_modules(PROMO_EMAIL)

    def test_cta_follows_the_copy_it_belongs_to(self):
        mods = parse_modules(PROMO_EMAIL)
        assert mods.index('hero') < mods.index('cta')


class TestOfferDetection:
    """"No discount mechanics" is editorial copy, not a promotion."""

    def test_a_real_offer_is_a_promo_banner(self):
        html = ('<body><h1>Winter sale</h1><p>Take 30% off everything until Friday. '
                'Use code WINTER30 at checkout.</p></body>')
        assert 'promo_banner' in parse_modules(html)

    @pytest.mark.parametrize('phrase', [
        'A warm editorial note with no discount mechanics anywhere in it at all.',
        'We run no promotions on this product line, ever, by design.',
    ])
    def test_negated_offers_are_not_promo_banners(self, phrase):
        html = f'<body><h1>The ritual</h1><p>{phrase}</p></body>'
        assert 'promo_banner' not in parse_modules(html)

    def test_bare_mention_of_sale_is_not_an_offer(self):
        html = ('<body><h1>Our story</h1><p>We started this roastery after a yard sale '
                'in 2011 and have grown slowly since then, one bag at a time.</p></body>')
        assert 'promo_banner' not in parse_modules(html)


def test_module_signature_round_trips():
    assert module_signature(['header', 'hero', 'cta']) == 'header>hero>cta'
    assert module_signature([]) == ''


def test_describe_modules_labels_every_block():
    described = describe_modules(['header', 'hero', 'cta'])
    assert [d['position'] for d in described] == [1, 2, 3]
    assert described[1]['label'] == 'Hero'
    assert described[1]['purpose'], 'every block explains why it is there'


class TestStructureSimilarity:
    def test_identical_layouts_score_one(self):
        layout = ['header', 'hero', 'cta', 'footer']
        assert structure_similarity(layout, layout) == 1.0

    def test_empty_layout_scores_zero(self):
        assert structure_similarity([], ['header']) == 0.0
        assert structure_similarity(['header'], []) == 0.0

    def test_order_matters(self):
        forward = ['hero', 'testimonial', 'cta']
        reversed_ = ['cta', 'testimonial', 'hero']
        assert structure_similarity(forward, forward) > structure_similarity(forward, reversed_)

    def test_shared_blocks_score_higher_than_disjoint(self):
        a = ['header', 'hero', 'cta', 'footer']
        near = ['header', 'hero', 'testimonial', 'cta', 'footer']
        far = ['promo_banner', 'product_grid']
        assert structure_similarity(a, near) > structure_similarity(a, far)


class TestConsensusStructure:
    def test_agreeing_campaigns_produce_the_shared_layout(self):
        shared = ['header', 'hero', 'cta', 'footer']
        result = consensus_structure([
            {'modules': shared, 'weight': 0.9},
            {'modules': shared, 'weight': 0.7},
        ])
        assert result == shared

    def test_blocks_only_one_weak_source_used_are_dropped(self):
        result = consensus_structure([
            {'modules': ['header', 'hero', 'cta'], 'weight': 0.9},
            {'modules': ['header', 'hero', 'cta'], 'weight': 0.9},
            {'modules': ['promo_banner'], 'weight': 0.05},
        ])
        assert 'promo_banner' not in result

    def test_output_ordering_follows_real_positions(self):
        result = consensus_structure([
            {'modules': ['header', 'hero', 'testimonial', 'cta', 'footer'], 'weight': 1.0},
            {'modules': ['header', 'hero', 'testimonial', 'cta', 'footer'], 'weight': 1.0},
        ])
        assert result.index('header') < result.index('hero') < result.index('footer')

    def test_no_evidence_produces_nothing(self):
        assert consensus_structure([]) == []
        assert consensus_structure([{'modules': [], 'weight': 1.0}]) == []

    def test_single_source_falls_back_to_its_real_layout(self):
        layout = ['header', 'hero', 'footer']
        assert consensus_structure([{'modules': layout, 'weight': 1.0}]) == layout


class TestSalientParts:
    def test_pulls_the_lines_that_carry_intent(self):
        parts = salient_parts(PROMO_EMAIL)
        assert parts['heading'] == 'The new season drop is here'
        assert parts['cta'] == 'Shop the drop'
        assert 'Loved by 12,000 runners' in parts['headings']
        assert parts['excerpt'], 'body excerpt should not be empty'

    def test_unusable_input_returns_blanks(self):
        for junk in ('', '   ', '<html></html>'):
            parts = salient_parts(junk)
            assert parts['heading'] == '' and parts['cta'] == ''


class TestRetrievalSummary:
    """Regression cover for the bug where real uploads never matched a brief.

    Campaign text used to be stored as raw marketing copy while briefs are written
    as intent, so cosine similarity collapsed and retrieval returned nothing for
    obviously relevant emails. The descriptor has to restate the email as intent.
    """

    def test_descriptor_restates_the_email_as_intent(self):
        modules = parse_modules(PROMO_EMAIL)
        text = summarize_for_retrieval(PROMO_EMAIL, modules, 'activewear')
        assert text.startswith('Email about'), text[:60]
        assert 'The new season drop is here' in text
        assert 'Shop the drop' in text, 'the CTA carries the intent'
        assert 'activewear brand' in text
        assert 'social proof' in text, 'layout is described in words, not codes'

    def test_descriptor_is_deterministic(self):
        modules = parse_modules(PROMO_EMAIL)
        a = summarize_for_retrieval(PROMO_EMAIL, modules, 'activewear')
        b = summarize_for_retrieval(PROMO_EMAIL, modules, 'activewear')
        assert a == b

    def test_descriptor_survives_input_with_no_structure(self):
        assert summarize_for_retrieval('', [], '') == ''
        assert summarize_for_retrieval('<html></html>', [], 'beauty') == 'beauty brand.'

    def test_descriptor_is_shorter_and_denser_than_raw_body(self):
        modules = parse_modules(PROMO_EMAIL)
        descriptor = summarize_for_retrieval(PROMO_EMAIL, modules, 'activewear')
        raw = ' '.join(PROMO_EMAIL.split())
        assert len(descriptor) < len(raw), 'descriptor must not just echo the whole email'

    def test_unknown_category_is_omitted_rather_than_printed(self):
        modules = parse_modules(PROMO_EMAIL)
        assert 'other brand' not in summarize_for_retrieval(PROMO_EMAIL, modules, 'other')


class TestCategoryInference:
    @pytest.mark.parametrize('text,expected', [
        ('new leggings for your workout and gym training', 'activewear'),
        ('one scoop of protein powder, a daily supplement', 'supplements'),
        ('a gentle cleanser and vitamin C serum for skincare', 'beauty'),
        ('our new single origin roast, brewed slow', 'food_beverage'),
    ])
    def test_infers_known_categories(self, text, expected):
        assert infer_category(text) == expected

    def test_unknown_text_is_other_not_a_guess(self):
        assert infer_category('') == 'other'
        assert infer_category(None) == 'other'
        assert infer_category('zzz qqq') == 'other'

    def test_every_inferred_category_is_in_the_vocabulary(self):
        assert infer_category('leggings gym') in CATEGORIES
        assert infer_category('nothing relevant') in CATEGORIES
