'use strict';
const $ = selector => document.querySelector(selector);
const labels = {fertilia:'Fertilia',cab:'Collect All Blocks',timekits:'TimeKits',announcements:'Announcements'};
const types = {p:'Paragraph',h2:'Heading',img:'Image',fixed:'Bullet list',button:'Button / link',signoff:'Sign-off',html:'Imported article HTML'};
let siteUrl = '';
let csrf = '', user = null, posts = [], editing = null, dirty = false, editingUser = null, deleting = null;
let noticeTimer;
function notice(message, error = false) {
  clearTimeout(noticeTimer); $('#notice').textContent = message; $('#notice').classList.toggle('error', error); $('#notice').hidden = false;
  noticeTimer = setTimeout(() => { $('#notice').hidden = true; }, error ? 12000 : 5000);
}
async function api(path, options = {}) {
  const headers = {'X-CSRF-Token': csrf, ...options.headers};
  if (options.body && !(options.body instanceof FormData)) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(options.body); }
  const response = await fetch('/api/' + path, {...options, headers, credentials:'same-origin'});
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && path !== 'login') { $('#dashboard').hidden = true; $('#login-view').hidden = false; $('#identity').hidden = true; }
    throw new Error(data.error || 'The request failed. Please try again.');
  }
  return data;
}
function on(element, event, action) {
  element.addEventListener(event, async e => {
    if (event === 'submit') e.preventDefault();
    const control = event === 'submit' ? element.querySelector('button[type="submit"], button.primary') : element;
    if (control instanceof HTMLButtonElement) control.disabled = true;
    try { await action(e); } catch (error) { notice(error.message, true); }
    finally { if (control instanceof HTMLButtonElement) control.disabled = false; }
  });
}
function el(tag, text, className) { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (className) element.className = className; return element; }
function button(text, action, className = 'quiet') { const element = el('button', text, className); element.type = 'button'; on(element, 'click', action); return element; }
function canLeave() { return !dirty || window.confirm('Leave without saving your changes?'); }
function showView(view) {
  if (!canLeave()) return false;
  dirty = false;
  ['posts','editor','users','account'].forEach(name => { $('#' + name + '-view').hidden = name !== view; });
  document.querySelectorAll('.tabs button').forEach(tab => tab.classList.toggle('active', tab.dataset.view === view));
  return true;
}
function showDashboard(session) {
  csrf = session.csrf; user = session.user; siteUrl = session.site_url;
  $('#login-view').hidden = true; $('#dashboard').hidden = false; $('#identity').hidden = false;
  $('#current-user').textContent = user.display_name + ' · ' + user.role;
  $('#users-tab').hidden = user.role !== 'admin';
}
async function loadPosts() { posts = (await api('posts')).posts; renderPosts(); }
function renderPosts() {
  const container = $('#post-list'); container.replaceChildren();
  const query = $('#search-posts').value.toLowerCase(); const status = $('#filter-status').value;
  const filtered = posts.filter(post => (!status || post.status === status) && (post.title + ' ' + labels[post.category]).toLowerCase().includes(query));
  if (!filtered.length) container.appendChild(el('p','No posts match. Start a new blog or change the filters.','empty'));
  filtered.forEach(post => {
    const row = el('div',undefined,'list-row'); const copy = el('div'); const meta = el('div',undefined,'list-meta');
    meta.append(el('span',post.status,'badge ' + post.status),el('span',labels[post.category]),el('span',post.date));
    copy.append(meta,el('h2',post.title),el('span','By ' + post.author,'muted'));
    const actions = el('div',undefined,'row-actions');
    actions.append(button('Edit',() => openEditor(post.id)), button('Delete',() => { deleting = post; $('#confirm-title').textContent = 'Delete “' + post.title + '”?'; $('#confirm-dialog').showModal(); },'danger'));
    row.append(copy,actions);container.appendChild(row);
  });
}
function assetUrl(path) { return path.startsWith('/uploads/') ? path : new URL(path, siteUrl).href; }
function slugify(value) { return value.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,100); }
async function openEditor(id = null) {
  if (!canLeave()) return;
  const post = id ? await api('posts/' + encodeURIComponent(id)) : {id:'',title:'',excerpt:'',category:'fertilia',author:user.display_name,date:new Date().toISOString().slice(0,10),thumb:'',status:'draft',content:[]};
  dirty = false; showView('editor'); editing = id ? post : null;
  $('#editor-title').textContent = id ? 'Edit dev blog' : 'New dev blog';
  for (const key of ['title','excerpt','category','author','date','thumb','status']) $('#post-' + key).value = post[key] || '';
  $('#post-slug').value = post.id; $('#post-slug').disabled = Boolean(id); $('#post-slug').dataset.manual = id ? 'true' : '';
  $('#blocks').replaceChildren();post.content.forEach(addBlock);$('#cover-upload').value = '';window.scrollTo(0,0);
}
function addField(block, name, title, value = '', multiline = false) {
  const label = el('label',title);const input = el(multiline ? 'textarea' : 'input');input.dataset.field = name;input.value = value; if (multiline) input.rows = 4;
  label.appendChild(input);block.appendChild(label);return input;
}
function addBlock(data) {
  const block = el('div',undefined,'block');block.dataset.type = data.type;
  const heading = el('div',undefined,'block-heading');const actions = el('div',undefined,'row-actions');
  actions.append(button('↑',() => { if (block.previousElementSibling) block.parentNode.insertBefore(block,block.previousElementSibling);dirty=true; }),button('↓',() => { if (block.nextElementSibling) block.parentNode.insertBefore(block.nextElementSibling,block);dirty=true; }),button('Remove',() => { block.remove();dirty=true; }));
  heading.append(el('strong',types[data.type]),actions);block.appendChild(heading);
  if (['p','html'].includes(data.type)) {
    const input = addField(block,'html',data.type==='html'?'Imported content (safe HTML)':'Paragraph (basic HTML formatting supported)',data.html || '',true);
    if (data.type==='p') {const format = el('div',undefined,'row-actions');for (const [text,tag] of [['Bold','strong'],['Italic','em']]) format.append(button(text,() => {const a=input.selectionStart,b=input.selectionEnd;input.setRangeText('<'+tag+'>'+input.value.slice(a,b)+'</'+tag+'>',a,b,'select');dirty=true;input.focus();}));block.appendChild(format);}
  } else if (data.type==='img') {
    const src=addField(block,'src','Image URL',data.src || '');addField(block,'alt','Image description (accessibility)',data.alt || '');
    const upload=el('input');upload.type='file';upload.accept='image/png,image/jpeg,image/webp';const uploadLabel=el('label','Or upload an image');uploadLabel.appendChild(upload);block.appendChild(uploadLabel);
    on(upload,'change',async()=>{const url=await uploadImage(upload.files[0]);if(url){src.value=url;dirty=true;}});
  } else if(data.type==='fixed') addField(block,'items','One bullet per line',(data.items||[]).join('\n'),true);
  else {addField(block,'text',data.type==='button'?'Button label':'Text',data.text||'',true);if(data.type==='button')addField(block,'href','Link URL',data.href||'');}
  $('#blocks').appendChild(block);
}
function readPost() {
  const post={id:$('#post-slug').value,content:[]};
  for(const key of ['title','excerpt','category','author','date','thumb','status'])post[key]=$('#post-'+key).value;
  for(const block of document.querySelectorAll('#blocks .block')) {
    const data={type:block.dataset.type};block.querySelectorAll('[data-field]').forEach(input=>{data[input.dataset.field]=input.dataset.field==='items'?input.value.split('\n').filter(Boolean):input.value;});post.content.push(data);
  }
  if(editing)post.revision=editing.revision;
  return post;
}
async function uploadImage(file) {
  if(!file)return;
  if(file.size>8*1024*1024)throw Error('Choose an image under 8 MB.');
  const data=new FormData();data.append('image',file);notice('Uploading image…');const result=await api('uploads',{method:'POST',body:data});notice('Image uploaded. Save the post to use it.');return result.url;
}
on($('#login-form'),'submit',async()=>{const data=Object.fromEntries(new FormData($('#login-form')));const session=await api('login',{method:'POST',body:data});$('#login-form').reset();showDashboard(session);showView('posts');await loadPosts();});
on($('#logout'),'click',async()=>{if(!canLeave())return;await api('logout',{method:'POST'});dirty=false;window.location.reload();});
document.querySelectorAll('.tabs button').forEach(tab=>on(tab,'click',async()=>{if(!showView(tab.dataset.view))return;if(tab.dataset.view==='posts')await loadPosts();if(tab.dataset.view==='users')await loadUsers();}));
on($('#new-post'),'click',()=>openEditor());on($('#editor-back'),'click',()=>{showView('posts');});
$('#search-posts').addEventListener('input',renderPosts);$('#filter-status').addEventListener('change',renderPosts);
$('#post-form').addEventListener('input',()=>{dirty=true;});
$('#post-form').addEventListener('change',()=>{dirty=true;});
$('#post-slug').addEventListener('input',()=>{$('#post-slug').dataset.manual='true';});
$('#post-title').addEventListener('input',()=>{if(!editing&&!$('#post-slug').dataset.manual)$('#post-slug').value=slugify($('#post-title').value);});
on($('#add-block'),'click',()=>{addBlock({type:$('#block-type').value});dirty=true;});
on($('#cover-upload'),'change',async()=>{const url=await uploadImage($('#cover-upload').files[0]);if(url){$('#post-thumb').value=url;dirty=true;}});
// Submit remains guarded while the network request is running, including keyboard submissions.
let saving=false;
on($('#post-form'),'submit',async()=>{
  if(saving)return;saving=true;$('#save-post').disabled=true;
  try{const result=await api(editing?'posts/'+encodeURIComponent(editing.id):'posts',{method:editing?'PUT':'POST',body:readPost()});editing=result.post;dirty=false;$('#post-slug').disabled=true;$('#editor-title').textContent='Edit dev blog';notice(editing.status==='published'?'Published. The public blog now uses this version.':'Draft saved.');await loadPosts();}finally{saving=false;$('#save-post').disabled=false;}
});
on($('#confirm-delete'),'click',async()=>{await api('posts/'+encodeURIComponent(deleting.id),{method:'DELETE',body:{revision:deleting.revision}});$('#confirm-dialog').close();await loadPosts();notice('Post deleted.');});
$('#confirm-cancel').addEventListener('click',()=>$('#confirm-dialog').close());
on($('#preview-button'),'click',async()=>{
  const data=readPost();data.status='draft';const {post}=await api('preview',{method:'POST',body:data});const article=$('#preview-content');article.replaceChildren(el('h1',post.title),el('p',post.author+' · '+post.date));
  for(const block of post.content){let element;if(block.type==='h2')element=el('h2',block.text);else if(block.type==='signoff')element=el('p','~ '+block.text);else if(block.type==='img'){element=el('img');element.src=assetUrl(block.src);element.alt=block.alt;}else if(block.type==='button'){element=el('a',block.text,'primary');element.href=block.href;element.target='_blank';element.rel='noopener noreferrer';}else if(block.type==='fixed'){element=el('ul');block.items.forEach(item=>{const li=el('li');li.innerHTML=item;element.appendChild(li);});}else{element=el(block.type==='p'?'p':'div');element.innerHTML=block.html;element.querySelectorAll('img').forEach(image=>image.src=assetUrl(image.getAttribute('src')));}article.appendChild(element);}
  $('#preview-dialog').showModal();
});
$('#close-preview').addEventListener('click',()=>$('#preview-dialog').close());
async function loadUsers(){const {users}=await api('users');$('#user-list').replaceChildren();users.forEach(account=>{const row=el('div',undefined,'list-row');const copy=el('div');copy.append(el('h2',account.display_name),el('span',account.username+' · '+account.role+' · '+(account.active?'Active':'Disabled'),'muted'));row.append(copy,button('Manage',()=>openUser(account)));$('#user-list').appendChild(row);});}
function openUser(account=null){editingUser=account;const form=$('#user-form');form.reset();for(const key of ['username','display_name','role'])if(account)form.elements[key].value=account[key];form.elements.username.disabled=Boolean(account);form.elements.active.value=account?.active?'true':account?'false':'true';form.elements.password.required=!account;$('#user-dialog-title').textContent=account?'Manage user':'Add user';$('#user-password-label').textContent=account?'Reset password (leave blank to keep current)':'Password (12+ characters)';$('#user-active-label').hidden=!account;$('#user-dialog').showModal();}
on($('#new-user'),'click',()=>openUser());$('#close-user').addEventListener('click',()=>$('#user-dialog').close());
on($('#user-form'),'submit',async()=>{const data=Object.fromEntries(new FormData($('#user-form')));data.active=data.active==='true';if(!data.password)delete data.password;await api(editingUser?'users/'+editingUser.id:'users',{method:editingUser?'PATCH':'POST',body:data});$('#user-dialog').close();$('#user-form').reset();await loadUsers();notice('User saved.');});
on($('#password-form'),'submit',async()=>{const data=Object.fromEntries(new FormData($('#password-form')));if(data.password!==data.confirmation)throw Error('The new passwords do not match.');const session=await api('password',{method:'POST',body:data});csrf=session.csrf;$('#password-form').reset();notice('Password updated. Other sessions were signed out.');});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
(async()=>{try{const session=await api('session');csrf=session.csrf;if(session.user){showDashboard(session);await loadPosts();}}catch(error){notice('Could not connect to the studio. Reload to try again.',true);}})();
