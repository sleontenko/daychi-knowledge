import json
from pathlib import Path

import pytest

from scripts.wiki_archive_export import export
from scripts.wiki_asr_pilot import sha256


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False))


@pytest.fixture
def archive(tmp_path):
    root = tmp_path/'asr'
    pcm = tmp_path/'pcm.wav'; pcm.write_bytes(b'synthetic PCM')
    original = tmp_path/'original.m4a'; original.write_bytes(b'synthetic original')
    log = tmp_path/'decode.log'; log.write_text('')
    source = {'id': 'recording-01', 'path': str(pcm), 'sha256': sha256(pcm),
              'seconds': 60, 'chunk_count': 1, 'excluded_intervals': [{'start': 0, 'end': 35}]}
    clip = {'id': 'part-01', 'recording_id': source['id'], 'path': str(pcm),
            'sha256': sha256(pcm), 'seconds': 10, 'source_offset_seconds': 35,
            'source_path': str(pcm), 'source_sha256': sha256(pcm)}
    save(root/'manifest.json', {'sources': [source], 'clips': [clip]})
    ids = ['drive:synthetic_a', 'drive:synthetic_b']
    save(root/'source-map.json', [{'recording_id': source['id'], 'source_ids': ids,
                                 'original_sha256': sha256(original), 'pcm_sha256': sha256(pcm),
                                 'duration_seconds': 60}])
    downloads = tmp_path/'downloads'
    for fid in ['synthetic_a', 'synthetic_b']:
        save(downloads/(fid+'.json'), {'id': fid, 'path': str(original), 'bytes': original.stat().st_size,
                                      'sha256': sha256(original), 'status': 'downloaded', 'name': 'Synthetic lesson'})
    collection = tmp_path/'collection.json'
    save(collection, {'collection_id': 'synthetic-archive', 'sources': [
        {'id': fid, 'title': 'Synthetic lesson', 'tags': ['архив']} for fid in ['synthetic_a', 'synthetic_b']]})
    audit = tmp_path/'audit.json'
    save(audit, {'files': [{'source_ids': ids, 'original_sha256': sha256(original), 'returncode': 0,
                          'status': 'decoded', 'stderr_path': str(log), 'stderr_sha256': sha256(log)}]})
    save(root/'production-review-queue.json', {'items': []})
    state = {'config': {'models': ['turbo', 'parakeet'], 'manifest_sha256': sha256(root/'manifest.json')}, 'models': {}}
    for model in ['turbo', 'parakeet']:
        result = {'clip_id': clip['id'], 'audio_sha256': clip['sha256'], 'seconds': 10,
                  'text': 'Наблюдаем расслабление тела.',
                  'segments': [{'text': 'Наблюдаем расслабление тела.', 'start': 1, 'end': 4,
                                'source_start': 36, 'source_end': 39}]}
        save(root/model/'part-01.json', result)
        state['models'][model] = {'status': 'finished', 'returncode': 0, 'completed_clips': 1,
                                 'response_sha256': {'part-01': sha256(root/model/'part-01.json')}}
    save(root/'worker-state.json', state)
    return root, tmp_path/'export', downloads, collection, audit


def rewrite_response(root, model, update):
    path = root/model/'part-01.json'
    result = json.loads(path.read_text()); update(result); save(path, result)
    state = json.loads((root/'worker-state.json').read_text())
    state['models'][model]['response_sha256']['part-01'] = sha256(path)
    save(root/'worker-state.json', state)


def test_archive_keeps_both_duplicate_ids_and_both_raw_engines(archive):
    result = export(*archive); root, output, *_ = archive
    record = result['recordings'][0]
    assert len(record['aliases']) == 2 and len(result['recordings']) == 1
    assert result['source_ids'] == ['drive:synthetic_a', 'drive:synthetic_b']
    assert record['excluded_intervals'] == [{'start': 0, 'end': 35}]
    assert '00:00:36,000 --> 00:00:39,000' in (output/'recording-01.turbo.srt').read_text()
    for model in ['turbo', 'parakeet']:
        assert (output/'raw'/model/'part-01.json').read_bytes() == (root/model/'part-01.json').read_bytes()
    assert result['content_approved'] is False and record['publication_ready'] is False
    assert export(*archive) == result


