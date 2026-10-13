"""Synthetic owner-inventory reconciliation; no audio/editorial approval."""
import copy
import time

import pytest

from scripts.wiki_workflow_snapshot import make_snapshot
from tests.test_wiki_archive_article_contract import archive_fixture


def row(resource, imported=True, reviewed=True):
    value = [''] * 26
    value[0] = resource
    value[12] = 'pass' if reviewed else ''
    value[15] = 'synthetic-import-receipt' if imported else ''
    value[24] = 'Manual period retained'
    return value


def inventory(duplicate=False):
    source = copy.deepcopy(archive_fixture()['sources'][0])
    if duplicate:
        alias = copy.deepcopy(source['archive']['aliases'][0])
        alias['resource_id'] = 'drive:synthetic_source_duplicate'
        source['archive']['aliases'].append(alias)
    return {'id': source['material_id'], 'archive_source': source,
            'archive_article': {'format': 'daychi-wiki-archive-articles/1',
                                'revision': 3, 'status': 'text_reviewed_asr_draft'},
            'links': [{'url': 'https://drive.google.com/file/d/' + a['resource_id'][6:]}
                      for a in source['archive']['aliases']]}


def snapshot(tmp_path, live, rows, visibility='owner_inventory'):
    registry = tmp_path / 'registry'; registry.write_bytes(b'Synthetic unchanged registry')
    before = copy.deepcopy(rows)
    result = make_snapshot(registry, rows, live, {'dto_visibility': visibility}, time.time())
    assert rows == before and registry.read_bytes() == b'Synthetic unchanged registry'
    return result


def test_active_archive_article_coalesces_verified_binary_aliases(tmp_path):
    material = inventory(True)
    rows = [row(a['resource_id']) for a in material['archive_source']['archive']['aliases']]
    result = snapshot(tmp_path, [material], rows)
    assert result['counts']['registry_server_disagreements'] == 0
    assert result['counts']['production_archive_articles'] == 1
    assert result['counts']['production_archive_aliases'] == 2
    assert result['counts']['production_summaries'] == 0
    task, = result['tasks']
    assert (task['kind'], task['state'], task['revision']) == ('article', 'published_existing', 3)
    assert task['scope'] == sorted(r[0] for r in rows)
    assert task['blocked_reasons'] == []
    assert snapshot(tmp_path, [material], list(reversed(rows)))['tasks'] == result['tasks']


def test_alias_review_gap_cannot_be_hidden_by_other_reviewed_alias(tmp_path):
    material = inventory(True)
    rows = [row(a['resource_id']) for a in material['archive_source']['archive']['aliases']]
    rows[1][12] = ''
    task, = snapshot(tmp_path, [material], rows)['tasks']
    assert (task['kind'], task['state']) == ('review', 'available')
    assert len(task['scope']) == 2


def test_alias_disagreement_remains_blocked_after_coalescing(tmp_path):
    material = inventory(True)
    rows = [row(a['resource_id']) for a in material['archive_source']['archive']['aliases']]
    rows[1][15] = ''
    result = snapshot(tmp_path, [material], rows)
    assert result['counts']['registry_server_disagreements'] == 1
    assert result['tasks'][0]['state'] == 'blocked'
    assert result['tasks'][0]['blocked_reasons'] == ['registry_production_disagree']


@pytest.mark.parametrize('imported', [False, True])
def test_registered_source_without_active_article_is_not_publication(tmp_path, imported):
    material = inventory(); material.pop('archive_article')
    result = snapshot(tmp_path, [material], [row(material['archive_source']['resource_id'], imported)])
    task, = result['tasks']
    assert task['kind'] == 'prepare'
    assert task['state'] == ('blocked' if imported else 'available')
    assert result['counts']['production_archive_articles'] == 0


@pytest.mark.parametrize('visibility', ['private', 'public_sanitized'])
def test_archive_publication_needs_owner_inventory(tmp_path, visibility):
    material = inventory()
    with pytest.raises(ValueError, match='owner inventory'):
        snapshot(tmp_path, [material], [], visibility)


@pytest.mark.parametrize('mutation, message', [
    ('material', 'material binding'), ('link', 'alias links'), ('bytes', 'binary duplicates'),
    ('status', 'active archive article'), ('revision_bool', 'active archive article'),
    ('format', 'active archive article'),
])
def test_invalid_active_binding_fails_closed(tmp_path, mutation, message):
    material = inventory(True)
    if mutation == 'material': material['id'] = 'c' * 32
    if mutation == 'link': material['links'].pop()
    if mutation == 'bytes': material['archive_source']['archive']['aliases'][1]['original_bytes'] += 1
    if mutation == 'status': material['archive_article']['status'] = 'approved'
    if mutation == 'revision_bool': material['archive_article']['revision'] = True
    if mutation == 'format': material['archive_article']['format'] = 'daychi-wiki-articles/1'
    with pytest.raises(ValueError, match=message): snapshot(tmp_path, [material], [])


def test_alias_conflict_and_unverified_multiple_sources_are_not_coalesced(tmp_path):
    material = inventory()
    other = copy.deepcopy(material); other['id'] = 'c' * 32
    other['archive_source']['material_id'] = other['id']
    with pytest.raises(ValueError, match='multiple materials'):
        snapshot(tmp_path, [material, other], [])
    unverified = {'id': 'c'*32, 'links': [
        {'url': 'https://drive.google.com/file/d/synthetic_source_alpha'},
        {'url': 'https://drive.google.com/file/d/synthetic_source_duplicate'}],
        'annotation': {'resource_id': 'abcdefghijk', 'revision': 1, 'points': []}}
    rows = [row('yt:abcdefghijk'), row('drive:synthetic_source_alpha')]
    # A Drive URL cannot inherit an unrelated YouTube summary's publication.
    result = snapshot(tmp_path, [unverified], rows)
    assert next(t for t in result['tasks'] if t['scope'] == ['drive:synthetic_source_alpha'])['state'] == 'blocked'
