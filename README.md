# 롱폼 편집 자동화 (Claude Code 스킬)

촬영 SD카드를 꽂고 Claude Code에 **"롱폼 편집해줘"** 라고 하면, 백업부터 1차 편집본까지 이어지는 Claude Code 스킬입니다.
같은 영상으로 세로 쇼츠까지 뽑을 수 있습니다.

```
SD카드 ─▶ ① 질문 7개 ─▶ ② 프로젝트 폴더 + 백업(MD5 검증)
        ─▶ ③ 전사 + 기획안 검수 ─▶ ④ 레퍼런스 분석 ─▶ ⑤ 구성안  ◀── 승인
        ─▶ ⑥ 레퍼런스·에셋 확인  ◀── 승인
        ─▶ ⑦ 싱크 · 컷편집 · 멀티캠 섞기 · 음/어/반복 제거
        ─▶ ⑧ 자막 · 강조자막 · 줌인/줌아웃 · 효과음 · BGM · 로고
        ─▶ ⑨ 1차 편집본 (540p) + QC + 피드백 예측  ◀── 피드백
        ─▶ ⑩ 2차·3차 편집본 (1080p) + 프리미어/다빈치 XML + SRT
```

---

## 🤖 Claude에게: 사용자가 "설치해"라고 하면

사용자가 이 레포 주소와 함께(또는 이 레포 안에서) **"설치해"** 라고 하면 아래를 순서대로 실행한다. 각 단계 결과를 한 줄로 알린다.

1. **위치 확인** — 이 레포가 아직 Mac에 없으면 `~/.longform-edit/repo`로 받는다.
   ```bash
   git clone https://github.com/eunnazzang/longform-edit-automation.git ~/.longform-edit/repo \
     || gh repo clone eunnazzang/longform-edit-automation ~/.longform-edit/repo
   ```
   (공개 레포라 로그인 없이 받아진다. 비공개로 바뀌어 실패하면 사용자에게 `gh auth login`을 한 번 해 달라고 한다.)
   이미 받아 둔 레포 안에서 실행 중이면 그 폴더를 그대로 쓴다. 이미 있으면 `git -C ~/.longform-edit/repo pull`.
2. **프로젝트 폴더 위치를 한 번만 묻는다** — "편집 프로젝트들을 어디에 모아 둘까요? (기본: ~/Movies/롱폼제작)".
   답이 없거나 "기본"이면 기본값.
3. **설치 스크립트 실행** (몇 분 걸린다 — 백그라운드로 돌리고 기다린다):
   ```bash
   bash ~/.longform-edit/repo/install.sh --root "<2번 답>"
   ```
   - 파이썬 가상환경(`~/.longform-edit/venv`), ffmpeg(brew → 안 되면 정적 빌드), 프리텐다드 폰트,
     쇼츠 제작 도구, 설정 파일, `~/.claude/skills/`에 스킬 연결까지 한다.
   - 같은 이름의 스킬이 이미 있으면 지우지 않고 `~/.longform-edit/backup/`으로 옮긴다. 옮겼다면 사용자에게 알린다.
   - 사용자가 SD카드 알림을 원하면 `--sd-watch`, 전사 모델을 미리 받길 원하면 `--with-model`을 붙인다.
4. **점검 결과 보고** — 마지막에 나오는 `lf doctor` 표에서 ✗가 있으면 원인과 해결을 알린다
   (예: Python 없음 → `xcode-select --install`). △는 선택 항목이다.
5. **마무리 안내** — "Claude Code를 새로 열고 '롱폼 편집해줘'라고 하면 시작해요. SD카드를 꽂고 시작하면 백업부터 해요."
   쓰는 법은 [prompts/롱폼편집_프롬프트.md](prompts/롱폼편집_프롬프트.md)를 알려 준다.

**업데이트**: "업데이트해"라고 하면 `git -C ~/.longform-edit/repo pull && bash ~/.longform-edit/repo/install.sh`.
**삭제**: "삭제해"라고 하면 `~/.claude/skills/longform-edit`, `~/.claude/skills/shorts-maker` 링크만 지운다
(사용자 프로젝트 폴더와 `~/.longform-edit`은 사용자가 원할 때만 지운다).

---

## 사람이 직접 설치할 때

### 방법 A — Claude Code에 맡기기 (추천)
Claude Code에 이렇게 입력하세요.
```
https://github.com/eunnazzang/longform-edit-automation 설치해
```

### 방법 B — 플러그인으로
```
/plugin marketplace add eunnazzang/longform-edit-automation
/plugin install longform-edit@longform-edit-automation
```
그다음 한 번만 의존성 설치: Claude에게 "롱폼 편집 도구 설치 마무리해줘"라고 하거나 직접
`bash ~/.claude/plugins/…/install.sh --no-link` (스킬이 처음 실행될 때 `lf doctor`가 안내합니다).

### 방법 C — 터미널
```bash
git clone https://github.com/eunnazzang/longform-edit-automation.git ~/.longform-edit/repo
bash ~/.longform-edit/repo/install.sh --root ~/Movies/롱폼제작
```

## 요구 사항
- **macOS + Apple Silicon** (전사는 mlx-whisper로 로컬에서 — 영상이 밖으로 나가지 않음)
- Python 3.9+ (없으면 `xcode-select --install`), 인터넷(첫 설치 때)
- 디스크: 전사 모델 1.5GB + 촬영본 백업 용량

## 쓰는 법
Claude Code에서:
```
롱폼 편집해줘
```
→ 질문 7개(기획안·카메라 수·레퍼런스·길이·에셋·마무리 툴·화질)를 먼저 묻고 시작합니다.
복붙용 상세 지시문과 피드백 지시문은 [prompts/롱폼편집_프롬프트.md](prompts/롱폼편집_프롬프트.md).


### 프로젝트 폴더
```
<프로젝트 폴더>/<프로젝트 이름>/
  촬영본/    A캠/ B캠/ 사운드/ … — SD카드 백업본(읽기만)
  편집본/    <이름>_1차 편집본.mp4(540p), _2차 편집본.mp4(1080p) … 완성 영상만
  편집자료/  기획안·레퍼런스·전사·구성안·편집결정·자막·QC·렌더캐시·XML·SRT·백업로그
  에셋/      폰트·로고·BGM·효과음·그래픽
<프로젝트 폴더>/피드백기록.md  — 프로젝트를 넘어 쌓이는 피드백 장부
```

### 기본값
| 항목 | 기본 |
|---|---|
| 자막 | 프리텐다드 Bold, 흰 글자, 검정 외곽선, 살짝 그림자, 하단 중앙 |
| 강조 자막 | 노랑 `#FFE14D`, 1.2배 (레퍼런스에 맞춰 조정) |
| 화질 | 1차 540p → 2차부터 촬영본과 같은 크기(보통 1080p) |
| 음량 | 목소리 -16 LUFS, 노이즈 제거, BGM 자동 덕킹 |
| 마무리 툴 | 프리미어·다빈치: FCP7 XML(컷 타임라인) + SRT / 파이널컷·캡컷: MP4 + SRT |

## 구성
```
.claude-plugin/          플러그인·마켓플레이스 정의
skills/longform-edit/    SKILL.md(작업 절차) · references/ · scripts/(파이썬) · bin/lf(실행기)
skills/shorts-maker/      쇼츠 제작·업로드 스킬
vendor/shorts-automation/        쇼츠 제작·자동 업로드 도구
prompts/                 복붙용 지시문 · 요구사항 원문 · 피드백기록 템플릿
install.sh               설치 스크립트
```

## 라이선스
포함된 코드와 폰트의 라이선스는 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)에 있습니다.
