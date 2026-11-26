"""Build a source download tied to a clean local Git revision.

No credentials or untracked runtime files are included. No network calls.
"""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args]).decode().strip()


def package():
    revision = git('rev-parse', 'HEAD')
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise SystemExit('Commit source changes before packaging a traceable build.')
    paths = git('ls-files', '-z').split('\0')
    files = {name: (ROOT / name).read_bytes() for name in paths if name}
    digest = hashlib.sha256()
    for name, data in sorted(files.items()):
        digest.update(name.encode() + b'\0' + hashlib.sha256(data).digest())
    info = {
        'name': 'Keyroom', 'version': (ROOT / 'VERSION').read_text().strip(),
        'git_commit': revision, 'source_tree_sha256': digest.hexdigest(),
        'upstream': json.loads((ROOT / 'upstream-reference.json').read_text()),
        'source_download': '/source',
        'note': 'Source checksum is an integrity aid, not an independent audit or digital signature.',
    }
    info_bytes = (json.dumps(info, indent=2) + '\n').encode()
    files['BUILD_INFO.json'] = info_bytes
    checksums = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(files.items()))
    files['CHECKSUMS.sha256'] = checksums.encode()
    static = ROOT / 'app' / 'static'
    static.mkdir(parents=True, exist_ok=True)
    (static / 'build-info.json').write_bytes(info_bytes)
    (ROOT / 'CHECKSUMS.sha256').write_text(checksums)
    with zipfile.ZipFile(static / 'keyroom-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            member = zipfile.ZipInfo('keyroom-source/' + name, date_time=(2026, 11, 26, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            archive.writestr(member, data)
    print(json.dumps({'version': info['version'], 'commit': revision, 'files': len(files), 'archive': str(static / 'keyroom-source.zip')}))


if __name__ == '__main__':
    package()
