"""Verify the exact local Run #3 candidate, without loading executable model data."""
import argparse
from contextlib import closing
from hashlib import file_digest, sha256
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = 'review.sqlite'
MODEL = 'review.sqlite.runs/1/checkpoint.json'
SEED_PINS = {
    DB: '1cbdafbac981d6dd8dea053aee103aaa6672ea40cb4e5fb142fd1c4cd17a4cf4',
    MODEL: 'a4056cde70e06dc75314ca295f9dafa58e479c5b4b220176e708559a5e225a21',
}
DATASET_CATALOG_PIN = '558c56ff8080357eb486c1ac830ae128636184f97f9d74902f942bdc07475b71'
DATASET_MANIFEST_PIN = 'c563e60a47479831139ea0c0ef4b9bb88e2019e1ff6be481bd741d13e456ff07'
SNAPSHOT_PIN = '8f02993551552c065e228d44a17e8d3eca10d787a4d3c2c486dac2706e24133c'


def check(ok, message):
    if not ok:
        raise ValueError(message)


def files_below(root):
    files = set()
    check(root.is_dir() and not root.is_symlink(), 'expected a real candidate directory')
    for path in root.rglob('*'):
        check(not path.is_symlink(), f'unexpected symlink: {path}')
        if not path.is_dir():
            check(path.is_file(), f'not a regular file: {path}')
            files.add(path.relative_to(root).as_posix())
    return files


def check_artifacts(root, pins):
    for name, expected in pins.items():
        with (root / name).open('rb') as stream:
            check(file_digest(stream, 'sha256').hexdigest() == expected, f'digest mismatch: {name}')


def verify(bundle, dataset):
    check(files_below(bundle) == {'SHA256SUMS', *SEED_PINS}, 'unexpected full-bundle files')
    checksum_text = ''.join(f'{digest}  {path}\n' for path, digest in SEED_PINS.items())
    check((bundle / 'SHA256SUMS').read_bytes() == checksum_text.encode('ascii'), 'seed catalogue differs from independent pins')
    check_artifacts(bundle, SEED_PINS)

    dataset_files = files_below(dataset)
    catalog = (dataset / 'SHA256SUMS').read_bytes()
    check(sha256(catalog).hexdigest() == DATASET_CATALOG_PIN, 'dataset catalogue differs from its independent pin')
    pins = {}
    for line in catalog.decode('ascii').splitlines():
        pin, name = line.split('  ', 1)
        check(re.fullmatch(r'[0-9a-f]{64}', pin) and name in dataset_files and name not in pins,
              'invalid dataset catalogue entry')
        pins[name] = pin
    check(len(pins) == 137 and pins['manifest.jsonl'] == DATASET_MANIFEST_PIN, 'invalid dataset membership')
    check(dataset_files == {'SHA256SUMS', 'ATTRIBUTION.md', *pins}, 'unexpected dataset files')
    check_artifacts(dataset, pins)

    uri = (bundle / DB).resolve().as_uri() + '?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        check(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'SQLite integrity failure')
        check(not db.execute('PRAGMA foreign_key_check').fetchall(), 'SQLite foreign key failure')
        runs = db.execute('SELECT id,status,fingerprint,snapshot,manifest_sha,checkpoint_sha FROM runs').fetchall()
        check(len(runs) == 1, 'expected one installed run')
        run, status, fingerprint, snapshot, manifest_sha, checkpoint_sha = runs[0]
        check((run, status, fingerprint, sha256(snapshot.encode()).hexdigest(), manifest_sha, checkpoint_sha)
              == (1, 'succeeded', SNAPSHOT_PIN, SNAPSHOT_PIN, DATASET_MANIFEST_PIN, SEED_PINS[MODEL]), 'seed run metadata mismatch')
        cases = db.execute("SELECT split,count(*),count(DISTINCT group_id) FROM cases GROUP BY split").fetchall()
        check(cases == [('train', 30, 15)], 'unexpected seed cohort')
        approvals = db.execute('''SELECT count(*) FROM cases JOIN revisions ON revisions.id=cases.approved
                                  WHERE latest=approved AND included=1 AND kind='approved'
                                  AND revisions.case_id=cases.id AND parent IS NULL''').fetchone()
        check(approvals == (30,) and db.execute('SELECT count(*) FROM revisions').fetchone() == (30,),
              'expected one approved revision per case')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT / 'starter/full-bundle')
    parser.add_argument('--dataset', type=Path, default=ROOT / 'training/dataset')
    args = parser.parse_args()
    try:
        verify(args.bundle, args.dataset)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Local candidate verification failed: {error}\n')
    print('Verified full local Run #3 candidate: 30 TRAIN cases, 15 groups, 106 masks, one installed checkpoint.')
    print('Not cleared for distribution.')


if __name__ == '__main__':
    main()
