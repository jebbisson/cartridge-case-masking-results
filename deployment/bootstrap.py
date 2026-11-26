"""Install a verified local starter bundle once, then exec the workbench."""
import fcntl
import hashlib
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

DATABASE = Path('review.sqlite')
CHECKPOINT = Path('review.sqlite.runs/1/checkpoint.json')
SEED_FILES = (CHECKPOINT, DATABASE)
CHUNK = 1024 * 1024


def read_checksums(path):
    """Parse only the two explicitly supported starter entries."""
    manifest = path.read_text(encoding='ascii')
    expected = {p.as_posix(): p for p in SEED_FILES}
    result = {}
    for line in manifest.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if match is None or match[2] not in expected or expected[match[2]] in result:
            raise ValueError('invalid starter SHA256SUMS entry')
        result[expected[match[2]]] = match[1]
    if result.keys() != set(SEED_FILES):
        raise ValueError('starter SHA256SUMS must list the database and checkpoint')
    return result


def copy_checked(source, destination, expected):
    """Verify the exact bytes staged on the volume, not a separate source read."""
    digest = hashlib.sha256()
    with source.open('rb') as reader, destination.open('xb') as writer:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    if digest.hexdigest() != expected:
        raise ValueError(f'starter checksum does not match: {source.name}')


def database_parts(bundle, trusted_parts=None):
    """Validate canonical, independently pinned transport parts (64 MiB max)."""
    raw = (bundle / 'PARTS.sha256').read_bytes()
    if trusted_parts is not None and raw != trusted_parts.read_bytes():
        raise ValueError('starter parts do not match trusted deployment pins')
    parts = []
    for index, line in enumerate(raw.decode('ascii').splitlines()):
        match = re.fullmatch(r'([0-9a-f]{64})  (review\.sqlite\.part-[0-9]{3})', line)
        if match is None or match[2] != f'review.sqlite.part-{index:03}' or index >= 100:
            raise ValueError('invalid starter part order or name')
        path = bundle / match[2]
        if path.is_symlink() or not 0 < path.stat().st_size <= 64 * 1024 * 1024:
            raise ValueError('invalid starter part size or symlink')
        parts.append((path, match[1]))
    if not parts:
        raise ValueError('empty starter parts catalogue')
    return parts


def copy_database(bundle, destination, expected, trusted_parts=None):
    if not (bundle / 'PARTS.sha256').exists():
        return copy_checked(bundle / DATABASE, destination, expected)
    parts = database_parts(bundle, trusted_parts)
    digest = hashlib.sha256()
    with destination.open('xb') as writer:
        for source, pin in parts:
            part = hashlib.sha256()
            with source.open('rb') as reader:
                while chunk := reader.read(CHUNK):
                    digest.update(chunk)
                    part.update(chunk)
                    writer.write(chunk)
            if part.hexdigest() != pin:
                raise ValueError(f'starter part checksum does not match: {source.name}')
        writer.flush()
        os.fsync(writer.fileno())
    if digest.hexdigest() != expected:
        raise ValueError('assembled starter database checksum does not match')


def install_seed(bundle, workspace, *, trusted_manifest=None, trusted_parts=None, empty_start=False):
    """Publish the checkpoint first, and the database as the completion marker."""
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / '.starter-init.lock').open('ab') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (workspace / DATABASE).exists() or empty_start:
            return False
        checksums = read_checksums(bundle / 'SHA256SUMS')
        if trusted_manifest is not None and read_checksums(trusted_manifest) != checksums:
            raise ValueError('starter checksums do not match trusted deployment pins')
        # Staging and hard-linking on the same volume prevents partial files and
        # refuses overwrites, even if a competing process touches the targets.
        with TemporaryDirectory(prefix='.starter-', dir=workspace) as temp:
            stage = Path(temp)
            for relative in SEED_FILES:
                if relative == DATABASE:
                    copy_database(bundle, stage / relative.name, checksums[relative], trusted_parts)
                else:
                    copy_checked(bundle / relative, stage / relative.name, checksums[relative])
            checkpoint = workspace / CHECKPOINT
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(stage / CHECKPOINT.name, checkpoint)
            except FileExistsError:
                with checkpoint.open('rb') as f:
                    existing = hashlib.file_digest(f, 'sha256').hexdigest()
                if existing != checksums[CHECKPOINT]:
                    raise ValueError('existing starter checkpoint differs; use a fresh volume') from None
            os.link(stage / DATABASE.name, workspace / DATABASE)
        return True


def main():
    if len(sys.argv) < 2:
        raise SystemExit('bootstrap needs the workbench command as its arguments')
    os.umask(0o027)
    try:
        installed = install_seed(
            Path(os.environ.get('REVIEWAPP_STARTER_DIR', 'starter/bundle')),
            Path(os.environ.get('REVIEWAPP_DATA_DIR', '.local')),
            trusted_manifest=Path(__file__).with_name('starter.sha256'),
            trusted_parts=Path(__file__).with_name('starter.parts.sha256'),
            empty_start=os.environ.get('REVIEWAPP_EMPTY_START') == '1',
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f'Cannot initialize starter workspace: {exc}') from None
    if installed:
        print('Installed starter cases and local model.', flush=True)
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == '__main__':
    main()
