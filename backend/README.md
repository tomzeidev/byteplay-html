# BytePlay blog CMS

The public website stays on GitHub Pages. The separate Python/Flask service serves the admin panel at `/admin`, stores users and posts in SQLite, and exposes published posts through a read-only public API. The browser signs in on the backend domain, so this design does not need third-party cookies or expose admin credentials to GitHub Pages.

## What is implemented

- Username/password login with hashed passwords, opaque server-side sessions, session rotation, HTTP-only cookies, CSRF protection, same-origin admin writes, and persistent login throttling.
- Admin and editor roles. Both manage posts; only admins create users, change roles, reset passwords, or disable accounts. Disabled accounts and password resets revoke sessions. The last active admin cannot be removed. Users can change their own password. There is no public signup or email recovery; use an admin reset or trusted server access.
- New posts, drafts, publication, editing, unpublishing, deletion, image uploads, server-sanitized previews, categories, dates, authors, descriptions, and cover images. The editor uses reorderable heading, paragraph, image, list, link, and sign-off blocks. Existing legacy articles retain their HTML in an editable imported block. URL slugs stay fixed after creation. Revision checks prevent stale saves and deletes from overwriting another editor's changes.
- Migration of all 18 existing posts (11 JSON and 7 legacy HTML articles), including historical images. The import runs once and does not resurrect deletions. Existing source files remain archived in Git.
- Managed public listing, filters, individual articles, related stories, previous/next navigation, and homepage stories. Public reads require no login. Drafts are excluded. Once the API is connected, API failures show an unavailable message rather than falling back to stale or deleted content.

## Local setup

Run from the repository root. Each cloud task already has an isolated checkout; use that checkout rather than making a worktree.

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
# Defaults store data in backend/data/ (ignored by Git).
.venv/bin/python -m flask --app backend.app:create_app import-posts
.venv/bin/python -m flask --app backend.app:create_app create-admin
# The password is entered through a hidden prompt, never as a CLI argument.
CMS_COOKIE_SECURE=false .venv/bin/python -m flask --app backend.app:create_app run --host 127.0.0.1 --port 8095
```

Open `/admin` on the backend for login. The first admin has no default password. In a separate terminal serve the existing public site using its extensionless-page helper, or use `python3 -m http.server 8096` and explicit `.html` URLs. For local public integration, temporarily set `apiBase` in `cms-config.js` to `http://127.0.0.1:8095`; restore it before committing. Never set `CMS_COOKIE_SECURE=false` on a public deployment.

The admin preview resolves historical images against `CMS_SITE_URL` (default `https://tomzeidev.github.io/byteplay-html/`). Uploaded images are served by the CMS. Image uploads are PNG, JPEG, or WebP, limited to 8 MB and 20 megapixels, decoded and re-encoded as WebP with generated filenames. Uploads not referenced by a saved post are retained; removing a post does not delete its image files.

## Deployment

Deploy the separate backend to a host with HTTPS and a persistent disk. Build from the repository root:

```bash
docker build -f backend/Dockerfile -t byteplay-cms .
docker volume create byteplay-cms-data
# Initialize disk ownership once, before starting the non-root service.
docker run --rm --user root --mount source=byteplay-cms-data,target=/data \
  byteplay-cms chown -R cms:cms /data
docker run -d --name byteplay-cms -p 127.0.0.1:8095:8080 \
  --mount source=byteplay-cms-data,target=/data byteplay-cms
docker exec byteplay-cms python -m flask --app backend.app:create_app import-posts
docker exec -it byteplay-cms python -m flask --app backend.app:create_app create-admin
```

Terminate HTTPS at the host's reverse proxy and forward to port 8080. Set `CMS_TRUST_PROXY=1` only behind one trusted proxy that overwrites forwarding headers and is the only route to the app. The container runs Gunicorn with two workers as a non-root user. Configure `CMS_DATABASE`, `CMS_UPLOADS`, and `CMS_SITE_URL` if you use different disk paths or a different public website URL. Environment variables in `backend/.env.example` are documentation; the application does not automatically source that file.

SQLite requires one machine with a local persistent volume. Do not scale this service across replicas with independent disks. A future multi-instance deployment needs a shared database and object storage. Back up the database and uploads outside the host; keeping data only on the runtime filesystem will lose it on redeployment.

### Optional Fly.io configuration

`fly.cms.toml` is a separate template and does not replace the existing static site's configuration. Choose a new unique app name and replace its placeholder. Creating a new app/volume uses your hosting account and may incur charges.

1. Create the separate Fly app and a `cms_data` persistent volume in `syd`.
2. Deploy with `fly deploy --config fly.cms.toml --ha=false`. Keep exactly one machine because the database is on its attached volume.
3. If volume permissions prevent startup, initialize `/data` ownership to UID 10001 using the provider's volume maintenance procedure before retrying. Do not run the public service as root.
4. Run the import and interactive `create-admin` command inside that machine via `fly ssh console --config fly.cms.toml`.
5. Confirm HTTPS `/api/health` is healthy, `/api/public/posts` returns 18 migrated published records, and sign-in at `/admin` works. Backups need to include both SQLite and uploads.

No Fly app was created or deployed by this implementation.

### Connect Pages after backend validation

In `cms-config.js`, set only the public backend origin:

```js
window.BYTEPLAY_CMS = { apiBase: 'https://your-cms-host.example' };
```

Commit and push that setting after the backend is deployed and verified. It contains no credentials. The footer's Studio login link then leads to the backend. Public cross-origin requests use `credentials: 'omit'`; only published content routes allow CORS. Admin endpoints accept authenticated same-origin requests only. With `apiBase` empty, the live static website keeps working exactly as before.

Publishing, editing, and deleting managed posts takes effect through the API and does not require a Git commit or a Pages rebuild. Existing raw JSON and legacy files are retained as historical repository assets, so removing imported content from the CMS is not an erasure of archived source files. Old HTML article links redirect to the managed article when the CMS is configured.

## Tests and maintenance

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -m flask --app backend.app:create_app backup /secure-backups/cms-YYYY-MM-DD.sqlite3
```

`backup` creates a consistent SQLite snapshot and refuses to overwrite existing files. Copy the upload directory separately and verify restoration. The audit table records post/user/login changes without passwords. Sessions expire after 12 hours. A password change or administrative reset invalidates other sessions. Recover a lost final admin account through trusted server access using `create-admin` to add another admin; passwords are never recoverable in plaintext.

The container can also be built offline in environments where Docker build containers cannot reach PyPI. Download wheels with TLS verification in the host first, then use the optional build argument:

```bash
.venv/bin/pip download --dest backend/wheels -r backend/requirements.txt
docker build --build-arg CMS_OFFLINE=true -f backend/Dockerfile -t byteplay-cms .
```

Wheels are ignored by Git. Production online builds use the same pinned dependencies. Keep dependencies patched and run the existing permission and migration tests when upgrading.
