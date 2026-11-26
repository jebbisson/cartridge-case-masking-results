"""Verify the full cohort and frozen Run #3 inputs without deserializing models."""
import argparse
from collections import Counter
from contextlib import closing
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
import sqlite3
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment.bootstrap import install_seed
DB = 'review.sqlite'
MODEL = 'review.sqlite.runs/1/checkpoint.json'
SEED_PINS = {DB:'1415fcaeb3d10fb7565638af32b9bb723857c39e103350cfbd22f4774f62d7a7', MODEL:'a4056cde70e06dc75314ca295f9dafa58e479c5b4b220176e708559a5e225a21'}
PART_PINS = {
 'review.sqlite.part-000':'8ff1483dcb85f54aad64e97d5b713b8ad4b5cfecc18af7739986c513d9425d08',
 'review.sqlite.part-001':'c61c8f296696c4db1d7058621d7ce8adb9976c27eb5c7b17e1d829a6a4611bc1',
 'review.sqlite.part-002':'eb2a529f0b4446d5770b65def00b0b4e43f63154cf4d4996901f86cf81b6d2d4'}
DATASET_CATALOG_PIN = 'ac078fde4158eaf17244ec957a90b150b73d6ec8d6cb8c4e683cd7b2c9e48ad5'
DATASET_MANIFEST_PIN = 'e5aed766f41a5d2b694e1b7120b66633f76ad4c93287e557913fc6fe35055294'
TRAIN_MANIFEST_PIN = 'c563e60a47479831139ea0c0ef4b9bb88e2019e1ff6be481bd741d13e456ff07'
SNAPSHOT_PIN = '8f02993551552c065e228d44a17e8d3eca10d787a4d3c2c486dac2706e24133c'
# Explicit excluded exercise fingerprints, never an identifier/source crosswalk.
EXCLUDED_IMAGE_SHA = '1ecce8f0b73b6af658acbee8abb77bd91a040f1146fcf9ed962bd7094b9d9be9'
EXCLUDED_PIXEL_SHA = '670f14d647298982115dc5f020cd1380c7732560f2120346b6ccc355aaee0601'
FROZEN_TABLE_PINS = {
 'cases':'7dabf6bfe63d0937b1cbb4f9a5c68942bb9850df8ecb3b867a9263995f867b9c',
 'revisions':'8a2c968df4986b541eb5968ddbbbf9dc132d4980373fd5a5258ff753a258e4f1',
 'labels':'f321125ba8be07c498e4a782d3182ac5e62821512c789c3285f7a4d29fdf4643',
 'runs':'8a71c424eebd9cfd7e31ef561c6ae7ac17a9791642471aafed83269cf835534e'}


def check(ok, message):
    if not ok: raise ValueError(message)


def files_below(root):
    check(root.is_dir() and not root.is_symlink(), 'expected real directory')
    files=set()
    for path in root.rglob('*'):
        check(not path.is_symlink(), f'unexpected symlink: {path}')
        if not path.is_dir():
            check(path.is_file(), 'not a regular file')
            files.add(path.relative_to(root).as_posix())
    return files


def catalogue(pins):
    return ''.join(f'{digest}  {path}\n' for path,digest in pins.items()).encode('ascii')


def check_artifacts(root,pins):
    for name,expected in pins.items():
        with (root/name).open('rb') as stream:
            check(file_digest(stream,'sha256').hexdigest()==expected, f'digest mismatch: {name}')


