"""Build a private, readable archive packet from completed paired ASR exports."""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import zipfile

from scripts.wiki_archive_export import identifier, stamp
from scripts.wiki_workflow import file_hash, require, write_private

GROUPS = {'retreat2016': 'Ретрит 2016', 'retreat2017': 'Ретрит 2017', 'neidan': 'Занятия Нэйдань'}
STYLE = '''body{font:18px/1.65 system-ui,sans-serif;max-width:880px;margin:48px auto;padding:0 24px;color:#252525}a{color:#285953}h1,h2,h3{line-height:1.25}h2{margin-top:40px}.notice{border-left:4px solid #aa7628;padding:12px 20px;background:#fff8ea}summary{cursor:pointer;font-weight:600}article{margin:24px 0;border-top:1px solid #ddd;padding-top:16px}.time{color:#666;font-size:14px}p{white-space:pre-wrap}li{margin:10px 0}code{overflow-wrap:anywhere}details{margin:20px 0}'''
NOTICE = 'Машинные черновики. Содержательная проверка и редактура не завершены. Таймкод блока обозначает начало аудиофрагмента, а не точное время каждого предложения.'


def page(title, body):
    return ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            + '<title>'+escape(title)+'</title><style>'+STYLE+'</style><main><h1>'+escape(title)+'</h1>'
            + '<p class="notice">'+NOTICE+'</p>'+body+'</main></html>').encode()


def checked_file(root, relative, expected):
    path = Path(relative)
    require(not path.is_absolute() and '..' not in path.parts, 'Unsafe packet input path')
    target = root/path
    require(not target.is_symlink() and target.resolve().is_relative_to(root.resolve()), 'Packet input escapes export')
    require(file_hash(target) == expected, 'Export file changed')
    return target


def source_url(metadata, fid):
    url = metadata['url']
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    require('resourcekey' not in {key.lower() for key in query}, 'Resource key must stay outside packet')
    require(parts.scheme == 'https' and parts.netloc == 'drive.google.com' and not parts.fragment
            and set(query) <= {'id', 'usp', 'authuser'}
            and ('id' not in query or query['id'] == [fid])
            and (parts.path in ['/file/d/'+fid, '/file/d/'+fid+'/view']
                 or (parts.path == '/open' and query.get('id') == [fid])), 'Drive URL identity differs')
    return url


