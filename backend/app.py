"""BytePlay CMS: same-origin admin, read-only public API, persistent SQLite storage."""
import hashlib
import io
import json
import os
import re
import secrets
import sqlite3
import time
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import bleach
import click
from flask import Flask, g, jsonify, request, send_from_directory
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
CATEGORIES = {'fertilia', 'cab', 'timekits', 'announcements'}
SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))
TAGS = {'p', 'b', 'strong', 'i', 'em', 'u', 's', 'br', 'a', 'code', 'h2', 'h3', 'ul', 'ol', 'li', 'img', 'blockquote'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def clean_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Image and link URLs must be shorter than 2048 characters.')
    value = value.strip()
    parts = urlsplit(value)
    if value.startswith('//') or '\\' in value or any(ord(c) < 32 for c in value):
        raise ValueError('Use a relative path or an HTTPS URL.')
    if parts.scheme and (parts.scheme != 'https' or not parts.netloc or parts.username or parts.password):
        raise ValueError('External images and links must use HTTPS.')
    return value


def clean_html(value):
    def attributes(tag, name, value):
        if (tag == 'a' and name == 'href') or (tag == 'img' and name == 'src'):
            try:
                return bool(clean_url(value))
            except ValueError:
                return False
        return tag == 'img' and name == 'alt'
    return bleach.clean(value, tags=TAGS, attributes=attributes, protocols={'https'}, strip=True)


def text_field(data, name, limit, required=False):
    value = data.get(name, '')
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{name} must be text, at most {limit} characters.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{name} is required.')
    return value


def validate_post(data):
    if not isinstance(data, dict):
        raise ValueError('A post object is required.')
    post = {key: text_field(data, key, limit, required) for key, limit, required in [
        ('id', 100, True), ('title', 180, True), ('excerpt', 500, False), ('author', 100, True),
        ('date', 10, True), ('category', 30, True), ('status', 20, True), ('thumb', 2048, False)]}
    if not SLUG.fullmatch(post['id']):
        raise ValueError('The URL slug must contain lowercase letters, numbers, and hyphens.')
    if post['category'] not in CATEGORIES or post['status'] not in {'draft', 'published'}:
        raise ValueError('Choose a valid category and publication status.')
    date.fromisoformat(post['date'])
    post['thumb'] = clean_url(post['thumb'])
    blocks = data.get('content')
    if not isinstance(blocks, list) or len(blocks) > 200:
        raise ValueError('Content must contain at most 200 blocks.')
    cleaned = []
    for block in blocks:
        if not isinstance(block, dict):
            raise ValueError('Invalid content block.')
        kind = block.get('type')
        if kind in {'h2', 'signoff'}:
            cleaned.append({'type': kind, 'text': text_field(block, 'text', 500, True)})
        elif kind in {'p', 'html'}:
            cleaned.append({'type': kind, 'html': clean_html(text_field(block, 'html', 30000, True))})
        elif kind == 'img':
            cleaned.append({'type': kind, 'src': clean_url(text_field(block, 'src', 2048, True)), 'alt': text_field(block, 'alt', 300)})
        elif kind == 'button':
            cleaned.append({'type': kind, 'text': text_field(block, 'text', 150, True), 'href': clean_url(text_field(block, 'href', 2048, True))})
        elif kind == 'fixed':
            items = block.get('items')
            if not isinstance(items, list) or len(items) > 100 or any(not isinstance(i, str) or len(i) > 2000 for i in items):
                raise ValueError('Lists accept at most 100 text items.')
            cleaned.append({'type': kind, 'items': [clean_html(i) for i in items]})
        else:
            raise ValueError('Unknown content block type.')
    if post['status'] == 'published' and not cleaned:
        raise ValueError('Add content before publishing.')
    post['content'] = cleaned
    return post


def create_app(test_config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SITE_URL=os.environ.get('CMS_SITE_URL', 'https://tomzeidev.github.io/byteplay-html/'),
        DATABASE=os.environ.get('CMS_DATABASE', str(ROOT / 'data' / 'cms.sqlite3')),
        UPLOADS=os.environ.get('CMS_UPLOADS', str(ROOT / 'data' / 'uploads')),
        COOKIE_SECURE=os.environ.get('CMS_COOKIE_SECURE', 'true').lower() == 'true',
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if os.environ.get('CMS_TRUST_PROXY') == '1':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    Path(app.config['UPLOADS']).mkdir(parents=True, exist_ok=True)

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'], timeout=10, isolation_level=None)
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop('db', None)
        if connection:
            connection.close()

    with app.app_context():
        db().executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor')),
                active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                csrf TEXT NOT NULL, expires INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY, data TEXT NOT NULL, status TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL,
                updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (key TEXT NOT NULL, at INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS attempts_key ON login_attempts(key,at);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action TEXT NOT NULL, target TEXT NOT NULL, at TEXT NOT NULL
            );
        ''')

    def now():
        return datetime.now(timezone.utc).isoformat()

    def audit(action, target):
        db().execute('INSERT INTO audit(user_id,action,target,at) VALUES(?,?,?,?)',
                     (g.user['id'] if g.user else None, action, str(target), now()))

    @app.before_request
    def identify():
        g.user = None
        g.session = None
        token = request.cookies.get('byteplay_session', '')
        if token:
            row = db().execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?', (digest(token), int(time.time()))).fetchone()
            if row:
                g.session = row
                if row['user_id']:
                    g.user = db().execute('SELECT * FROM users WHERE id=? AND active=1', (row['user_id'],)).fetchone()
        if request.path.startswith('/api/') and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            # Admin requests are same-origin; Pages only accesses read-only routes.
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                return jsonify(error='This request must come from the admin site.'), 403
            supplied = request.headers.get('X-CSRF-Token', '')
            if not g.session or not secrets.compare_digest(g.session['csrf'], supplied):
                return jsonify(error='Your session expired. Reload the page and sign in again.'), 403

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.path.startswith('/admin'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/api/public/'):
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith('/api/'):
            return jsonify(error=error.description), error.code
        return error

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error=str(error)), 400

    def payload():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('A JSON object is required.')
        return data

    def require(role=None):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not g.user:
                    return jsonify(error='Sign in to continue.'), 401
                if role and g.user['role'] != role:
                    return jsonify(error='Only admins can manage users.'), 403
                return fn(*args, **kwargs)
            return wrapped
        return decorator

    def user_public(row):
        return {key: row[key] for key in ('id', 'username', 'display_name', 'role', 'active')}

    def new_session(user_id=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        expires = int(time.time()) + (43200 if user_id else 1800)
        db().execute('DELETE FROM sessions WHERE expires < ?', (int(time.time()),))
        db().execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), user_id, csrf, expires))
        response = jsonify(user=user_public(g.user) if g.user else None, csrf=csrf, site_url=app.config['SITE_URL'])
        response.set_cookie('byteplay_session', token, httponly=True, secure=app.config['COOKIE_SECURE'], samesite='Strict', max_age=expires-int(time.time()), path='/')
        return response

    @app.get('/api/health')
    def health():
        db().execute('SELECT 1')
        return jsonify(status='ok')

    @app.get('/api/session')
    def session():
        if g.session:
            return jsonify(user=user_public(g.user) if g.user else None, csrf=g.session['csrf'], site_url=app.config['SITE_URL'])
        return new_session()

    @app.post('/api/login')
    def login():
        data = payload()
        username = text_field(data, 'username', 50, True).lower()
        password = text_field(data, 'password', 128, True)
        keys = [digest('ip:' + (request.remote_addr or 'unknown')), digest('user:' + username)]
        cutoff = int(time.time()) - 900
        db().execute('DELETE FROM login_attempts WHERE at < ?', (cutoff,))
        if any(db().execute('SELECT COUNT(*) FROM login_attempts WHERE key=? AND at>=?', (key, cutoff)).fetchone()[0] >= 10 for key in keys):
            return jsonify(error='Too many login attempts. Try again in 15 minutes.'), 429
        row = db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        valid = check_password_hash(row['password_hash'] if row else DUMMY_HASH, password)
        if not row or not valid or not row['active']:
            for key in keys:
                db().execute('INSERT INTO login_attempts VALUES(?,?)', (key, int(time.time())))
            return jsonify(error='Incorrect username or password.'), 401
        db().execute('DELETE FROM sessions WHERE token_hash=?', (g.session['token_hash'],))
        g.user = row
        audit('login', row['username'])
        return new_session(row['id'])

    @app.post('/api/logout')
    def logout():
        db().execute('DELETE FROM sessions WHERE token_hash=?', (g.session['token_hash'],))
        response = jsonify(ok=True)
        response.delete_cookie('byteplay_session', path='/', secure=app.config['COOKIE_SECURE'], httponly=True, samesite='Strict')
        return response

    @app.post('/api/password')
    @require()
    def change_password():
        data = payload()
        if not check_password_hash(g.user['password_hash'], text_field(data, 'current_password', 128, True)):
            return jsonify(error='Current password is incorrect.'), 400
        password = validated_password(data.get('password'))
        db().execute('BEGIN IMMEDIATE')
        try:
            db().execute('UPDATE users SET password_hash=? WHERE id=?', (generate_password_hash(password), g.user['id']))
            db().execute('DELETE FROM sessions WHERE user_id=?', (g.user['id'],))
            audit('password-change', g.user['id'])
            db().execute('COMMIT')
        except Exception:
            db().execute('ROLLBACK'); raise
        return new_session(g.user['id'])

    def validated_password(password):
        if not isinstance(password, str) or not 12 <= len(password) <= 128 or password != password.strip():
            raise ValueError('Passwords must be 12–128 characters, with no surrounding spaces.')
        return password

    @app.get('/api/users')
    @require('admin')
    def users():
        return jsonify(users=[user_public(row) for row in db().execute('SELECT * FROM users ORDER BY username')])

    @app.post('/api/users')
    @require('admin')
    def create_user():
        data = payload()
        username = text_field(data, 'username', 50, True).lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,49}', username):
            raise ValueError('Username must be 3–50 lowercase letters, numbers, dots, underscores, or hyphens.')
        name = text_field(data, 'display_name', 100, True)
        role = data.get('role')
        if role not in {'admin', 'editor'}:
            raise ValueError('Choose admin or editor.')
        password = validated_password(data.get('password'))
        try:
            row = db().execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                               (username, name, generate_password_hash(password), role, now()))
        except sqlite3.IntegrityError:
            return jsonify(error='That username is already in use.'), 409
        audit('user-create', row.lastrowid)
        return jsonify(user=user_public(db().execute('SELECT * FROM users WHERE id=?', (row.lastrowid,)).fetchone())), 201

    @app.patch('/api/users/<int:user_id>')
    @require('admin')
    def update_user(user_id):
        data = payload()
        db().execute('BEGIN IMMEDIATE')
        try:
            row = db().execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                db().execute('ROLLBACK'); return jsonify(error='User not found.'), 404
            role, active = data.get('role', row['role']), data.get('active', bool(row['active']))
            if role not in {'admin', 'editor'} or not isinstance(active, bool):
                raise ValueError('Invalid role or account status.')
            if row['role'] == 'admin' and row['active'] and (role != 'admin' or not active):
                if db().execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                    raise ValueError('Keep at least one active administrator.')
            if user_id == g.user['id'] and (role != 'admin' or not active):
                raise ValueError('Another admin must change your own access.')
            name = text_field(data, 'display_name', 100, True) if 'display_name' in data else row['display_name']
            password_hash = generate_password_hash(validated_password(data['password'])) if data.get('password') else row['password_hash']
            db().execute('UPDATE users SET display_name=?,role=?,active=?,password_hash=? WHERE id=?', (name, role, int(active), password_hash, user_id))
            if not active or role != row['role'] or data.get('password'):
                db().execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            audit('user-update', user_id)
            db().execute('COMMIT')
        except Exception:
            db().execute('ROLLBACK'); raise
        return jsonify(ok=True)

    def unpack(row, content=True):
        post = json.loads(row['data'])
        if not content:
            post.pop('content', None)
        post.update(revision=row['revision'], updated_at=row['updated_at'])
        return post

    def public_data(row, content=True):
        post = unpack(row, content)
        def asset(value):
            return request.host_url.rstrip('/') + value if value.startswith('/uploads/') else value
        post['thumb'] = asset(post.get('thumb', ''))
        for block in post.get('content', []):
            if block['type'] == 'img': block['src'] = asset(block['src'])
        return post

    @app.get('/api/public/posts')
    def public_posts():
        rows = db().execute("SELECT * FROM posts WHERE status='published'").fetchall()
        return jsonify(posts=sorted([public_data(row, False) for row in rows], key=lambda p: p['date'], reverse=True))

    @app.get('/api/public/posts/<slug>')
    def public_post(slug):
        row = db().execute("SELECT * FROM posts WHERE id=? AND status='published'", (slug,)).fetchone()
        if not row:
            return jsonify(error='Post not found.'), 404
        return jsonify(public_data(row))

    @app.get('/api/posts')
    @require()
    def posts():
        rows = db().execute('SELECT * FROM posts ORDER BY updated_at DESC').fetchall()
        return jsonify(posts=[unpack(row, False) for row in rows])

    @app.get('/api/posts/<slug>')
    @require()
    def post(slug):
        row = db().execute('SELECT * FROM posts WHERE id=?', (slug,)).fetchone()
        return (jsonify(unpack(row)) if row else (jsonify(error='Post not found.'), 404))

    @app.post('/api/preview')
    @require()
    def preview():
        return jsonify(post=validate_post(payload()))

    @app.post('/api/posts')
    @require()
    def create_post():
        post = validate_post(payload())
        try:
            db().execute('INSERT INTO posts(id,data,status,updated_at,updated_by) VALUES(?,?,?,?,?)', (post['id'], json.dumps(post), post['status'], now(), g.user['id']))
        except sqlite3.IntegrityError:
            return jsonify(error='That URL slug is already in use.'), 409
        audit('post-create', post['id'])
        return jsonify(post=unpack(db().execute('SELECT * FROM posts WHERE id=?', (post['id'],)).fetchone())), 201

    @app.put('/api/posts/<slug>')
    @require()
    def update_post(slug):
        data = payload()
        post = validate_post(data)
        if post['id'] != slug:
            raise ValueError('The URL slug cannot change after creation; this preserves existing links.')
        result = db().execute('UPDATE posts SET data=?,status=?,revision=revision+1,updated_at=?,updated_by=? WHERE id=? AND revision=?',
                              (json.dumps(post), post['status'], now(), g.user['id'], slug, data.get('revision')))
        if not result.rowcount:
            exists = db().execute('SELECT 1 FROM posts WHERE id=?', (slug,)).fetchone()
            return jsonify(error='This post changed elsewhere. Reload before saving.' if exists else 'Post not found.'), 409 if exists else 404
        audit('post-update', slug)
        return jsonify(post=unpack(db().execute('SELECT * FROM posts WHERE id=?', (slug,)).fetchone()))

    @app.delete('/api/posts/<slug>')
    @require()
    def delete_post(slug):
        data = payload()
        result = db().execute('DELETE FROM posts WHERE id=? AND revision=?', (slug, data.get('revision')))
        if not result.rowcount:
            return jsonify(error='The post changed or was already deleted. Reload the list.'), 409
        audit('post-delete', slug)
        return jsonify(ok=True)

    @app.post('/api/uploads')
    @require()
    def upload():
        file = request.files.get('image')
        if not file:
            raise ValueError('Choose an image.')
        try:
            with Image.open(file.stream) as image:
                if image.width * image.height > 20_000_000 or image.format not in {'PNG', 'JPEG', 'WEBP'}:
                    raise ValueError('Use a PNG, JPEG, or WebP image under 20 megapixels.')
                image.load()
                output = io.BytesIO()
                image.convert('RGBA' if image.mode in {'RGBA', 'LA', 'P'} else 'RGB').save(output, format='WEBP')
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValueError('The file is not a supported image.')
        name = secrets.token_hex(16) + '.webp'
        (Path(app.config['UPLOADS']) / name).write_bytes(output.getvalue())
        audit('image-upload', name)
        return jsonify(url='/uploads/' + name), 201

    @app.get('/uploads/<filename>')
    def uploaded_image(filename):
        if not re.fullmatch(r'[a-f0-9]{32}\.webp', filename):
            return jsonify(error='Image not found.'), 404
        return send_from_directory(app.config['UPLOADS'], filename, mimetype='image/webp', max_age=31536000)

    @app.get('/')
    @app.get('/admin')
    @app.get('/admin/')
    def admin():
        return send_from_directory(ROOT / 'admin', 'index.html')

    @app.get('/admin/<filename>')
    def admin_asset(filename):
        if filename not in {'admin.js', 'admin.css'}:
            return jsonify(error='Not found.'), 404
        return send_from_directory(ROOT / 'admin', filename)

    @app.cli.command('create-admin')
    @click.option('--username', prompt=True)
    @click.option('--name', prompt='Display name')
    @click.password_option(confirmation_prompt=True)
    def bootstrap(username, name, password):
        """Create an administrator, using a hidden password prompt."""
        username = username.lower().strip()
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{2,49}', username):
            raise click.ClickException('Use a username of 3–50 lowercase letters, numbers, dots, underscores, or hyphens.')
        validated_password(password)
        if not name.strip() or len(name) > 100:
            raise click.ClickException('A display name of at most 100 characters is required.')
        try:
            db().execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)', (username, name.strip(), generate_password_hash(password), 'admin', now()))
        except sqlite3.IntegrityError:
            raise click.ClickException('Username already exists.')
        click.echo('Administrator created. Sign in at /admin.')

    @app.cli.command('import-posts')
    def import_posts():
        """Import repository blog posts once. Existing or deleted posts stay untouched."""
        from backend.migrate import collect_posts
        if db().execute("SELECT 1 FROM audit WHERE action='initial-import'").fetchone():
            click.echo('Import already completed. Existing edits and deletions were preserved.'); return
        source = collect_posts(ROOT.parent)
        db().execute('BEGIN IMMEDIATE')
        try:
            for post in source:
                post = validate_post(post)
                db().execute('INSERT OR IGNORE INTO posts(id,data,status,updated_at) VALUES(?,?,?,?)', (post['id'], json.dumps(post), 'published', now()))
            db().execute("INSERT INTO audit(action,target,at) VALUES('initial-import',?,?)", (str(len(source)), now()))
            db().execute('COMMIT')
        except Exception:
            db().execute('ROLLBACK'); raise
        click.echo(f'Imported {len(source)} source posts. Back up the database before future migrations.')

    @app.cli.command('backup')
    @click.argument('destination', type=click.Path())
    def backup(destination):
        """Create a consistent SQLite backup. Back up the uploads directory separately."""
        target = Path(destination)
        if target.exists():
            raise click.ClickException('Choose a new backup path; existing files are not overwritten.')
        with sqlite3.connect(target) as backup_db:
            db().backup(backup_db)
        click.echo('Database backed up. Also copy the uploads directory.')

    return app
