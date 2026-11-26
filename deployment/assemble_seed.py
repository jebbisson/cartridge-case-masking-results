"""Assemble Git-safe seed parts into a pinned native SQLite starter."""
import argparse
from pathlib import Path
import shutil
from bootstrap import install_seed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--pins', required=True, type=Path)
    parser.add_argument('--parts-pins', required=True, type=Path)
    args = parser.parse_args()
    try:
        if not install_seed(args.bundle, args.output, trusted_manifest=args.pins,
                            trusted_parts=args.parts_pins):
            raise ValueError('assembly destination already contains a database')
        shutil.copyfile(args.pins, args.output / 'SHA256SUMS')
        (args.output / '.starter-init.lock').unlink()
    except (OSError, ValueError) as error:
        parser.exit(1, f'Cannot assemble starter: {error}\n')
    print('Assembled and verified database, checkpoint, and all transport parts.')

if __name__ == '__main__':
    main()
