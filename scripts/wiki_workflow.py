"""Coordinator-owned reservations and acceptance; never a second source catalogue.

One private database on the coordinator host. Participant copies are read-only
packets, not authorities. CLI identities are audit labels, not authentication;
filesystem access to this database is restricted to the coordinator.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

from daychi_contracts.content import Batch
from daychi_contracts.semantics import SemanticBatch
from daychi_contracts.articles import ArticleBatch
from daychi_contracts.archive_articles import ArchiveBatch

MAX_SNAPSHOT_AGE = 86400
ACTIVE = ('claimed', 'submitted', 'needs_changes', 'review_pass', 'accepted',
          'publishing', 'imported')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temp.chmod(0o600)
    temp.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def batch_payload(path, kind):
    if kind == 'article' and read(path).get('format') == 'daychi-wiki-archive-articles/1':
        return ArchiveBatch.model_validate_json(Path(path).read_text()).model_dump()
    model = {'semantic': SemanticBatch, 'article': ArticleBatch, 'summary': Batch}[kind]
    return model.model_validate_json(Path(path).read_text()).model_dump()


def batch_scope(batch, kind):
    if kind == 'article':
        resources = []
        for source in batch['sources']:
            archive = source.get('archive')
            resources.extend(a['resource_id'] for a in archive['aliases']) if archive else resources.append(resource_scope(source['resource_id']))
        return sorted(resources + ['concept:' + c['id'] for c in batch['concepts']])
    if kind == 'semantic':
        return sorted(p['concept_id'] for p in batch['pages'])
    return sorted('yt:' + r['resource_id'] for r in batch['records'])


def resource_scope(resource_id):
    return resource_id if resource_id.startswith('drive:') else 'yt:' + resource_id


class Workflow:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(path, timeout=30, isolation_level=None)
        path.chmod(0o600)
        self.c.row_factory = sqlite3.Row
        self.c.executescript('''
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, target TEXT, kind TEXT,
            revision INTEGER, payload TEXT, state TEXT, assignment TEXT);
          CREATE TABLE IF NOT EXISTS assignments(id TEXT PRIMARY KEY, batch_id TEXT UNIQUE,
            editor TEXT, reviewer TEXT, kind TEXT, scope TEXT, snapshot TEXT,
            state TEXT, result_hash TEXT, review_hash TEXT, acceptance TEXT,
            authorization TEXT, receipt TEXT);
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
            at REAL, actor TEXT, action TEXT, subject TEXT, evidence TEXT);
        ''')

    def close(self):
        self.c.close()

    @contextmanager
    def transaction(self):
        self.c.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.c.execute('COMMIT')
        except BaseException:
            self.c.execute('ROLLBACK')
            raise

    def setting(self, key):
        row = self.c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def set(self, key, value):
        self.c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, value))

    def event(self, actor, action, subject, evidence):
        require(bool(actor.strip()), 'Actor is required')
        self.c.execute('INSERT INTO events(at,actor,action,subject,evidence) VALUES (?,?,?,?,?)',
                       (time.time(), actor, action, subject, json.dumps(evidence)))

    def initialize(self, acceptor):
        with self.transaction():
            require(self.setting('acceptor') is None, 'Already initialized; delegation needs an explicit governance change')
            require(bool(acceptor.strip()), 'Acceptor is required')
            self.set('acceptor', acceptor)
            self.event(acceptor, 'initialize', 'workflow', {'protocol_version': 1})

    def fresh(self):
        raw = self.setting('snapshot')
        require(raw is not None, 'No synchronized snapshot')
        snap = json.loads(raw)
        age = time.time() - snap['checked_at']
        require(0 <= age <= MAX_SNAPSHOT_AGE, 'Snapshot expired; refresh production and registry before proceeding')
        require(file_hash(snap['registry_path']) == snap['registry_sha256'],
                'Registry changed; refresh without overwriting manual edits')
        return snap

    def sync(self, snapshot, actor):
        require(snapshot.get('protocol_version') == 1 and snapshot.get('live_complete') is True,
                'Complete live production snapshot required')
        require(0 <= time.time() - snapshot['checked_at'] <= MAX_SNAPSHOT_AGE, 'Stale snapshot')
        require(file_hash(snapshot['registry_path']) == snapshot['registry_sha256'], 'Registry digest differs')
        items = snapshot['tasks']
        require(len({t['id'] for t in items}) == len(items), 'Duplicate task IDs')
        for item in items:
            require(item['kind'] in ('summary', 'prepare', 'review', 'semantic', 'article'), 'Unknown work kind')
            require(item['state'] in ('available', 'blocked', 'published_existing'), 'Invalid intake state')
            require(item['id'] == f"{item['kind']}:{item['target']}:r{item['revision']}", 'Task identity differs')
        with self.transaction():
            require(self.setting('acceptor') is not None, 'Initialize final acceptor first')
            present = {t['id'] for t in items}
            for old in self.c.execute('SELECT * FROM tasks').fetchall():
                if old['id'] not in present and old['state'] != 'verified':
                    self.c.execute("UPDATE tasks SET state='blocked' WHERE id=?", (old['id'],))
            for item in items:
                payload = json.dumps(item, sort_keys=True)
                old = self.c.execute('SELECT * FROM tasks WHERE id=?', (item['id'],)).fetchone()
                if old is None:
                    self.c.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,NULL)',
                                   (item['id'], item['target'], item['kind'], item['revision'], payload, item['state']))
                elif old['assignment'] and (old['payload'] != payload or old['state'] == 'blocked'):
                    # Never silently release an assignment or overwrite an accepted result.
                    self.c.execute("UPDATE tasks SET state='blocked',payload=? WHERE id=?", (payload, item['id']))
                elif old['state'] not in (*ACTIVE, 'verified'):
                    self.c.execute('UPDATE tasks SET payload=?,state=? WHERE id=?', (payload, item['state'], item['id']))
            self.set('snapshot', json.dumps({k: v for k, v in snapshot.items() if k != 'tasks'}))
            self.event(actor, 'sync', 'workflow', {'snapshot_sha256': digest(snapshot), 'tasks': len(items)})

    def claim(self, ids, editor, reviewer, batch_id, actor):
        require(ids and len(set(ids)) == len(ids), 'Unique nonempty task IDs required')
        require(editor.strip() and reviewer.strip() and editor != reviewer, 'Independent editor and reviewer required')
        with self.transaction():
            snapshot = self.fresh()
            tasks = [self.c.execute('SELECT * FROM tasks WHERE id=?', (i,)).fetchone() for i in ids]
            require(all(t is not None and t['state'] == 'available' and not t['assignment'] for t in tasks),
                    'Task unavailable, already reserved, published or blocked')
            require(len({t['kind'] for t in tasks}) == 1, 'One work kind per assignment')
            require(len({t['target'] for t in tasks}) == len(tasks), 'Duplicate target in assignment')
            for task in tasks:
                conflict = self.c.execute("SELECT id FROM tasks WHERE target=? AND kind=? AND assignment IS NOT NULL AND state NOT IN ('verified','released')",
                                          (task['target'], task['kind'])).fetchall()
                require(not conflict, 'Target already reserved at another revision; reconcile explicitly')
            scope = sorted(s for t in tasks for s in json.loads(t['payload'])['scope'])
            require(len(scope) == len(set(scope)), 'Overlapping source/page scope')
            if tasks[0]['kind'] != 'semantic':
                for prior in self.c.execute("SELECT scope FROM assignments WHERE kind=? AND state NOT IN ('verified','released')", (tasks[0]['kind'],)):
                    require(not set(scope).intersection(json.loads(prior['scope'])), 'Source already reserved under another target')
            assignment = uuid.uuid4().hex
            self.c.execute('INSERT INTO assignments VALUES (?,?,?,?,?,?,?, ?,NULL,NULL,NULL,NULL,NULL)',
                           (assignment, batch_id, editor, reviewer, tasks[0]['kind'], json.dumps(scope),
                            json.dumps(snapshot), 'claimed'))
            self.c.executemany("UPDATE tasks SET state='claimed',assignment=? WHERE id=?", [(assignment, i) for i in ids])
            packet = {'protocol_version': 1, 'assignment_id': assignment, 'batch_id': batch_id,
                      'editor': editor, 'reviewer': reviewer, 'snapshot': snapshot,
                      'tasks': [json.loads(t['payload']) for t in tasks]}
            self.event(actor, 'claim', assignment, {'task_ids': ids, 'packet_sha256': digest(packet)})
            return packet

    def assignment(self, identifier):
        row = self.c.execute('SELECT * FROM assignments WHERE id=?', (identifier,)).fetchone()
        require(row is not None, 'Unknown assignment')
        return row

    def move(self, identifier, state):
        self.c.execute('UPDATE assignments SET state=? WHERE id=?', (state, identifier))
        self.c.execute('UPDATE tasks SET state=? WHERE assignment=?', (state, identifier))

    def tasks_intact(self, identifier):
        rows = self.c.execute('SELECT * FROM tasks WHERE assignment=?', (identifier,)).fetchall()
        require(rows and all(r['state'] != 'blocked' for r in rows), 'Assignment needs reconciliation after source/status change')
        return rows

    def submit(self, identifier, path, actor):
        with self.transaction():
            self.fresh()
            assignment = self.assignment(identifier)
            require(actor == assignment['editor'], 'Only assigned editor submits')
            require(assignment['state'] in ('claimed', 'needs_changes'), 'Submission out of sequence')
            self.tasks_intact(identifier)
            if assignment['kind'] in ('summary', 'semantic', 'article'):
                batch = batch_payload(path, assignment['kind'])
                require(batch['batch_id'] == assignment['batch_id'], 'Batch ID differs')
                require(batch_scope(batch, assignment['kind']) == json.loads(assignment['scope']), 'Batch is outside assigned scope')
                for task in self.tasks_intact(identifier):
                    item = json.loads(task['payload'])
                    if assignment['kind'] == 'article':
                        objects = [(resource_scope(a['resource_id']), a) for a in batch['articles']] + [('concept:' + c['id'], c) for c in batch['concepts']]
                        revisions = item.get('object_revisions', {})
                        require(revisions and set(revisions) == {identity for identity, value in objects}, 'Article assignment requires explicit object revisions')
                        require(all(value['revision'] == revisions[identity] for identity, value in objects), 'Revision differs from assignment')
                    else:
                        records = batch['pages'] if assignment['kind'] == 'semantic' else batch['records']
                        matched = [r for r in records if (r['concept_id'] if assignment['kind'] == 'semantic' else 'yt:' + r['resource_id']) in item['scope']]
                        require(matched and all(r['revision'] == item['revision'] for r in matched), 'Revision differs from assignment')
                value = digest(batch)
            else:
                value = file_hash(path)
            self.c.execute('UPDATE assignments SET result_hash=?,review_hash=NULL,acceptance=NULL,authorization=NULL WHERE id=?',
                           (value, identifier))
            self.move(identifier, 'submitted')
            self.event(actor, 'submit', identifier, {'result_sha256': value})
            return value

    def review(self, identifier, report, actor):
        with self.transaction():
            self.fresh()
            a = self.assignment(identifier)
            self.tasks_intact(identifier)
            require(a['state'] == 'submitted' and actor == a['reviewer'] and actor != a['editor'], 'Independent assigned reviewer required')
            require(report['assignment_id'] == identifier and report['result_sha256'] == a['result_hash'], 'Review refers to another result')
            require(report['decision'] in ('pass', 'needs_changes', 'blocked'), 'Invalid review decision')
            require(bool(report.get('evidence')), 'Review evidence paths/hashes required')
            if report['decision'] == 'pass':
                require(report.get('full_source_read') is True, 'Full source reading must be confirmed')
                require(set(report.get('scope', [])) == set(json.loads(a['scope'])), 'Incomplete review coverage')
            state = 'review_pass' if report['decision'] == 'pass' else report['decision']
            self.c.execute('UPDATE assignments SET review_hash=? WHERE id=?', (digest(report), identifier))
            self.move(identifier, state)
            self.event(actor, 'review', identifier, report)

    def accept(self, identifier, actor, reference):
        with self.transaction():
            self.fresh()
            a = self.assignment(identifier)
            self.tasks_intact(identifier)
            require(actor == self.setting('acceptor'), 'Only the designated final acceptor may accept')
            require(a['state'] == 'review_pass' and reference.strip(), 'Review pass and explicit acceptance reference required')
            evidence = {'acceptor': actor, 'reference': reference, 'result_sha256': a['result_hash'], 'review_sha256': a['review_hash']}
            self.c.execute('UPDATE assignments SET acceptance=? WHERE id=?', (json.dumps(evidence), identifier))
            self.move(identifier, 'accepted')
            self.event(actor, 'accept', identifier, evidence)

    def authorize_publication(self, identifier, actor, reference):
        with self.transaction():
            self.fresh()
            a = self.assignment(identifier)
            self.tasks_intact(identifier)
            require(actor == self.setting('acceptor') and a['state'] == 'accepted', 'Final acceptor must authorize the accepted batch')
            require(a['kind'] in ('summary', 'semantic', 'article') and reference.strip(), 'Publishable batch and explicit authorization reference required')
            self.c.execute('UPDATE assignments SET authorization=? WHERE id=?', (reference, identifier))
            self.event(actor, 'authorize_publication', identifier, {'reference': reference, 'result_sha256': a['result_hash']})

    def check_import(self, identifier, batch, kind, origin):
        snapshot = self.fresh()
        a = self.assignment(identifier)
        self.tasks_intact(identifier)
        require(snapshot['origin'] == origin, 'Import origin differs from synchronized production')
        require(a['state'] == 'accepted' and a['kind'] == kind and a['authorization'], 'Accepted batch with explicit publication authorization required')
        require(digest(batch) == a['result_hash'] and batch['batch_id'] == a['batch_id'], 'Accepted batch was changed')
        return a

    def begin_import(self, identifier, batch, kind, origin):
        with self.transaction():
            a = self.check_import(identifier, batch, kind, origin)
            self.move(identifier, 'publishing')
            self.event(self.setting('acceptor'), 'begin_import', identifier, {'result_sha256': a['result_hash']})

    def imported(self, identifier, receipt):
        with self.transaction():
            a = self.assignment(identifier)
            require(a['state'] == 'publishing', 'Import out of sequence')
            self.c.execute('UPDATE assignments SET receipt=? WHERE id=?', (json.dumps(receipt), identifier))
            self.move(identifier, 'imported')
            self.event('coordinator', 'imported', identifier, {'receipt_sha256': digest(receipt)})

    def reconcile_import(self, identifier, report, actor):
        with self.transaction():
            self.fresh()
            a = self.assignment(identifier)
            require(actor == self.setting('acceptor') and a['state'] == 'publishing', 'Final acceptor reconciles interrupted imports')
            require(report.get('result_sha256') == a['result_hash'] and report.get('evidence'), 'Exact result and live server evidence required')
            require(report.get('server_write') in ('present_exact', 'absent'), 'Unknown or conflicting server state stays blocked')
            if report['server_write'] == 'present_exact':
                require(report.get('receipt'), 'Server receipt/status evidence required')
                self.c.execute('UPDATE assignments SET receipt=? WHERE id=?', (json.dumps(report['receipt']), identifier))
                self.move(identifier, 'imported')
            else:
                self.c.execute('UPDATE assignments SET authorization=NULL WHERE id=?', (identifier,))
                self.move(identifier, 'accepted')
            self.event(actor, 'reconcile_import', identifier, report)

    def complete(self, identifier, report, actor):
        with self.transaction():
            self.fresh()
            a = self.assignment(identifier)
            require(actor == self.setting('acceptor') and a['state'] == 'accepted' and a['kind'] in ('review', 'prepare'),
                    'Final acceptor completes non-publication work')
            require(report.get('result_sha256') == a['result_hash'] and report.get('registry_updated') is True and report.get('evidence'),
                    'Accepted result and registry update evidence required')
            self.move(identifier, 'verified')
            self.event(actor, 'complete', identifier, report)

    def verify(self, identifier, report, actor):
        with self.transaction():
            self.fresh()
            a = self.assignment(identifier)
            require(a['state'] == 'imported' and report['result_sha256'] == a['result_hash'], 'Imported result digest required')
            require(report.get('assignment_id') == identifier and report.get('batch_id') == a['batch_id'], 'Verification scope differs')
            require(all(report.get(k) is True for k in ('all_payloads_exact', 'source_fields_unchanged', 'idempotent_replay',
                                                        'anonymous_access_checked', 'authorized_ui_checked', 'registry_updated')),
                    'Production QA incomplete; imported does not mean verified')
            require(bool(report.get('evidence')), 'Production verification evidence required')
            self.move(identifier, 'verified')
            self.event(actor, 'verify', identifier, report)

    def release(self, identifier, actor, reason):
        with self.transaction():
            a = self.assignment(identifier)
            require(actor == self.setting('acceptor') and reason.strip(), 'Final acceptor and release reason required')
            require(a['state'] not in ('publishing', 'imported', 'verified'), 'Possible server write: reconcile production before releasing')
            self.move(identifier, 'released')
            self.c.execute("UPDATE tasks SET state='blocked',assignment=NULL WHERE assignment=?", (identifier,))
            self.event(actor, 'release', identifier, {'reason': reason})

    def status(self):
        try:
            self.fresh()
            freshness = 'fresh'
        except ValueError as error:
            freshness = str(error)
        snap = json.loads(self.setting('snapshot') or '{}')
        return {'protocol_version': 1, 'acceptor': self.setting('acceptor'), 'freshness': freshness,
                'snapshot_checked_at': snap.get('checked_at'), 'source_snapshot_counts': snap.get('counts'),
                'states': dict(self.c.execute('SELECT state,count(*) FROM tasks GROUP BY state').fetchall()),
                'assignment_states': dict(self.c.execute('SELECT state,count(*) FROM assignments GROUP BY state').fetchall())}

    def queue(self, state):
        self.fresh()
        return [{**json.loads(r['payload']), 'state': r['state'], 'assignment_id': r['assignment']}
                for r in self.c.execute('SELECT * FROM tasks WHERE state=? ORDER BY id', (state,))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init'); p.add_argument('--acceptor', required=True)
    p = sub.add_parser('sync'); p.add_argument('--snapshot', type=Path, required=True); p.add_argument('--actor', required=True)
    sub.add_parser('status')
    p = sub.add_parser('queue'); p.add_argument('--state', default='available')
    p = sub.add_parser('claim')
    for name in ('editor', 'reviewer', 'batch-id', 'actor'): p.add_argument('--' + name, required=True)
    p.add_argument('--task', action='append', required=True); p.add_argument('--output', type=Path, required=True)
    for command in ('submit', 'review', 'accept', 'authorize-publication', 'verify', 'release', 'complete', 'reconcile-import'):
        p = sub.add_parser(command); p.add_argument('--assignment', required=True); p.add_argument('--actor', required=True)
        if command in ('submit', 'review', 'verify', 'complete', 'reconcile-import'): p.add_argument('--file', type=Path, required=True)
        else: p.add_argument('--reference', required=True)
    args = parser.parse_args()
    workflow = Workflow(args.db)
    try:
        if args.command == 'init': workflow.initialize(args.acceptor)
        elif args.command == 'sync': workflow.sync(read(args.snapshot), args.actor)
        elif args.command == 'status': print(json.dumps(workflow.status(), ensure_ascii=False))
        elif args.command == 'queue':
            print(json.dumps(workflow.queue(args.state), ensure_ascii=False))
        elif args.command == 'claim': write_private(args.output, workflow.claim(args.task, args.editor, args.reviewer, args.batch_id, args.actor))
        elif args.command == 'submit': print(workflow.submit(args.assignment, args.file, args.actor))
        elif args.command == 'review': workflow.review(args.assignment, read(args.file), args.actor)
        elif args.command == 'accept': workflow.accept(args.assignment, args.actor, args.reference)
        elif args.command == 'authorize-publication': workflow.authorize_publication(args.assignment, args.actor, args.reference)
        elif args.command == 'verify': workflow.verify(args.assignment, read(args.file), args.actor)
        elif args.command == 'complete': workflow.complete(args.assignment, read(args.file), args.actor)
        elif args.command == 'reconcile-import': workflow.reconcile_import(args.assignment, read(args.file), args.actor)
        elif args.command == 'release': workflow.release(args.assignment, args.actor, args.reference)
    except (ValueError, KeyError, sqlite3.IntegrityError) as error:
        parser.exit(2, f'Blocked: {error}\n')
    finally:
        workflow.close()


if __name__ == '__main__':
    main()
