"""Verify the workbench checkpoint against the exact offline experiment on real scans."""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import base64

import joblib
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
import model_fidelity as bench

CASES = ('18d0a850-fd47-4e21-9097-e1f5d68c7084', '2a93d964-2891-44e5-afe0-8f99825da70b',
         'de971355-1ace-4ef0-bc89-67edda8b208d')
VERSION = 'review-multiscale-cleanup-v1'
CANDIDATE_SHA = 'da80090264bc62e20d5f32725578737e715e180f9fff08d61c5b342d0f539d57'
GOLDEN = json.loads(Path(__file__).with_name('multiscale_golden.json').read_text())


def check(args):
    manifest = args.run / 'manifest.jsonl'
    raw = manifest.read_bytes()
    checkpoint = args.run / 'checkpoint.json'
    checkpoint_bytes = checkpoint.read_bytes()
    if not args.url and hashlib.sha256(checkpoint_bytes).hexdigest() != args.expected_model_sha256:
        raise ValueError('offline parity requires the trusted, independently pinned checkpoint digest')
    model = json.loads(checkpoint_bytes)
    assert model['version'] == VERSION
    assert model['manifest_sha256'] == hashlib.sha256(raw).hexdigest()
    rows = {r['id']: r for r in bench.legacy.manifest_rows(raw)}
    assert model['training_ids'] == sorted(rows)
    candidate = args.candidate.read_bytes()
    if hashlib.sha256(candidate).hexdigest() != CANDIDATE_SHA:
        raise ValueError('candidate does not match the trusted baseline artifact')
    fit = joblib.load(BytesIO(candidate))
    assert fit['manifest_sha256'] == model['manifest_sha256']
    for cid in CASES:
        row = rows[cid]
        image = args.run / row['image']
        im = bench.legacy.read_image(image)
        _, expected = bench.outputs(fit['regions'], fit['priors'], bench.feature_image(im))
        if args.url:
            url = args.url.rstrip('/') + '/api/cases/' + cid
            with urlopen(url, timeout=10) as response:
                detail = json.load(response)
            query = json.dumps({'base_revision': detail['latest']}).encode()
            request = Request(url+'/estimate', data=query, headers={'Content-Type':'application/json'})
            with urlopen(request, timeout=30) as response:
                output = json.load(response)
            assert output['run_id'] == int(args.run.name)
            assert output['base_revision'] == detail['latest']
            def read_png(key):
                return Image.open(BytesIO(base64.b64decode(output['targets'][key]['mask_png'], validate=True)))
            compare(im, expected, output['targets'], read_png, GOLDEN[cid])
            with urlopen(url, timeout=10) as response:
                assert json.load(response) == detail
        else:
            with tempfile.TemporaryDirectory(prefix='multiscale-parity-') as scratch:
                out = Path(scratch)
                subprocess.run([sys.executable, '-E', str(ROOT/'experiments/multiscale_worker.py'), 'predict',
                                '--model', str(checkpoint), '--image', str(image), '--out', str(out),
                                '--expected-model-sha256', args.expected_model_sha256], check=True)
                result = json.loads((out/'proposal.json').read_text())
                assert result['model_version'] == VERSION
                assert result['model_sha256'] == hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                assert result['image_sha256'] == hashlib.sha256(image.read_bytes()).hexdigest()
                compare(im, expected, result['targets'], lambda key: Image.open(out/result['targets'][key]['mask']), GOLDEN[cid])
        print(cid, 'all mask pixels match the experiment; arrow is not predicted', flush=True)


def compare(im, expected, actual, read_png, golden):
    assert set(actual) == set(bench.legacy.TARGETS) == set(golden)
    for key in bench.legacy.TARGETS:
        grid = expected.get(key)
        expected_status = 'present' if grid is not None and grid.any() else 'indeterminate'
        assert actual[key]['status'] == expected_status, (key, expected_status)
        if expected_status == 'present':
            assert grid is not None
            with read_png(key) as png:
                assert png.size == im.size and png.mode == 'L'
                same = Image.fromarray(grid).resize(im.size, Image.Resampling.NEAREST)
                assert np.array_equal(np.asarray(png), np.asarray(same, dtype=np.uint8)*255), key
                assert hashlib.sha256(png.tobytes()).hexdigest() == golden[key], key
        else:
            assert golden[key] is None, key
            assert all(actual[key].get(field) is None for field in ('mask', 'mask_png', 'start', 'end')), key


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--expected-model-sha256')
    check(parser.parse_args())
