---
name: shorts-maker
description: 롱폼 영상에서 세로 쇼츠(1080×1920)를 뽑고 유튜브·인스타에 예약 업로드한다 — 전사, 얼굴 크롭, 후킹 제목, 자막 v3.1, 프리미어 XML, MP4, 자동 업로드까지. "쇼츠 만들어줘", "이 롱폼으로 쇼츠 뽑아줘", "쇼츠 업로드" 같은 요청에 쓴다.
---

# 쇼츠 제작

코드와 전체 문서는 이 레포의 `vendor/shorts-automation/`에 있다.
**작업 전에 `vendor/shorts-automation/README.md`와 `PROCESS.md`를 읽고 그 순서·규칙을 그대로 따른다.**

실행은 롱폼 스킬의 실행기로: `L="<이 스킬 폴더>/../longform-edit/bin/lf"`

| 단계 | 명령 |
|---|---|
| ① 전사 | `$L shorts/transcribe.py "<롱폼>.mp4" <words.json>` |
| ② 얼굴 타임라인 | `$L shorts/face_timeline.py "<롱폼>.mp4"` (facescan 필요 — `lf doctor`로 확인) |
| ②' 화자 타임라인 | `$L shorts/speaker_timeline.py --help` |
| ③ 클립정의.json | `vendor/shorts-automation/examples/클립정의_예시.json` 참고 |
| ④ 프리미어 XML + 클립 | `$L shorts/shorts_premiere.py "<롱폼>.mp4" words.json 클립정의.json --out <출력> --faces faces.json` |
| ⑤ 완성 MP4 | `$L shorts/xml_to_mp4.py <출력>/쇼츠_프리미어.xml --out <완성본>` |
| ⑥ 자동 업로드 | `vendor/shorts-automation/upload/설명서.md` (최초 1회 OAuth 연결은 사용자가 직접) |

## 사람이 개입하는 두 지점 (건너뛰지 않는다)
1. **구간 확인** — 후보 구간이 혼자 봐도 말이 되는지.
2. **후킹 제목 승인** — A안/B안 표 → `1. A / 2. 직접 수정 / 3. 삭제`로 답받기. 승인 전 파일명 확정 금지.

## 폴더
롱폼 프로젝트에서 쇼츠를 뽑을 때는 산출물을 `편집자료/쇼츠/`(작업 파일)와 `편집본/쇼츠/`(완성 MP4)에 둔다.
롱폼 프로젝트가 아니면 사용자가 지정한 폴더에 README 구조대로.

## 커스터마이즈
`shorts/shorts_render.py` 상단 상수: `WATERMARK`(현재 "비건먼지 Veganmonji"), 영상 존 위치, 제목 색, 자막 위치(`CAP_FRAC`).
