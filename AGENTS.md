# DCInside project

For DCInside tasks in this project, read `SKILL.md` once and use `scripts/dcinside`.
This is an HTTP tool; supported operations do not need browser automation.
Version 0.4.2 targets mobile web (`https://m.dcinside.com`) with a mobile User-Agent,
mobile HTML parsers, and mobile AJAX endpoints. Do not fall back to PC pages for login
verification; older PC sessions may require login again for mobile web.

Quick commands (from this directory):

```sh
./scripts/dcinside list --gallery thesingularity --limit 5
./scripts/dcinside read POST_ID --gallery thesingularity
./scripts/dcinside comments POST_ID --gallery thesingularity
./scripts/dcinside status
./scripts/dcinside login --user ACCOUNT
```

Public reads do not require login. Password entry is through the terminal, and session cookies are saved privately by `login`. Never store credentials in this repository. Commands emit JSON and should be used directly rather than rewriting ad hoc scraping code.

Text comments are available with `scripts/dcinside comment POST_ID --text-file FILE`: preview by default; add `--send` only for the user-authorized text and target. Check `verified:true` and the returned comment ID. On CAPTCHA, stop and report the version in `error.details`; v3 does not mean an image puzzle is required. An unknown submission result must never be retried automatically. Post creation and replies to individual comments are not implemented. Do not silently open a browser to compensate; respect an HTTP-only preference.

Saved-session commands refresh cookies without extending the original expiry and must run sequentially. `SESSION_BUSY` means no network operation started. A session-save warning never changes the reported publication outcome or authorizes a resend.

`dcinside_http_login.py` remains an importable HTTP client and a legacy one-shot login check. Its legacy CLI does not save sessions; use `scripts/dcinside login` for reusable login.

After changes, run `python3 -m unittest discover -s tests -v`. Install/update the personal skill with `python3 install.py`. The installer copies only a fixed public-file allowlist, never cookies or `.venv`.
