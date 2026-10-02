"""Optional Jevgrep retrieval. No inference during setup or readiness checks."""
import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import time
from urllib.parse import urlsplit

import alloy_routing as routing

MAX_OUTPUT = 4_000_000
MIN_VERSION = (0, 3, 2)
PROVIDERS = ('typesafe', 'openrouter', 'vercel', 'opencode', 'custom')


class SearchError(Exception):
    pass


def credentials_path():
    return Path(os.environ.get('XDG_CONFIG_HOME') or str(Path.home() / '.config')) / 'jevgrep' / 'credentials.json'


def credentials():
    """Read only for readiness/redaction; never return this record to the caller."""
    try:
        with credentials_path().open() as f:
            value = json.loads(f.read(16385))
        provider = value.get('provider', 'vercel')
        secret = value.get('apiKey', '')
        if provider not in PROVIDERS or not isinstance(secret, str):
            raise ValueError()
        if provider == 'custom':
            # Only inspect saved format; jg owns endpoint/model semantics.
            base = value.get('baseURL')
            model = value.get('model')
            if not isinstance(base, str) or not isinstance(model, str):
                raise ValueError()
            url = urlsplit(base.strip())
            if (not url.hostname or url.scheme not in ('https', 'http')
                    or (url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1'))
                    or url.username or url.password or '?' in base or '#' in base
                    or not model.strip() or re.search(r'\s', model.strip())):
                raise ValueError()
        secret = secret.strip()
        if not secret or len(secret.encode()) > 8192 or re.search(r'\s', secret):
            raise ValueError()
        return provider, secret
    except (OSError, ValueError, AttributeError):
        raise SearchError('Jevgrep credentials missing or invalid. Run jg auth, or alloy search --auth-from-routing.') from None


def invoke(core, argv, timeout, secret=None):
    """Bound output and time; cancel the whole process group, including children."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE if secret else subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL if secret else subprocess.PIPE,
                            stderr=subprocess.DEVNULL if secret else subprocess.STDOUT,
                            start_new_session=True, env=routing.clean_env())
    with core._LIVE_LOCK:
        core._LIVE_PGIDS.add(proc.pid)
    output = bytearray()
    started = time.monotonic()
    status = None
    try:
        if secret:
            # Auth output is discarded, including errors that might echo input.
            proc.communicate((secret + '\n').encode(), timeout=timeout)
        else:
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        status = 'timeout'
                        break
                    for key, _ in selector.select(min(remaining, 0.1)):
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        output.extend(chunk[:max(0, MAX_OUTPUT + 1 - len(output))])
                        if len(output) > MAX_OUTPUT:
                            status = 'output_limit'
                            break
                    if status:
                        break
            if not status:
                proc.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
    except subprocess.TimeoutExpired:
        status = 'timeout'
    finally:
        # Also reap descendants that outlive a successful parent.
        core._kill_group(proc.pid)
        proc.wait()
        if proc.stdout:
            proc.stdout.close()
        with core._LIVE_LOCK:
            core._LIVE_PGIDS.discard(proc.pid)
    return proc.returncode, output[:MAX_OUTPUT].decode('utf-8', errors='replace'), status


def readiness(core, root, need_credentials=True):
    blockers = []
    binary = shutil.which('jg')
    version = None
    provider = None
    if not binary:
        blockers.append('Install Node.js 22+ and npm install --global @dzhng/jevgrep@latest (requires jg >= 0.3.2).')
    elif any(core._is_within(os.path.realpath(binary), str(base))
             for base in (root, Path.cwd().resolve()) if base != Path.home().resolve()):
        blockers.append('Refusing a jg executable inside the search root or current project; install Jevgrep outside the project.')
        binary = None
    else:
        code, output, failure = invoke(core, [binary, '--version'], 10)
        match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)\s*', output.strip())
        if code or failure or not match or tuple(map(int, match.groups())) < MIN_VERSION:
            blockers.append('Cannot verify jg >= 0.3.2; update with npm install --global @dzhng/jevgrep@latest.')
        else:
            version = output.strip()
    if need_credentials:
        try:
            provider, _ = credentials()
            if provider == 'custom' and version and tuple(map(int, version.split('.'))) < (0, 8, 0):
                blockers.append('Custom endpoint credentials require jg >= 0.8.0 in Alloy; update Jevgrep.')
        except SearchError as exc:
            blockers.append(str(exc))
    return dict(ready=not blockers, binary=binary, version=version, provider=provider,
                blockers=blockers, access_verified=False)


def command(core, args):
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SearchError('Search root must be an existing directory.')
    if args.replace_auth and not args.auth_from_routing:
        raise SearchError('--replace-auth requires --auth-from-routing.')
    if args.query and (args.check or args.auth_from_routing):
        raise SearchError('Use a query, --check, or --auth-from-routing separately.')
    if not (args.check or args.auth_from_routing):
        if not args.query or not args.query.strip() or len(args.query.encode()) > 8192:
            raise SearchError('Provide a nonempty search question of at most 8192 bytes.')
        # jg interprets these as commands even after --. Never dispatch auth/skill
        # installation/doctor inference from text supplied as a search question.
        if args.query in ('auth', 'skill', 'doctor', 'cache', 'files'):
            raise SearchError('Rephrase this reserved Jevgrep command as a search question.')
        if '\x00' in args.query:
            raise SearchError('Search question cannot contain NUL.')
    report = readiness(core, root, need_credentials=not args.auth_from_routing)
    if args.check:
        print(json.dumps(report, indent=2) if args.json else
              ('Jevgrep ready locally (%s, %s); provider access/billing not verified.' %
               (report['version'], report['provider']) if report['ready'] else
               'Jevgrep blocked:\n- ' + '\n- '.join(report['blockers'])))
        return 0 if report['ready'] else 1
    if report['blockers']:
        raise SearchError('Jevgrep blocked:\n- ' + '\n- '.join(report['blockers']))
    if args.auth_from_routing:
        if os.path.lexists(str(credentials_path())) and not args.replace_auth:
            raise SearchError('Jevgrep already has a credential file; use --replace-auth to replace it explicitly.')
        config = routing.read_json(routing.root() / 'routing.json', {})
        if not isinstance(config, dict):
            raise SearchError('Invalid Alloy routing configuration.')
        provider = config.get('jev_provider', 'typesafe')
        secret = routing.key(provider)
        if not secret or len(secret.encode()) > 8191 or re.search(r'\s', secret):
            raise SearchError('Routing key must be one nonempty token, at most 8191 bytes.')
        code, _, failure = invoke(core, [report['binary'], 'auth', '--provider', provider, '--stdin'], 10, secret)
        if code or failure:
            raise SearchError('Jevgrep credential setup failed; no inference was attempted. Run jg auth in your terminal.')
        # No key in argv, logs, or reports. jg owns its separate private storage.
        print(json.dumps(dict(status='configured', provider=provider, access_verified=False))
              if args.json else 'Jevgrep configured through %s; no inference performed.' % provider)
        return 0
    provider, secret = credentials()
    # Keep upstream's tuned search/output defaults unless explicitly overridden.
    argv = [report['binary']]
    if args.max_source_bytes is not None:
        argv += ['--max-source-bytes', str(args.max_source_bytes)]
    if args.concurrency is not None:
        argv += ['--concurrency', str(args.concurrency)]
    if args.no_cache:
        argv.append('--no-cache')
    argv += ['--', args.query, str(root)]
    core.log('Jevgrep search via %s: source under %s may be sent to the provider (metered API).' % (provider, root))
    started = time.monotonic()
    code, output, failure = invoke(core, argv, args.timeout)
    output = core.redact_secrets(output.replace(secret, '[REDACTED]'))[0]
    status = failure or {0: 'complete', 2: 'incomplete', 130: 'interrupted'}.get(code, 'failed')
    result = dict(status=status, root=str(root), provider=provider, version=report['version'],
                  duration_s=round(time.monotonic() - started, 3), context=output,
                  complete=status == 'complete', exit_code=code)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        # Native agent-facing packet, not a human summary or another model call.
        print(output, end='')
        if status != 'complete':
            core.log('Jevgrep %s. Use useful excerpts, then fill gaps with rg/read; do not infer absence.' % status)
    return {'complete': 0, 'incomplete': 2, 'timeout': 124, 'output_limit': 2, 'interrupted': 130}.get(status, 1)


def positive(value):
    try:
        parsed = int(value)
        if parsed > 0:
            return parsed
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('must be a positive integer')


def source_bytes(value):
    if value == '0':
        return 0  # Upstream meaning: all selected source.
    return positive(value)


def register(sub, core):
    parser = sub.add_parser('search', help='opt-in source retrieval through Jevgrep (jg; metered API)')
    parser.add_argument('query', nargs='?', help='behavior or symptom to locate; visible in the jg process arguments')
    parser.add_argument('--root', default='.', help='authorized directory to search (default: current directory)')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--check', action='store_true', help='local installation/credential check; no inference')
    action.add_argument('--auth-from-routing', action='store_true', help='copy your Alloy provider/key via jg auth stdin; no inference')
    parser.add_argument('--replace-auth', action='store_true', help='explicitly replace existing Jevgrep credentials')
    parser.add_argument('--json', action='store_true', help='structured status and context')
    parser.add_argument('--timeout', type=positive, default=300, help='whole-search deadline in seconds')
    parser.add_argument('--max-source-bytes', type=source_bytes, help='override jg excerpt allocation; 0 includes all selected source (not an API token budget)')
    parser.add_argument('--concurrency', type=positive, help='override jg concurrent requests; otherwise keep upstream default')
    parser.add_argument('--no-cache', action='store_true', help='disable Jevgrep evaluation cache reads/writes')
    parser.set_defaults(func=lambda args: command(core, args))
