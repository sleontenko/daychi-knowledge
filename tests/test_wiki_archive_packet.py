import copy
import json
import zipfile

import pytest

from scripts.wiki_archive_export import export
from scripts.wiki_archive_packet import build
from tests.test_wiki_archive_export import archive, save, rewrite_response


def prepare(archive):
    root, output, downloads, collection, audit = archive
    data=json.loads(collection.read_text())
    data['title']='Synthetic archive'
    for s in data['sources']:s['group']='retreat2016'
    save(collection,data)
    export(*archive)
    metadata=root.parent/'metadata.json'
    save(metadata,[{'id':fid,'url':'https://drive.google.com/file/d/'+fid+'/view'}
                   for fid in ['synthetic_a','synthetic_b']])
    return output,metadata,collection


def test_packet_covers_aliases_preserves_both_texts_and_private_bytes(archive):
    root=archive[0]
    rewrite_response(root,'turbo',lambda r:r.update(text='Полный текст <script>alert(1)</script>'))
    exports,metadata,collection=prepare(archive)
    output=root.parent/'packet'
    result=build([exports],[metadata],collection,output)
    assert len(result['source_ids'])==2 and len(result['recordings'])==1
    index=(output/'index.html').read_text()
    assert index.count('batch-1-recording-01.html')==2
    text=(output/'batch-1-recording-01.html').read_text()
    assert 'Полный текст &lt;script&gt;alert(1)&lt;/script&gt;' in text
    assert '<script>' not in text and 'Наблюдаем расслабление тела.' in text
    assert 'turbo:text_segment_alignment_mismatch' in text
    assert result['content_approved'] is False
    with zipfile.ZipFile(output/'archive-reading-packet.zip') as z:
        assert z.read('batch-1-recording-01/raw/turbo/part-01.json')==(exports/'raw/turbo/part-01.json').read_bytes()
    with pytest.raises(ValueError,match='already exists'):build([exports],[metadata],collection,output)


@pytest.mark.parametrize('damage',['scope','bytes','url','key','escape'])
def test_packet_rejects_missing_scope_tampering_and_unsafe_input(archive,damage):
    exports,metadata,collection=prepare(archive)
    output=archive[0].parent/'packet'
    if damage=='scope':
        data=json.loads(collection.read_text());data['sources'].append(dict(data['sources'][0],id='another'));save(collection,data)
    elif damage=='bytes':
        (exports/'raw/turbo/part-01.json').write_text('altered')
    elif damage in ['url','key']:
        data=json.loads(metadata.read_text());data[0]['url']=('https://other.test/file/d/synthetic_a/view' if damage=='url'
            else 'https://drive.google.com/file/d/synthetic_a/view?resourcekey=private');save(metadata,data)
    else:
        p=exports/'provenance.json';d=json.loads(p.read_text())
        d['recordings'][0]['raw_results'][0]['responses']['turbo']['path']='../../private-note.json';save(p,d)
    with pytest.raises(ValueError):build([exports],[metadata],collection,output)
    assert not output.exists()


def test_subtitle_timing_flags_survive_in_reading_page(archive):
    rewrite_response(archive[0],'turbo',lambda r:r['segments'][0].update(source_end=59))
    exports,metadata,collection=prepare(archive)
    output=archive[0].parent/'packet'
    build([exports],[metadata],collection,output)
    text=(output/'batch-1-recording-01.html').read_text()
    assert 'invalid_absolute_timing' in text
    assert 'Сегментов, пропущенных в SRT: 1' in text
    assert 'Наблюдаем расслабление тела.' in text


def test_rejects_duplicate_recording_keys_before_output(archive):
    exports, metadata, collection = prepare(archive)
    p = exports / 'provenance.json'
    data = json.loads(p.read_text())
    second = copy.deepcopy(data['recordings'][0])
    second['aliases'] = [second['aliases'][1]]
    data['recordings'][0]['aliases'] = data['recordings'][0]['aliases'][:1]
    data['recordings'].append(second)
    save(p, data)
    output = archive[0].parent / 'packet'
    with pytest.raises(ValueError):
        build([exports], [metadata], collection, output)
    assert not output.exists()


def test_rejects_duplicate_raw_clip_ids_before_output(archive):
    exports, metadata, collection = prepare(archive)
    p = exports / 'provenance.json'
    data = json.loads(p.read_text())
    raw = data['recordings'][0]['raw_results']
    raw.append(copy.deepcopy(raw[0]))
    save(p, data)
    output = archive[0].parent / 'packet'
    with pytest.raises(ValueError):
        build([exports], [metadata], collection, output)
    assert not output.exists()


@pytest.mark.parametrize('url',[
    'https://drive.google.com/file/d/synthetic_a/../synthetic_b/view',
    'https://drive.google.com/file/d/synthetic_a/%2e%2e/synthetic_b/view',
    'https://drive.google.com/file/d/synthetic_a/view#private',
    'https://drive.google.com/open?id=synthetic_b',
])
def test_rejects_drive_path_that_normalizes_to_other_source(archive,url):
    exports, metadata, collection = prepare(archive)
    data = json.loads(metadata.read_text())
    data[0]['url'] = url
    save(metadata, data)
    output = archive[0].parent / 'packet'
    with pytest.raises(ValueError):
        build([exports], [metadata], collection, output)
    assert not output.exists()


def test_zip_hashes_all_links_and_private_permissions(archive):
    exports, metadata, collection = prepare(archive)
    output = archive[0].parent / 'packet'
    result = build([exports], [metadata], collection, output)
    from hashlib import sha256
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self):
            super().__init__(); self.links = []
        def handle_starttag(self, tag, attrs):
            if tag == 'a': self.links.extend(v for k, v in attrs if k == 'href')
    with zipfile.ZipFile(output / 'archive-reading-packet.zip') as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        for name, expected in result['files'].items():
            assert sha256(z.read(name)).hexdigest() == expected
            assert (output / name).stat().st_mode & 0o777 == 0o600
        assert json.loads(z.read('packet.json')) == result
    for page in output.glob('*.html'):
        links = Links(); links.feed(page.read_text())
        for link in links.links:
            if not link.startswith('https://'):
                assert (output / link).is_file()
    assert result['content_approved'] is False and result['publication_ready'] is False


def test_cannot_substitute_turbo_response_under_parakeet_label(archive):
    root = archive[0]
    rewrite_response(root, 'parakeet', lambda r: r.update(text='Уникальный текст Parakeet.', segments=[
        {'text': 'Уникальный текст Parakeet.', 'start': 1, 'end': 4, 'source_start': 36, 'source_end': 39}]))
    exports, metadata, collection = prepare(archive)
    path = exports / 'provenance.json'
    data = json.loads(path.read_text())
    responses = data['recordings'][0]['raw_results'][0]['responses']
    responses['parakeet'] = copy.deepcopy(responses['turbo'])
    save(path, data)
    output = root.parent / 'packet'
    with pytest.raises(ValueError):
        build([exports], [metadata], collection, output)
    assert not output.exists()
