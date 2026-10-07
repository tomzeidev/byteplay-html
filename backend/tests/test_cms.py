import io
import json
import sqlite3
from pathlib import Path

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash
from backend.app import create_app
from backend.migrate import collect_posts


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.sqlite3'), 'UPLOADS': str(tmp_path / 'uploads'), 'COOKIE_SECURE': False})
    with sqlite3.connect(app.config['DATABASE']) as db:
        for name, role in [('owner','admin'),('writer','editor')]:
            db.execute('INSERT INTO users(username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?)', (name,name.title(),generate_password_hash('test password 123'),role,'2026-10-07'))
    return app


def login(client, username='owner'):
    csrf = client.get('/api/session').json['csrf']
    response = client.post('/api/login', json={'username': username, 'password': 'test password 123'}, headers={'X-CSRF-Token': csrf})
    assert response.status_code == 200
    return {'X-CSRF-Token': response.json['csrf']}


def post(**kwargs):
    return {'id':'test-update','title':'A new world','excerpt':'Updates','date':'2026-10-07','category':'fertilia','author':'Studio','status':'draft','thumb':'img/update-10.PNG','content':[{'type':'p','html':'Hello <strong>world</strong>.'}],**kwargs}


def test_unauthenticated_cannot_read_or_write_private(app):
    c=app.test_client()
    for path in ['/api/posts','/api/users','/api/posts/test-update']:
        assert c.get(path).status_code==401
    headers={'X-CSRF-Token': c.get('/api/session').json['csrf']}
    assert c.post('/api/posts',json=post(),headers=headers).status_code==401
    assert c.get('/admin/app.py').status_code==404
    assert c.get('/backend/data/cms.sqlite3').status_code==404


def test_csrf_origin_and_session_rotation(app):
    c=app.test_client();first=c.get('/api/session').json['csrf']
    assert c.post('/api/login',json={'username':'owner','password':'test password 123'}).status_code==403
    assert c.post('/api/login',json={'username':'owner','password':'test password 123'},headers={'X-CSRF-Token':first,'Origin':'https://evil.example'}).status_code==403
    headers=login(c)
    assert headers['X-CSRF-Token']!=first
    assert c.post('/api/posts',json=post(),headers={'X-CSRF-Token':first}).status_code==403
    assert c.post('/api/logout',headers=headers).status_code==200
    assert c.get('/api/posts').status_code==401


def test_editor_posts_but_not_users(app):
    c=app.test_client();headers=login(c,'writer')
    assert c.post('/api/posts',json=post(),headers=headers).status_code==201
    assert c.get('/api/users').status_code==403
    assert c.post('/api/users',json={'username':'x'},headers=headers).status_code==403
    assert c.patch('/api/users/1',json={'active':False},headers=headers).status_code==403


def test_draft_publish_modify_delete_and_persistence(app):
    c=app.test_client();h=login(c)
    saved=c.post('/api/posts',json=post(),headers=h).json['post']
    assert c.get('/api/public/posts').json['posts']==[]
    assert c.get('/api/public/posts/test-update').status_code==404
    saved.update(status='published',title='Published update')
    saved=c.put('/api/posts/test-update',json=saved,headers=h).json['post']
    assert c.get('/api/public/posts/test-update').json['title']=='Published update'
    assert c.get('/api/public/posts').json['posts'][0]['title']=='Published update'
    restarted=create_app({**app.config,'TESTING':True})
    assert restarted.test_client().get('/api/public/posts/test-update').json['title']=='Published update'
    saved.update(status='draft')
    saved=c.put('/api/posts/test-update',json=saved,headers=h).json['post']
    assert c.get('/api/public/posts/test-update').status_code==404
    assert c.delete('/api/posts/test-update',json={'revision':saved['revision']},headers=h).status_code==200
    assert c.get('/api/posts/test-update').status_code==404


def test_stale_edits_and_deletes_are_rejected(app):
    c=app.test_client();h=login(c);saved=c.post('/api/posts',json=post(),headers=h).json['post']
    assert c.put('/api/posts/test-update',json={**saved,'title':'First edit'},headers=h).status_code==200
    assert c.put('/api/posts/test-update',json={**saved,'title':'Stale edit'},headers=h).status_code==409
    assert c.delete('/api/posts/test-update',json={'revision':saved['revision']},headers=h).status_code==409
    assert c.get('/api/posts/test-update').json['title']=='First edit'


def test_duplicate_and_immutable_slug(app):
    c=app.test_client();h=login(c);saved=c.post('/api/posts',json=post(),headers=h).json['post']
    assert c.post('/api/posts',json=post(),headers=h).status_code==409
    assert c.put('/api/posts/test-update',json={**saved,'id':'changed-url'},headers=h).status_code==400


@pytest.mark.parametrize('bad',[
    {'id':'../secret'},{'category':'unknown'},{'date':'tomorrow'},{'status':'hidden'},
    {'content':[{'type':'script','text':'bad'}]},{'status':'published','content':[]},
    {'thumb':'javascript:alert(1)'},{'thumb':'//evil.example/image'},
    {'content':[{'type':'button','text':'click','href':'data:text/html,bad'}]},
])
def test_invalid_input(app,bad):
    c=app.test_client();h=login(c)
    assert c.post('/api/posts',json=post(**bad),headers=h).status_code==400


def test_html_is_sanitized_and_preview_does_not_save(app):
    c=app.test_client();h=login(c)
    data=post(content=[{'type':'p','html':'<script>alert(1)</script><strong onclick="bad()">OK</strong><a href="javascript:bad()">link</a><img src="https://safe.example/p.png" onerror="bad()">'}])
    preview=c.post('/api/preview',json=data,headers=h).json['post']['content'][0]['html']
    assert '<script' not in preview and 'onclick' not in preview and 'javascript:' not in preview and 'onerror' not in preview
    assert '<strong>OK</strong>' in preview
    assert c.get('/api/posts').json['posts']==[]