def build(exports, metadata_paths, collection_path, output):
    output = Path(output)
    require(not output.exists(), 'Packet output already exists; use a new revision')
    collection = json.loads(Path(collection_path).read_text())
    catalog = {identifier(s['id']): s for s in collection['sources']}
    require(len(catalog) == len(collection['sources']), 'Duplicate collection source')
    metadata = {}
    for path in metadata_paths:
        data = json.loads(Path(path).read_text())
        for item in (data['files'] if isinstance(data, dict) else data):
            fid = identifier(item['id'])
            require(fid not in metadata, 'Duplicate connector metadata')
            metadata[fid] = item
    groups, files, rows, seen = {}, {}, [], set()
    pins = {str(Path(p).resolve()): file_hash(p) for p in [collection_path, *metadata_paths]}
    for number, root in enumerate(map(Path, exports), 1):
        provenance_path = root/'provenance.json'
        provenance = json.loads(provenance_path.read_text())
        pins[str(provenance_path.resolve())] = file_hash(provenance_path)
        require(provenance['schema'] == 'private_drive_asr_archive_v1'
                and provenance['collection_id'] == collection['collection_id']
                and provenance['status'] == 'machine_unverified'
                and provenance['content_approved'] is False
                and provenance['publication_ready'] is False, 'Unrecognized archive draft')
        declared = []
        recording_ids = [identifier(record['recording_id']) for record in provenance['recordings']]
        require(len(recording_ids) == len(set(recording_ids)), 'Duplicate recording ID')
        for record in provenance['recordings']:
            require(record['content_approved'] is False and record['publication_ready'] is False, 'Approved record is out of scope')
            key = f"batch-{number}-"+identifier(record['recording_id'])
            aliases = []
            for alias in record['aliases']:
                fid = identifier(alias['source_id'].removeprefix('drive:'))
                require(alias['source_id'] == 'drive:'+fid and fid in catalog and fid not in seen, 'Source scope differs')
                seen.add(fid); declared.append('drive:'+fid)
                aliases.append({'source_id': 'drive:'+fid, 'title': alias['title'], 'group': catalog[fid]['group'],
                                'url': source_url(metadata[fid], fid), 'tags': catalog[fid]['tags']})
            require(aliases, 'Recording has no source IDs')
            row = {'key': key, 'aliases': aliases, 'page': key+'.html', 'pcm_seconds': record['pcm_seconds'],
                   'decode_warnings': record['source_warnings'], 'content_approved': False, 'publication_ready': False}
            title = aliases[0]['title']
            body = '<a href="index.html">← Каталог архива</a><h2>Оригиналы</h2><ul>'
            for alias in aliases:
                body += '<li><a href="'+escape(alias['url'], quote=True)+'">'+escape(alias['title'])+'</a> · '+escape(GROUPS.get(alias['group'],alias['group']))+'</li>'
                groups.setdefault(alias['group'], []).append((alias, row))
            body += '</ul><p>Продолжительность PCM: '+escape(stamp(record['pcm_seconds']).replace(',', '.'))+'</p>'
            if len(aliases) > 1:
                body += '<p>Одна бинарная запись, несколько исходных ID. Все ссылки сохранены.</p>'
            excluded = record['excluded_intervals']
            body += '<details><summary>Интервалы вне VAD: '+str(len(excluded))+'</summary><p>Не проверены прослушиванием.</p><ul>'
            body += ''.join('<li>'+stamp(i['start'])+' — '+stamp(i['end'])+'</li>' for i in excluded)+'</ul></details>'
            if record['source_warnings']:
                body += '<p class="notice">Декодер сообщил ошибки: требуется проверка оригинала.</p>'
            review_flags = {r['clip_id']: set(r['quarantine_reasons']) for r in record['raw_results']}
            require(len(review_flags) == len(record['raw_results']), 'Duplicate raw clip ID')
            for segments in record['segments'].values():
                for segment in segments:
                    require(segment['clip_id'] in review_flags, 'Unknown segment clip')
                    review_flags[segment['clip_id']].update(segment['quarantine_reasons'])
            flagged = sum(bool(flags) for flags in review_flags.values())
            row['flagged_clips'] = flagged
            body += '<p>Фрагментов для проверки: '+str(flagged)+' из '+str(len(record['raw_results']))+'. Флаги — эвристика, не измеренная точность.</p>'
            for model in ['turbo','parakeet']:
                body += '<details'+(' open' if model == 'turbo' else '')+'><summary>'+model.title()+' · полный распознанный текст</summary>'
                body += '<p>Сегментов, пропущенных в SRT: '+str(record['exports'][model]['srt_omitted_segments'])+'. Исходный текст сохранён.</p>'
                for clip in record['raw_results']:
                    response = clip['responses'][model]
                    require(response['path'] == 'raw/'+model+'/'+identifier(clip['clip_id'])+'.json', 'Model response namespace differs')
                    path = checked_file(root, response['path'], response['sha256'])
                    raw = path.read_bytes(); data = json.loads(raw)
                    require(data['clip_id'] == clip['clip_id'] and data['audio_sha256'] == clip['audio_sha256'], 'Raw clip identity differs')
                    destination = key+'/'+response['path']
                    files[destination] = raw
                    body += '<article><div class="time">Начало фрагмента: '+stamp(clip['source_offset_seconds'])+'</div>'
                    if review_flags[clip['clip_id']]:
                        body += '<details><summary>Требует проверки</summary><ul>'+''.join('<li>'+escape(f)+'</li>' for f in sorted(review_flags[clip['clip_id']]))+'</ul></details>'
                    body += '<p>'+escape(data['text'])+'</p></article>'
                body += '</details><p>'
                for path_field, hash_field, label in [('full_text_path','full_text_sha256','Полный TXT'),('txt_path','txt_sha256','Сегменты TXT'),('srt_path','srt_sha256','SRT')]:
                    exported = record['exports'][model]
                    suffix = {'full_text_path':'.full.txt','txt_path':'.txt','srt_path':'.srt'}[path_field]
                    require(exported[path_field] == record['recording_id']+'.'+model+suffix, 'Model export namespace differs')
                    path = checked_file(root, exported[path_field], exported[hash_field])
                    relative = key+'/'+Path(exported[path_field]).name
                    files[relative] = path.read_bytes()
                    body += '<a href="'+escape(relative,quote=True)+'">'+label+'</a> · '
                body += '</p>'
            files[key+'.html'] = page(title, body)
            rows.append(row)
        require(sorted(declared) == sorted(provenance['source_ids']), 'Export source list differs')
        files['batch-'+str(number)+'/provenance.json'] = provenance_path.read_bytes()
    require(seen == set(catalog), 'Packet does not cover entire collection')
    body = '<p>Источников: '+str(len(seen))+'. Уникальных записей: '+str(len(rows))+'.</p>'
    for group in sorted(groups):
        body += '<h2>'+escape(GROUPS.get(group,group))+'</h2><ul>'
        for alias, row in sorted(groups[group], key=lambda r:r[0]['title']):
            body += '<li><a href="'+row['page']+'">'+escape(alias['title'])+'</a> · '+str(row['flagged_clips'])+' фрагментов для проверки</li>'
        body += '</ul>'
    files['index.html'] = page(collection['title'],body)
    manifest = {'schema':'private_archive_reading_packet_v1','collection_id':collection['collection_id'],
                'source_ids': sorted('drive:'+fid for fid in seen),'recordings':rows,'input_hashes':pins,
                'files': {},'status':'machine_unverified','content_approved':False,'publication_ready':False}
    import hashlib
    manifest['files'] = {name:hashlib.sha256(data).hexdigest() for name,data in files.items()}
    files['packet.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    output.mkdir(parents=True,mode=0o700)
    for name,data in files.items():
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        path.write_bytes(data);path.chmod(0o600)
    archive=output/'archive-reading-packet.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in files: z.write(output/name,arcname=name)
    archive.chmod(0o600)
    write_private(output/'receipt.json',{'zip_sha256':file_hash(archive),'packet_sha256':file_hash(output/'packet.json'),
                  'source_count':len(seen),'recording_count':len(rows),'content_approved':False})
    return manifest


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--exports',type=Path,action='append',required=True)
    p.add_argument('--metadata',type=Path,action='append',required=True)
    p.add_argument('--collection',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    result=build(args.exports,args.metadata,args.collection,args.output)
    print('Prepared reading packet for',len(result['source_ids']),'source IDs; machine drafts only')
