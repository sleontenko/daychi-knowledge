"""Measure a private article batch; report aggregates without source names/IDs.

Wall intervals can overlap and must not be added. Token usage and cost stay null
unless an authoritative measurement is supplied separately. No imports or API calls.
"""
import argparse
import json
from pathlib import Path
import time

from scripts.wiki_article_validate import validate
from scripts.wiki_workflow import file_hash, write_private


def intervals(events):
    starts = {}; completed = []; last = None
    for event in events:
        at = event['at']; stage = event['stage']
        if not isinstance(at, (int, float)) or not 0 <= at < float('inf'):
            raise ValueError('Event time must be finite and nonnegative')
        if last is not None and at < last:
            raise ValueError('Events must be chronological')
        last = at
        if event['event'] == 'start':
            if stage in starts:
                raise ValueError('Stage already started')
            starts[stage] = at
        elif event['event'] == 'end':
            if stage not in starts:
                raise ValueError('Stage end has no start')
            begin = starts.pop(stage)
            completed.append({'stage': stage, 'elapsed_seconds': at - begin})
        else:
            raise ValueError('Unknown stage event')
    return {'completed': completed, 'open_stages': sorted(starts),
            'observed_wall_seconds': events[-1]['at'] - events[0]['at'] if events else None}


def benchmark(root, review=None):
    root = Path(root)
    started = time.perf_counter()
    checked = validate(root, review)
    validation_seconds = time.perf_counter() - started
    data = json.loads((root / 'article-document.json').read_text())
    sources = json.loads((root / 'source-manifest.json').read_text())
    events_path = root / 'benchmark-events.jsonl'
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()] if events_path.exists() else []
    articles = data['articles']
    pairs = {tuple(sorted((a['material_id'], r['material_id']))) for a in articles for r in a['related']}
    report = {'format': 'daychi-article-benchmark/1', 'validation': checked,
              'counts': {'sources': len(sources), 'words': sum(s['words'] for s in sources),
                         'segments': sum(s['segment_count'] for s in sources),
                         'recording_seconds': sum(s['duration_seconds'] for s in sources),
                         'articles': len(articles), 'sections': sum(len(a['sections']) for a in articles),
                         'article_paragraphs': sum(len(a['claims']) for a in articles),
                         'concepts': len(data['concepts']), 'concept_claims': sum(len(c['claims']) for c in data['concepts']),
                         'links': len(data['links']), 'inline_mentions': sum(len(c['mentions']) for a in articles for c in a['claims']),
                         'directed_related_paths': sum(len(a['related']) for a in articles), 'unique_related_pairs': len(pairs),
                         'evidence_windows': len(data['evidence'])},
              'timing': intervals(events), 'validation_seconds': validation_seconds,
              'events_sha256': file_hash(events_path) if events_path.exists() else None,
              'token_usage': None, 'cost': None, 'audio_listened': False,
              'accuracy_measured': False, 'production_ui_verified': False}
    write_private(root / 'benchmark-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--mark', metavar='STAGE:start|end', help='Record one measured wall-clock event without validation')
    args = parser.parse_args()
    if args.mark:
        stage, separator, event = args.mark.rpartition(':')
        if not separator or not stage or event not in ('start', 'end'):
            parser.error('--mark requires STAGE:start or STAGE:end')
        path = args.root / 'benchmark-events.jsonl'
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        events.append({'stage': stage, 'event': event, 'at': time.time()})
        intervals(events)
        args.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(''.join(json.dumps(e) + '\n' for e in events))
        path.chmod(0o600)
        print(f'Recorded {stage}:{event}.')
        return
    print(json.dumps(benchmark(args.root, args.review), ensure_ascii=False))


if __name__ == '__main__':
    main()
