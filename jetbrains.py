import argparse
import hashlib
import json
import os
import urllib.parse
import urllib.request

from collections.abc import Mapping, Sequence
from string import Template


JETBRAINS_BASE_URL = 'https://data.services.jetbrains.com/products/releases'

WHATSNEW_MAIN_TEMPLATE = Template("""<!DOCTYPE html><html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>$product - What's New</title>
<style>
article header { margin-bottom: 1em; }
article header h2 { margin-bottom: 0; }
article:not(:last-child) { padding: 1em 0; border-bottom: 1px solid #ddd; }
article section { margin-bottom: 1em; }

.subtitle { font-size: 0.9em; color: #666; margin-top: 0; }
</style>
<body>
<h1>What's New in $product</h1>
$content
</body>
</html>
""")

WHATSNEW_ENTRY_TEMPLATE = Template("""<article>
<header>
<h2 id="$version">$version ($build)</h2>
<span class="subtitle">$date</span>
</header>
<section>
$whatsnew
</section>
<footer>
<a href="$notesLink">Release Notes</a></div>
</footer>
</article>
""")

WHATSNEW_EMPTY_NOTES = 'No information provided.'

RaiseException = object()


def get_item(obj, *keys, default=RaiseException):
    """Return a value in a nested dict and/or list via keys and indexes.

    If `default` is RaiseException and an IndexError or KeyError exception occurs, the exception will be raised.
    Otherwise, the `default` value will be returned if an IndexError or KeyError occur.
    """
    if not isinstance(obj, (Mapping, Sequence)):
        raise TypeError('Invalid mapping or sequence instance: {}'.format(obj))

    NoMoreKeys = object()
    keys = list(keys)

    try:
        key = keys.pop(0)
    except IndexError:
        key = NoMoreKeys

    current = obj

    while key is not NoMoreKeys:
        try:
            current = current[key]
        except (KeyError, IndexError) as exc:
            if default is RaiseException:
                raise exc
            return default

        try:
            key = keys.pop(0)
        except IndexError:
            key = NoMoreKeys

    return current

def get_url_filename(url):
    parsed_url = urllib.parse.urlparse(url)
    return os.path.basename(parsed_url.path)


def download(url, destination):
    filename = get_url_filename(url)
    output_file = os.path.join(destination, filename)

    with open(output_file, 'wb') as fo, urllib.request.urlopen(url) as urlfo:
        while True:
            data = urlfo.read(1024)
            if data:
                fo.write(data)
            else:
                break
    return output_file

def read(url):
    with urllib.request.urlopen(url) as urlfo:
        return urlfo.read()

def validate(filename, checksum_value):
    h = hashlib.sha256()

    with open(filename, 'rb') as fi:
        while True:
            data = fi.read(1024)
            if data:
                h.update(data)
            else:
                break
    return checksum_value == h.hexdigest()


def generate_whatsnew(name, releases):
    entries = []

    for release in releases:
        whatsnew = release.get('whatsnew')

        if whatsnew is None or whatsnew.strip() == '':
            release['whatsnew'] = WHATSNEW_EMPTY_NOTES

        entry = WHATSNEW_ENTRY_TEMPLATE.substitute(**release)
        entries.append(entry)

    return WHATSNEW_MAIN_TEMPLATE.substitute(product=name, content=''.join(entries))


