# DCInside 모바일 웹 HTTP 도구

모바일 웹 `https://m.dcinside.com`을 모바일 User-Agent로 접근해 갤러리 목록·본문·댓글을 읽고 로그인 세션을 재사용하며, 로그인한 계정으로 텍스트 댓글을 등록합니다. 0.4.0부터 목록·본문 파서와 댓글 조회·전송을 모바일 HTML/AJAX 기준으로 처리합니다. 댓글 등록 시 서버가 CAPTCHA를 요구하면 중단합니다. 에이전트가 읽는 `SKILL.md`, 프로젝트용 `AGENTS.md`, 실행 가능한 CLI를 함께 제공합니다.

## 다른 에이전트가 터미널에서 바로 사용

공개 저장소: [yongop/dcinside-http](https://github.com/yongop/dcinside-http). macOS/Linux에서 [uv](https://docs.astral.sh/uv/getting-started/installation/)가 있으면 아래 한 줄로 패키지와 의존성을 내려받고 최신글을 조회합니다. Python 3.9 이상을 사용하며 필요한 Python이 없으면 uv가 준비합니다. Git 없이도 받도록 GitHub 소스 압축파일 URL을 사용합니다.

```sh
uvx --from https://github.com/yongop/dcinside-http/archive/refs/tags/v0.4.2.tar.gz dcinside list --gallery thesingularity --limit 5 --anonymous
```

`uvx`는 전용 환경에 도구를 준비해 실행하며 다음 실행에 재사용합니다. `list` 뒤의 명령과 인자만 바꾸면 됩니다. 다른 에이전트에 아래 명령으로 지침을 읽도록 전달하세요. 지침도 JSON으로 출력합니다.

```sh
uvx --from https://github.com/yongop/dcinside-http/archive/refs/tags/v0.4.2.tar.gz dcinside instructions
```

자주 쓴다면 영구 설치할 수 있습니다. 실행 파일 폴더가 PATH에 없으면 uv가 안내하는 경로를 사용하거나 `uv tool update-shell` 후 터미널을 다시 여세요.

```sh
uv tool install https://github.com/yongop/dcinside-http/archive/refs/tags/v0.4.2.tar.gz
dcinside capabilities
dcinside list --gallery thesingularity --limit 5 --anonymous
```

`uv` 없이 Python만 있는 환경에서도 설치할 수 있습니다.

```sh
python3 -m venv ~/.local/share/dcinside-http/venv && ~/.local/share/dcinside-http/venv/bin/python -m pip install https://github.com/yongop/dcinside-http/archive/refs/tags/v0.4.2.tar.gz && ~/.local/share/dcinside-http/venv/bin/dcinside capabilities
```

이 방식은 CLI를 설치합니다. 각 에이전트의 스킬 목록에 등록하려면 아래 소스/스킬 설치 방식으로 `SKILL.md`를 연결하세요. 공개 조회는 로그인 없이 가능하며 로그인은 사용할 컴퓨터에서 따로 수행합니다.

## 소스/스킬 설치

macOS 또는 Linux, Python 3.9 이상과 인터넷 연결이 필요합니다. 이 폴더에서 실행하세요.

```sh
python3 install.py
```

다른 컴퓨터에서 Git으로 소스와 스킬을 함께 받는 예:

```sh
git clone --branch v0.4.2 --depth 1 https://github.com/yongop/dcinside-http.git && cd dcinside-http && python3 install.py
```

기본 설치 위치는 `${CODEX_HOME:-~/.codex}/skills/dcinside`입니다. 설치 프로그램이 필요한 파일을 복사하고 전용 `.venv`에 의존성을 설치합니다. 다른 위치에는 `python3 install.py --target /원하는/skills/dcinside`로 설치할 수 있습니다. 같은 명령으로 업데이트합니다. 기존 설치 파일을 직접 수정한 경우 덮어쓰지 않고 중단합니다.

이 컴퓨터는 `~/.codex/skills`를 사용합니다. 최신 Codex의 `~/.agents/skills` 검색 위치를 사용하는 환경에서는 `python3 install.py --target ~/.agents/skills/dcinside`로 설치하세요. [공식 스킬 검색 위치 안내](https://learn.chatgpt.com/docs/build-skills)

설치가 출력한 실행 파일 경로를 사용하세요. 기본 위치의 예:

```sh
~/.codex/skills/dcinside/scripts/dcinside list --gallery thesingularity --limit 5
~/.codex/skills/dcinside/scripts/dcinside read 1464030 --gallery thesingularity
~/.codex/skills/dcinside/scripts/dcinside comments 1464030 --gallery thesingularity --page 1
~/.codex/skills/dcinside/scripts/dcinside login --user YOUR_ID
~/.codex/skills/dcinside/scripts/dcinside status
~/.codex/skills/dcinside/scripts/dcinside logout
```

프로젝트 폴더에서는 `./scripts/dcinside ...`도 사용할 수 있습니다. 설치 전 직접 실행하려면 `python3 -m pip install -r requirements.txt`로 의존성을 준비합니다.

## 에이전트에서 사용

새 채팅에서 `$dcinside 특이점이 온다 갤러리 최신글 5개 제목 알려줘`라고 요청할 수 있습니다. 스킬의 자동 선택도 허용되어 있습니다. 기존 채팅에서 새 스킬이 보이지 않으면 설치된 `SKILL.md`를 읽도록 지시하거나 새 채팅을 시작하세요. 스킬 목록이 갱신되지 않으면 Codex를 재시작하세요. 다른 에이전트 제품에서는 해당 제품의 스킬 설치 위치에 이 폴더를 설치하고 `SKILL.md`를 읽도록 연결해야 합니다; 모든 제품이 Codex 경로를 자동으로 읽는 것은 아닙니다.

이 프로젝트에서 시작한 에이전트는 `AGENTS.md`에서 CLI와 스킬 안내를 찾습니다. 설치만으로 기존 채팅의 문맥이나 실행 중인 작업에 명령을 보내지는 않습니다.

## 기능과 제한

- `capabilities`, `instructions`: 지원 기능과 에이전트 사용 지침. 네트워크 요청이나 세션 접근 없이 JSON으로 반환합니다.
- `list`: 번호·제목·모바일 링크·댓글 수. 기본적으로 공지와 광고 제외. `--page`, `--limit`, `--include-notices` 지원. `--limit`는 선택한 모바일 페이지의 상한이며 추가 페이지를 자동 조회하지 않습니다.
- `read`: 본문 텍스트와 이미지·동영상 등 첨부 링크. 지연 로딩 이미지의 `data-original`을 우선해 로딩용 이미지 대신 원본 링크를 반환합니다. 이미지 안의 글자는 자동 OCR하지 않습니다.
- `comments`: 모바일 댓글 API에서 한 페이지의 댓글 텍스트, 댓글 번호, 작성자 닉네임, 답글 정보, 미디어 링크를 읽습니다. 최신순으로 조회하며 답글은 원댓글 아래에 묶입니다. IP와 계정 식별 코드는 출력하지 않습니다.
- `login`, `status`, `logout`: HTTP 로그인, 서버에서 실제 로그인 상태 확인, 이 도구의 로컬 세션 삭제.
- `comment POST_ID --text-file FILE`: 작성 전 미리보기. 사용자가 지정한 대상과 내용으로 등록하려면 `--send` 추가. `--text`로 직접 전달할 수도 있습니다. 모바일 로그인 필요. 모바일 폼·CSRF 토큰을 확인하고 전송 시에만 `/ajax/access`에서 토큰을 받아 `/ajax/comment-write`에 한 번 제출합니다. 미리보기의 `ready:true`는 폼 검사 결과이며 서버 수락을 보장하지 않습니다. 등록 후 계정 식별 정보가 일치하는 새 본인 댓글을 다시 조회해 확인합니다. 이미 본인의 동일 내용이 조회되면 중복 등록하지 않습니다.
- 기본 갤러리는 `thesingularity`(특이점이 온다). 일반 갤러리는 `--kind main`, 마이너는 `--kind minor`.
- 글 작성, 개별 댓글에 대한 답글, 수정·삭제, 추천, 업로드, 미니·인물 갤러리는 미지원입니다. `write`는 등록하지 않고 `UNSUPPORTED_OPERATION`을 반환합니다.
- 댓글 전송 후 `WRITE_UNCONFIRMED`가 나오면 이미 등록됐을 가능성이 있으므로 재전송하지 말고 댓글 목록을 확인하세요. `USER_ACTION_REQUIRED`는 CAPTCHA 등 추가 인증이 필요하다는 뜻입니다. 댓글 응답의 `error.details.version`은 `v2`, `v3`, `unknown`을 구분합니다. v3는 백그라운드 검사이므로 이미지 퍼즐을 직접 풀어야 한다는 뜻은 아닙니다. 서버가 요청한 인증은 우회하지 않습니다.

출력은 JSON입니다. `ok:true`는 명령 처리 성공이고, 로그인 여부는 별도의 `authenticated` 값입니다. 상태 파일이 없으면 `status`는 `authenticated:false`를 반환합니다. 실패는 `ok:false`와 오류 코드를 반환하고 종료 코드 2로 끝납니다. `--help`, `capabilities`로 전체 사용법과 지원 범위를 확인할 수 있습니다.

## 로그인과 세션

`login` 실행 후 터미널에서 비밀번호를 입력합니다. 비밀번호는 저장하지 않습니다. `msign.dcinside.com` 로그인에 모바일 User-Agent와 모바일 복귀 URL을 사용하고, 모바일 갤러리의 계정 필드와 로그아웃 표시를 검증한 다음 세션을 저장합니다. PC 페이지로 로그인 여부를 대신 확인하지 않습니다. 목록·상태 페이지가 닉네임을 노출하지 않으면 `nickname`은 null일 수 있습니다.

0.4.1은 모바일 HTML/AJAX 요청 헤더와 리다이렉트의 Referer 처리를 맞추고, 로그인 폼에서 체크된 `loginCash`의 기본값을 그대로 전송합니다. 이전의 빈 값 전송과 다릅니다. 비밀번호 규칙 변경 안내에 지원하는 “나중에 변경” 버튼이 있으면 공개 스크립트의 동작을 확인해 안내를 미루고 계속 진행합니다. 비밀번호를 변경하지 않으며, 최종 모바일 인증을 따로 확인합니다. 로그인 실패 진단에는 경로·인증 표시 유무만 포함하고 비밀번호·쿠키·토큰 값은 포함하지 않습니다.

기존 PC 로그인 쿠키만으로는 모바일에서 로그인되지 않을 수 있습니다. 공개 조회는 `--anonymous`로 계속 사용할 수 있으며, 인증이 필요할 때 `AUTH_FAILED` 또는 `LOGIN_REQUIRED`가 나오면 `./scripts/dcinside login --user YOUR_ID`로 모바일 로그인 세션을 새로 저장하세요. 기존 세션을 자동 삭제하지 않습니다.

세션 쿠키는 기본적으로 `~/.local/state/dcinside/session.json`에 저장됩니다. `XDG_STATE_HOME` 또는 `DCINSIDE_STATE_DIR`로 바꿀 수 있고, 명령 앞의 `--state-dir DIR`도 지원합니다. 폴더 권한은 700, 파일 권한은 600이며 **파일 자체는 암호화되지 않습니다**. 쿠키는 계정 접근 권한이므로 공유·커밋하지 마세요. 설치·업데이트 패키지는 쿠키를 포함하지 않습니다.

로컬 세션은 최대 7일 보관하며 서버가 먼저 만료시킬 수 있습니다. 만료되면 다시 로그인하세요. 공개 글은 `--anonymous`로 로그인 없이 읽을 수 있습니다. `logout`은 이 도구의 파일만 삭제하고 다른 브라우저를 로그아웃시키지는 않습니다. CAPTCHA나 추가 인증을 요구하면 중단하고 `USER_ACTION_REQUIRED`를 반환합니다. 자동으로 브라우저를 열거나 인증을 우회하지 않습니다.

저장된 세션을 사용하는 명령은 요청 중 갱신된 쿠키도 보존합니다. CAPTCHA 거절 때도 갱신하되 최초 로그인 기준 7일 만료 시점은 연장하지 않습니다. 같은 세션의 명령은 순서대로 실행하세요. 동시 실행에는 `SESSION_BUSY`를 반환하며 네트워크 요청을 시작하지 않습니다. 쿠키 저장 실패 경고 `SESSION_SAVE_FAILED`가 있더라도 게시 결과는 그대로 유효하므로 댓글을 재전송하지 마세요.

`--password-stdin`은 이미 준비된 신뢰할 수 있는 비밀 입력 파이프용입니다. 비밀번호를 명령줄 인자·셸 기록·소스 파일에 넣지 마세요. 로그인 허가가 다른 외부 게시 행위까지 허가하는 것은 아닙니다.

## 검증

```sh
python3 -m unittest discover -s tests -v
```

이 테스트 명령은 `tests/`가 포함된 소스 프로젝트에서 실행합니다. 테스트는 가짜 응답을 이용해 파서·리다이렉트·세션 저장·지원하지 않는 작업을 검사합니다. 실사이트 검증은 별도로 수행하며 공개 글 조회, 사용자가 승인한 로그인과 댓글 작성만 수행합니다.

0.4.0 모바일 전환 검증(2026-10-07): 공개 마이너/일반 갤러리 목록, 본문과 원본 이미지 링크, 댓글과 답글, 목록·댓글 페이지 이동을 CLI로 실사이트에서 확인했습니다. 자동 테스트는 모바일 로그인 복귀·인증 판정, CSRF 헤더, 전송 폼과 대상 검사, 본인 계정 확인, 중복 방지, CAPTCHA 중단, 타임아웃·불명확한 응답에서 재시도 금지, 세션 쿠키 보호를 검사합니다.

0.4.1 실사이트 인증 검증(2026-10-07): 사용자가 터미널에서 비밀번호를 입력한 뒤 모바일 로그인, 세션 저장, 별도 `status` 명령의 인증 유지, 인증한 계정의 댓글 미리보기까지 확인했습니다. 비밀번호 변경 안내의 계속 진행 처리, 기본 체크된 로그인 항목 전송, 모바일 요청 헤더를 보완했습니다.

사용자가 지정한 같은 글에 승인된 두 문구를 각각 한 번 제출했지만, 서버는 두 요청 모두 “등록하기에 적합한 단어가 아닙니다.”라고 거절했습니다. 댓글 목록에서도 등록을 확인하지 못했습니다. 특정 문구가 금칙어인지, 다른 요청 검사에서 거절됐는지는 확인되지 않았으며 댓글 등록 성공은 여전히 미검증입니다. 사용자의 댓글을 임의 변경하거나 자동 재전송하지 않습니다. CAPTCHA 면제를 보장하지 않으며 브라우저·기기 검사용 쿠키를 임의 생성하지 않습니다.

자동 테스트 46개는 로그인 폼 체크박스의 기본값·비밀번호 변경 안내의 안전한 계속 진행·헤더/리다이렉트 처리·댓글 전송 값·개인 정보 보호·중복 및 재시도 방지를 포함합니다.

이전 0.3.1의 PC 댓글 전송은 2026-10-06에 서버가 reCAPTCHA v3를 요구해 거절했으며, 등록 완료는 확인하지 못했습니다. 모바일 전환은 접근 경로와 폼 구현의 변경이며 이 인증을 우회하는 기능이 아닙니다.
