"""Fetch reviewed RC1 registry products without credentials, installs or execution."""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

import prepare_release_products as P

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / 'evaluation/reports/V6/V6-08R-verification.json'
SUMMARY_SHA256 = '32b3251e3ef7d9536830f15ed1c196a45f2c1a91c31093dce2d99aed99471312'
MANIFEST_SHA256 = '7ab4ba1aeebfce8b83871f7bda8bf09cfdc39e6e405f28a0ca88fe55ecbdc663'
PACKAGES = ('cragkit', 'cragkit-langchain', 'cragkit-mcp')
MAX_METADATA = 256 * 1024
MAX_REQUESTS = 18
REQUEST_SECONDS = 5.0
TOTAL_SECONDS = 60.0
REPORT = 'registry-report.json'


class RegistryError(ValueError):
    """A fixed diagnostic that never includes a remote body or URL."""


def require(condition, code):
    if not condition:
        raise RegistryError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'json_duplicate_key')
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               RegistryError('json_nonfinite')))
        pending = [value]
        while pending:
            item = pending.pop()
            require(not isinstance(item, float) or math.isfinite(item), 'json_nonfinite')
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
        require(type(value) is dict, 'json_shape')
        return value
    except RegistryError:
        raise
    except Exception:
        raise RegistryError('json_invalid') from None


def reviewed_products():
    raw = P.read_file(SUMMARY, 1024 * 1024)
    require(digest(raw) == SUMMARY_SHA256, 'reviewed_summary_digest')
    summary = parse_json(raw)
    require(summary.get('manifest_sha256') == MANIFEST_SHA256
            and summary.get('source_commit') == P.SOURCE_COMMIT,
            'reviewed_summary_identity')
    products = summary.get('products')
    require(type(products) is list and len(products) == 9, 'reviewed_inventory')
    expected = set()
    for package in PACKAGES:
        expected.add(f'products/npm/{package}-1.0.0-rc.1.tgz')
        stem = package.replace('-', '_') + '-1.0.0rc1'
        expected.update((f'products/pypi/{stem}-py3-none-any.whl',
                         f'products/pypi/{stem}.tar.gz'))
    require({item['path'] for item in products} == expected, 'reviewed_inventory')
    return products


def safe_url(url, host):
    require(type(url) is str and len(url) <= 2048 and url.isascii()
            and not any(ord(char) <= 32 or ord(char) == 127 for char in url),
            'unsafe_url')
    parts = urlsplit(url)
    require(parts.scheme == 'https' and parts.netloc == host
            and parts.hostname == host and parts.username is None
            and parts.password is None and not parts.query and not parts.fragment
            and '%' not in parts.path and '\\' not in parts.path and '//' not in parts.path
            and all(part not in ('.', '..') for part in parts.path.split('/')),
            'unsafe_url')
    return parts.path


