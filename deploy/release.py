"""Manual, fail-closed PythonAnywhere staging release. Never reloads the web app."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.request import Request, urlopen


def passed_run(payload, sha, repository):
    # Inspect the latest push run, not an older successful run followed by failure.
    runs = [r for r in payload.get('workflow_runs', []) if
            r['head_sha'] == sha and r['head_branch'] == 'main' and r['event'] == 'push'
            and r['head_repository']['full_name'].lower() == repository.lower()
            and r['path'] == '.github/workflows/ci.yml']
    if not runs:
        raise RuntimeError('No main push CI run found for this exact commit.')
    latest = max(runs, key=lambda r: r['id'])
    if latest['status'] != 'completed' or latest['conclusion'] != 'success':
        raise RuntimeError('Latest CI run for this commit has not passed.')
    return latest['html_url']


def backup_database(source, destination):
    if not source.exists():
        return False  # First deployment has no database to back up.
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as old:
        with closing(sqlite3.connect(destination)) as backup:
            old.backup(backup)
            if backup.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Database backup failed integrity check.')
    return True


def run(args):
    import fcntl  # PythonAnywhere/Linux; helpers are testable on Windows.
    os.umask(0o077)
    if not re.fullmatch(r'[0-9a-f]{40}', args.commit):
        raise ValueError('Select a full lowercase 40-character commit SHA, not a branch or tag.')
    repo, root, venv, config_path = [Path(p).expanduser().resolve() for p in
                                    (args.repo, args.root, args.venv, args.config)]
    config = json.loads(config_path.read_text())
    data = Path(config['data_dir']).expanduser().resolve()
    for path in (root, venv, config_path, data):
        if path.is_relative_to(repo):
            raise ValueError('Release root, virtualenv, secrets and data must be outside the source clone.')
    for path in (config_path, data, venv):
        if path.is_relative_to(root):
            raise ValueError('Secrets, data and virtualenv must be outside the release tree.')
    if not args.maintenance_confirmed:
        raise ValueError('Put the web app into maintenance first, then pass --maintenance-confirmed.')
    origin = subprocess.check_output(['git', '-C', str(repo), 'remote', 'get-url', 'origin'], text=True).strip().removesuffix('.git')
    if origin != f'https://github.com/{args.repository}':
        raise RuntimeError('origin must match the selected HTTPS repository without embedded credentials.')
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('Source clone has local changes; commit/push them first.')
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.release.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        token = os.environ.get('GITHUB_TOKEN') or getpass.getpass('GitHub read-only token (hidden): ')
        url = f'https://api.github.com/repos/{args.repository}/actions/workflows/ci.yml/runs?head_sha={args.commit}&event=push&per_page=100'
        request = Request(url, headers={'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with urlopen(request, timeout=30) as response:
            ci_url = passed_run(json.load(response), args.commit, args.repository)
        subprocess.run(['git', '-C', str(repo), 'fetch', 'origin', 'main'], check=True)
        subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', args.commit, 'origin/main'], check=True)
        python = venv / 'bin/python'
        version = subprocess.check_output([str(python), '-c', 'import sys; print("%s.%s" % sys.version_info[:2])'], text=True).strip()
        if version != '3.13':
            raise RuntimeError('Use the same Python 3.13 virtualenv as CI and the Web app.')
        current = root / 'current'
        if current.exists() and not current.is_symlink():
            raise RuntimeError('current must be a symlink, never a checkout directory.')
        previous = str(current.resolve()) if current.exists() else None
        release = root / 'releases' / args.commit
        release.parent.mkdir(exist_ok=True)
        if release.exists():
            raise RuntimeError('Release directory already exists. Inspect the previous attempt; do not overwrite it.')
        subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '--detach', str(release), args.commit], check=True)
        data.mkdir(parents=True, exist_ok=True)
        for name in ('media', 'test-emails', 'backups'):
            (data / name).mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = data / 'backups' / f'{stamp}-before-{args.commit[:12]}.sqlite3'
        backed_up = backup_database(data / 'db.sqlite3', backup)
        print(f'CI: {ci_url}\nPrevious release: {previous}\nDatabase backup: {backup if backed_up else "none (first deployment)"}', flush=True)
        # Keep credentials out of application subprocesses.
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='silent_space.settings_staging', STAGING_CONFIG=str(config_path))
        env.pop('GITHUB_TOKEN', None)
        def command(*parts):
            subprocess.run([str(python), *parts], cwd=release, env=env, check=True)
        command('-m', 'pip', 'install', '-r', 'requirements.txt')
        command('manage.py', 'check')
        command('manage.py', 'makemigrations', '--check', '--dry-run')
        command('manage.py', 'migrate', '--noinput')
        command('manage.py', 'collectstatic', '--noinput')
        manifest = {'commit': args.commit, 'ci_url': ci_url, 'previous': previous,
                    'database_backup': str(backup) if backed_up else None, 'released_at': stamp}
        (root / f'release-{stamp}.json').write_text(json.dumps(manifest, indent=2))
        pending = root / 'current.next'
        if pending.is_symlink():
            pending.unlink()
        pending.symlink_to(release, target_is_directory=True)
        os.replace(pending, current)
        print(f'''Release prepared: {args.commit}
In PythonAnywhere Web tab:
1. Restore the staging WSGI loader if maintenance replaced it.
2. Virtualenv: {venv}; source/working directory: {current}
3. Map /static/ to {current}/staticfiles and /media/ to {data}/media.
4. Enable Force HTTPS. Click Reload for {config['hostname']}.
5. Open https://{config['hostname']}/static/css/base.css directly:
   require HTTP 200, text/css and a CSS body (not a login/error HTML page).
6. Check /, /menu/, /spaces/, /book-a-table/, /orders/bag/, /staff/ and /admin/.
7. Verify synthetic order/booking links refresh, upload photo, and mobile menu.
Email remains file-only and live payments remain disabled. No reload was performed.''')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--venv', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--repository', default='MHamzaAhmed-dev/silent-space-cafe')
    parser.add_argument('--maintenance-confirmed', action='store_true')
    try:
        run(parser.parse_args())
    except Exception as error:
        parser.exit(1, f'Release stopped: {error}\nKeep maintenance enabled. Inspect the printed backup/previous release before rollback.\n')
