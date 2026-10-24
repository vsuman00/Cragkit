"""Save a Cohere key through a hidden prompt, outside the repository."""
import getpass
import os
from pathlib import Path
import stat
import tempfile
import warnings


def save_key(key: str, directory: Path) -> None:
    if (type(key) is not str or not 20 <= len(key) <= 4096
            or any(not 33 <= ord(char) <= 126 for char in key)
            or key.startswith(('"', "'", 'Bearer ', '{\\rtf'))):
        raise ValueError('Invalid key format. Enter only the API key.')
    if key.startswith(('sk-proj-', 'sk-svcacct-')):
        raise ValueError('Use a Cohere key, not an OpenAI key.')
    for parent in (directory.parent.parent, directory.parent, directory):
        parent.mkdir(exist_ok=True, mode=0o700)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('Expected an owned private directory.')
    if stat.S_IMODE(directory.stat().st_mode) != 0o700:
        raise ValueError('Key directory must have permissions 0700.')
    target = directory / 'api-key'
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Existing key must be an owned regular file with permissions 0600.')
    fd, temporary = tempfile.mkstemp(prefix='.api-key-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(key)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main() -> int:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('Cohere API key (hidden): ').strip()
        save_key(key, Path.home() / '.config/cragkit/cohere')
    except (Exception, KeyboardInterrupt):
        print('Key was not saved. Check the key format and private-file permissions.')
        return 1
    print('Cohere key saved privately. No API request was made.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
