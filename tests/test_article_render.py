import json
from pathlib import Path

from scripts.wiki_article_render import render
from scripts.wiki_workflow import file_hash


def test_preview_preserves_unicode_mentions_paragraphs_and_targets(tmp_path):
    data = json.loads((Path(__file__).parent / 'fixtures/article-batch-v1.json').read_text())
    data.pop('review')
    article = data['articles'][0]
    claim = next(c for c in article['claims'] if c['mentions'])
    mention = claim['mentions'][0]
    claim['text'] = '🪷 ' + claim['text']
    for span in claim['mentions']:
        span['start'] += 2
        span['end'] += 2
    (tmp_path / 'article-document.json').write_text(json.dumps(data, ensure_ascii=False))
    manifest = render(tmp_path)
    text = (tmp_path / 'readable' / f"article-{article['material_id']}.md").read_text()
    link = next(l for l in data['links'] if l['id'] == mention['link_id'])
    selected = claim['text'][mention['start']:mention['end']]
    assert f"[{selected}](concept-{link['concept_id']}.md)" in text
    assert '🪷 ' in text
    for section in article['sections']:
        assert '\n\n## ' + section['heading'] + '\n\n' in text
    for related in article['related']:
        assert f"article-{related['material_id']}.md" in text
    assert manifest['article_document_sha256'] == file_hash(tmp_path / 'article-document.json')
    assert all(file_hash(f['path']) == f['sha256'] for f in manifest['files'])
    assert manifest['production_ui_verified'] is False
