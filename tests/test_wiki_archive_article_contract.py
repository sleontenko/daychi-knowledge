import copy
import json

import pytest
from pydantic import ValidationError

from daychi_contracts.archive_articles import ArchiveBatch
from daychi_contracts.articles import ArticleBatch
from scripts.wiki_workflow import batch_payload, batch_scope, resource_scope
from tests.test_wiki_article_contract import fixture
from tests.test_wiki_workflow import ready, snapshot


def archive_fixture():
    value = fixture()
    value['format'] = 'daychi-wiki-archive-articles/1'
    identities = {'abcdefghijk': 'drive:synthetic_source_alpha', 'otherid1234': 'drive:synthetic_source_beta'}
    materials = {'stable': 'a' * 32, 'other': 'b' * 32}
    for source in value['sources']:
        source['resource_id'] = identities[source['resource_id']]
        source['material_id'] = materials[source['material_id']]
        source['archive'] = {'collection_id': 'synthetic-archive', 'cohort': 'neidan',
            'aliases': [{'resource_id': source['resource_id'], 'title': 'Synthetic original recording',
                         'original_sha256': 'e' * 64, 'original_bytes': 100}],
            'pcm_sha256': 'f' * 64, 'pcm_seconds': 60.0,
            'paired_asr_sha256': {'turbo': 'a' * 64, 'parakeet': 'b' * 64},
            'provenance_sha256': 'c' * 64, 'quarantine_sha256': 'd' * 64,
            'source_warnings': ['decoder_warning']}
    for article in value['articles']:
        article['resource_id'] = identities[article['resource_id']]
        article['material_id'] = materials[article['material_id']]
        article['status'] = 'text_reviewed_asr_draft'
        article['coverage_note'] = 'Only reviewed machine text; the recording has not been listened to.'
        for related in article['related']:
            related['material_id'] = materials[related['material_id']]
    for concept in value['concepts']:
        concept['status'] = 'text_reviewed_asr_draft'
    for link in value['links']:
        link['resource_id'] = identities[link['resource_id']]
    for evidence in value['evidence']:
        evidence['resource_id'] = identities[evidence['resource_id']]
        evidence['admission'] = {'basis': 'paired_asr_text_supported',
            'reason': 'The bounded source window supports the attributed paragraph in both text variants.',
            'clip_ids': ['synthetic-clip'], 'source_warning_codes': ['decoder_warning'],
            'clip_warning_codes': ['word_disagreement'], 'unresolved_issue_codes': [], 'audio_verified': False}
    return value


def test_archive_does_not_relax_the_active_youtube_contract():
    value = archive_fixture()
    assert ArchiveBatch(**value).articles[0].status == 'text_reviewed_asr_draft'
    with pytest.raises(ValidationError):
        ArticleBatch(**value)
    assert ArticleBatch(**fixture()).format == 'daychi-wiki-articles/1'


@pytest.mark.parametrize('mutation', ['warning', 'negation', 'audio', 'status', 'bounds', 'canonical', 'alias_bytes'])
def test_archive_rejects_fabricated_or_inconsistent_source_admission(mutation):
    value = archive_fixture()
    if mutation == 'warning': value['evidence'][0]['admission']['source_warning_codes'] = []
    if mutation == 'negation': value['evidence'][0]['admission']['unresolved_issue_codes'] = ['negation_conflict']
    if mutation == 'audio': value['evidence'][0]['admission']['audio_verified'] = True
    if mutation == 'status': value['articles'][0]['status'] = 'source_checked_draft'
    if mutation == 'bounds': value['evidence'][0]['end_seconds'] = 61
    if mutation == 'canonical': value['sources'][0]['resource_id'] = 'drive:wrong_source_identifier'
    if mutation == 'alias_bytes':
        value['sources'][0]['archive']['aliases'].append({'resource_id': 'drive:synthetic_source_z',
            'title': 'Synthetic duplicate', 'original_sha256': 'e' * 64, 'original_bytes': 101})
    with pytest.raises(ValidationError): ArchiveBatch(**value)


def test_corrected_pair_cannot_be_used_without_named_pinned_models():
    value = archive_fixture(); value['evidence'][0]['admission']['source_basis'] = 'corrected_pair'
    with pytest.raises(ValidationError): ArchiveBatch(**value)
    value['sources'][0]['archive']['corrected_asr'] = {
        'full_text_sha256': {'turbo_auto': 'a' * 64, 'large_auto': 'b' * 64},
        'model_ids': {'turbo_auto': 'Synthetic multilingual Turbo', 'large_auto': 'Synthetic multilingual Large'},
        'provenance_sha256': 'c' * 64, 'quarantine_sha256': 'd' * 64}
    assert ArchiveBatch(**value).evidence[0].admission.source_basis == 'corrected_pair'
    value['sources'][0]['archive']['corrected_asr']['model_ids']['parakeet'] = value['sources'][0]['archive']['corrected_asr']['model_ids'].pop('large_auto')
    with pytest.raises(ValidationError): ArchiveBatch(**value)


def test_duplicate_alias_is_reserved_and_revision_gate_preserved(ready, tmp_path):
    workflow, registry, _ = ready
    value = archive_fixture()
    alias = copy.deepcopy(value['sources'][0]['archive']['aliases'][0])
    alias['resource_id'] = 'drive:synthetic_source_z'
    value['sources'][0]['archive']['aliases'].append(alias)
    scope = batch_scope(value, 'article')
    assert alias['resource_id'] in scope and not any(s.startswith('yt:drive:') for s in scope)
    task = {'id': 'article:synthetic-archive:r1', 'target': 'synthetic-archive', 'kind': 'article',
            'revision': 1, 'state': 'available', 'scope': scope, 'source_fingerprint': 'synthetic',
            'object_revisions': {resource_scope(a['resource_id']): a['revision'] for a in value['articles']} |
                                {'concept:' + c['id']: c['revision'] for c in value['concepts']}}
    workflow.sync(snapshot(registry, [task]), 'coordinator')
    packet = workflow.claim([task['id']], 'editor', 'reviewer', value['batch_id'], 'coordinator')
    path = tmp_path/'batch.json'; path.write_text(json.dumps(value))
    assert batch_payload(path, 'article') == ArchiveBatch(**value).model_dump()
    workflow.submit(packet['assignment_id'], path, 'editor')
    workflow.review(packet['assignment_id'], {'assignment_id': packet['assignment_id'],
        'result_sha256': workflow.assignment(packet['assignment_id'])['result_hash'], 'decision': 'pass',
        'full_source_read': True, 'scope': scope, 'evidence': [{'path': 'synthetic-proof', 'sha256': 'c'*64}]}, 'reviewer')
    workflow.accept(packet['assignment_id'], 'owner', 'Synthetic explicit acceptance')
    with pytest.raises(ValueError, match='authorization'):
        workflow.check_import(packet['assignment_id'], batch_payload(path, 'article'), 'article', 'https://example.test')