def main(command, code, name=None, version=None, build=None, latest=False, **kwargs):
    code = code.upper()
    
    params = dict(code=code.upper(),
                  type='release',
                  latest='true' if latest else 'false')
    
    encoded_params = urllib.parse.urlencode(params)
    url = f'{JETBRAINS_BASE_URL}?{encoded_params}'

    with urllib.request.urlopen(url) as urlfio:
        releases = json.loads(urlfio.read())

    if command in ('version', 'build'):
        result = releases[code][0].get(command, '')
        print(result)
    elif command in ('download', 'download_url', 'checksum', 'checksum_url'):
        match = False
        get_first_match = not (version or build)
        for release in releases[code]:
            if get_first_match or (version and release['version'] == version) or (build and release['build'] == build):
                match = True

            if match:
                if command in ('download', 'download_url'):
                    download_url = get_item(release, 'downloads', 'linux', 'link')
                    if command == 'download':
                        dest = kwargs.get('dest') or '.'
                        filename = download(download_url, dest)
                        if not kwargs.get('skip_validation', False):
                            checksum_url = get_item(release, 'downloads', 'linux', 'checksumLink')
                            data = read(checksum_url) 
                            checksum_value = data.decode().strip().split()[0]
                            if not validate(filename, checksum_value):
                                print('Checksum validation failed', file=sys.stderr)
                                return 2
                        print(filename)
                    elif command == 'download_url':
                        print(download_url)
                elif command in ('checksum', 'checksum_url'):
                    checksum_url = get_item(release, 'downloads', 'linux', 'checksumLink')
                    if command == 'checksum':
                        dest = kwargs.get('dest')
                        if dest:
                            filename = download(checksum_url, dest)
                            print(filename)
                        else:
                            data = read(checksum_url) 
                            print(data.decode().strip())
                    elif command == 'checksum_url':
                        print(checksum_url)
                break
        else:
            print('Could not find matching release', file=sys.stderr)
            return 1
    elif command == 'generate_whatsnew':
        product_name = kwargs.get('name')
        output = generate_whatsnew(product_name, releases[code])
        print(output)
    return 0


if __name__ == '__main__':
    import sys

    latest = False

    parser = argparse.ArgumentParser(description='JetBrains')
    subparsers = parser.add_subparsers(dest='command', help='Subcommand', required=True)

    version_parser = subparsers.add_parser('version', help='Print the latest version')
    version_parser.add_argument('-c', '--code', required=True, help='Product code')

    build_parser = subparsers.add_parser('build', help='Print the latest build')
    build_parser.add_argument('-c', '--code', required=True, help='Product code')

    download_parser = subparsers.add_parser('download', help='Download the version or build specified')
    download_parser.add_argument('-c', '--code', required=True, help='Product code')
    download_parser.add_argument('-d', '--dest')
    download_parser.add_argument('--skip-validation', action='store_true', default=False, help='Disable checksum validation')
    download_mutex = download_parser.add_mutually_exclusive_group(required=False)
    download_mutex.add_argument('-v', '--version', help='Version to download')
    download_mutex.add_argument('-b', '--build', help='Build to download')

    download_url_parser = subparsers.add_parser('download_url', help='Get download URL for the version or build specified')
    download_url_parser.add_argument('-c', '--code', required=True, help='Product code')
    download_url_mutex = download_url_parser.add_mutually_exclusive_group(required=False)
    download_url_mutex.add_argument('-v', '--version', help='Version to download')
    download_url_mutex.add_argument('-b', '--build', help='Build to download')

    checksum_parser = subparsers.add_parser('checksum', help='Get checksum for the version or build specified')
    checksum_parser.add_argument('-c', '--code', required=True, help='Product code')
    checksum_parser.add_argument('-d', '--dest')
    checksum_mutex = checksum_parser.add_mutually_exclusive_group(required=False)
    checksum_mutex.add_argument('-v', '--version', help='Version')
    checksum_mutex.add_argument('-b', '--build', help='Build')

    checksum_url_parser = subparsers.add_parser('checksum_url', help='Get checksum URL for the version or build specified')
    checksum_url_parser.add_argument('-c', '--code', required=True, help='Product code')
    checksum_url_mutex = checksum_url_parser.add_mutually_exclusive_group(required=False)
    checksum_url_mutex.add_argument('-v', '--version', help='Version to get checksum')
    checksum_url_mutex.add_argument('-b', '--build', help='Build to get checksum')

    gen_whatsnew_parser = subparsers.add_parser('generate_whatsnew', help='Generate "What\'s new" changelog HTML file')
    gen_whatsnew_parser.add_argument('-n', '--name', required=True, help='Product name (IDEA, PyCharm, GoLand, etc.)')
    gen_whatsnew_parser.add_argument('-c', '--code', required=True, help='Product code')

    args = parser.parse_args()

    if args.command in ('version', 'build') or (
            (args.command in ('download', 'download_url', 'checksum', 'checksum_url') and
             (args.version, args.build).count(None) == 2)):
        latest = True

    sys.exit(main(**vars(args)))

