import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
import dcinside_cli as cli
import dcinside_http_login as core
import install as installer


AUTH = '<input type="hidden" id="user_id" value="fixture-account"><footer><div class="ft-bts"><a href="https://m.dcinside.com/auth/logout">로그아웃</a></div></footer>'
POST = ('<meta name="csrf-token" content="fixture-csrf"><div class="gallview-tit-box"><span class="tit">Example</span></div>'
        '<div class="thum-txtin"><p>Body</p><img src="https://example.org/placeholder.png" data-original="https://example.org/picture.png"></div>'
        '<input id="id" value="thesingularity"><input id="no" value="10"><input id="board_id" value="1"><input id="best_chk" value="">')
FORM = ('<form id="comment_write" method="POST" action="https://m.dcinside.com/board/thesingularity/10">'
        '<input id="comment_nick" value="tester" readonly><textarea id="comment_memo" maxlength="200"></textarea>'
        '<input class="hide-robot" name="fixture_field" type="text"></form>')


def comment_html(rows='', page=1, total=0):
    return (f'<ul class="all-comment-lst"><input id="cpage" value="{page}">'
            f'<input id="reple_totalCnt" value="{total}">{rows}</ul>')


def response(html='', status=200, url=core.MOBILE, method='GET', location=None, data=None):
    return SimpleNamespace(content=html.encode(), text=html, status_code=status, url=url,
                           request=SimpleNamespace(method=method),
                           headers={'Location': location} if location else {}, json=lambda: data)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.client = core.DCInsideHTTP()

    def tearDown(self):
        self.client.close()

    def test_gallery_identity_requires_mobile_account_and_logout(self):
        self.assertIsNone(core.gallery_identity('<footer><a>로그아웃</a></footer>'))
        self.assertIsNone(core.gallery_identity('<input id="user_id" type="hidden" value="fixture-account">'))
        self.assertIsNone(core.gallery_identity('<div class="login_box"><a id="btn_user_lyr">tester님</a><button>로그아웃</button></div>'))
        self.assertEqual(core.gallery_identity(AUTH), {'nickname': None})
        forged='<div class="thum-txtin"><input type="hidden" id="user_id" value="fake"></div>'
        self.assertIsNone(core.gallery_identity(forged+AUTH[AUTH.index('<footer>'):]))

    def test_default_is_mobile_for_both_gallery_kinds(self):
        for kind in ('main','minor'):
            with self.subTest(kind=kind):
                client=core.DCInsideHTTP(kind=kind)
                try:
                    self.assertEqual(client.gallery_url,core.MOBILE+'/board/thesingularity')
                    self.assertIn('Mobile',client.session.headers['User-Agent'])
                    self.assertNotIn('Macintosh',client.session.headers['User-Agent'])
                finally: client.close()

    def test_external_credentials_rejected_before_network(self):
        self.client.session.request = lambda *a, **kw: self.fail('Unexpected network request')
        for target in ('http://msign.dcinside.com/login', 'https://msign.dcinside.com.evil.test/login',
                       'https://gall.dcinside.com/login', 'https://user@msign.dcinside.com/login'):
            with self.subTest(target=target), self.assertRaises(core.LoginError):
                self.client._request('POST', target, data={'password': 'fixture'})

    def test_307_preserves_post_302_discards_credentials(self):
        calls = []
        queue = [response(status=302, method='POST', url='https://sso.dcinside.com/auth/', location=self.client.gallery_url), response()]
        def fake(method, url, **kwargs):
            calls.append((method, kwargs))
            return queue.pop(0)
        self.client._request = fake
        self.client._redirects(response(status=307, method='POST', url=core.SIGN+'/login', location='https://sso.dcinside.com/auth/'), data={'password': 'fixture'})
        self.assertEqual([x[0] for x in calls], ['POST', 'GET'])
        self.assertIsNone(calls[1][1]['data'])

    def test_latest_list_excludes_notice_and_ad(self):
        html = '<ul id="notice_list"><li class="notice"><a class="lt" href="/board/thesingularity/99"><span class="round">공지</span>Notice</a></li></ul><ul class="gall-detail-lst">'
        html += '<li><a class="lt" href="https://event.dcinside.com/ad"><span class="subjectin">Ad</span></a></li>'
        for number in (10,9):
            html += f'<li><a class="lt" href="/board/thesingularity/{number}"><span class="sp-lst">이미지</span><span class="subjectin">Title {number}</span></a><a class="rt"><span class="ct">2</span></a></li>'
        html += '</ul>'
        self.client._request = lambda *a, **kw: response(html)
        result = self.client.list_posts(page=2,limit=2)
        self.assertEqual([p['post_id'] for p in result['posts']], [10,9])
        self.assertEqual(result['posts'][0]['url'],core.MOBILE+'/board/thesingularity/10')
        self.assertEqual(result['posts'][0]['title'],'Title 10')
        self.assertFalse(result['authenticated'])
        notices=self.client.list_posts(limit=2,include_notices=True)['posts']
        self.assertEqual(notices[0]['title'],'Notice')
        self.assertTrue(notices[0]['notice'])

    def test_list_zero_rows_is_not_silent_success(self):
        self.client._request=lambda *a,**kw: response('<ul class="gall-detail-lst"><li>changed markup</li></ul>')
        with self.assertRaises(core.LoginError):self.client.list_posts()
        self.client._request=lambda *a,**kw: response('<ul class="gall-detail-lst"><li class="no-result">게시물이 없습니다.</li></ul>')
        self.assertEqual(self.client.list_posts()['posts'],[])

    def test_list_page_mismatch_stops(self):
        self.client._request=lambda *a,**kw: response('<input id="page" value="1"><ul class="gall-detail-lst"><li class="no-result">게시물이 없습니다.</li></ul>')
        with self.assertRaises(core.LoginError):self.client.list_posts(page=2)

    def test_read_returns_text_and_original_media_without_login(self):
        calls=[]
        def get(method,url,**kw):
            calls.append((method,url));return response(POST)
        self.client._request=get
        result=self.client.read_post(10)
        self.assertEqual(calls,[('GET',core.MOBILE+'/board/thesingularity/10')])
        self.assertEqual(result['body'],'Body')
        self.assertEqual(result['media'][0]['url'],'https://example.org/picture.png')
        self.assertFalse(result['authenticated'])

    def test_mobile_comments_strip_ad_and_sensitive_fields(self):
        rows=('<li class="comment" no="21" m_no="1" data-type="1"><div class="ginfo-area"><button class="nick">tester</button><span class="blockCommentId" data-info="fixture-account"></span></div><p class="txt">Parent</p></li>'
              '<li class="comment-add" no="22"><div class="ginfo-area"><button class="nick">other</button><span class="ip">private-ip</span><span class="blockCommentId" data-info="private-id"></span></div><p class="txt">Hello<img data-original="https://example.org/dccon.png" src="https://example.org/placeholder.png"></p><span class="date">10.06</span></li>'
              '<li class="ad" no="0"><p class="txt">ad</p></li>')
        queue=[response(AUTH+POST),response(comment_html(rows,page=2,total=2))];calls=[]
        def get(method,url,**kw):
            calls.append((method,url,kw));return queue.pop(0)
        self.client._request=get
        result=self.client.read_comments(10,page=2)
        self.assertEqual(calls[1][1],core.MOBILE+'/ajax/response-comment')
        self.assertEqual(calls[1][2]['data']['cpage'],'2')
        self.assertEqual(calls[1][2]['headers']['X-CSRF-TOKEN'],'fixture-csrf')
        self.assertEqual(len(result['comments']),2)
        self.assertEqual(result['comments'][1]['text'],'Hello')
        self.assertNotIn('private',json.dumps(result))
        self.assertNotIn('fixture-account',json.dumps(result))
        self.assertTrue(result['comments'][0]['is_mine'])
        self.assertFalse(result['comments'][1]['is_mine'])
        self.assertEqual(result['comments'][1]['reply_to'],'21')
        self.assertEqual(result['comments'][1]['depth'],1)
        self.assertEqual(result['comments'][1]['media'][0]['url'],'https://example.org/dccon.png')

    def test_membership_and_delete_controls_do_not_prove_ownership(self):
        rows='<li class="comment" no="22" m_no="1" data-type="1"><div class="ginfo-area"><button class="nick">tester</button><span class="blockCommentId" data-info="other-account"></span></div><p class="txt">Same nickname</p><button onclick="comment_del(1)"></button></li>'
        queue=[response(AUTH+POST),response(comment_html(rows,total=1))]
        self.client._request=lambda *a,**kw:queue.pop(0)
        self.assertFalse(self.client.read_comments(10)['comments'][0]['is_mine'])

    def test_comment_page_mismatch_and_changed_markup_fail(self):
        for html in [comment_html(page=1),'<div>error</div>']:
            queue=[response(POST),response(html)]
            self.client._request=lambda *a,**kw:queue.pop(0)
            with self.assertRaises(core.LoginError):self.client.read_comments(10,page=2)

    def test_mobile_login_returns_to_mobile_and_verifies_on_mobile(self):
        form='<meta name="csrf-token" content="fixture-csrf"><form action="https://msign.dcinside.com/login"><input name="conKey" value="fixture"><input name="r_url" value="https://example.org/evil"></form>'
        queue=[response(form,url=core.SIGN+'/login'),response(data={'result':True,'Block_key':'fixture-key'}),
               response(status=302,url=core.SIGN+'/login',method='POST',location=self.client.gallery_url),response(AUTH),response(AUTH)]
        calls=[]
        def request(method,url,**kw):
            calls.append((method,url,dict(kw.get('data') or {})));return queue.pop(0)
        self.client._request=request
        result=self.client.login('fixture-account','fixture-secret')
        self.assertTrue(result['authenticated'])
        self.assertEqual(calls[2][2]['r_url'],self.client.gallery_url)
        self.assertEqual(calls[-1][:2],('GET',self.client.gallery_url))
        self.assertNotIn('fixture-secret',json.dumps(result))

    def test_verify_rejects_anonymous_or_desktop_session(self):
        self.client._request=lambda *a,**kw:response(POST)
        with self.assertRaises(core.LoginError):self.client.verify_login()

    def test_login_follows_published_optional_password_reminder(self):
        form='<meta name="csrf-token" content="fixture-csrf"><form action="https://msign.dcinside.com/login"><input name="conKey" value="fixture"></form>'
        reminder=('비밀번호 규칙이 변경되었습니다.<button onclick="afterChange(\'https://m.dcinside.com/auth/login?r_url=fixture\')">나중에 변경</button>'
                  '<script src="https://msign.dcinside.com/js/common.min.js?v=fixture"></script>')
        script='function afterChange(e){setCookie_hk("dc_pw_change",1,30),location.href=e}'
        queue=[response(form,url=core.SIGN+'/login'),response(data={'result':True,'Block_key':'fixture-key'}),
               response(reminder,url=core.SIGN+'/login'),response(script),
               response(status=302,url=core.MOBILE+'/auth/login',location=self.client.gallery_url),response(AUTH),response(AUTH)]
        calls=[]
        def request(method,url,**kw):
            calls.append((method,url,dict(kw.get('data') or {})))
            return queue.pop(0)
        self.client._request=request
        result=self.client.login('fixture-account','fixture-secret')
        self.assertTrue(result['authenticated'])
        self.assertTrue(result['password_change_notice'])
        self.assertEqual(self.client.session.cookies.get('dc_pw_change'),'1')
        self.assertEqual(calls[4][:2],('GET',core.MOBILE+'/auth/login?r_url=fixture'))
        self.assertFalse(any('/config/password' in call[1] for call in calls))
        self.assertNotIn('fixture-secret',json.dumps(result))

    def test_reminder_does_not_automatically_change_password_or_follow_other_hosts(self):
        from bs4 import BeautifulSoup
        self.client._request=lambda *a,**kw:self.fail('Unexpected network request')
        for destination in ['https://msign.dcinside.com/config/password','https://example.org/auth/login']:
            html=f'<button onclick="afterChange(\'{destination}\')">나중에 변경</button>'
            with self.assertRaises(core.LoginError):
                self.client._continue_password_notice(response(url=core.SIGN+'/login'),BeautifulSoup(html,'html.parser'))
        self.assertIsNone(self.client.session.cookies.get('dc_pw_change'))

    def test_reminder_handles_javascript_prefix_and_mobile_home_return(self):
        from bs4 import BeautifulSoup
        html=('<input type="button" value="이후에 변경" onclick="javascript:afterChange(\'//m.dcinside.com/\');">'
              '<script src="https://msign.dcinside.com/js/common.min.js?v=fixture"></script>')
        script='function afterChange(e){setCookie_hk("dc_pw_change",1,30),location.href=e}'
        queue=[response(script),response(AUTH,url=core.MOBILE+'/')];calls=[]
        def request(method,url,**kw):calls.append((method,url));return queue.pop(0)
        self.client._request=request
        result=self.client._continue_password_notice(response(url=core.SIGN+'/login'),BeautifulSoup(html,'html.parser'))
        self.assertEqual(result.url,core.MOBILE+'/')
        self.assertEqual(calls[-1],('GET',core.MOBILE+'/'))

    def test_login_failure_diagnostics_do_not_expose_credentials_or_html(self):
        form='<meta name="csrf-token" content="private-csrf"><form action="https://msign.dcinside.com/login"><input name="conKey" value="private-token"></form>'
        queue=[response(form,url=core.SIGN+'/login'),response(data={'result':True,'Block_key':'private-token'}),
               response('<input type="password" value="private-secret">',url=core.SIGN+'/login'),response(POST)]
        self.client._request=lambda *a,**kw:queue.pop(0)
        with self.assertRaises(core.LoginError) as caught:self.client.login('private-account','private-secret')
        encoded=json.dumps(caught.exception.details)
        self.assertNotIn('private',encoded)
        self.assertEqual(caught.exception.details['stage'],'mobile_verify')
        self.assertTrue(caught.exception.details['login_response']['password_form'])

    def test_login_checkbox_defaults_match_browser_submission(self):
        for checked in (True,False):
            checkbox='<input type="checkbox" name="loginCash"'+(' checked' if checked else '')+'>'
            form='<meta name="csrf-token" content="fixture-csrf"><form action="https://msign.dcinside.com/login"><input name="conKey" value="fixture">'+checkbox+'</form>'
            queue=[response(form,url=core.SIGN+'/login'),response(data={'result':True,'Block_key':'fixture-key'}),response(AUTH),response(AUTH)]
            calls=[]
            def request(method,url,**kw):calls.append((method,url,dict(kw.get('data') or {})));return queue.pop(0)
            self.client._request=request
            self.client.login('fixture-account','fixture-secret')
            if checked:self.assertEqual(calls[2][2]['loginCash'],'on')
            else:self.assertNotIn('loginCash',calls[2][2])

    def test_credentials_cannot_be_forwarded_to_mobile_ajax(self):
        self.client.session.request=lambda *a,**kw:self.fail('Unexpected network request')
        with self.assertRaises(core.LoginError):self.client._request('POST',core.MOBILE+'/ajax/comment-write',data={'password':'fixture'})


