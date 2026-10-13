"""Reviewer-authored synthetic tests for retained legacy YouTube source gates."""
import copy,json
from pathlib import Path
import pytest
from daychi_contracts.archive_articles import ArchiveDocument
from scripts.wiki_archive_article_validate import validate,reading
from scripts.wiki_workflow import batch_scope,file_hash
from tests.test_wiki_article_contract import fixture
from tests.test_wiki_archive_article_validate import packet as drive_packet

def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def pin(p):return {'path':str(p),'sha256':file_hash(p)}

def packet(root):
    value,manifest=drive_packet(root)
    legacy=fixture()['sources'][0];old_id=value['sources'][0]['resource_id'];old_mid=value['sources'][0]['material_id']
    value['sources'][0]=legacy
    for article in value['articles']:
        if article['resource_id']==old_id:
            article.update(resource_id=legacy['resource_id'],material_id=legacy['material_id'],status='source_checked_draft',coverage_note='')
        for related in article['related']:
            if related['material_id']==old_mid:related['material_id']=legacy['material_id']
    for link in value['links']:
        if link['resource_id']==old_id:link['resource_id']=legacy['resource_id']
    for e in value['evidence']:
        if e['resource_id']==old_id:e.update(resource_id=legacy['resource_id'],admission=None)
    provenance=json.loads((root/'evidence-provenance.json').read_text())
    for i,source in enumerate(value['sources'][:1]):
        e=value['evidence'][i];folder=root/source['resource_id'];folder.mkdir()
        words=e['text'].split();mid=max(1,len(words)//2);half=(e['start_seconds']+e['end_seconds'])/2
        segments=[{'text':' '.join(words[:mid]),'start_seconds':e['start_seconds'],'end_seconds':half},
                  {'text':' '.join(words[mid:]),'start_seconds':half,'end_seconds':e['end_seconds']}]
        files={}
        for name,body in [('source.txt',e['text']),('source.ru.srt','1\n00:00:00,000 --> 00:00:01,000\nSynthetic source\n'),('segments.json',json.dumps(segments,ensure_ascii=False))]:
            p=folder/name;p.write_text(body);files[name]=pin(p)
        source['transcript_sha256']=files['source.txt']['sha256'];source['subtitles_sha256']=files['source.ru.srt']['sha256']
        manifest[i]={'kind':'legacy_youtube','pin':source,'files':files,'reading_files':copy.deepcopy(files),
                     'segment_count':2,'forbidden_segment_indexes':[]}
        provenance[i]={'id':e['id'],'resource_id':e['resource_id'],'segment_indexes':[0,1],'text_join':'whitespace'}
    return value,manifest,provenance

def finalize(root,value,manifest,provenance,mutation):
    doc=ArchiveDocument(**value).model_dump();save(root/'article-document.json',doc)
    for m,s in zip(manifest,doc['sources']):m['pin']=s
    save(root/'source-manifest.json',manifest);save(root/'evidence-provenance.json',provenance)
    assignment={'assignment_id':'synthetic-legacy','editor':'editor','reviewer':'reviewer','tasks':[{'scope':batch_scope(doc,'article')}]}
    save(root/'assignment.json',assignment)
    for role in ['editor','reviewer']:
        reader=role+'-actual-reader';records=[]
        for i,m in enumerate(manifest):
            if m.get('kind')!='legacy_youtube':
                prior={role:reader,'complete_paired_ASR_text_read':True,'audio_listened':False,
                       'recording_id':m['recording_id'],'asr_batch':m['asr_batch'],'read_clip_ids':m['clip_ids'],
                       'file_hashes':{f['path']:f['sha256'] for f in m['reading_files'].values()}}
                path=root/'prior'/(role+str(i)+'.json');save(path,prior)
                records.append({'resource_id':m['pin']['resource_id'],'files':m['reading_files'],
                                'read_clip_ids':m['clip_ids'],'prior_proofs':[dict(pin(path),reader=reader)]})
                continue
            prior_record={'resource_id':m['pin']['resource_id'],'files':m['reading_files'],'read_segment_indexes':[0,1]}
            prior={role:reader,'full_source_read':True,'audio_listened':False,'records':[prior_record]}
            if role=='reviewer' and i==0:
                if mutation=='forged_prior_reader':prior[role]='unrelated-reader'
                if mutation=='prior_missing_segment':prior_record['read_segment_indexes']=[0]
                if mutation=='prior_wrong_source':prior_record['resource_id']=manifest[1]['pin']['resource_id']
                if mutation=='false_full_read':prior['full_source_read']=False
            path=root/'prior'/(role+str(i)+'.json');save(path,prior)
            records.append({'resource_id':m['pin']['resource_id'],'files':m['reading_files'],
                            'read_segment_indexes':[0] if mutation=='missing_segment' and role=='reviewer' and i==0 else [0,1],
                            'prior_proofs':[dict(pin(path),reader=reader)]})
        proof={'assignment_id':assignment['assignment_id'],role:role,'readers':[reader],
               'article_document_sha256':file_hash(root/'article-document.json'),
               'sources_manifest_sha256':file_hash(root/'source-manifest.json'),
               'complete_paired_asr_text_read':True,'audio_listened':False,'records':records}
        save(root/('source-reading-proof.json' if role=='editor' else 'review/source-review-proof.json'),proof)
    links={x['id']:x for x in doc['links']};reason='Independently assessed this synthetic destination and exact paragraph placement.'
    review={'assignment_id':assignment['assignment_id'],'result_sha256':file_hash(root/'article-document.json'),
            'reviewer':'reviewer','decision':'pass','scope':assignment['tasks'][0]['scope'],
            'source_review_proof_sha256':file_hash(root/'review/source-review-proof.json'),
            'claims':[{'claim_id':c['id'],'evidence_ids':c['evidence_ids'],'decision':'pass'} for a in doc['articles']+doc['concepts'] for c in a['claims']],
            **{key:[{'id':o['id'],'decision':'pass'} for o in doc[target]] for key,target in [('concepts','concepts'),('links','links'),('admissions','evidence')]},
            'inline_mentions':[{'resource_id':a['resource_id'],'claim_id':c['id'],'text':c['text'][m['start']:m['end']],
                                'concept_id':links[m['link_id']]['concept_id'],'decision':'pass','reason':reason}
                               for a in doc['articles'] for c in a['claims'] for m in c['mentions']],
            'related_materials':[{'resource_id':a['resource_id'],'target_material_id':r['material_id'],
                                  'via_concept_id':r['via_concept_id'],'supporting_link_ids':r['supporting_link_ids'],
                                  'decision':'pass','reason':reason} for a in doc['articles'] for r in a['related']],
            'evidence':[pin(root/'article-document.json')]}
    save(root/'review/review.json',review)
    if mutation=='source_changed':Path(manifest[0]['files']['source.txt']['path']).write_text('Changed after actual reading.')
    return validate(root,root/'review/review.json')

CASES=[('positive',None),
       ('forged_prior_reader','Prior YouTube reading must retain its actual reader and text-only status'),
       ('missing_segment','Incomplete reused YouTube source reading'),
       ('prior_missing_segment','Prior YouTube source pins or reading coverage differ'),
       ('prior_wrong_source','Prior YouTube source pins or reading coverage differ'),
       ('false_full_read','Prior YouTube reading must retain its actual reader and text-only status'),
       ('source_changed','Pinned archive file changed'),('forbidden','Quarantined legacy evidence'),
       ('wrong_source','Evidence source differs'),('wrong_quote','Legacy quote text differs'),
       ('invalid_selected_timing','Legacy selected timing is invalid'),
       ('unbound_reading_files','Legacy reading files differ from source pins')]

@pytest.mark.parametrize('mutation,expected',CASES,ids=[c[0] for c in CASES])
def test_legacy_source_gate(tmp_path,mutation,expected):
    value,manifest,provenance=packet(tmp_path)
    if mutation=='forbidden':manifest[0]['forbidden_segment_indexes']=[1]
    if mutation=='wrong_source':provenance[0]['resource_id']=value['sources'][1]['resource_id']
    if mutation=='wrong_quote':value['evidence'][0]['text']+=' Unsupported text.'
    if mutation=='invalid_selected_timing':
        p=Path(manifest[0]['files']['segments.json']['path']);segments=json.loads(p.read_text())
        segments[0]['end_seconds']=segments[0]['start_seconds'];save(p,segments)
        manifest[0]['files']['segments.json']=pin(p);manifest[0]['reading_files']=copy.deepcopy(manifest[0]['files'])
    if mutation=='unbound_reading_files':
        folder=tmp_path/'old_read';folder.mkdir()
        files={}
        for name in manifest[0]['files']:
            p=folder/name;p.write_text('Different older source content');files[name]=pin(p)
        manifest[0]['reading_files']=files
    if expected:
        with pytest.raises(ValueError,match=expected):finalize(tmp_path,value,manifest,provenance,mutation)
    else:
        result=finalize(tmp_path,value,manifest,provenance,mutation)
        assert result['sources']==2 and result['independent_review_checked'] is True

@pytest.mark.parametrize('mutation,expected',[
    ('half_open',None),('actual_windows',None),('embedded',None),
    ('gap','Prior reader did not cover every source clip'),
    ('wrong_count','Prior reader did not cover every source clip'),
    ('outside','Prior reader did not cover every source clip'),
    ('wrong_file_hash','Prior reading pins differ'),
    ('not_full','Prior source proof lacks complete text reading')])
def test_attributed_historical_window_proof(tmp_path,mutation,expected):
    files={}
    for model in ['turbo','parakeet']:
        path=tmp_path/(model+'.full.txt');path.write_text('Synthetic complete '+model+' source.')
        files[model]=pin(path)
    source={'recording_id':'same-recording-id','asr_batch':'synthetic-classes',
            'clip_ids':['c0','c1','c2'],'reading_files':files}
    old={'reviewer':'historical-reader','recording_id':source['recording_id'],
         'complete_paired_ASR_text_read':True,'audio_listened':False,'all_clips_count':3,
         'clip_windows_read':[[0,2],[2,3]],'file_hashes':{f['path']:f['sha256'] for f in files.values()}}
    if mutation=='actual_windows':old['actual_clip_windows_read']=old.pop('clip_windows_read')
    if mutation=='gap':old['clip_windows_read']=[[0,1],[2,3]]
    if mutation=='wrong_count':old['all_clips_count']=4
    if mutation=='outside':old['clip_windows_read']=[[0,4]]
    if mutation=='wrong_file_hash':old['file_hashes'][files['turbo']['path']]='0'*64
    if mutation=='not_full':old['complete_paired_ASR_text_read']=False
    path=tmp_path/'prior.json';save(path,{'read_proof':old} if mutation=='embedded' else old)
    proof={'assignment_id':'synthetic','article_document_sha256':'d'*64,'sources_manifest_sha256':'e'*64,
           'complete_paired_asr_text_read':True,'audio_listened':False,'reviewer':'assigned-reviewer',
           'readers':['historical-reader'],'records':[{'resource_id':'drive:synthetic_scope',
                'read_clip_ids':source['clip_ids'],'files':files,
                'prior_proofs':[dict(pin(path),reader='historical-reader')]}]}
    call=lambda:reading(proof,{'drive:synthetic_scope':source},{'assignment_id':'synthetic','reviewer':'assigned-reviewer'},'d'*64,'e'*64,'reviewer')
    if expected:
        with pytest.raises(ValueError,match=expected):call()
    else:call()