@pytest.mark.parametrize('changed', ['original', 'pcm', 'response', 'incomplete', 'scope'])
def test_rejects_changed_or_incomplete_evidence_before_writing(archive, changed):
    root, output, downloads, collection, _ = archive
    if changed in ['original', 'pcm']:
        (root.parent/('original.m4a' if changed == 'original' else 'pcm.wav')).write_bytes(b'changed')
    elif changed == 'response':
        path = root/'turbo/part-01.json'; path.write_bytes(path.read_bytes()+b' ')
    elif changed == 'scope':
        data = json.loads(collection.read_text()); data['sources'].pop(); save(collection, data)
    else:
        state = json.loads((root/'worker-state.json').read_text()); state['models'].pop('parakeet'); save(root/'worker-state.json', state)
    with pytest.raises(ValueError): export(*archive)
    assert not output.exists()


def test_absolute_time_damage_is_retained_in_raw_and_omitted_from_srt(archive):
    root, output, *_ = archive
    rewrite_response(root, 'turbo', lambda r: r['segments'][0].update(source_end=59))
    result = export(*archive)
    assert (output/'recording-01.turbo.srt').read_text() == '\n'
    record = result['recordings'][0]
    assert record['exports']['turbo']['srt_omitted_segments'] == 1
    assert 'invalid_absolute_timing' in record['segments']['turbo'][0]['quarantine_reasons']
    assert 'Наблюдаем' in (output/'recording-01.turbo.txt').read_text()


def test_recomputes_missing_disagreement_and_keeps_manual_flags(archive):
    root = archive[0]
    rewrite_response(root, 'parakeet', lambda r: r.update(text='Другая фраза.', segments=[
        {'text': 'Другая фраза.', 'start': 1, 'end': 4, 'source_start': 36, 'source_end': 39}]))
    save(root/'production-review-queue.json', {'items': [{'clip_id': 'part-01', 'reasons': ['manual_review_required']}]})
    result = export(*archive)
    for model in ['turbo', 'parakeet']:
        flags = result['recordings'][0]['segments'][model][0]['quarantine_reasons']
        assert {'manual_review_required', 'word_disagreement_above_15_percent'} <= set(flags)


def test_decode_warning_and_conflicting_replay_remain_visible(archive):
    root, output, _, _, audit = archive
    data = json.loads(audit.read_text()); data['files'][0]['status'] = 'decoded_with_warnings'; save(audit, data)
    log = root.parent/'decode.log'; log.write_text('Synthetic decoder warning')
    data['files'][0]['stderr_sha256'] = sha256(log); save(audit, data)
    result = export(*archive)
    assert result['recordings'][0]['source_warnings'] == ['decode_warnings_require_source_review']
    existing = output/'recording-01.turbo.txt'; existing.write_text('owner note')
    before = (output/'provenance.json').read_bytes()
    with pytest.raises(ValueError, match='Export exists'): export(*archive)
    assert existing.read_text() == 'owner note' and (output/'provenance.json').read_bytes() == before


def test_preserves_words_without_alignment_without_inventing_sentence_times(archive):
    root, output, *_ = archive
    rewrite_response(root, 'turbo', lambda r: r.update(text='Наблюдаем расслабление тела. Ещё одна фраза.'))
    result = export(*archive)
    assert 'Ещё одна фраза.' in (output/'recording-01.turbo.full.txt').read_text()
    assert 'Ещё одна фраза.' not in (output/'recording-01.turbo.srt').read_text()
    assert 'turbo:text_segment_alignment_mismatch' in result['recordings'][0]['segments']['turbo'][0]['quarantine_reasons']


