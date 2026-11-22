"""Verify this local-review starter against the curation pins; never load the model."""
import argparse
import hashlib
from pathlib import Path
import sqlite3
from contextlib import closing

DATABASE = Path('review.sqlite')
CHECKPOINT = Path('review.sqlite.runs/1/checkpoint.json')
# These come from curation and Run #3 payload reconciliation, not SHA256SUMS
# supplied next to the candidate files. Do not regenerate pins for unknown data.
PINS = {
    DATABASE: '022953cd5fff55d9ab43ca648be05f083a09083ed260d5e46037967e565ea1a7',
    CHECKPOINT: 'a4056cde70e06dc75314ca295f9dafa58e479c5b4b220176e708559a5e225a21',
}


def verify(bundle):
    for path, pin in PINS.items():
        with (bundle / path).open('rb') as f:
            actual = hashlib.file_digest(f, 'sha256').hexdigest()
        if actual != pin:
            kind = 'checkpoint' if path == CHECKPOINT else 'database'
            raise ValueError(f'{path} does not match trusted {kind} pin')
    canonical = {f'{pin}  {path.as_posix()}' for path, pin in PINS.items()}
    lines = (bundle / 'SHA256SUMS').read_text(encoding='ascii').splitlines()
    if len(lines) != len(canonical) or set(lines) != canonical:
        raise ValueError('SHA256SUMS differs from trusted curation pins')

    # This is a static reviewed seed; ignore any external WAL or journal. The
    # deployer copies only the pinned database and checkpoint into a fresh volume.
    uri = (bundle / DATABASE).resolve().as_uri() + '?mode=ro&immutable=1'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        if (db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]
                or db.execute('PRAGMA foreign_key_check').fetchall()):
            raise ValueError('invalid SQLite structure')
        if db.execute('SELECT id,status,checkpoint_sha FROM runs').fetchall() != [(1, 'succeeded', PINS[CHECKPOINT])]:
            raise ValueError('database run metadata does not bind the pinned checkpoint')
        count, = db.execute("SELECT count(*) FROM cases WHERE split='train'").fetchone()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path, nargs='?', default=Path(__file__).resolve().with_name('bundle'))
    args = parser.parse_args()
    try:
        count = verify(args.bundle)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Starter verification failed: {error}\n')
    print(f'Verified local starter: {count} TRAIN surfaces and pinned checkpoint at runs/1. Not cleared to distribute.')


if __name__ == '__main__':
    main()
