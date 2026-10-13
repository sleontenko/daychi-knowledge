"""Validate or import a private reviewed structured article batch through the owner API."""
import argparse
import http.cookiejar
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

from daychi_contracts.articles import ArticleBatch
from daychi_contracts.archive_articles import ArchiveBatch
from scripts.wiki_workflow import Workflow, write_private


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch',type=Path,required=True)
    parser.add_argument('--origin',default='https://daychee-api-production.up.railway.app')
    parser.add_argument('--password-file',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--workflow-db',type=Path)
    parser.add_argument('--assignment')
    parser.add_argument('--receipt',type=Path)
    args=parser.parse_args();raw=args.batch.read_text()
    archive=json.loads(raw).get('format')=='daychi-wiki-archive-articles/1'
    batch=(ArchiveBatch if archive else ArticleBatch).model_validate_json(raw)
    endpoint='/api/admin/wiki/archive-articles' if archive else '/api/admin/wiki/articles'
    print(f'Validated {len(batch.articles)} articles / {len(batch.concepts)} concepts / {len(batch.links)} relations')
    if not args.apply:return
    origin=args.origin.rstrip('/');parts=urlsplit(origin)
    if parts.scheme!='https' or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username:
        parser.error('origin must be an HTTPS origin without credentials/path')
    if args.password_file is None:parser.error('--apply requires the existing owner password file')
    if not (args.workflow_db and args.assignment and args.receipt):
        parser.error('--apply requires --workflow-db, --assignment and --receipt; see docs/collaboration-workflow.md')
    workflow=Workflow(args.workflow_db)
    try:workflow.check_import(args.assignment,batch.model_dump(),'article',origin)
    finally:workflow.close()
    opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()));csrf=''
    def call(method,path,body=None):
        headers={'Origin':origin,'Content-Type':'application/json'}
        if csrf:headers['X-CSRF-Token']=csrf
        data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
        with opener.open(Request(origin+path,data=data,headers=headers,method=method),timeout=60) as response:
            return json.load(response)
    login=call('POST','/api/admin/login',{'password':args.password_file.read_text().strip()});csrf=login['csrf']
    try:
        workflow=Workflow(args.workflow_db)
        try:workflow.begin_import(args.assignment,batch.model_dump(),'article',origin)
        finally:workflow.close()
        imported=call('POST',endpoint,batch.model_dump())
        write_private(args.receipt,{'assignment_id':args.assignment,'batch_id':batch.batch_id,'origin':origin,
                                   'import':imported,'state':'server_write_confirmed_replay_pending'})
        replay=call('POST',endpoint,batch.model_dump())
        assert imported['articles']==len(batch.articles) and imported['concepts']==len(batch.concepts) and imported['links']==len(batch.links) and replay['already_imported']
        receipt={'assignment_id':args.assignment,'batch_id':batch.batch_id,'origin':origin,
                 'import':imported,'replay':replay,'stored':call('GET','/api/admin/wiki/articles')}
        write_private(args.receipt,receipt)
        workflow=Workflow(args.workflow_db)
        try:workflow.imported(args.assignment,receipt)
        finally:workflow.close()
        print(json.dumps({'receipt':str(args.receipt),'articles':imported['articles'],'concepts':imported['concepts'],'already_imported':replay['already_imported']}))
    finally:call('POST','/api/admin/logout')


if __name__=='__main__':main()
