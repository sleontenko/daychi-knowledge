"""Synthetic local repros only; never touches corpus, coordinator or network."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from daychi_contracts.archive_articles import ArchiveDocument
from scripts.wiki_archive_article_validate import validate
from scripts.wiki_workflow import batch_scope
from tests.test_wiki_archive_article_contract import archive_fixture

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def file(path):return {'path':str(path),'sha256':sha(path)}

def packet(root,corrected=False):
    value=archive_fixture();value.pop('review')
    original=[];manifest=[]
    for i,pin in enumerate(value['sources']):
        rid=f'recording-{i:02}';clip='synthetic-clip';e=value['evidence'][i]
        audio=root/(rid+'.original');audio.write_bytes(b'Synthetic original, not real audio.')
        pcm=root/(rid+'.pcm');pcm.write_bytes(b'Synthetic PCM bytes.')
        subs=root/(rid+'.srt');subs.write_text(e['text'])
        reads={};responses={}
        for model in ('turbo','parakeet'):
            full=root/(rid+'.'+model+'.full.txt');full.write_text(e['text'])
            reads[model]=file(full)
            raw=root/'raw-original'/rid/(model+'.json')
            body={'clip_id':clip,'audio_sha256':'1'*64,'model_id':'actual-'+model,'text':e['text'],
                  'segments':[{'start':e['start_seconds'],'end':e['end_seconds'],'text':e['text']}]}
            save(raw,body);responses[model]={'path':str(raw.relative_to(root/'raw-original')),'sha256':sha(raw)}
        pin.update(transcript_sha256=reads['turbo']['sha256'],subtitles_sha256=sha(subs))
        pin['archive'].update(pcm_sha256=sha(pcm),paired_asr_sha256={m:reads[m]['sha256'] for m in reads})
        for alias in pin['archive']['aliases']:alias.update(original_sha256=sha(audio),original_bytes=audio.stat().st_size)
        seg={'clip_id':clip,'segment_index':0,'text':e['text'],'start_seconds':e['start_seconds'],
             'end_seconds':e['end_seconds'],'valid_srt_timing':True,'quarantine_reasons':['word_disagreement']}
        rec={'recording_id':rid,'aliases':[{'source_id':a['resource_id'],'original_sha256':a['original_sha256']} for a in pin['archive']['aliases']],
             'pcm_sha256':sha(pcm),'pcm_seconds':60.0,'source_warnings':['decoder_warning'],
             'raw_results':[{'clip_id':clip,'audio_sha256':'1'*64,'source_offset_seconds':0.0,
                 'responses':responses,'quarantine_reasons':['word_disagreement']}],
             'segments':{m:[copy.deepcopy(seg)] for m in reads},
             'exports':{m:{'full_text_sha256':reads[m]['sha256']} for m in reads}}
        original.append(rec)
        manifest.append({'pin':pin,'recording_id':rid,'asr_batch':'synthetic-asr','clip_ids':[clip],
            'raw_root':str(root/'raw-original'),'reading_files':reads,
            'files':{'pcm':file(pcm),'wire_transcript':reads['turbo'],'wire_subtitles':file(subs),
                     **{'original:'+a['resource_id']:file(audio) for a in pin['archive']['aliases']}}})
    prov=root/'original-provenance.json';save(prov,{'collection_id':'synthetic-archive','recordings':original})
    q=root/'original-quarantine.json';save(q,{'diagnostic':'synthetic'})
    for m in manifest:
        m['files'].update(original_provenance=file(prov),original_quarantine=file(q))
        m['pin']['archive'].update(provenance_sha256=sha(prov),quarantine_sha256=sha(q))
    if corrected:
        rec=copy.deepcopy(original[0]);rec['original_provenance_sha256']=sha(prov)
        models={'turbo_auto':'actual-whisper-turbo','large_auto':'actual-whisper-large-v3'}
        rec['model_ids']=models;rec['segments']={};rec['exports']={};rec['raw_results'][0]['responses']={}
        reads={}
        for name,actual in models.items():
            full=root/('corrected.'+name+'.full.txt');full.write_text(value['evidence'][0]['text'])
            reads[name]=file(full);rec['exports'][name]={'full_text_sha256':sha(full),'model_id':actual}
            rec['segments'][name]=copy.deepcopy(original[0]['segments']['turbo'])
            raw=root/'raw-corrected'/(name+'.json')
            body=json.loads((root/'raw-original/recording-00/turbo.json').read_text());body['model_id']=actual
            save(raw,body);rec['raw_results'][0]['responses'][name]={'path':raw.name,'sha256':sha(raw)}
        cprov=root/'corrected-provenance.json';save(cprov,{'recordings':[rec]})
        cq=root/'corrected-quarantine.json';save(cq,{'diagnostic':'corrected-synthetic'})
        source=manifest[0];source['original_raw_root']=source['raw_root'];source['raw_root']=str(root/'raw-corrected');source['reading_files']=reads
        source['files'].update(corrected_provenance=file(cprov),corrected_quarantine=file(cq))
        source['pin']['archive']['corrected_asr']={'full_text_sha256':{m:f['sha256'] for m,f in reads.items()},
            'model_ids':models,'provenance_sha256':sha(cprov),'quarantine_sha256':sha(cq)}
        value['evidence'][0]['admission']['source_basis']='corrected_pair'
    save(root/'evidence-provenance.json',[{'id':e['id'],'resource_id':e['resource_id'],
        'model':'turbo_auto' if corrected and i==0 else 'turbo','clip_id':'synthetic-clip','segment_indexes':[0]}
        for i,e in enumerate(value['evidence'])])
    return value,manifest

def finalize(root,value,manifest,prior_empty=False,include_layout=True,include_related=True):
    doc=ArchiveDocument(**value).model_dump();save(root/'article-document.json',doc)
    for m,pin in zip(manifest,doc['sources']):m['pin']=pin
    save(root/'source-manifest.json',manifest)
    assignment={'assignment_id':'synthetic-assignment','editor':'editor','reviewer':'reviewer',
                'tasks':[{'scope':batch_scope(doc,'article')}]};save(root/'assignment.json',assignment)
    for role in ('editor','reviewer'):
        records=[];reader=role+'-actual-reader'
        for m in manifest:
            prior=root/(role+'-'+m['recording_id']+'-prior.json')
            old={role:reader,'complete_paired_ASR_text_read':True,'audio_listened':False,
                 'recording_id':m['recording_id'],'asr_batch':m['asr_batch'],
                 'read_clip_ids':[] if prior_empty else m['clip_ids'],
                 'file_hashes':{f['path']:f['sha256'] for f in m['reading_files'].values()}}
            save(prior,old)
            records.append({'resource_id':m['pin']['resource_id'],'read_clip_ids':m['clip_ids'],
                'files':m['reading_files'],'prior_proofs':[dict(file(prior),reader=reader)]})
        proof={'assignment_id':assignment['assignment_id'],'article_document_sha256':sha(root/'article-document.json'),
               'sources_manifest_sha256':sha(root/'source-manifest.json'),'complete_paired_asr_text_read':True,
               'audio_listened':False,role:assignment[role],'readers':[reader],'records':records}
        save(root/('source-reading-proof.json' if role=='editor' else 'review/source-review-proof.json'),proof)
    review={'assignment_id':assignment['assignment_id'],'result_sha256':sha(root/'article-document.json'),
            'reviewer':'reviewer','decision':'pass','scope':assignment['tasks'][0]['scope'],
            'source_review_proof_sha256':sha(root/'review/source-review-proof.json'),
            'claims':[{'claim_id':c['id'],'evidence_ids':c['evidence_ids'],'decision':'pass'}
                      for a in doc['articles']+doc['concepts'] for c in a['claims']],
            **{key:[{'id':o['id'],'decision':'pass'} for o in doc[target]]
               for key,target in [('concepts','concepts'),('links','links'),('admissions','evidence')]},
            'evidence':[file(root/'article-document.json')]}
    if include_layout:
        links={link['id']:link for link in doc['links']}
        reason='Independently checked synthetic placement and its explicit linked destination.'
        review['inline_mentions']=[{'resource_id':a['resource_id'],'claim_id':claim['id'],
            'text':claim['text'][mention['start']:mention['end']],
            'concept_id':links[mention['link_id']]['concept_id'],'decision':'pass','reason':reason}
            for a in doc['articles'] for claim in a['claims'] for mention in claim.get('mentions',[])]
        review['related_materials']=[{'resource_id':a['resource_id'],
            'target_material_id':related['material_id'],'via_concept_id':related['via_concept_id'],
            'supporting_link_ids':related['supporting_link_ids'],'decision':'pass','reason':reason}
            for a in doc['articles'] for related in a['related']]
    else:
        review['inline_mentions']=[]
        review['related_materials']=[]
    if not include_related:
        review['related_materials']=[]
    save(root/'review/review.json',review)
    return validate(root,root/'review/review.json')

def run(name,mutate,corrected=False,expected=None):
    with tempfile.TemporaryDirectory(prefix='independent-archive-gate-') as directory:
        root=Path(directory);value,manifest=packet(root,corrected)
        mutate(root,value,manifest)
        try:
            result=finalize(root,value,manifest,prior_empty=name=='prior_clip_coverage_empty',
                include_layout=name!='missing_inline_and_related_reviews',
                include_related=name!='missing_related_reviews')
        except (ValueError,KeyError,OSError,StopIteration) as error:
            if expected is None or expected not in str(error):
                raise AssertionError(f'{name}: wrong rejection: {error!r}') from error
            print(json.dumps({'case':name,'passed':True,'expected_rejection':str(error)}))
            return
        if expected is not None:
            raise AssertionError(f'{name}: bad packet unexpectedly accepted: {result}')
        review=json.loads((root/'review/review.json').read_text())
        assert review['inline_mentions'] and review['related_materials'], 'Positive fixture must exercise inline and related gates'
        print(json.dumps({'case':name,'passed':True,'validation':result,
            'inline_reviews':len(review['inline_mentions']),'related_reviews':len(review['related_materials'])}))

def no_inline(root,value,manifest):pass
def corrected_pins(root,value,manifest):
    c=value['sources'][0]['archive']['corrected_asr']
    c['full_text_sha256']={key:'0'*64 for key in c['full_text_sha256']}
    c['model_ids']={key:'mislabelled-Parakeet' for key in c['model_ids']}
    c['quarantine_sha256']='9'*64
def changed_pcm(root,value,manifest):
    p=Path(manifest[0]['files']['pcm']['path']);p.write_bytes(b'Changed physical PCM, old Source PCM pin unchanged.')
    manifest[0]['files']['pcm']=file(p)
def effective_warning(root,value,manifest):
    p=Path(manifest[0]['files']['corrected_provenance']['path']);prov=json.loads(p.read_text())
    prov['recordings'][0]['raw_results'][0]['quarantine_reasons'].append('corrected_unknown_token')
    save(p,prov);manifest[0]['files']['corrected_provenance']=file(p)
    value['sources'][0]['archive']['corrected_asr']['provenance_sha256']=sha(p)
def changed_original_raw(root,value,manifest):
    p=root/'raw-original/recording-00/turbo.json';raw=json.loads(p.read_text());raw['text']+=' Changed after review.';save(p,raw)
    value['evidence'][0]['admission']['source_basis']='original_pair'
    prov=json.loads((root/'evidence-provenance.json').read_text());prov[0]['model']='turbo';save(root/'evidence-provenance.json',prov)

def corrected_models(root,value,manifest):
    c=value['sources'][0]['archive']['corrected_asr']
    c['model_ids']={key:'mislabelled-Parakeet' for key in c['model_ids']}

def corrected_full_text(root,value,manifest):
    c=value['sources'][0]['archive']['corrected_asr']
    c['full_text_sha256']={key:'0'*64 for key in c['full_text_sha256']}

def stale_reading_file(root,value,manifest):
    # The second model is separately read but is not the wire_transcript file.
    p=Path(manifest[0]['reading_files']['parakeet']['path'])
    p.write_text('Changed full text after attributed reading.')

def corrected_raw_model_mismatch(root,value,manifest):
    source=manifest[0]
    path=Path(source['files']['corrected_provenance']['path'])
    provenance=json.loads(path.read_text())
    record=provenance['recordings'][0]
    response=record['raw_results'][0]['responses']['large_auto']
    raw_path=Path(source['raw_root'])/response['path']
    raw=json.loads(raw_path.read_text());raw['model_id']='actual-other-model'
    save(raw_path,raw);response['sha256']=sha(raw_path)
    save(path,provenance);source['files']['corrected_provenance']=file(path)
    source['pin']['archive']['corrected_asr']['provenance_sha256']=sha(path)

def missing_corrected_pair_response(root,value,manifest):
    source=manifest[0];path=Path(source['files']['corrected_provenance']['path'])
    provenance=json.loads(path.read_text())
    del provenance['recordings'][0]['raw_results'][0]['responses']['large_auto']
    save(path,provenance);source['files']['corrected_provenance']=file(path)
    source['pin']['archive']['corrected_asr']['provenance_sha256']=sha(path)

def missing_original_pair_response(root,value,manifest):
    path=Path(manifest[0]['files']['original_provenance']['path'])
    provenance=json.loads(path.read_text())
    del provenance['recordings'][0]['raw_results'][0]['responses']['parakeet']
    save(path,provenance)
    for source in manifest:
        source['files']['original_provenance']=file(path)
        source['pin']['archive']['provenance_sha256']=sha(path)


import pytest

CASES=[
    ('positive_original_pair',no_inline,False,None),
    ('positive_corrected_pair',no_inline,True,None),
    ('missing_inline_and_related_reviews',no_inline,False,'Incomplete inline placement review'),
    ('missing_related_reviews',no_inline,False,'Incomplete related path review'),
    ('corrected_model_hash_quarantine_unbound',corrected_pins,True,'Corrected quarantine differs'),
    ('corrected_model_identity_unbound',corrected_models,True,'Corrected paired text/model pins differ'),
    ('corrected_full_text_unbound',corrected_full_text,True,'Corrected paired text/model pins differ'),
    ('physical_pcm_changed_source_pin_old',changed_pcm,False,'Physical PCM differs from source pin'),
    ('prior_clip_coverage_empty',no_inline,False,'Prior reader did not cover every source clip'),
    ('effective_raw_diagnostics_dropped',effective_warning,True,'Window admission dropped immutable/corrected diagnostics'),
    ('original_raw_changed_in_corrected_source',changed_original_raw,True,'Effective raw ASR changed'),
    ('reading_file_changed_after_prior_read',stale_reading_file,False,'Pinned archive file changed'),
    ('corrected_raw_model_identity_mismatch',corrected_raw_model_mismatch,True,'Corrected raw model identity differs'),
    ('corrected_pair_missing_raw_response',missing_corrected_pair_response,True,'Paired raw ASR model coverage differs'),
    ('original_pair_missing_raw_response',missing_original_pair_response,False,'Paired raw ASR model coverage differs')]

@pytest.mark.parametrize("name,mutation,corrected,expected",CASES,ids=[c[0] for c in CASES])
def test_independent_archive_gates(name,mutation,corrected,expected):
    run(name,mutation,corrected,expected)
