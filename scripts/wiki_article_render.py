"""Render a private structured document into readable Markdown for editorial review.

This preview retains paragraphs, sections and contextual links. It is not proof
of the production reader or permission to publish. Outputs contain private content.
"""
import argparse
from pathlib import Path

from daychi_contracts.articles import ArticleDocument
from scripts.wiki_workflow import file_hash, write_private


def label(text):
    return text.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')


def render(root):
    root = Path(root)
    document_path = root / 'article-document.json'
    data = ArticleDocument.model_validate_json(document_path.read_text()).model_dump()
    output = root / 'readable'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    sources = {s['resource_id']: s for s in data['sources']}
    materials = {s['material_id']: s for s in data['sources']}
    links = {link['id']: link for link in data['links']}
    files = []

    def save(name, text):
        path = output / name
        path.write_text(text, encoding='utf-8')
        path.chmod(0o600)
        files.append({'path': str(path), 'sha256': file_hash(path)})

    def paragraph(claim):
        text = claim['text']; result = []; position = 0
        for mention in claim['mentions']:
            result.append(text[position:mention['start']])
            target = links[mention['link_id']]['concept_id']
            result.append(f"[{label(text[mention['start']:mention['end']])}](concept-{target}.md)")
            position = mention['end']
        result.append(text[position:])
        return ''.join(result)

    for article in data['articles']:
        claims = {c['id']: c for c in article['claims']}
        chunks = ['# ' + label(sources[article['resource_id']]['expected_title']),
                  'Статья по расшифровке · черновик']
        chunks.extend(paragraph(claims[i]) for i in article['introduction_claim_ids'])
        for section in article['sections']:
            chunks.append('## ' + label(section['heading']))
            chunks.extend(paragraph(claims[i]) for i in section['claim_ids'])
        chunks.append('## Связанные материалы')
        for related in article['related']:
            target = materials[related['material_id']]
            chunks.append(f"[{label(target['expected_title'])}](article-{target['material_id']}.md)\n\n{related['reason']}")
        save(f"article-{article['material_id']}.md", '\n\n'.join(chunks) + '\n')
    for concept in data['concepts']:
        chunks = ['# ' + label(concept['title']), 'По проверенным расшифровкам · черновик']
        chunks.extend(c['text'] for c in concept['claims'])
        chunks.append('## Материалы и подтверждения')
        for link in data['links']:
            if link['concept_id'] == concept['id']:
                source = sources[link['resource_id']]
                chunks.append(f"[{label(source['expected_title'])}](article-{source['material_id']}.md)\n\n{link['rationale']}")
        save(f"concept-{concept['id']}.md", '\n\n'.join(chunks) + '\n')
    manifest = {'article_document_sha256': file_hash(document_path), 'format': 'private-markdown-preview/1',
                'production_ui_verified': False, 'files': files}
    write_private(root / 'render-manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    manifest = render(args.root)
    print(f"Rendered {len(manifest['files'])} private pages; production UI not verified.")


if __name__ == '__main__':
    main()
