#!/usr/bin/env python3
"""Browser-free DCInside mobile-web reads, login, and text comments.

Dependencies: requests, beautifulsoup4
Credentials are prompted, never persisted. Reuse DCInsideHTTP in one process.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import time
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SIGN = "https://msign.dcinside.com"
MOBILE = "https://m.dcinside.com"
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
MOBILE_HTML_HEADERS = {
    "User-Agent": MOBILE_UA, "Accept-Language": "ko,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Sec-CH-UA-Mobile": "?1", "Sec-CH-UA-Platform": '"Android"',
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-site",
    "Sec-Fetch-User": "?1", "Upgrade-Insecure-Requests": "1",
}
ALLOWED_HOSTS = {"m.dcinside.com", "msign.dcinside.com", "sso.dcinside.com", "sign.dcinside.com"}


class LoginError(RuntimeError):
    """An error safe to display; never includes request bodies or cookies."""

    def __init__(self, message, code="AUTH_FAILED", *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def check_destination(url: str, credentials: bool = False) -> None:
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise LoginError("Unexpected authentication destination; stopped.")
    if credentials and (parsed.hostname, parsed.path) not in {
        ("msign.dcinside.com", "/login"), ("sso.dcinside.com", "/auth/"),
    }:
        raise LoginError("Unexpected credential submission destination; stopped.")


def page_value(soup, selector):
    element = soup.select_one(selector)
    return element.get("value", "") if element else ""


def visible_text(element):
    return re.sub(r"\s+", " ", element.get_text(" ", strip=True)).strip()


def account_id(soup):
    # Never take account controls from user-authored post or comment content.
    fields = [el for el in soup.select('input#user_id[type="hidden"]')
              if not el.find_parent(class_="thum-txtin") and not el.find_parent(id="comment_box")]
    return fields[0].get("value", "") if len(fields) == 1 else ""


def gallery_identity(html: bytes | str) -> dict | None:
    """Confirm mobile account state without returning the private account ID."""
    soup = BeautifulSoup(html, "html.parser")
    if not account_id(soup):
        return None
    logout = False
    for link in soup.select("footer .ft-bts a[href]"):
        destination = urlparse(urljoin(MOBILE, link["href"]))
        if (destination.scheme == "https" and destination.hostname in ALLOWED_HOSTS
                and destination.path in ("/logout", "/auth/logout", "/login/logout")
                and "로그아웃" in link.get_text()):
            logout = True
    if not logout:
        return None
    return {"nickname": page_value(soup, "#comment_write #comment_nick") or None}


class DCInsideHTTP:
    def __init__(self, gallery: str = "thesingularity", kind: str = "minor"):
        if not re.fullmatch(r"[a-z0-9_]{1,80}", gallery):
            raise ValueError("Invalid gallery ID")
        self.gallery = gallery
        if kind not in ("minor", "main"):
            raise ValueError("Supported gallery kinds: minor, main")
        self.kind = kind
        self.board_root = MOBILE + "/board"
        self.gallery_url = f"{self.board_root}/{gallery}"
        self.session = requests.Session()
        self.session.headers.update(MOBILE_HTML_HEADERS)

    def close(self):
        self.session.cookies.clear()
        self.session.close()

    def _request(self, method: str, url: str, *, data=None, headers=None):
        check_destination(url, credentials=data is not None and "password" in data)
        return self.session.request(method, url, data=data, headers=headers, timeout=20, allow_redirects=False)

    def _redirects(self, response, *, data=None, headers=None):
        source = (headers or {}).get("Referer") or response.url
        for _ in range(8):
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            if not location:
                raise LoginError("Authentication redirect is missing its destination.")
            destination = urljoin(response.url, location)
            repeat_post = response.status_code in (307, 308) and response.request.method == "POST"
            source_url, target_url = urlparse(source), urlparse(destination)
            same_origin = (source_url.scheme, source_url.netloc) == (target_url.scheme, target_url.netloc)
            # Match normal navigation metadata; credentials and CSRF headers
            # are still dropped when a redirect switches from POST to GET.
            navigation = {"Referer": source if same_origin else f"{source_url.scheme}://{source_url.netloc}/",
                          "Sec-Fetch-Site": "same-origin" if same_origin else "same-site"}
            response = self._request("POST" if repeat_post else "GET", destination,
                                     data=data if repeat_post else None,
                                     headers={**(headers or {}), **navigation} if repeat_post else navigation)
        raise LoginError("Too many authentication redirects.")

    def login(self, account: str, password: str) -> dict:
        # A fresh session prevents old browser/account cookies from masking errors.
        self.session.cookies.clear()
        response = self._request("GET", SIGN + "/login?" + urlencode({"r_url": self.gallery_url}),
                                 headers={"Referer": MOBILE + "/"})
        if response.status_code != 200:
            raise LoginError("Login form could not be loaded.")
        soup = BeautifulSoup(response.content, "html.parser")
        form = soup.select_one("form")
        csrf = soup.select_one('meta[name="csrf-token"]')
        if not form or not csrf:
            raise LoginError("Login form changed or additional verification is required.")
        if soup.select_one('img#captchaCode[src]:not([src=""])'):
            raise LoginError("User action required: CAPTCHA.", "USER_ACTION_REQUIRED")
        fields = {el["name"]: el.get("value", "") for el in form.select("input[name]")
                  if el["name"] in ("conKey", "r_url", "_token")}
        fields["_token"] = fields.get("_token") or csrf["content"]
        fields["r_url"] = self.gallery_url
        if not fields.get("conKey"):
            raise LoginError("Login form is missing its session token.")
        headers = {"Referer": response.url, "Origin": SIGN, "X-CSRF-TOKEN": csrf["content"],
                   "Sec-Fetch-Site": "same-origin"}
        access = self._request("POST", SIGN + "/login/access", data={
            "token_verify": "dc_login", "conKey": fields["conKey"],
            "code": account, "randcode": "undefined",
        }, headers={**headers, "X-Requested-With": "XMLHttpRequest", "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-User": None})
        try:
            result = access.json()
        except ValueError:
            raise LoginError("Login preflight returned an unexpected response.") from None
        if not isinstance(result, dict) or result.get("result") not in (True, 1):
            raise LoginError("Login preflight failed or user verification is required.", "USER_ACTION_REQUIRED")
        fields.update(code=account, password=password,
                      conKey=result.get("Block_key") or fields["conKey"])
        remember = form.select_one('input[name="loginCash"][type="checkbox"]')
        if remember is not None and remember.has_attr("checked"):
            # An HTML checkbox with no value submits "on" when checked;
            # an unchecked checkbox is omitted, rather than sent as empty.
            fields["loginCash"] = remember.get("value", "on")
        try:
            response = self._request("POST", urljoin(SIGN, form.get("action", "/login")),
                                     data=fields, headers=headers)
            response = self._redirects(response, data=fields, headers=headers)
        finally:
            fields.clear()
        body = BeautifulSoup(response.content, "html.parser")
        notice = "비밀번호 규칙이 변경" in body.get_text()
        if notice:
            response = self._continue_password_notice(response, body)
        # The password reminder is not proof of failure or success. Verify the
        # mobile account state after SSO, using the same mobile UA and cookie jar.
        try:
            verified = self.verify_login()
        except LoginError as exc:
            # Report only routing and structural flags, never credentials,
            # cookies, CSRF tokens, or the returned HTML.
            destination = urlparse(response.url)
            exc.details["stage"] = "mobile_verify"
            exc.details["login_response"] = {
                "status": response.status_code, "host": destination.hostname,
                "path": destination.path, "password_form": BeautifulSoup(response.content, "html.parser").select_one('input[type="password"]') is not None,
                "password_change_notice": notice,
                "sso_form": any(urlparse(urljoin(response.url, form.get("action", ""))).hostname == "sso.dcinside.com"
                                for form in body.select("form")),
            }
            raise
        verified["password_change_notice"] = notice
        return verified

    def _continue_password_notice(self, response, soup):
        """Follow only the site's explicit optional-reminder continuation."""
        if urlparse(response.url).hostname != "msign.dcinside.com":
            raise LoginError("Unexpected password-reminder destination.", "FORM_CHANGED")
        destinations = set()
        after_change_controls = 0
        for element in soup.select("[onclick], a[href]"):
            action = (element.get("onclick", "") or element.get("href", "")).strip().removeprefix("javascript:")
            match = re.fullmatch(r"\s*(?:return\s+)?afterChange\(\s*(['\"])([^'\"\s]*)\1\s*\)\s*;?\s*", action)
            if match:
                after_change_controls += 1
                destination = urljoin(response.url, match[2])
                check_destination(destination)
                parsed = urlparse(destination)
                if ((parsed.hostname == "m.dcinside.com" and parsed.path in ("", "/", urlparse(self.gallery_url).path, "/auth/login"))
                        or (parsed.hostname == "msign.dcinside.com" and parsed.path == "/login")
                        or (parsed.hostname == "sso.dcinside.com" and parsed.path == "/auth/")):
                    destinations.add(destination)
        if len(destinations) != 1:
            raise LoginError("Password reminder has no uniquely supported continue-later button.", "USER_ACTION_REQUIRED",
                             details={"stage": "password_reminder", "password_changed": False,
                                      "after_change_controls": after_change_controls,
                                      "supported_destinations": len(destinations)})
        script = next((urljoin(response.url, el["src"]) for el in soup.select("script[src]")
                       if urlparse(urljoin(response.url, el["src"])).hostname == "msign.dcinside.com"
                       and urlparse(urljoin(response.url, el["src"])).path == "/js/common.min.js"), None)
        if not script:
            raise LoginError("Password-reminder continuation script changed.", "FORM_CHANGED")
        published = self._request("GET", script)
        if (published.status_code != 200 or not re.search(
                r'function afterChange\((\w+)\)\{setCookie_hk\("dc_pw_change",1,30\),location.href=\1\}', published.text)):
            raise LoginError("Password-reminder continuation behavior changed.", "FORM_CHANGED")
        # This is the published reminder preference, not an authentication or
        # browser/device verification token. It never changes the password.
        self.session.cookies.set("dc_pw_change", "1", domain=".dcinside.com", path="/",
                                 expires=int(time.time()) + 30 * 24 * 60 * 60, secure=True)
        return self._redirects(self._request("GET", destinations.pop(), headers={"Referer": response.url}))

    def verify_login(self) -> dict:
        response = self._request("GET", self.gallery_url)
        identity = gallery_identity(response.content) if response.status_code == 200 else None
        if not identity:
            soup = BeautifulSoup(response.content, "html.parser")
            raise LoginError("The mobile gallery did not confirm a logged-in session. Run login again for mobile web.",
                             details={"mobile_account_present": bool(account_id(soup)),
                                      "logout_label_present": any("로그아웃" in link.get_text()
                                                                  for link in soup.select("footer .ft-bts a[href]"))})
        return {"authenticated": True, **identity, "gallery": self.gallery,
                "gallery_url": self.gallery_url, "surface": "mobile"}

    def list_posts(self, page=1, limit=5, include_notices=False) -> dict:
        if page < 1 or not 1 <= limit <= 100:
            raise ValueError("Page must be positive; limit must be 1 to 100")
        url = f"{self.gallery_url}?page={page}"
        response = self._request("GET", url)
        soup = BeautifulSoup(response.content, "html.parser")
        listing = soup.select_one(".gall-detail-lst")
        if (response.status_code != 200 or listing is None
                or (soup.select_one("#page") and page_value(soup, "#page") != str(page))):
            raise LoginError("Mobile gallery list is unavailable or its structure changed.", "READ_FAILED")
        posts = []
        rows = list(listing.select(":scope > li"))
        if include_notices:
            rows = list(soup.select("#notice_list > li.notice")) + rows
        seen = set()
        for row in rows:
            link = row.select_one("a.lt[href]")
            if not link:
                continue
            destination = urlparse(urljoin(url, link["href"]))
            match = re.fullmatch(r"/board/" + re.escape(self.gallery) + r"/([1-9][0-9]*)", destination.path)
            if destination.scheme != "https" or destination.hostname != "m.dcinside.com" or not match:
                continue
            notice = "notice" in row.get("class", []) or row.select_one(".ntc-line-orange") is not None
            if notice and not include_notices:
                continue
            post_id = int(match[1])
            if post_id in seen:
                continue
            seen.add(post_id)
            title = row.select_one(".subjectin")
            if title is None and notice:
                title = BeautifulSoup(str(link), "html.parser")
                for badge in title.select(".round"):
                    badge.decompose()
            if title is None or not title.get_text(strip=True):
                raise LoginError("Mobile list title structure changed.", "READ_FAILED")
            count = row.select_one("a.rt .ct")
            count_match = re.search(r"[0-9][0-9,]*", count.get_text() if count else "0")
            posts.append({"post_id": post_id, "title": visible_text(title),
                          "url": f"{self.gallery_url}/{post_id}",
                          "comment_count": int(count_match[0].replace(",", "")) if count_match else 0,
                          "notice": bool(notice)})
            if len(posts) >= limit:
                break
        if not posts and not listing.select_one(".no-result"):
            raise LoginError("No posts were parsed and the mobile list has no empty-state marker.", "READ_FAILED")
        return {"gallery": self.gallery, "kind": self.kind, "surface": "mobile", "page": page, "posts": posts,
                "authenticated": bool(gallery_identity(response.content))}

    def _post_page(self, post_id):
        if post_id < 1:
            raise ValueError("Invalid post ID")
        url = f"{self.gallery_url}/{post_id}"
        response = self._request("GET", url)
        soup = BeautifulSoup(response.content, "html.parser")
        title, body = soup.select_one(".gallview-tit-box .tit"), soup.select_one(".thum-txtin")
        if response.status_code != 200 or not title or not body:
            raise LoginError("Post is unavailable, restricted, deleted, or its structure changed.", "POST_UNAVAILABLE")
        return url, response, soup

    def read_post(self, post_id):
        url, response, soup = self._post_page(post_id)
        body = soup.select_one(".thum-txtin")
        for unwanted in body.select("script,style"):
            unwanted.decompose()
        return {"gallery": self.gallery, "post_id": post_id, "url": url,
                "title": visible_text(soup.select_one(".gallview-tit-box .tit")),
                "body": body.get_text("\n", strip=True),
                "media": self._media(body, url),
                "authenticated": bool(gallery_identity(response.content)), "surface": "mobile"}

    @staticmethod
    def _media(soup, base):
        found = []
        for element in soup.select("img,video,source,iframe"):
            src = element.get("data-original") or element.get("data-src") or element.get("src") or ""
            url = urljoin(base, src)
            if src and urlparse(url).scheme in ("https", "http"):
                found.append({"type": element.name, "url": url, "alt": element.get("alt", "")})
        return found

    def read_comments(self, post_id, page=1):
        if page < 1:
            raise ValueError("Page must be positive")
        url, response, soup = self._post_page(post_id)
        return self._read_comments_from_page(post_id, page, url, response, soup)

    def _read_comments_from_page(self, post_id, page, url, response, soup):
        """Read comments without reloading or replacing the current form context."""
        comments = self._request("POST", MOBILE + "/ajax/response-comment", data={
            "id": self.gallery, "no": str(post_id), "cpage": str(page), "csort": "new",
            "managerskill": page_value(soup, "#managerskill"),
            "permission_pw": page_value(soup, "#secret_pw"),
        }, headers=self._ajax_headers(soup, url))
        content = BeautifulSoup(comments.content, "html.parser")
        total = page_value(content, "#reple_totalCnt")
        if (comments.status_code != 200 or content.select_one(".all-comment-lst") is None
                or not total.isdigit() or page_value(content, "#cpage") != str(page)):
            raise LoginError("Mobile comment lookup failed or its HTML structure changed.", "READ_FAILED")
        items = []
        current_account = account_id(soup) if gallery_identity(response.content) else ""
        parent_id = None
        for row in content.select(".all-comment-lst > li"):
            number = row.get("no", "")
            if not number.isdigit() or int(number) <= 0:
                continue
            memo, author, date = row.select_one(".txt"), row.select_one(".ginfo-area .nick"), row.select_one(".date")
            if memo is None:
                raise LoginError("Mobile comment text structure changed.", "READ_FAILED")
            author_id = row.select_one(".ginfo-area .blockCommentId[data-info]")
            # Membership and delete controls are not proof of ownership.
            is_mine = bool(current_account and author_id and
                           author_id["data-info"].casefold() == current_account.casefold())
            reply = "comment-add" in row.get("class", [])
            if not reply:
                parent_id = number
            for unwanted in memo.select("script,style"):
                unwanted.decompose()
            items.append({"comment_id": int(number), "author": author.get_text(" ", strip=True) if author else None,
                          "is_mine": is_mine, "text": memo.get_text("\n", strip=True),
                          "date": date.get_text(strip=True) if date else None,
                          "depth": int(reply), "reply_to": parent_id if reply else None,
                          "media": self._media(memo, url)})
        if int(total) > 0 and content.select(".all-comment-lst > li") and not items:
            raise LoginError("No mobile comment rows could be parsed.", "READ_FAILED")
        return {"gallery": self.gallery, "post_id": post_id, "page": page, "surface": "mobile",
                "total": int(total), "comments": items,
                "authenticated": bool(gallery_identity(response.content))}

    @staticmethod
    def _ajax_headers(soup, url):
        csrf = soup.select_one('meta[name="csrf-token"]')
        if not csrf or not csrf.get("content"):
            raise LoginError("Mobile CSRF token is unavailable.", "FORM_CHANGED")
        return {"Referer": url, "Origin": MOBILE, "X-Requested-With": "XMLHttpRequest",
                "X-CSRF-TOKEN": csrf["content"], "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin", "Sec-Fetch-User": None}

    @staticmethod
    def _verification_error(payload, stage):
        cause = str(payload.get("cause", "")).lower()
        if "captcha" not in cause:
            return None
        version = payload.get("version", payload.get("recaptcha_version"))
        version = version if version in ("v2", "v3") else "unknown"
        verification = "image_captcha" if payload.get("ran_code") else "recaptcha" if "recaptcha" in cause or version != "unknown" else "captcha"
        return LoginError("Server requires CAPTCHA verification. Nothing was retried.", "USER_ACTION_REQUIRED",
                          details={"verification": verification, "version": version,
                                   "stage": stage, "submitted": False, "retried": False})

    def create_comment(self, post_id, text, *, send=False):
        if not text or not text.strip() or "\x00" in text:
            raise ValueError("Comment text must not be empty")
        text = text.strip()
        url, response, soup = self._post_page(post_id)
        identity = gallery_identity(response.content)
        if not identity:
            raise LoginError("A logged-in mobile session is required. Run login again for mobile web.", "LOGIN_REQUIRED")
        form = soup.select_one("form#comment_write")
        memo = form.select_one("#comment_memo") if form else None
        if memo is None or memo.has_attr("disabled") or memo.has_attr("readonly"):
            raise LoginError("Comment entry is unavailable on this post.", "COMMENTS_CLOSED")
        if form.select_one("#captcha_codeC, .g-recaptcha, .grecaptcha-submit"):
            raise LoginError("Mobile comment form requires user verification.", "USER_ACTION_REQUIRED",
                             details={"verification": "image_captcha" if form.select_one("#captcha_codeC") else "recaptcha",
                                      "version": "unknown", "stage": "comment_form", "submitted": False, "retried": False})
        maximum = memo.get("maxlength", "")
        if not maximum.isdigit():
            raise LoginError("Mobile comment length limit is unavailable.", "FORM_CHANGED")
        if len(text.encode("utf-16-le")) // 2 > int(maximum):
            raise ValueError("Comment exceeds the page's length limit")
        # Require the page's exact target and top-level form before any write.
        if (page_value(soup, "#id") != self.gallery or page_value(soup, "#no") != str(post_id)
                or urljoin(url, form.get("action", "")) != url
                or form.get("method", "").upper() != "POST"
                or not page_value(soup, "#board_id").isdigit()
                or soup.select_one("#best_chk") is None):
            raise LoginError("Mobile comment target/form structure changed.", "FORM_CHANGED")
        headers = self._ajax_headers(soup, url)
        marker = form.select_one("input.hide-robot[name]")
        if not marker or not re.fullmatch(r"[a-zA-Z0-9_]{1,80}", marker["name"]):
            raise LoginError("Mobile comment form field changed.", "FORM_CHANGED")
        payload = {"id": self.gallery, "no": str(post_id), "mode": "com_write", "comment_no": "",
                   "comment_memo": text, "comment_nick": page_value(form, "#comment_nick"),
                   "comment_pw": page_value(form, "#comment_pw") if form.select_one("#comment_pw") else "undefined",
                   "best_chk": page_value(soup, "#best_chk"), "board_id": page_value(soup, "#board_id"),
                   "reple_id": "", "cpage": "1"}
        # Match the published form's substring-before-trim behavior. Subject
        # is optional notification context, separate from the clean preview title.
        subject = re.sub(r"<[^>]*>", "", soup.select_one(".gallview-tit-box .tit").get_text()[:40].strip())
        if subject:
            payload["subject"] = subject
        if marker["name"] in payload or marker["name"] in ("con_key", "use_gall_nickname", "password", "subject"):
            raise LoginError("Mobile form field conflicts with the comment target or content.", "FORM_CHANGED")
        payload[marker["name"]] = "1"
        if soup.select_one("#use_gall_nickname"):
            payload["use_gall_nickname"] = page_value(soup, "#use_gall_nickname")
        before = self._read_comments_from_page(post_id, 1, url, response, soup)["comments"]
        matching = [item for item in before if item["is_mine"] and item["text"] == text]
        preview = {"post_id": post_id, "gallery": self.gallery, "url": url, "surface": "mobile",
                   "title": visible_text(soup.select_one(".gallview-tit-box .tit")),
                   "nickname": identity["nickname"], "text": text}
        if matching:
            return {**preview, "submitted": False, "already_present": True,
                    "verified": True, "comment_id": matching[0]["comment_id"]}
        if not send:
            return {**preview, "submitted": False, "dry_run": True, "ready": True}
        # Fetch the mobile form token only for an explicitly requested send.
        access = self._request("POST", MOBILE + "/ajax/access",
                               data={"token_verify": "com_submit"}, headers=headers)
        try:
            token = access.json()
        except ValueError:
            raise LoginError("Mobile comment preflight returned an unexpected response.", "FORM_CHANGED") from None
        if not isinstance(token, dict):
            raise LoginError("Mobile comment preflight structure changed.", "FORM_CHANGED")
        verification = self._verification_error(token, "comment_preflight")
        if verification:
            raise verification
        key = token.get("Block_key")
        if (access.status_code != 200 or token.get("result") in (False, 0, "0")
                or not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,512}", key)):
            raise LoginError("Mobile comment preflight was rejected. No comment was sent.", "WRITE_REJECTED")
        payload["con_key"] = key
        # Complete the mobile site's double-submit token handshake. The value
        # is the server-issued preflight key, not a locally generated token.
        for cookie in list(self.session.cookies):
            if (cookie.name == "cmtw_chk" and
                    cookie.domain.lstrip(".") in ("dcinside.com", "m.dcinside.com")):
                self.session.cookies.clear(cookie.domain, cookie.path, cookie.name)
        self.session.cookies.set("cmtw_chk", key, domain=".dcinside.com", path="/",
                                 expires=int(time.time()) + 180, secure=True)
        try:
            posted = self._request("POST", MOBILE + "/ajax/comment-write", data=payload, headers=headers)
        except requests.RequestException:
            raise LoginError("Submission outcome is unknown. Check comments; do not retry automatically.", "WRITE_UNCONFIRMED") from None
        try:
            result = posted.json()
        except ValueError:
            raise LoginError("Submission returned an unknown response. Check comments; do not retry automatically.", "WRITE_UNCONFIRMED") from None
        if not isinstance(result, dict):
            raise LoginError("Submission returned an unknown response. Do not retry automatically.", "WRITE_UNCONFIRMED")
        if result.get("result") in (False, 0, "0"):
            verification = self._verification_error(result, "comment_submit")
            if verification:
                raise verification
            reason = BeautifulSoup(str(result.get("cause", "Server rejected the comment")), "html.parser").get_text()[:180]
            raise LoginError("Comment rejected: " + reason, "WRITE_REJECTED")
        if posted.status_code != 200 or result.get("result") not in (True, 1, "1"):
            raise LoginError("Submission result is unknown. Check comments; do not retry automatically.", "WRITE_UNCONFIRMED")
        try:
            after = self.read_comments(post_id)["comments"]
        except (requests.RequestException, LoginError, ValueError):
            raise LoginError("Submission sent but read-back failed. Do not retry automatically.", "WRITE_UNCONFIRMED") from None
        before_ids = {item["comment_id"] for item in before}
        matches = [item for item in after if item["comment_id"] not in before_ids and item["is_mine"] and item["text"] == text]
        if len(matches) != 1:
            raise LoginError("Submission could not be uniquely verified. Check comments; do not retry automatically.", "WRITE_UNCONFIRMED")
        return {**preview, "submitted": True, "verified": True, "comment_id": matches[0]["comment_id"],
                "comment_url": url + "?comment=" + str(matches[0]["comment_id"])}

    def probe_post(self, post_id: int) -> dict:
        """Legacy authenticated read-only verification entry point."""
        post = self.read_post(post_id)
        if not post["authenticated"]:
            raise LoginError("Post did not confirm the logged-in session.")
        comments = self.read_comments(post_id)
        return {"authenticated": True, "post_id": post_id, "title": post["title"],
                "body_characters": len(post["body"]), "comment_total": comments["total"],
                "comments_on_page": len(comments["comments"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", help="Account identifier; password is prompted without echo.")
    parser.add_argument("--gallery", default="thesingularity", help="Minor gallery ID")
    parser.add_argument("--post", type=int, help="Optional known post ID to verify after login")
    args = parser.parse_args()
    account = args.user or input("Account: ").strip()
    password = getpass.getpass("Password: ")
    client = DCInsideHTTP(args.gallery)
    try:
        result = client.login(account, password)
        password = ""
        result["session_reuse"] = client.verify_login()["authenticated"]
        if args.post:
            result["post_check"] = client.probe_post(args.post)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except LoginError as exc:
        print(json.dumps({"authenticated": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    except requests.RequestException:
        print(json.dumps({"authenticated": False, "error": "Network request failed."}))
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