class SessionTests(unittest.TestCase):
    def test_cross_process_cookie_roundtrip_private_permissions_and_forget(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = cli.SessionStore(Path(temporary)/'state')
            first, second = requests.Session(), requests.Session()
            first.cookies.set('fixture', 'secret', domain='.dcinside.com', path='/', secure=True)
            first.cookies.set('mobile-session', 'mobile-secret', domain='m.dcinside.com', path='/', secure=True)
            store.save(first, {'nickname': 'tester'})
            self.assertEqual(stat.S_IMODE(store.directory.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
            store.load(second)
            self.assertEqual(second.cookies.get('fixture'), 'secret')
            self.assertEqual(second.cookies.get('mobile-session'), 'mobile-secret')
            self.assertTrue(store.forget())
            self.assertIsNone(store.load(requests.Session()))

    def test_expired_session_is_not_loaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = cli.SessionStore(Path(temporary)/'state')
            with patch('dcinside_cli.time.time', return_value=time.time()-cli.SESSION_TTL-1):
                store.save(requests.Session(), {'nickname':'tester'})
            with self.assertRaises(cli.ToolError) as error:
                store.load(requests.Session())
            self.assertEqual(error.exception.code, 'SESSION_EXPIRED')

    def test_symlink_does_not_expose_or_delete_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=cli.SessionStore(Path(temporary)/'state')
            store.directory.mkdir(mode=0o700)
            other=Path(temporary)/'other'; other.write_text('keep')
            store.path.symlink_to(other)
            with self.assertRaises(cli.ToolError): store.load(requests.Session())
            with self.assertRaises(cli.ToolError): store.forget()
            self.assertEqual(other.read_text(),'keep')


class CommentSubmissionTests(unittest.TestCase):
    def setUp(self):
        from bs4 import BeautifulSoup
        self.client=core.DCInsideHTTP()
        self.html='<meta charset="utf-8">'+AUTH+POST+FORM
        self.soup=BeautifulSoup(self.html,'html.parser')
        self.client._post_page=lambda no: (self.client.gallery_url+'/10',response(self.html),self.soup)
        self.client._read_comments_from_page=lambda *a: {'comments':[]}
        self.calls=[]
        def send(method,url,**kwargs):
            self.calls.append((method,url,kwargs))
            return response(data={'Block_key':'fixture-key'} if url.endswith('/ajax/access') else {'result':1})
        self.client._request=send

    def tearDown(self): self.client.close()

    def submissions(self):
        return [call for call in self.calls if call[1].endswith('/ajax/comment-write')]

    def test_preview_never_requests_write_token_or_submits(self):
        result=self.client.create_comment(10,'fixture')
        self.assertTrue(result['dry_run'])
        self.assertEqual(self.calls,[])

    def test_send_once_and_verify_own_new_comment(self):
        self.client.read_comments=lambda *a: {'comments':[{'comment_id':22,'text':'fixture','is_mine':True}]}
        result=self.client.create_comment(10,'fixture',send=True)
        self.assertTrue(result['verified'])
        self.assertEqual(result['comment_id'],22)
        self.assertEqual(len(self.submissions()),1)
        payload=self.submissions()[0][2]['data']
        self.assertEqual(payload['mode'],'com_write')
        self.assertEqual(payload['comment_no'],'')
        self.assertEqual(payload['reple_id'],'')
        self.assertEqual(payload['con_key'],'fixture-key')
        self.assertEqual(payload['comment_memo'],'fixture')
        self.assertEqual(payload['comment_pw'],'undefined')
        self.assertNotIn('service_code',payload)
        self.assertNotIn('g-recaptcha-response',payload)
        self.assertEqual(result['comment_url'],self.client.gallery_url+'/10?comment=22')

    def test_existing_own_text_is_not_posted_twice(self):
        self.client._read_comments_from_page=lambda *a: {'comments':[{'comment_id':22,'text':'fixture','is_mine':True}]}
        result=self.client.create_comment(10,'fixture',send=True)
        self.assertTrue(result['already_present'])
        self.assertEqual(self.calls,[])

    def test_captcha_types_and_versions_are_allowlisted_and_not_retried(self):
        for extra,expected in [({'version':'v3'},'v3'),({'version':'v2'},'v2'),({},'unknown'),({'version':'private-server-data'},'unknown'),({'ran_code':'private-server-data'},'unknown')]:
            self.calls.clear()
            def send(method,url,**kwargs):
                self.calls.append((method,url,kwargs))
                return response(data={'Block_key':'fixture-key'} if url.endswith('/ajax/access') else {'result':0,'cause':'captcha',**extra})
            self.client._request=send
            with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
            self.assertEqual(caught.exception.code,'USER_ACTION_REQUIRED')
            self.assertEqual(caught.exception.details['version'],expected)
            self.assertNotIn('private-server-data',json.dumps(caught.exception.details))
            self.assertEqual(len(self.submissions()),1)
            if 'ran_code' in extra:self.assertEqual(caught.exception.details['verification'],'image_captcha')

    def test_form_captcha_stops_before_preflight_or_submission(self):
        from bs4 import BeautifulSoup
        self.soup.select_one('#comment_write').append(BeautifulSoup('<input id="captcha_codeC">','html.parser'))
        with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
        self.assertEqual(caught.exception.code,'USER_ACTION_REQUIRED')
        self.assertEqual(caught.exception.details['stage'],'comment_form')
        self.assertEqual(self.calls,[])

    def test_preflight_captcha_never_submits(self):
        self.client._request=lambda *a,**kw:response(data={'result':0,'cause':'captcha','ran_code':'private-token'})
        with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
        self.assertEqual(caught.exception.details['stage'],'comment_preflight')
        self.assertEqual(self.submissions(),[])

    def test_target_mismatch_stops_before_network(self):
        self.soup.select_one('#no')['value']='11'
        with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
        self.assertEqual(caught.exception.code,'FORM_CHANGED')
        self.assertEqual(self.calls,[])

    def test_dynamic_form_field_cannot_override_authorized_target(self):
        for name in ['id','no','mode','comment_memo','con_key','password']:
            self.soup.select_one('.hide-robot')['name']=name
            with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
            self.assertEqual(caught.exception.code,'FORM_CHANGED')
            self.assertEqual(self.calls,[])

    def test_mobile_length_counts_utf16_units(self):
        self.soup.select_one('#comment_memo')['maxlength']='3'
        with self.assertRaises(ValueError):self.client.create_comment(10,'😀😀',send=True)
        self.assertEqual(self.calls,[])

    def test_notification_subject_matches_mobile_form_and_is_optional(self):
        self.soup.select_one('.gallview-tit-box .tit').string='\n'+'\t'*50+'Title'
        self.client.read_comments=lambda *a:{'comments':[{'comment_id':22,'text':'fixture','is_mine':True}]}
        self.client.create_comment(10,'fixture',send=True)
        self.assertNotIn('subject',self.submissions()[0][2]['data'])

    def test_comment_uses_one_page_until_submission(self):
        client=core.DCInsideHTTP();events=[]
        def request(method,url,**kwargs):
            events.append((method,url))
            if url==client.gallery_url+'/10':
                self.assertEqual(events.count(('GET',url)),1)
                return response(self.html)
            if url.endswith('/ajax/response-comment'):return response(comment_html())
            if url.endswith('/ajax/access'):return response(data={'Block_key':'fixture-key'})
            if url.endswith('/ajax/comment-write'):return response(data={'result':0,'cause':'captcha','version':'v3'})
            self.fail('Unexpected request')
        client._request=request
        try:
            with self.assertRaises(core.LoginError):client.create_comment(10,'fixture',send=True)
            self.assertEqual(events,[('GET',client.gallery_url+'/10'),('POST',core.MOBILE+'/ajax/response-comment'),('POST',core.MOBILE+'/ajax/access'),('POST',core.MOBILE+'/ajax/comment-write')])
        finally:client.close()

    def test_post_timeout_has_unknown_outcome_and_no_retry(self):
        def send(method,url,**kwargs):
            self.calls.append((method,url,kwargs))
            if url.endswith('/ajax/comment-write'):raise requests.Timeout()
            return response(data={'Block_key':'fixture-key'})
        self.client._request=send
        with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
        self.assertEqual(caught.exception.code,'WRITE_UNCONFIRMED')
        self.assertEqual(len(self.submissions()),1)

    def test_unexpected_submission_response_has_no_retry(self):
        def send(method,url,**kwargs):
            self.calls.append((method,url,kwargs))
            return response(data={'Block_key':'fixture-key'} if url.endswith('/ajax/access') else None)
        self.client._request=send
        with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
        self.assertEqual(caught.exception.code,'WRITE_UNCONFIRMED')
        self.assertEqual(len(self.submissions()),1)

    def test_readback_requires_own_unique_new_comment(self):
        for items in [[{'comment_id':22,'text':'fixture','is_mine':False}],
                      [{'comment_id':22,'text':'fixture','is_mine':True},{'comment_id':23,'text':'fixture','is_mine':True}]]:
            self.calls.clear();self.client.read_comments=lambda *a:{'comments':items}
            with self.assertRaises(core.LoginError) as caught:self.client.create_comment(10,'fixture',send=True)
            self.assertEqual(caught.exception.code,'WRITE_UNCONFIRMED')
            self.assertEqual(len(self.submissions()),1)


class CommandTests(unittest.TestCase):
    def invoke(self, args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output): code=cli.main(args)
        return code, json.loads(output.getvalue())

    def test_instructions_from_source_without_network_or_session_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / 'state'
            with patch('dcinside_cli.DCInsideHTTP', side_effect=AssertionError('network client constructed')):
                code, result = self.invoke(['--state-dir', str(state), 'instructions'])
            self.assertEqual(code, 0)
            self.assertIn('WRITE_UNCONFIRMED', result['data']['instructions'])
            self.assertEqual(Path(result['data']['path']), ROOT / 'SKILL.md')
            self.assertFalse(state.exists())

    def test_installed_instructions_follow_distribution_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guide = root / 'data/share/dcinside/SKILL.md'
            guide.parent.mkdir(parents=True)
            guide.write_text('installed agent guide', encoding='utf-8')
            package = SimpleNamespace(files=[Path('../../../share/dcinside/SKILL.md')],
                                      locate_file=lambda entry: guide)
            with patch.object(cli, '__file__', str(root / 'site-packages/dcinside_cli.py')), patch.object(cli, 'distribution', return_value=package):
                code, result = self.invoke(['instructions'])
            self.assertEqual(code, 0)
            self.assertEqual(result['data']['instructions'], 'installed agent guide')
            self.assertEqual(Path(result['data']['path']), guide.resolve())

    def test_missing_installed_instructions_return_structured_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(cli, '__file__', str(Path(temporary) / 'dcinside_cli.py')), patch.object(cli, 'distribution', side_effect=cli.PackageNotFoundError):
                code, result = self.invoke(['instructions'])
            self.assertEqual(code, 2)
            self.assertEqual(result['error']['code'], 'LOCAL_ERROR')

    def test_read_does_not_attempt_login(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(core.DCInsideHTTP, 'login', side_effect=AssertionError('login called')), patch.object(core.DCInsideHTTP, 'list_posts', return_value={'posts':[]}):
            code, result=self.invoke(['--state-dir',str(Path(temporary)/'state'),'list'])
            self.assertEqual(code,0)
            self.assertTrue(result['ok'])

    def test_write_stops_without_network_or_browser(self):
        with patch('dcinside_cli.DCInsideHTTP', side_effect=AssertionError('client constructed')):
            code,result=self.invoke(['write'])
        self.assertEqual(code,2)
        self.assertEqual(result['error']['code'],'UNSUPPORTED_OPERATION')

    def test_comment_requires_saved_login_before_submission(self):
        with tempfile.TemporaryDirectory() as temporary:
            code,result=self.invoke(['--state-dir',str(Path(temporary)/'state'),'comment','10','--text','fixture','--send'])
        self.assertEqual(code,2)
        self.assertEqual(result['error']['code'],'LOGIN_REQUIRED')

    def test_invalid_argument_does_not_echo_secret(self):
        code,result=self.invoke(['login','--user','test','--password','fixture-secret'])
        self.assertEqual(code,2)
        self.assertNotIn('fixture-secret',json.dumps(result))

    def test_missing_session_is_status_not_login(self):
        with tempfile.TemporaryDirectory() as temporary:
            code,result=self.invoke(['--state-dir',str(Path(temporary)/'state'),'status'])
        self.assertEqual(code,0)
        self.assertEqual(result['data']['reason'],'NO_SESSION')

    def test_cookie_refresh_survives_captcha_and_preserves_expiry(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary)/'state'; store=cli.SessionStore(state)
            original_time=time.time()-3600
            with requests.Session() as initial:
                initial.cookies.set('fixture','old',domain='.dcinside.com',path='/')
                store.save(initial,{'nickname':'tester'},saved_at=original_time)
            def rejected(client,*args,**kwargs):
                client.session.cookies.set('fixture','updated',domain='.dcinside.com',path='/')
                raise core.LoginError('Verification required','USER_ACTION_REQUIRED',details={'version':'v3'})
            with patch.object(core.DCInsideHTTP,'create_comment',rejected):
                code,result=self.invoke(['--state-dir',str(state),'comment','10','--text','fixture','--send'])
            self.assertEqual(code,2)
            self.assertEqual(result['error']['details']['version'],'v3')
            with requests.Session() as next_session:
                saved=store.load(next_session)
                self.assertEqual(saved['saved_at'],original_time)
                self.assertEqual(next_session.cookies.get('fixture'),'updated')

    def test_cookie_refresh_after_success_preserves_expiry(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary)/'state';store=cli.SessionStore(state)
            original_time=time.time()-3600
            with requests.Session() as initial:
                store.save(initial,{'nickname':'tester'},saved_at=original_time)
            def read(client,*args):
                client.session.cookies.set('fixture','updated',domain='.dcinside.com',path='/')
                return {'posts':[]}
            with patch.object(core.DCInsideHTTP,'list_posts',read):
                code,result=self.invoke(['--state-dir',str(state),'list'])
            self.assertEqual(code,0)
            with requests.Session() as next_session:
                self.assertEqual(store.load(next_session)['saved_at'],original_time)
                self.assertEqual(next_session.cookies.get('fixture'),'updated')

    def test_save_failure_does_not_mask_verified_publication_or_captcha(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary)/'state'
            with requests.Session() as initial:
                cli.SessionStore(state).save(initial,{'nickname':'tester'})
            for rejected in (False,True):
                outcome=core.LoginError('Verification required','USER_ACTION_REQUIRED',details={'version':'v3'}) if rejected else None
                with patch.object(core.DCInsideHTTP,'create_comment',side_effect=outcome,return_value={'submitted':True,'verified':True}), patch.object(cli.SessionStore,'save',side_effect=OSError()):
                    code,result=self.invoke(['--state-dir',str(state),'comment','10','--text','fixture','--send'])
                if rejected:
                    self.assertEqual(result['error']['code'],'USER_ACTION_REQUIRED')
                    self.assertEqual(result['error']['details']['session_warning']['code'],'SESSION_SAVE_FAILED')
                else:
                    self.assertEqual(code,0)
                    self.assertTrue(result['data']['verified'])
                    self.assertEqual(result['data']['warnings'][0]['code'],'SESSION_SAVE_FAILED')

    def test_parallel_saved_session_commands_stop_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            state=Path(temporary)/'state'
            with cli.SessionStore(state).lock(), patch('dcinside_cli.DCInsideHTTP',side_effect=AssertionError('network client constructed')):
                code,result=self.invoke(['--state-dir',str(state),'status'])
            self.assertEqual(code,2)
            self.assertEqual(result['error']['code'],'SESSION_BUSY')

    def test_install_only_public_files_and_preserves_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/'source';target=Path(temporary)/'installed'
            for name in installer.FILES:
                destination=source/name;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(ROOT/name,destination)
            (source/'session.json').write_text('fixture-secret')
            command=[sys.executable,str(source/'install.py'),'--target',str(target),'--skip-dependencies']
            first=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(first.returncode,0,first.stderr)
            self.assertFalse((target/'session.json').exists())
            self.assertEqual(subprocess.run(command,capture_output=True).returncode,0)
            (target/'SKILL.md').write_text('local edit')
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual((target/'SKILL.md').read_text(),'local edit')


if __name__ == '__main__':
    unittest.main()