class PublicHTTPS:
    """Direct HTTPS never consults proxy, auth, netrc or certificate env settings."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        # Passing explicit system trust paths avoids SSL_CERT_FILE/SSL_CERT_DIR.
        paths = ssl.get_default_verify_paths()
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.load_verify_locations(cafile=paths.openssl_cafile,
                                           capath=paths.openssl_capath)

    def get(self, url, *, limit, timeout, deadline):
        parts = urlsplit(url)
        connection = http.client.HTTPSConnection(parts.hostname, timeout=timeout,
                                                 context=self.context)
        try:
            connection.request('GET', parts.path, headers={
                'Accept': 'application/json, application/octet-stream',
                'Accept-Encoding': 'identity', 'User-Agent': 'cragkit-registry-check/RPK-r1'})
            response = connection.getresponse()
            require(response.status == 200 or response.status == 404, 'http_status')
            # Do not read arbitrary error bodies, including 404 bodies.
            if response.status == 404:
                return 404, b''
            encodings = response.headers.get_all('Content-Encoding') or []
            require(not encodings or encodings == ['identity'], 'http_encoding')
            lengths = response.headers.get_all('Content-Length') or []
            require(len(lengths) <= 1, 'http_length')
            if lengths:
                require(lengths[0].isdigit() and int(lengths[0]) <= limit, 'http_length')
            raw = bytearray()
            while True:
                remaining = deadline - self.clock()
                require(remaining > 0, 'request_deadline')
                if connection.sock is not None:
                    connection.sock.settimeout(min(timeout, remaining))
                block = response.read1(min(16 * 1024, limit + 1 - len(raw)))
                require(self.clock() < deadline, 'request_deadline')
                if not block:
                    break
                raw.extend(block)
                require(len(raw) <= limit, 'response_size_limit')
            if lengths:
                require(len(raw) == int(lengths[0]), 'http_length')
            return 200, bytes(raw)
        except RegistryError:
            raise
        except Exception:
            raise RegistryError('https_failed') from None
        finally:
            connection.close()


class SupervisedHTTPS:
    """One disposable interpreter enforces each request's wall-clock deadline."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock

    def get(self, url, *, limit, timeout, deadline):
        # The parent never performs DNS or TLS work. No inherited environment,
        # stdin, stderr or auth configuration is available to the worker.
        with tempfile.TemporaryDirectory(prefix='cragkit-registry-http-') as temporary:
            output = Path(temporary) / 'response.bin'
            process = None
            try:
                require(deadline > self.clock(), 'request_deadline')
                process = subprocess.Popen([
                    sys.executable, '-E', '-s', '-B', str(Path(__file__).resolve()),
                    '--http-worker', url, '--worker-output', str(output),
                    '--worker-limit', str(limit), '--worker-timeout', str(timeout)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env={}, close_fds=True)
                remaining = deadline - self.clock()
                require(remaining > 0, 'request_deadline')
                try:
                    status = process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    raise RegistryError('request_deadline') from None
                require(self.clock() < deadline, 'request_deadline')
                # Exit status encodes only success/absence/error; no child output
                # is interpreted as trusted text or retained in diagnostics.
                require(status in (0, 4), 'https_failed')
                raw = P.read_file(output, limit)
                require(status == 0 or raw == b'', 'worker_response')
                return (200 if status == 0 else 404), raw
            except RegistryError:
                raise
            except Exception:
                raise RegistryError('https_failed') from None
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    # Always reap before the temporary directory goes away.
                    process.wait()


def http_worker(argv):
    """Internal bounded GET helper; no response text reaches logs or stdout."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--http-worker', required=True)
    parser.add_argument('--worker-output', type=Path, required=True)
    parser.add_argument('--worker-limit', type=int, required=True)
    parser.add_argument('--worker-timeout', type=float, required=True)
    try:
        args = parser.parse_args(argv)
        url = args.http_worker
        host = urlsplit(url).hostname
        require(host in ('pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org'), 'unsafe_url')
        safe_url(url, host)
        require(0 < args.worker_limit <= MAX_METADATA * 2
                and 0 < args.worker_timeout <= REQUEST_SECONDS, 'worker_limits')
        transport = PublicHTTPS()
        status, raw = transport.get(url, limit=args.worker_limit,
            timeout=args.worker_timeout, deadline=time.monotonic() + args.worker_timeout)
        with args.worker_output.open('xb') as stream:
            os.chmod(args.worker_output, 0o600)
            stream.write(raw)
        return 0 if status == 200 else 4
    except Exception:
        return 1


class Budget:
    def __init__(self, transport, clock=time.monotonic):
        self.transport, self.clock = transport, clock
        self.deadline = clock() + TOTAL_SECONDS
        self.calls = 0

    def get(self, url, host, limit):
        safe_url(url, host)
        require(self.calls < MAX_REQUESTS, 'request_limit')
        remaining = self.deadline - self.clock()
        require(remaining > 0, 'shared_deadline')
        self.calls += 1
        seconds = min(REQUEST_SECONDS, remaining)
        deadline = self.clock() + seconds
        try:
            status, raw = self.transport.get(url, limit=limit, timeout=seconds,
                                             deadline=deadline)
        except RegistryError:
            raise
        except Exception:
            raise RegistryError('https_failed') from None
        require(self.clock() < deadline and self.clock() < self.deadline,
                'request_deadline')
        require(type(status) is int and status in (200, 404), 'http_status')
        require(type(raw) is bytes and len(raw) <= limit, 'response_size_limit')
        return None if status == 404 else raw

    def metadata(self, url, host):
        raw = self.get(url, host, MAX_METADATA)
        return None if raw is None else parse_json(raw)


def verify_bytes(raw, product):
    require(len(raw) == product['bytes'], 'product_size')
    require(digest(raw) == product['prepared_sha256'], 'product_digest')


def verify_integrity(raw, dist):
    present = False
    if 'shasum' in dist:
        present = True
        require(dist['shasum'] == hashlib.sha1(raw).hexdigest(), 'npm_shasum')
    if 'integrity' in dist:
        present = True
        integrity = dist['integrity']
        require(type(integrity) is str and len(integrity) <= 512, 'npm_integrity')
        matches = re.fullmatch(r'(sha512|sha384|sha256|sha1)-([A-Za-z0-9+/]+={0,2})', integrity)
        require(matches is not None, 'npm_integrity')
        algorithm, encoded = matches.groups()
        expected = base64.b64encode(hashlib.new(algorithm, raw).digest()).decode('ascii')
        require(encoded == expected, 'npm_integrity')
    require(present, 'npm_digest_missing')


def verify_pypi_digests(raw, metadata):
    algorithms = {'sha256': digest(raw), 'md5': hashlib.md5(raw).hexdigest(),
                  'blake2b_256': hashlib.blake2b(raw, digest_size=32).hexdigest()}
    for algorithm, declared in metadata['digests'].items():
        require(algorithm in algorithms or not declared, 'pypi_digest_algorithm')
        if algorithm in algorithms:
            require(declared == algorithms[algorithm], 'pypi_digest')
    if 'md5_digest' in metadata:
        require(metadata['md5_digest'] == algorithms['md5'], 'pypi_digest')


def pypi_metadata(budget, products):
    package, version = products[0]['package'], products[0]['version']
    metadata = budget.metadata(f'https://pypi.org/pypi/{package}/{version}/json', 'pypi.org')
    if metadata is None:
        return None
    info = metadata.get('info')
    require(type(info) is dict and info.get('name') == package
            and info.get('version') == version, 'pypi_identity')
    urls = metadata.get('urls')
    require(type(urls) is list and len(urls) <= 2, 'pypi_inventory')
    expected = {Path(item['path']).name: item for item in products}
    found = {}
    for item in urls:
        require(type(item) is dict and type(item.get('filename')) is str,
                'pypi_inventory')
        name = item['filename']
        require(name in expected and name not in found, 'pypi_inventory')
        product = expected[name]
        require(type(item.get('size')) is int and item['size'] == product['bytes'],
                'pypi_size')
        require(type(item.get('digests')) is dict
                and item['digests'].get('sha256') == product['prepared_sha256'],
                'pypi_digest')
        require(item.get('packagetype') == ('bdist_wheel' if product['kind'] == 'wheel'
                                           else 'sdist') and item.get('yanked') is False,
                'pypi_metadata')
        path = safe_url(item.get('url'), 'files.pythonhosted.org')
        require(re.fullmatch(r'/packages/[0-9a-f]{2}/[0-9a-f]{2}/[0-9a-f]{60}/' + re.escape(name), path)
                is not None, 'pypi_file_url')
        found[name] = item
    return found


def npm_metadata(budget, product):
    package, version = product['package'], product['version']
    metadata = budget.metadata(f'https://registry.npmjs.org/{package}/{version}',
                               'registry.npmjs.org')
    if metadata is None:
        return None
    require(metadata.get('name') == package and metadata.get('version') == version,
            'npm_identity')
    dist = metadata.get('dist')
    require(type(dist) is dict, 'npm_dist')
    expected = f'https://registry.npmjs.org/{package}/-/{package}-{version}.tgz'
    require(dist.get('tarball') == expected, 'npm_tarball_url')
    safe_url(dist['tarball'], 'registry.npmjs.org')
    return dist


def error_code(error):
    return str(error) if isinstance(error, RegistryError) else 'registry_invalid'


def inspect_products(budget, products):
    records, outputs = [], {}
    for registry in ('pypi', 'npm'):
        for package in PACKAGES:
            group = [item for item in products
                     if item['registry'] == registry and item['package'] == package]
            try:
                metadata = (pypi_metadata(budget, group) if registry == 'pypi'
                            else npm_metadata(budget, group[0]))
                metadata_error = None
            except Exception as error:
                metadata, metadata_error = None, error_code(error)
            for product in group:
                record = {key: product[key] for key in ('path', 'registry', 'package', 'version', 'bytes')}
                record['sha256'] = product['prepared_sha256']
                try:
                    if metadata_error:
                        raise RegistryError(metadata_error)
                    file_metadata = (None if metadata is None else
                        metadata.get(Path(product['path']).name) if registry == 'pypi' else metadata)
                    url = (None if file_metadata is None else file_metadata['url']
                           if registry == 'pypi' else file_metadata['tarball'])
                    raw = None if url is None else budget.get(url,
                        'files.pythonhosted.org' if registry == 'pypi' else 'registry.npmjs.org',
                        product['bytes'])
                    require(url is None or raw is not None, 'registry_file_missing')
                    if raw is None:
                        record['state'] = 'absent'
                    else:
                        verify_bytes(raw, product)
                        if registry == 'npm':
                            verify_integrity(raw, metadata)
                        else:
                            verify_pypi_digests(raw, file_metadata)
                        record['state'] = 'verified'
                        outputs[product['path']] = raw
                except Exception as error:
                    record.update(state='error', reason=error_code(error))
                records.append(record)
    return records, outputs


def inspect_tags(budget):
    tags = []
    for package in PACKAGES:
        record = dict(package=package, expected='1.0.0-rc.1', observed=None)
        try:
            metadata = budget.metadata(f'https://registry.npmjs.org/-/package/{package}/dist-tags',
                                       'registry.npmjs.org')
            observed = None if metadata is None else metadata.get('next')
            require(observed is None or type(observed) is str and len(observed) <= 128
                    and re.fullmatch(r'[A-Za-z0-9.+-]+', observed) is not None, 'npm_tag')
            record.update(observed=observed, state='absent' if observed is None else
                          'match' if observed == record['expected'] else 'different')
        except Exception as error:
            record.update(state='error', reason=error_code(error))
        tags.append(record)
    return tags


def write_output(output, outputs, report):
    """Reuse exclusive claim and owned-file cleanup; report is the final marker."""
    expected = dict(outputs)
    expected[REPORT] = P.encode_json(report)
    stage = Path(tempfile.mkdtemp(prefix='.cragkit-registry-', dir=output.parent))
    try:
        for relative, raw in expected.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o600)
        P.publish_directory(stage, output, expected, completion_marker=REPORT)
    finally:
        shutil.rmtree(stage)


def check_registry(*, output, allow_missing=False, transport=None, clock=time.monotonic):
    try:
        require(not os.path.lexists(output), 'output_exists')
        require(output.parent.is_dir()
                and not any(path.is_symlink() for path in (output.parent, *output.parent.parents)),
                'output_parent')
        products = reviewed_products()
        budget = Budget(SupervisedHTTPS(clock) if transport is None else transport, clock)
        records, outputs = inspect_products(budget, products)
        tags = inspect_tags(budget)
        failed = any(item['state'] == 'error' for item in records + tags)
        complete = (not failed and all(item['state'] == 'verified' for item in records)
                    and all(item['state'] == 'match' for item in tags))
        report = dict(revision='RPK-r1', manifest_sha256=MANIFEST_SHA256,
                      state='failed' if failed else 'complete' if complete else 'partial',
                      publication_complete=complete, allow_missing=allow_missing,
                      request_count=budget.calls, products=records, npm_next_tags=tags)
        write_output(output, outputs, report)
        return report
    except RegistryError:
        raise
    except Exception:
        raise RegistryError('registry_invalid') from None


def main(argv=None):
    if argv is None and len(sys.argv) > 1 and sys.argv[1] == '--http-worker':
        return http_worker(sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-missing', action='store_true')
    args = parser.parse_args(argv)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        report = check_registry(output=args.output, allow_missing=args.allow_missing)
        passed = report['publication_complete'] or args.allow_missing and report['state'] != 'failed'
        print(json.dumps(dict(revision='RPK-r1', state=report['state'],
                              publication_complete=report['publication_complete'])))
        return 0 if passed else 1
    except RegistryError as error:
        print(json.dumps(dict(revision='RPK-r1', state='failed', reason=str(error))))
        return 1
    except KeyboardInterrupt:
        print(json.dumps(dict(revision='RPK-r1', state='failed', reason='request_interrupted')))
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    raise SystemExit(main())
