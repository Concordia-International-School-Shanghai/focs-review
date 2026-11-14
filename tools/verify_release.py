"""Public release verification only. No build source, student data or deployment API."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import stat
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(root, expected):
    root = Path(root).resolve()
    raw = (root / 'release-manifest.json').read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', expected) or sha(raw) != expected:
        raise ValueError('Release manifest does not match the independently supplied hash.')
    m = json.loads(raw)
    course, build = m['course'], m['build']
    if m['formatVersion'] != 1 or course not in ('apcsa', 'focs') or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}-[a-z0-9-]+\.\d+', build):
        raise ValueError('Unsupported release identity.')
    repo = 'Concordia-International-School-Shanghai/' + course + '-review'
    if m['repository'] != repo:
        raise ValueError('Wrong repository identity.')
    zpath = 'offline/' + build + '/' + course + '-review.zip'
    required = {'index.html', 'release.json', 'UPDATE.txt', zpath}
    # Retained immutable downloads may be explicitly listed for warm older pages.
    retained = set(m.get('retainedDownloads', []))
    if any(not re.fullmatch(r'offline/\d{4}\.\d{2}\.\d{2}-[a-z0-9-]+\.\d+/' + course + r'-review\.zip', p) for p in retained):
        raise ValueError('Invalid retained download path.')
    if set(m['siteFiles']) != required | retained:
        raise ValueError('Site allowlist is not the required release files.')
    control = {'.gitattributes', '.github/workflows/pages.yml', 'README.md', 'tools/verify_release.py'}
    if set(m['controlFiles']) != control:
        raise ValueError('Unexpected publishing-control files.')
    expected_files = {'release-manifest.json'} | control | {'site/' + p for p in m['siteFiles']}
    actual = set()
    for p in root.rglob('*'):
        rel = p.relative_to(root).as_posix()
        if rel == '.git' or rel.startswith('.git/'):
            continue
        if p.is_symlink():
            raise ValueError('Symbolic links are not allowed: ' + rel)
        if p.is_file():
            if p.stat().st_nlink != 1:
                raise ValueError('Hard links are not allowed: ' + rel)
            actual.add(rel)
    if actual != expected_files:
        raise ValueError('Repository file allowlist mismatch: ' + repr(sorted(actual ^ expected_files)))
    for prefix, files in [('site/', m['siteFiles']), ('', m['controlFiles'])]:
        for name, digest in files.items():
            if sha((root / (prefix + name)).read_bytes()) != digest:
                raise ValueError('File hash mismatch: ' + name)
    html = (root / 'site/index.html').read_bytes()
    if ("id: '" + build + "'").encode() not in html:
        raise ValueError('HTML build identity mismatch.')
    for name in [zpath] + sorted(retained):
        with zipfile.ZipFile(io.BytesIO((root / 'site' / name).read_bytes())) as z:
            if z.namelist() != [course + '-review.html']:
                raise ValueError('Offline ZIP must contain only its named app HTML.')
            info = z.infolist()[0]
            if stat.S_ISLNK(info.external_attr >> 16) or info.file_size > 20_000_000:
                raise ValueError('Invalid ZIP entry.')
            offline = z.read(info)
            if name == zpath and offline != html:
                raise ValueError('Hosted/offline HTML byte mismatch.')
    info = json.loads((root / 'site/release.json').read_bytes())
    expected_info = {'build': build, 'course': course, 'bankVersion': m['bankVersion'],
                     'htmlSha256': sha(html), 'offlineZip': zpath, 'offlineZipSha256': m['siteFiles'][zpath]}
    # Older immutable downloads/manifests predate update notices and stay valid.
    if 'releaseSequence' in m:
        sequence = m['releaseSequence']
        if type(sequence) is not int or sequence < 1 or ('releaseSequence: ' + str(sequence) + ' }').encode() not in html:
            raise ValueError('Release sequence/HTML mismatch.')
        expected_info.update(formatVersion=1, releaseSequence=sequence)
    if info != expected_info:
        raise ValueError('Public release information mismatch.')
    return m


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--expected-sha', required=True)
    p.add_argument('--stage', type=Path)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    m = verify(root, args.expected_sha)
    if args.stage:
        dest = args.stage.resolve()
        if dest == root or root in dest.parents:
            raise ValueError('Staging must be outside the publishing checkout.')
        dest.mkdir(parents=True, exist_ok=False)
        for name in m['siteFiles']:
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / 'site' / name, target)
    print('PASS:', m['repository'], m['build'], len(m['siteFiles']), 'explicit site files; offline HTML matches')


if __name__ == '__main__':
    main()