def test_user_lifecycle_revokes_sessions_and_last_admin_protected(app):
    owner=app.test_client();h=login(owner)
    writer=app.test_client();wh=login(writer,'writer')
    assert owner.patch('/api/users/1',json={'active':False},headers=h).status_code==400
    assert owner.patch('/api/users/1',json={'role':'editor'},headers=h).status_code==400
    assert owner.patch('/api/users/2',json={'active':False},headers=h).status_code==200
    assert writer.get('/api/posts').status_code==401
    assert owner.patch('/api/users/2',json={'active':True,'password':'reset password 456'},headers=h).status_code==200
    token=writer.get('/api/session').json['csrf']
    assert writer.post('/api/login',json={'username':'writer','password':'test password 123'},headers={'X-CSRF-Token':token}).status_code==401
    assert writer.post('/api/login',json={'username':'writer','password':'reset password 456'},headers={'X-CSRF-Token':token}).status_code==200
    assert owner.post('/api/users',json={'username':'newuser','display_name':'New','role':'editor','password':'a sufficiently long password'},headers=h).status_code==201
    assert owner.post('/api/users',json={'username':'newuser','display_name':'New','role':'editor','password':'a sufficiently long password'},headers=h).status_code==409


def test_password_change_invalidates_other_sessions(app):
    a=app.test_client();b=app.test_client();h=login(a);login(b)
    assert a.post('/api/password',json={'current_password':'wrong','password':'another good password'},headers=h).status_code==400
    result=a.post('/api/password',json={'current_password':'test password 123','password':'another good password'},headers=h)
    assert result.status_code==200
    assert a.get('/api/posts').status_code==200
    assert b.get('/api/posts').status_code==401


def test_login_rate_limit(app):
    c=app.test_client();csrf=c.get('/api/session').json['csrf']
    for _ in range(10):
        assert c.post('/api/login',json={'username':'owner','password':'wrong'},headers={'X-CSRF-Token':csrf}).status_code==401
    assert c.post('/api/login',json={'username':'owner','password':'test password 123'},headers={'X-CSRF-Token':csrf}).status_code==429


def test_image_upload_and_public_url(app):
    c=app.test_client();h=login(c);image=io.BytesIO();Image.new('RGB',(20,20)).save(image,format='PNG');image.seek(0)
    upload=c.post('/api/uploads',data={'image':(image,'file.png')},headers=h)
    assert upload.status_code==201
    url=upload.json['url'];assert c.get(url).content_type=='image/webp'
    saved=c.post('/api/posts',json=post(status='published',thumb=url,content=[{'type':'img','src':url,'alt':'Test'}]),headers=h)
    assert saved.status_code==201
    public=c.get('/api/public/posts/test-update').json
    assert public['thumb'].startswith('http://localhost/uploads/')
    assert public['content'][0]['src']==public['thumb']
    assert c.post('/api/uploads',data={'image':(io.BytesIO(b'<svg onload="bad()">'),'evil.svg')},headers=h).status_code==400


def test_public_cors_without_private_cors_and_cookie_flags(tmp_path):
    app=create_app({'TESTING':True,'DATABASE':str(tmp_path/'secure.sqlite3'),'UPLOADS':str(tmp_path/'uploads')})
    c=app.test_client();response=c.get('/api/session')
    cookie=response.headers['Set-Cookie'];assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=Strict' in cookie
    assert 'Access-Control-Allow-Origin' not in response.headers
    assert c.get('/api/public/posts').headers['Access-Control-Allow-Origin']=='*'
    assert "frame-ancestors 'none'" in c.get('/admin').headers['Content-Security-Policy']


def test_migration_all_posts_and_repeatability(app):
    source=collect_posts(Path(__file__).resolve().parents[2]);assert len(source)==18
    assert len({post['id'] for post in source})==18
    assert all(post['content'] for post in source)
    runner=app.test_cli_runner();result=runner.invoke(args=['import-posts']);assert result.exit_code==0,result.output
    c=app.test_client();assert len(c.get('/api/public/posts').json['posts'])==18
    h=login(c);saved=c.get('/api/posts/fertilia-update-10').json
    assert c.delete('/api/posts/fertilia-update-10',json={'revision':saved['revision']},headers=h).status_code==200
    result=runner.invoke(args=['import-posts']);assert result.exit_code==0
    assert len(c.get('/api/public/posts').json['posts'])==17
    assert c.get('/api/public/posts/fertilia-update-10').status_code==404


def test_backup_can_be_restored(app,tmp_path):
    c=app.test_client();h=login(c);c.post('/api/posts',json=post(status='published'),headers=h)
    path=tmp_path/'backup.sqlite3';result=app.test_cli_runner().invoke(args=['backup',str(path)])
    assert result.exit_code==0,result.output
    with sqlite3.connect(path) as db: assert db.execute('SELECT COUNT(*) FROM posts').fetchone()[0]==1
    assert app.test_cli_runner().invoke(args=['backup',str(path)]).exit_code!=0


def test_pages_artifact_excludes_backend_and_databases(tmp_path):
    from backend.prepare_pages import prepare
    destination=prepare(tmp_path/'public')
    assert (destination/'index.html').is_file()
    assert (destination/'cms-config.js').is_file()
    assert (destination/'posts/fertilia-update-10.json').is_file()
    assert not (destination/'backend').exists()
    assert not (destination/'.github').exists()
    assert not (destination/'.env').exists()
    assert not list(destination.rglob('*.sqlite3'))
    with pytest.raises(ValueError): prepare(destination)
