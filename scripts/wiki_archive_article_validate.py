"""Validate exact Drive archive pins, bounded text admissions and independent review.

Diagnostic flags remain immutable. A coherent window can be admitted as reviewed
machine text only when its specific unresolved-issue list is empty. This check
verifies evidence bindings; the separate reader must still assess every claim.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from daychi_contracts.archive_articles import ArchiveDocument
from scripts.wiki_workflow import batch_scope, file_hash, require


def read(path):
    return json.loads(Path(path).read_text())


def check_file(file):
    require(file_hash(file['path']) == file['sha256'], 'Pinned archive file changed')


def reading(proof, manifest, assignment, document_hash, manifest_hash, role):
    require(proof['assignment_id'] == assignment['assignment_id'] and
            proof['article_document_sha256'] == document_hash and
            proof['sources_manifest_sha256'] == manifest_hash,
            'Archive reading proof belongs to different final bytes')
    require(proof['complete_paired_asr_text_read'] is True and proof['audio_listened'] is False,
            'Archive proof must truthfully distinguish text reading from audio listening')
    require(proof[role] == assignment[role], 'Archive reader identity differs')
    records = {r['resource_id']: r for r in proof['records']}
    require(len(records) == len(proof['records']) and set(records) == set(manifest),
            'Incomplete archive source reading coverage')
    for rid, source in manifest.items():
        r = records[rid]
        if source.get('kind') == 'legacy_youtube':
            require(r['read_segment_indexes'] == list(range(source['segment_count'])) and r['files'] == source['reading_files'], 'Incomplete reused YouTube source reading')
            require(r['prior_proofs'], 'Attributed YouTube reading evidence required')
            for previous in r['prior_proofs']:
                check_file(previous); old = read(previous['path'])
                actor = old.get('editor', old.get('reviewer'))
                require(actor == previous['reader'] and actor in proof['readers'] and old.get('full_source_read') is True and old.get('audio_listened') is False, 'Prior YouTube reading must retain its actual reader and text-only status')
                require(any(item['resource_id'] == rid and item['files'] == source['reading_files'] and item['read_segment_indexes'] == r['read_segment_indexes'] for item in old['records']), 'Prior YouTube source pins or reading coverage differ')
            continue
        require(r['read_clip_ids'] == source['clip_ids'] and r['files'] == source['reading_files'],
                'Full paired source reading differs from source bytes')
        require(r['prior_proofs'], 'Attributed source reading evidence required')
        for previous in r['prior_proofs']:
            check_file(previous)
            envelope = read(previous['path'])
            old = envelope.get('read_proof', envelope)
            actor = old.get('editor', old.get('reviewer'))
            require(actor == previous['reader'] and actor in proof['readers'],
                    'Reading may only be reused from its actual attributed reader')
            require(old.get('complete_paired_ASR_text_read', old.get('complete_paired_asr_text_read')) is True
                    and old.get('audio_listened') is False, 'Prior source proof lacks complete text reading')
            if 'read_clip_ids' in old:
                complete_clips = old['read_clip_ids'] == source['clip_ids']
            else:
                windows = old.get('clip_windows_read', old.get('actual_clip_windows_read', []))
                complete_clips = old.get('all_clips_count') == len(source['clip_ids']) and bool(windows) and all(isinstance(a, int) and isinstance(b, int) and 0 <= a < b <= len(source['clip_ids']) for a, b in windows) and {i for a, b in windows for i in range(a, b)} == set(range(len(source['clip_ids'])))
            require(complete_clips, 'Prior reader did not cover every source clip')
            require(old['recording_id'] == source['recording_id'] and
                    old.get('asr_batch', source['asr_batch']) == source['asr_batch'], 'Prior reading source differs')
            require(all(old['file_hashes'].get(f['path']) == f['sha256']
                        for f in source['reading_files'].values()), 'Prior reading pins differ')


def validate(root, review_path=None):
    root = Path(root)
    document_path = root / 'article-document.json'
    document = ArchiveDocument.model_validate_json(document_path.read_text()).model_dump()
    document_hash = file_hash(document_path)
    assignment = read(root / 'assignment.json')
    scope = sorted(s for t in assignment['tasks'] for s in t['scope'])
    require(batch_scope(document, 'article') == scope, 'Archive is outside its reserved aliases/pages')
    manifest_path = root / 'source-manifest.json'
    values = read(manifest_path)
    manifest = {s['pin']['resource_id']: s for s in values}
    require(len(manifest) == len(values) and set(manifest) == {s['resource_id'] for s in document['sources']},
            'Archive source manifest coverage differs')
    records = {}
    for pin in document['sources']:
        source = manifest[pin['resource_id']]
        require(pin == source['pin'], 'Archive source pin differs')
        for file in list(source['files'].values()) + list(source['reading_files'].values()):
            check_file(file)
        if pin.get('archive') is None:
            require(source.get('kind') == 'legacy_youtube' and not pin['resource_id'].startswith('drive:'), 'Missing Drive archive authority')
            require(source['reading_files'] == source['files'], 'Legacy reading files differ from source pins')
            require(pin['transcript_sha256'] == source['files']['source.txt']['sha256'] and pin['subtitles_sha256'] == source['files']['source.ru.srt']['sha256'], 'Legacy wire transcript pins differ')
            segments = read(source['files']['segments.json']['path'])
            require(len(segments) == source['segment_count'] and Path(source['files']['source.txt']['path']).read_text().split() == ' '.join(s['text'] for s in segments).split(), 'Legacy full TXT and segments differ')
            records[pin['resource_id']] = segments
            continue
        require(pin['transcript_sha256'] == source['files']['wire_transcript']['sha256'] and
                pin['subtitles_sha256'] == source['files']['wire_subtitles']['sha256'], 'Wire transcript pins differ')
        require(pin.get('archive') is not None, 'Archive validator requires Drive sources')
        require(source['files']['pcm']['sha256'] == pin['archive']['pcm_sha256'], 'Physical PCM differs from source pin')
        original = read(source['files']['original_provenance']['path'])
        record = next(r for r in original['recordings'] if r['recording_id'] == source['recording_id'])
        require(sorted(a['source_id'] for a in record['aliases']) ==
                sorted(a['resource_id'] for a in pin['archive']['aliases']), 'Archive aliases differ')
        require(record['pcm_sha256'] == pin['archive']['pcm_sha256'] and
                record['pcm_seconds'] == pin['archive']['pcm_seconds'] and
                original['collection_id'] == pin['archive']['collection_id'], 'Original archive provenance differs')
        require(source['files']['original_provenance']['sha256'] == pin['archive']['provenance_sha256'] and
                source['files']['original_quarantine']['sha256'] == pin['archive']['quarantine_sha256'],
                'Immutable archive diagnostic pins differ')
        require(record['source_warnings'] == pin['archive']['source_warnings'], 'Source diagnostics omitted')
        for alias, expected in zip(sorted(record['aliases'], key=lambda a: a['source_id']),
                                   sorted(pin['archive']['aliases'], key=lambda a: a['resource_id'])):
            require(alias['original_sha256'] == expected['original_sha256'], 'Original alias bytes differ')
            original_file = source['files']['original:' + expected['resource_id']]
            require(original_file['sha256'] == expected['original_sha256'] and
                    Path(original_file['path']).stat().st_size == expected['original_bytes'], 'Original audio pin differs')
        require(record['raw_results'] and [r['clip_id'] for r in record['raw_results']] == source['clip_ids'],
                'Archive clip coverage differs')
        for model in ('turbo', 'parakeet'):
            require(pin['archive']['paired_asr_sha256'][model] == record['exports'][model]['full_text_sha256'],
                    'Original paired text pin differs')
        for model in ('turbo', 'parakeet'):
            full = next((f for f in source['files'].values() if f['sha256'] == record['exports'][model]['full_text_sha256']), None)
            require(full is not None, 'Original paired full text file not pinned')
        effective = record
        if pin['archive'].get('corrected_asr'):
            require(source.get('original_raw_root'), 'Corrected source requires a separate original raw root')
            check_file(source['files']['corrected_provenance'])
            require(source['files']['corrected_provenance']['sha256'] ==
                    pin['archive']['corrected_asr']['provenance_sha256'], 'Corrected provenance differs')
            effective = next(r for r in read(source['files']['corrected_provenance']['path'])['recordings']
                             if r['recording_id'] == source['recording_id'])
            require(effective['original_provenance_sha256'] == pin['archive']['provenance_sha256'],
                    'Corrected text lost original lineage')
            corrected = pin['archive']['corrected_asr']
            require(source['files']['corrected_quarantine']['sha256'] == corrected['quarantine_sha256'], 'Corrected quarantine differs')
            require(effective['model_ids'] == corrected['model_ids'] and
                    {m: e['full_text_sha256'] for m, e in effective['exports'].items()} == corrected['full_text_sha256'], 'Corrected paired text/model pins differ')
            for model, expected in corrected['full_text_sha256'].items():
                require(any(f['sha256'] == expected for f in source['reading_files'].values()), 'Corrected full text file not pinned')
            require([r['clip_id'] for r in effective['raw_results']] == source['clip_ids'], 'Corrected clip coverage differs')
        records[pin['resource_id']] = (record, effective)
        actual_models = {model: set() for model in effective['raw_results'][0]['responses']}
        for provenance_record, raw_root in [(record, source.get('original_raw_root', source['raw_root'])), (effective, source['raw_root'])]:
          for raw in provenance_record['raw_results']:
            expected_models = set(effective['model_ids']) if provenance_record is effective and pin['archive'].get('corrected_asr') else {'turbo', 'parakeet'}
            require(set(raw['responses']) == expected_models, 'Paired raw ASR model coverage differs')
            for model, response in raw['responses'].items():
                path = Path(raw_root) / response['path']
                require(file_hash(path) == response['sha256'], 'Effective raw ASR changed')
                value = read(path)
                require(value['clip_id'] == raw['clip_id'] and value['audio_sha256'] == raw['audio_sha256'],
                        'Effective ASR audio binding differs')
                if provenance_record is effective and pin['archive'].get('corrected_asr'):
                    actual_model = value.get('model_id', value.get('settings', {}).get('model'))
                    require(actual_model, 'Corrected raw model identity missing')
                    actual_models[model].add(actual_model)
        if pin['archive'].get('corrected_asr'):
            for model, actual in actual_models.items():
                expected = effective['model_ids'][model]
                require(expected == ('hybrid:' + '|'.join(sorted(actual))) if expected.startswith('hybrid:')
                        else actual == {expected}, 'Corrected raw model identity differs')
                require(effective['exports'][model].get('model_id') == expected, 'Corrected export model identity differs')
    evidence_provenance = read(root / 'evidence-provenance.json')
    by_id = {p['id']: p for p in evidence_provenance}
    require(len(by_id) == len(evidence_provenance) and set(by_id) == {e['id'] for e in document['evidence']},
            'Evidence provenance coverage differs')
    for evidence in document['evidence']:
        p = by_id[evidence['id']]
        require(p['resource_id'] == evidence['resource_id'], 'Evidence source differs')
        if manifest[evidence['resource_id']].get('kind') == 'legacy_youtube':
            indexes = p['segment_indexes']; segments = records[evidence['resource_id']]
            require(indexes and indexes == list(range(indexes[0], indexes[-1] + 1)) and 0 <= indexes[0] <= indexes[-1] < len(segments), 'Invalid legacy evidence window')
            require(not set(indexes).intersection(manifest[evidence['resource_id']]['forbidden_segment_indexes']), 'Quarantined legacy evidence')
            selected = [segments[i] for i in indexes]
            require(all(0 <= s['start_seconds'] < s['end_seconds'] for s in selected), 'Legacy selected timing is invalid')
            require(evidence['start_seconds'] == min(s['start_seconds'] for s in selected) and evidence['end_seconds'] == max(s['end_seconds'] for s in selected), 'Legacy quote timing differs')
            require(p['text_join'] in ('newline', 'whitespace'), 'Unknown legacy quote normalization')
            require(evidence['text'] == '\n'.join(s['text'] for s in selected) if p['text_join'] == 'newline' else evidence['text'].split() == ' '.join(s['text'] for s in selected).split(), 'Legacy quote text differs')
            continue
        original, effective = records[evidence['resource_id']]
        admission = evidence['admission']
        record = effective if admission['source_basis'] == 'corrected_pair' else original
        selected = [s for s in record['segments'][p['model']] if s['clip_id'] == p['clip_id']
                    and s['segment_index'] in p['segment_indexes']]
        indexes = p['segment_indexes']
        require(indexes and indexes == list(range(indexes[0], indexes[-1] + 1)) and
                len(selected) == len(indexes) and all(s['valid_srt_timing'] for s in selected),
                'Evidence needs an exact contiguous valid timing window')
        require(evidence['text'].split() == ' '.join(s['text'] for s in selected).split() and
                evidence['start_seconds'] == min(s['start_seconds'] for s in selected) and
                evidence['end_seconds'] == max(s['end_seconds'] for s in selected), 'Evidence quote/timing differs')
        raw = next(r for r in original['raw_results'] if r['clip_id'] == p['clip_id'])
        inherited = set(raw['quarantine_reasons'])
        effective_raw = next(r for r in effective['raw_results'] if r['clip_id'] == p['clip_id'])
        inherited.update(effective_raw['quarantine_reasons'])
        inherited.update(f for s in selected for f in s['quarantine_reasons'])
        require(set(admission['clip_warning_codes']) == inherited and admission['clip_ids'] == [p['clip_id']],
                'Window admission dropped immutable/corrected diagnostics')
    reading(read(root / 'source-reading-proof.json'), manifest, assignment, document_hash,
            file_hash(manifest_path), 'editor')
    if review_path:
        review_path = Path(review_path); review = read(review_path)
        require(review['assignment_id'] == assignment['assignment_id'] and review['result_sha256'] == document_hash
                and review['reviewer'] == assignment['reviewer'] and review['decision'] == 'pass'
                and assignment['reviewer'] != assignment['editor'] and set(review['scope']) == set(scope),
                'Independent exact-result archive review required')
        proof_path = review_path.parent / 'source-review-proof.json'
        require(file_hash(proof_path) == review['source_review_proof_sha256'], 'Reviewer proof changed')
        reading(read(proof_path), manifest, assignment, document_hash, file_hash(manifest_path), 'reviewer')
        editor_readers = set(read(root / 'source-reading-proof.json')['readers'])
        reviewer_readers = set(read(proof_path)['readers'])
        for source in manifest:
            editors = {p['reader'] for r in read(root / 'source-reading-proof.json')['records']
                       if r['resource_id'] == source for p in r['prior_proofs']}
            reviewers = {p['reader'] for r in read(proof_path)['records']
                         if r['resource_id'] == source for p in r['prior_proofs']}
            require(editors.isdisjoint(reviewers), 'A source author cannot independently review their own source')
        claims = [c for a in document['articles'] for c in a['claims']] + [c for cpt in document['concepts'] for c in cpt['claims']]
        require(Counter((c['id'], tuple(c['evidence_ids'])) for c in claims) ==
                Counter((c['claim_id'], tuple(c['evidence_ids'])) for c in review['claims']) and
                all(c['decision'] == 'pass' for c in review['claims']), 'Incomplete archive claim review')
        for key, objects in [('concepts', document['concepts']), ('links', document['links']), ('admissions', document['evidence'])]:
            require(Counter(o['id'] for o in objects) == Counter(o['id'] for o in review[key])
                    and all(o['decision'] == 'pass' for o in review[key]), 'Incomplete ' + key + ' review')
        links = {link['id']: link for link in document['links']}
        spans = Counter((a['resource_id'], c['id'], c['text'][m['start']:m['end']], links[m['link_id']]['concept_id'])
                        for a in document['articles'] for c in a['claims'] for m in c['mentions'])
        require(spans == Counter((m['resource_id'], m['claim_id'], m['text'], m['concept_id'])
                                for m in review['inline_mentions']) and
                all(m['decision'] == 'pass' and len(m.get('reason', '').strip()) >= 30 for m in review['inline_mentions']),
                'Incomplete inline placement review')
        paths = Counter((a['resource_id'], r['material_id'], r['via_concept_id'], tuple(r['supporting_link_ids']))
                        for a in document['articles'] for r in a['related'])
        require(paths == Counter((r['resource_id'], r['target_material_id'], r['via_concept_id'], tuple(r['supporting_link_ids']))
                                for r in review['related_materials']) and
                all(r['decision'] == 'pass' and len(r.get('reason', '').strip()) >= 30 for r in review['related_materials']),
                'Incomplete related path review')
        for file in review['evidence']:
            check_file(file)
    return {'article_document_sha256': document_hash, 'sources': len(values),
            'articles': len(document['articles']), 'concepts': len(document['concepts']),
            'independent_review_checked': bool(review_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.root, args.review)))
    except (ValueError, KeyError, OSError, StopIteration) as error:
        parser.exit(2, f'Blocked: {error}\n')


if __name__ == '__main__':
    main()
