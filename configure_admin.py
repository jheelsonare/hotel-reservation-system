"""Configure the local demo administrator without putting passwords in shell history."""
from getpass import getpass
from pathlib import Path
import os
import secrets
from dotenv import dotenv_values, set_key
from werkzeug.security import generate_password_hash


def main():
    password = getpass('Choose an admin password (at least 12 characters): ')
    if len(password) < 12:
        raise SystemExit('Password must contain at least 12 characters.')
    if password != getpass('Confirm admin password: '):
        raise SystemExit('Passwords do not match.')
    env_path = Path(__file__).resolve().parent / '.env'
    if not env_path.exists():
        env_path.write_text(env_path.with_name('.env.example').read_text(), encoding='utf-8')
    if os.name == 'posix':
        env_path.chmod(0o600)
    values = dotenv_values(env_path)
    secret = values.get('SECRET_KEY') or ''
    if len(secret) < 32 or secret == 'replace-with-a-random-secret':
        set_key(str(env_path), 'SECRET_KEY', secrets.token_hex(32))
    set_key(str(env_path), 'ADMIN_USERNAME', values.get('ADMIN_USERNAME') or 'admin')
    set_key(str(env_path), 'ADMIN_PASSWORD_HASH', generate_password_hash(password))
    print('Admin access configured. Set DB_PASSWORD in .env, then start the app.')


if __name__ == '__main__':
    main()
