"""Export private Drive ASR drafts with stable aliases; never a publication batch."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

from scripts.wiki_asr_gate import reasons
from scripts.wiki_asr_pilot import sha256
from scripts.wiki_asr_score import errors, words
from scripts.wiki_workflow import require


def load(path):
    return json.loads(Path(path).read_text())


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]+', value),
            'Unsafe local identifier')
    return value


def stamp(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return 'invalid-timestamp'
    ms = round(value * 1000)
    return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'


def export(root, output, downloads, collection, decode_audit):
    root, output, downloads = Path(root), Path(output), Path(downloads)
    manifest = load(root/'manifest.json')
    mappings = load(root/'source-map.json')
    state = load(root/'worker-state.json')
    catalog = load(collection)
    audit = load(decode_audit)
    queue = load(root/'production-review-queue.json')
    sources = {identifier(s['id']): s for s in manifest['sources']}
    require(len(sources) == len(manifest['sources']), 'Duplicate recording')
    require(len({m['recording_id'] for m in mappings}) == len(mappings)
            and {m['recording_id'] for m in mappings} == set(sources), 'Source mapping differs')
    source_ids = [s for m in mappings for s in m['source_ids']]
    require(all(m['source_ids'] for m in mappings), 'Recording has no source aliases')
    require(len(source_ids) == len(set(source_ids)), 'Duplicate source alias')
    catalog_sources = {'drive:'+identifier(s['id']): s for s in catalog['sources']}
    require(len(catalog_sources) == len(catalog['sources']), 'Duplicate catalogue source')
    require(set(source_ids) <= set(catalog_sources), 'Unassigned archive source')
    clips = {identifier(c['id']): c for c in manifest['clips']}
    require(len(clips) == len(manifest['clips']), 'Duplicate clip')
    require(all(c['recording_id'] in sources for c in clips.values()), 'Unknown clip recording')
    require(state['config']['manifest_sha256'] == sha256(root/'manifest.json'), 'Worker manifest differs')
    require(state['config']['models'] == ['turbo', 'parakeet'], 'Paired models required')
    for model in ['turbo', 'parakeet']:
        run = state['models'].get(model, {})
        require(run.get('status') == 'finished' and run.get('returncode') == 0
                and run.get('completed_clips') == len(clips)
                and set(run.get('response_sha256', {})) == set(clips), 'Incomplete paired ASR')
    flags = {}
    for item in queue['items']:
        require(item['clip_id'] in clips and item['clip_id'] not in flags, 'Invalid review queue')
        flags[item['clip_id']] = list(item.get('reasons') or ['queued_for_review'])
    audits = {s: row for row in audit['files'] for s in row['source_ids']}
    files, records = {}, []
    for mapping in mappings:
        source = sources[mapping['recording_id']]
        pcm_hash = sha256(source['path'])
        require(pcm_hash == source['sha256'] == mapping['pcm_sha256'], 'PCM source changed')
        require(source['seconds'] == mapping['duration_seconds'], 'PCM duration differs')
        aliases = []
        source_warnings = set()
        for rid in mapping['source_ids']:
            fid = identifier(rid.removeprefix('drive:'))
            require(rid == 'drive:'+fid, 'Drive source ID required')
            receipt_path = downloads/(fid+'.json')
            receipt = load(receipt_path)
            require(receipt['id'] == fid and receipt['status'] == 'downloaded', 'Original identity differs')
            require(Path(receipt['path']).stat().st_size == receipt['bytes']
                    and sha256(receipt['path']) == receipt['sha256'] == mapping['original_sha256'],
                    'Original audio changed')
            checked = audits.get(rid, {})
            require(checked.get('original_sha256') == receipt['sha256']
                    and checked.get('returncode') == 0
                    and checked.get('status') in ['decoded', 'decoded_with_warnings']
                    and sha256(checked['stderr_path']) == checked['stderr_sha256'], 'Decode evidence differs')
            require(bool(Path(checked['stderr_path']).read_text().strip())
                    == (checked['status'] == 'decoded_with_warnings'), 'Decode status hides stderr')
            if checked['status'] == 'decoded_with_warnings':
                source_warnings.add('decode_warnings_require_source_review')
            aliases.append({'source_id': rid, 'title': receipt['name'],
                            'catalog_title': catalog_sources[rid]['title'],
                            'tags': catalog_sources[rid]['tags'],
                            'original_path': receipt['path'], 'original_sha256': receipt['sha256'],
                            'download_receipt_sha256': sha256(receipt_path),
                            'decode_status': checked['status']})
        selected = sorted((c for c in manifest['clips'] if c['recording_id'] == source['id']),
                          key=lambda c: c['source_offset_seconds'])
        require(len(selected) == source['chunk_count'], 'Recording clip count differs')
        require(all(a['source_offset_seconds'] + a['seconds'] <= b['source_offset_seconds'] + .001
                    for a, b in zip(selected, selected[1:])), 'Overlapping source clips')
        segments, full_text, raw, model_files = {}, {}, [], {}
        for model in ['turbo', 'parakeet']:
            segments[model] = []
            full_text[model] = []
        for clip in selected:
            require(sha256(clip['path']) == clip['sha256']
                    and clip['source_sha256'] == pcm_hash
                    and Path(clip['source_path']).resolve() == Path(source['path']).resolve(),
                    'Clip provenance differs')
            require(0 <= clip['source_offset_seconds'] < source['seconds']
                    and 0 < clip['seconds'] <= source['seconds'] - clip['source_offset_seconds'] + .001,
                    'Clip bounds differ')
            responses, results, gates = {}, {}, {}
            for model in ['turbo', 'parakeet']:
                path = root/model/(clip['id']+'.json')
                data = path.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                result = json.loads(data)
                require(digest == state['models'][model]['response_sha256'][clip['id']], 'ASR response changed')
                require(result['clip_id'] == clip['id'] and result['audio_sha256'] == clip['sha256']
                        and result['seconds'] == clip['seconds'], 'ASR audio binding differs')
                relative = 'raw/'+model+'/'+clip['id']+'.json'
                files[relative] = data
                gate = reasons(result)
                responses[model] = {'path': relative, 'sha256': digest, 'mechanical_flags': gate}
                results[model], gates[model] = result, gate
            a, b = (words(results[model]['text']) for model in ['turbo', 'parakeet'])
            disagreement = errors(a, b)['errors'] / max(len(a), len(b)) if a or b else 0
            combined = set(flags.get(clip['id'], [])) | source_warnings
            combined.update(model+':'+reason for model, gate in gates.items() for reason in gate)
            if disagreement > .15:
                combined.add('word_disagreement_above_15_percent')
            if bool(a) != bool(b):
                combined.add('one_engine_empty')
            if not a and not b:
                combined.add('both_empty_on_vad_speech')
            for model, result in results.items():
                full_text[model].append(f"[clip starts {stamp(clip['source_offset_seconds'])}] {result['text']}")
                if result['text'].strip() and not result['segments']:
                    combined.add(model+':text_without_segments')
                if words(result['text']) != words(' '.join(s['text'] for s in result['segments'])):
                    combined.add(model+':text_segment_alignment_mismatch')
            for model, result in results.items():
                for number, segment in enumerate(result['segments']):
                    start, end = segment['source_start'], segment['source_end']
                    valid = (all(isinstance(v, (int, float)) and math.isfinite(v)
                                 for v in [start, end, segment['start'], segment['end']])
                             and 0 <= segment['start'] < segment['end'] <= clip['seconds'] + .001
                             and 0 <= start < end <= source['seconds']
                             and abs(start - clip['source_offset_seconds'] - segment['start']) < .001
                             and abs(end - clip['source_offset_seconds'] - segment['end']) < .001)
                    timing_flags = set() if valid else {'invalid_absolute_timing'}
                    if valid and round(end * 1000) <= round(start * 1000):
                        valid = False
                        timing_flags.add('srt_millisecond_interval_collapsed')
                    segments[model].append({'clip_id': clip['id'], 'segment_index': number,
                                            'text': segment['text'], 'start_seconds': start,
                                            'end_seconds': end, 'valid_srt_timing': valid,
                                            'quarantine_reasons': sorted(combined | timing_flags),
                                            'content_approved': False})
            raw.append({'clip_id': clip['id'], 'audio_sha256': clip['sha256'],
                        'source_offset_seconds': clip['source_offset_seconds'], 'responses': responses,
                        'quarantine_reasons': sorted(combined), 'normalized_distance': disagreement,
                        'flags_are_heuristic': True, 'content_approved': False})
        for model, items in segments.items():
            prefix = source['id']+'.'+model
            text = ('Machine ASR draft. Not listened to, edited or approved.\n'
                    + '\n'.join(f"[{stamp(s['start_seconds'])}] {s['text']}" for s in items) + '\n')
            valid = sorted((s for s in items if s['valid_srt_timing'] and s['text'].strip()),
                           key=lambda s: (s['start_seconds'], s['end_seconds']))
            srt = '\n\n'.join(f"{n}\n{stamp(s['start_seconds'])} --> {stamp(s['end_seconds'])}\n{s['text']}"
                                for n, s in enumerate(valid, 1)) + '\n'
            complete = ('Machine ASR draft. Clip-start markers are not sentence timestamps.\n'
                        + '\n\n'.join(full_text[model]) + '\n')
            for suffix, content in [('txt', text), ('srt', srt), ('full.txt', complete)]:
                files[prefix+'.'+suffix] = content.encode()
            model_files[model] = {'txt_path': prefix+'.txt', 'srt_path': prefix+'.srt',
                                  'txt_sha256': hashlib.sha256(text.encode()).hexdigest(),
                                  'srt_sha256': hashlib.sha256(srt.encode()).hexdigest(),
                                  'full_text_path': prefix+'.full.txt',
                                  'full_text_sha256': hashlib.sha256(complete.encode()).hexdigest(),
                                  'srt_omitted_segments': len(items) - len(valid)}
        records.append({'recording_id': source['id'], 'aliases': aliases,
                        'pcm_sha256': pcm_hash, 'pcm_seconds': source['seconds'],
                        'excluded_intervals': source['excluded_intervals'],
                        'source_warnings': sorted(source_warnings), 'raw_results': raw,
                        'segments': segments, 'exports': model_files,
                        'status': 'machine_unverified', 'verified_by_listener': False,
                        'content_approved': False, 'publication_ready': False})
    value = {'schema': 'private_drive_asr_archive_v1', 'collection_id': catalog['collection_id'],
             'input_hashes': {str(Path(p).resolve()): sha256(p) for p in
                             [root/'manifest.json', root/'source-map.json', root/'worker-state.json',
                              root/'production-review-queue.json', collection, decode_audit]},
             'source_ids': sorted(source_ids), 'recordings': records,
             'status': 'machine_unverified', 'content_approved': False, 'publication_ready': False}
    files['provenance.json'] = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()
    # Validate every conflict before writing any output; replay must preserve bytes.
    require(not output.is_symlink(), 'Export directory is a symlink')
    destination = output.resolve()
    for name, data in files.items():
        path = output/name
        require(not path.is_symlink() and path.resolve().is_relative_to(destination), 'Export path escapes directory')
        require(not path.exists() or path.read_bytes() == data, 'Export exists with different content')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name, data in files.items():
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        require(path.parent.resolve().is_relative_to(destination), 'Export path escapes directory')
        if not path.exists():
            fd, name = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
            temp = Path(name)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                # Atomic creation refuses to overwrite a file appearing during export.
                os.link(temp, path)
            finally:
                temp.unlink()
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['root', 'output', 'downloads', 'collection', 'decode-audit']:
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    result = export(args.root, args.output, args.downloads, args.collection, args.decode_audit)
    print(f"Exported {len(result['recordings'])} machine drafts for {len(result['source_ids'])} Drive IDs; no approval")