def test_nonempty_unsegmented_text_stays_in_readable_txt(archive):
    root, output, *_ = archive
    rewrite_response(root, 'turbo', lambda r: r.update(text='Сохрани полный текст без сегментов.', segments=[]))
    result = export(*archive)
    assert result['recordings'][0]['content_approved'] is False
    full_path = result['recordings'][0]['exports']['turbo'].get('full_text_path', 'recording-01.turbo.txt')
    assert 'Сохрани полный текст без сегментов.' in (output / full_path).read_text()


def test_nonempty_decoder_log_cannot_export_as_clean(archive):
    *_, audit = archive
    data = json.loads(audit.read_text())
    log = Path(data['files'][0]['stderr_path'])
    log.write_text('Error submitting packet to decoder: Invalid data found when processing input\n')
    data['files'][0]['stderr_sha256'] = sha256(log)
    save(audit, data)
    with pytest.raises(ValueError, match='Decode status hides stderr'):
        export(*archive)
    assert not archive[1].exists()


def test_predictable_temp_symlink_never_modifies_external_file(archive, tmp_path):
    _, output, *_ = archive
    output.mkdir()
    victim = tmp_path / 'unrelated-private-note.txt'
    victim.write_text('must remain unchanged')
    (output / 'recording-01.turbo.txt.tmp').symlink_to(victim)
    try:
        export(*archive)
    except ValueError:
        pass
    assert victim.read_text() == 'must remain unchanged'


def test_output_parent_symlink_never_writes_outside_export(archive, tmp_path):
    _, output, *_ = archive
    output.mkdir()
    external = tmp_path / 'unrelated-directory'
    external.mkdir()
    (output / 'raw').symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match='Export path escapes directory'):
        export(*archive)
    assert list(external.iterdir()) == []


def test_shuffled_clip_manifest_is_sorted_or_rejected(archive):
    root, output, *_ = archive
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    first = manifest['clips'][0]
    second = dict(first, id='part-02', source_offset_seconds=45)
    manifest['sources'][0]['chunk_count'] = 2
    manifest['clips'] = [second, first]
    save(manifest_path, manifest)
    state = json.loads((root / 'worker-state.json').read_text())
    state['config']['manifest_sha256'] = sha256(manifest_path)
    for model in ['turbo', 'parakeet']:
        data = json.loads((root / model / 'part-01.json').read_text())
        data['clip_id'] = 'part-02'
        data['text'] = 'Следующая часть.'
        data['segments'] = [{'text': 'Следующая часть.', 'start': 1, 'end': 4, 'source_start': 46, 'source_end': 49}]
        save(root / model / 'part-02.json', data)
        state['models'][model]['completed_clips'] = 2
        state['models'][model]['response_sha256']['part-02'] = sha256(root / model / 'part-02.json')
    save(root / 'worker-state.json', state)
    export(*archive)
    text = (output / 'recording-01.turbo.srt').read_text()
    assert text.index('00:00:36,000') < text.index('00:00:46,000')


def test_srt_millisecond_rounding_does_not_emit_zero_length_cue(archive):
    root, output, *_ = archive
    rewrite_response(root, 'turbo', lambda r: r['segments'][0].update(
        start=1.0001, end=1.0002, source_start=36.0001, source_end=36.0002))
    result = export(*archive)
    assert '00:00:36,000 --> 00:00:36,000' not in (output / 'recording-01.turbo.srt').read_text()
    assert result['recordings'][0]['exports']['turbo']['srt_omitted_segments'] == 1
    segment = result['recordings'][0]['segments']['turbo'][0]
    assert (segment['start_seconds'], segment['end_seconds']) == (36.0001, 36.0002)
    assert 'srt_millisecond_interval_collapsed' in segment['quarantine_reasons']
    assert 'Наблюдаем расслабление тела.' in (output/'recording-01.turbo.txt').read_text()
    assert (output/'raw/turbo/part-01.json').read_bytes() == (root/'turbo/part-01.json').read_bytes()
