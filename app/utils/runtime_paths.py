import os
import sys
import secrets


def get_base_path() -> str:
    """Return base path for static/templates, PyInstaller-safe."""
    try:
        return getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
    except Exception:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def load_or_create_secret_key(filename: str = 'secret_key.txt') -> str:
    """Load secret key from a file next to the EXE when frozen, otherwise project root; create if missing."""
    try:
        if getattr(sys, 'frozen', False):
            secret_dir = os.path.dirname(sys.executable)
        else:
            secret_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        os.makedirs(secret_dir, exist_ok=True)
        secret_path = os.path.join(secret_dir, filename)
        if os.path.exists(secret_path):
            with open(secret_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return content
        new_secret = secrets.token_hex(32)
        with open(secret_path, 'w', encoding='utf-8') as f:
            f.write(new_secret)
        return new_secret
    except Exception:
        return secrets.token_hex(32)


