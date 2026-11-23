"""Fetch one immutable public repository snapshot; verify every byte before use."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
import urllib.request
import zipfile


def fetch(root):
    root = Path(root).resolve()
    version = json.loads((root / 'VERSION.json').read_text(encoding='utf-8'))
    manifest = json.loads((root / 'SOURCE.sha256.json').read_text(encoding='utf-8'))
    commit = version['repositoryCommit']
    if len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit):
        raise ValueError('invalid immutable source commit')
    destination = root / 'source'
    if destination.exists():
        raise FileExistsError('source exists; verify it or choose a fresh installer directory')
    with tempfile.TemporaryDirectory(prefix='.source-fetch-', dir=root) as directory:
        temporary = Path(directory).resolve()
        if temporary.parent != root:
            raise ValueError('temporary source directory escaped installer')
        archive = temporary / 'source.zip'
        url = 'https://codeload.github.com/jianzi123/maas/zip/' + commit
        with urllib.request.urlopen(url, timeout=60) as response, archive.open('wb') as output:
            received = 0
            while chunk := response.read(1 << 20):
                received += len(chunk)
                if received > 64 << 20:
                    raise ValueError('source archive exceeds bound')
                output.write(chunk)
        staged = temporary / 'verified'
        staged.mkdir()
        with zipfile.ZipFile(archive) as source:
            prefix = source.namelist()[0].split('/')[0] + '/'
            for name, expected in manifest.items():
                parts = PurePosixPath(name).parts
                if '\\' in name or name.startswith('/') or '..' in parts:
                    raise ValueError('unsafe source path')
                target = (staged / name).resolve()
                if not target.is_relative_to(staged):
                    raise ValueError('source escaped staging directory')
                info = source.getinfo(prefix + name)
                if info.file_size != expected['bytes']:
                    raise ValueError('source size mismatch: ' + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with source.open(info) as stream, target.open('wb') as output:
                    remaining = expected['bytes']
                    while chunk := stream.read(min(1 << 20, remaining + 1)):
                        remaining -= len(chunk)
                        if remaining < 0:
                            raise ValueError('source expanded beyond bound')
                        digest.update(chunk); output.write(chunk)
                if remaining or digest.hexdigest() != expected['sha256']:
                    raise ValueError('source hash mismatch: ' + name)
        lock = json.loads((staged / 'deploy/build-sources.lock.json').read_text())
        if lock['backend']['sourceCommit'] != version['codeCommit'] or lock['console']['sourceCommit'] != version['codeCommit']:
            raise ValueError('source code lock differs from installer')
        for name, expected in version['sourceLockSha256'].items():
            if hashlib.sha256((staged / name).read_bytes()).hexdigest() != expected:
                raise ValueError('source metadata differs from installer: ' + name)
        # Both paths are explicitly confined to this installer; never overwrite.
        if destination.parent != root or destination.exists():
            raise ValueError('source destination changed')
        staged.rename(destination)
    return {'repositoryCommit': commit, 'codeCommit': version['codeCommit'],
            'sourceFilesVerified': len(manifest), 'passed': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    print(json.dumps(fetch(parser.parse_args().root)))