def verify_database(path, rows):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        check(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)], 'SQLite integrity failure')
        check(not db.execute('PRAGMA foreign_key_check').fetchall(), 'foreign key failure')
        for table,pin in FROZEN_TABLE_PINS.items():
            values=db.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()
            if table=='cases': values=[r for r in values if r[0].startswith('run3-case-')]
            if table in ('revisions','labels'): values=[r for r in values if r[0]<=30]
            raw=json.dumps(values,separators=(',',':'),ensure_ascii=True).encode()
            check(sha256(raw).hexdigest()==pin, f'frozen payload changed: {table}')
        run=db.execute('SELECT fingerprint,snapshot,manifest_sha,checkpoint_sha FROM runs').fetchone()
        if run is None: raise ValueError('missing fitted run')
        check((run[0],sha256(run[1].encode()).hexdigest(),run[2],run[3])==(SNAPSHOT_PIN,SNAPSHOT_PIN,TRAIN_MANIFEST_PIN,SEED_PINS[MODEL]), 'fitted snapshot changed')
        check(db.execute('SELECT split,count(*),count(DISTINCT group_id) FROM cases GROUP BY split').fetchall()==[('test',12,6),('train',30,15),('validation',6,3)], 'unexpected cohort')
        check(db.execute("SELECT count(*) FROM cases WHERE split!='train' AND (included!=0 OR approved IS NOT NULL)").fetchone()==(0,), 'holdout approval/inclusion')
        check(db.execute('SELECT count(*) FROM revisions WHERE parent IS NOT NULL').fetchone()==(0,), 'private revision history')
        check(db.execute('SELECT count(*) FROM revisions').fetchone()==(48,), 'expected one revision per case')
        for table in ('imports','imported_proposals','import_run_cutoffs','retired_revision_ids'):
            check(db.execute(f'SELECT count(*) FROM {table}').fetchone()==(0,), f'private history: {table}')
        names={}; assets=set()
        for row in rows:
            names[row['id']]=row['source']['image']['original_filename']
            c=db.execute('SELECT name,split,group_id,image,pixels,latest FROM cases WHERE id=?',(row['id'],)).fetchone()
            if c is None: raise ValueError('missing cohort case')
            check(c[:5]==(names[row['id']],row['split'],row['group_id'],row['image_sha256'],row['decoded_pixel_sha256']), 'case inventory mismatch')
            assets.add(c[3])
            labels={r[0]:r[1:] for r in db.execute('SELECT target,status,mask,origin,rank FROM labels WHERE revision=?',(c[5],))}
            for target,label in row['labels'].items():
                if 'mask' in label: assets.add(label['mask_sha256'])
                if row['split']!='train':
                    check(labels[target]==(label['status'],label.get('mask_sha256'),label.get('origin',''),label.get('rank','')), 'source label changed')
            if row['split']!='train':
                kind,source=db.execute('SELECT kind,source FROM revisions WHERE id=?',(c[5],)).fetchone()
                check(kind=='source' and json.loads(source)=={'type':'local_cohort_source','attribution':row['source']}, 'source revision provenance mismatch')
        check(dict(db.execute('SELECT id,name FROM cases'))==names, 'extra scan or exercise case')
        check({r[0] for r in db.execute('SELECT digest FROM assets')}==assets, 'unused/private assets')
        check(EXCLUDED_IMAGE_SHA not in assets, 'excluded exercise blob')
        check(db.execute('SELECT count(*) FROM cases WHERE pixels=? OR image=?', (EXCLUDED_PIXEL_SHA,EXCLUDED_IMAGE_SHA)).fetchone()==(0,), 'excluded exercise pixels/image')
        metadata=json.dumps(rows)+''.join(r[0] for r in db.execute('SELECT source FROM revisions'))+run[1]
        check(not re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|/home/|scan-[0-9a-f]{64}|unmasked imprint',metadata,re.I), 'private IDs/paths/exercise metadata')


def verify(bundle,dataset):
    check(files_below(bundle)=={'SHA256SUMS','PARTS.sha256',MODEL,*PART_PINS}, 'unexpected bundle files')
    for filename,pins in [('SHA256SUMS',SEED_PINS),('PARTS.sha256',PART_PINS)]:
        check((bundle/filename).read_bytes()==catalogue(pins), 'bundle catalogue differs from pins')
    check((ROOT/'deployment/starter.full.sha256').read_bytes()==catalogue(SEED_PINS), 'deployment seed pin mismatch')
    check((ROOT/'deployment/starter.parts.sha256').read_bytes()==catalogue(PART_PINS), 'deployment part pin mismatch')
    check_artifacts(bundle,{MODEL:SEED_PINS[MODEL],**PART_PINS})
    files=files_below(dataset); catalog=(dataset/'SHA256SUMS').read_bytes()
    check(sha256(catalog).hexdigest()==DATASET_CATALOG_PIN, 'dataset catalogue differs from independent pin')
    pins={}
    for line in catalog.decode('ascii').splitlines():
        pin,name=line.split('  ',1)
        check(re.fullmatch(r'[0-9a-f]{64}',pin) and name in files and name not in pins, 'invalid catalogue entry')
        pins[name]=pin
    check(len(pins)==191 and pins.get('manifest.jsonl')==DATASET_MANIFEST_PIN and pins.get('train.jsonl')==TRAIN_MANIFEST_PIN, 'invalid dataset membership')
    check(files=={'SHA256SUMS','ATTRIBUTION.md',*pins}, 'unexpected dataset files')
    check_artifacts(dataset,pins)
    rows=[json.loads(l) for l in (dataset/'manifest.jsonl').read_text().splitlines()]
    train=[json.loads(l) for l in (dataset/'train.jsonl').read_text().splitlines()]
    check(Counter(r['split'] for r in rows)=={'train':30,'validation':6,'test':12}, 'split mismatch')
    for key in ('group_id','image_sha256','decoded_pixel_sha256'):
        owners={}
        for row in rows:
            check(owners.setdefault(row[key],row['split'])==row['split'], f'cross-split {key} overlap')
    check(len({(r['width'],r['height'],r['decoded_pixel_sha256']) for r in rows})==48, 'duplicate decoded scans')
    check([r for r in rows if r['split']=='train']==train, 'training labels/membership changed')
    check({r['id'] for r in rows}=={f'run3-case-{i:03}' for i in range(1,31)}|{f'cohort-case-{i:03}' for i in range(31,49)}, 'unexpected cohort IDs')
    referenced={'manifest.jsonl','train.jsonl'}
    for row in rows:
        name=row['source']['image']['original_filename']
        check(row['image_sha256']!=EXCLUDED_IMAGE_SHA and row['decoded_pixel_sha256']!=EXCLUDED_PIXEL_SHA, 'excluded exercise fingerprint')
        check(Path(name).name==name and row['image']==f'images/{name}', 'unsafe or changed filename')
        referenced.add(row['image'])
        for target,label in row['labels'].items():
            if 'mask' in label:
                check(label['mask']==f'masks/{Path(name).stem}/{target}.png', 'unsafe mask path')
                referenced.add(label['mask'])
    check(referenced==set(pins), 'unreferenced or missing assets')
    with TemporaryDirectory(prefix='verify-cohort-') as temp:
        work=Path(temp)
        install_seed(bundle,work,trusted_manifest=ROOT/'deployment/starter.full.sha256',trusted_parts=ROOT/'deployment/starter.parts.sha256')
        check_artifacts(work,SEED_PINS)
        verify_database(work/DB,rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=ROOT/'starter/full-bundle')
    parser.add_argument('--dataset',type=Path,default=ROOT/'training/dataset')
    args=parser.parse_args()
    try: verify(args.bundle,args.dataset)
    except (OSError,ValueError,sqlite3.Error) as error:
        parser.exit(1,f'Local candidate verification failed: {error}\n')
    print('Verified 48 cases (30 train / 6 validation / 12 test), 141 masks; 30 frozen approvals and exact model unchanged.')
    print('Verified parts and assembled SQLite; no private history or exercise. Asset terms: docs/data-licenses.md.')

if __name__=='__main__': main()
