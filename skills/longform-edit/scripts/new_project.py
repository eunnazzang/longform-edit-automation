#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""프로젝트 폴더를 만든다(이미 있으면 빠진 하위 폴더만 채운다).

사용:  new_project.py "<프로젝트 이름>" [--root <프로젝트들을 모아 두는 폴더>]
       기본 root = ~/.longform-edit/config.json 의 projects_root

<root>/<이름>/
  촬영본/    카메라·사운드별로 정리된 원본 (A캠/ B캠/ 사운드/ …) — 읽기만, 수정·삭제 금지
  편집본/    렌더해서 뽑은 완성 영상만 (<이름>_1차 편집본.mp4 …)
  편집자료/  그 외 편집 진행 자료 전부 (기획안·레퍼런스·전사·구성안·편집결정·자막·렌더캐시·QC·XML·로그)
  에셋/      폰트·로고·자막 디자인·BGM·효과음·그래픽·엔딩
마지막 줄에 프로젝트 경로를 출력한다.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))
from common import ASSETS, EDITS, SHOOT, WORK, config, nfc, save_json  # noqa: E402

SUB = {
    SHOOT: [],
    EDITS: [],
    WORK: ["기획안", "레퍼런스", "전사", "구성안", "시트", "중간저장", "렌더캐시", "QC", "로그", "백업로그"],
    ASSETS: ["폰트", "로고", "BGM", "효과음", "그래픽"],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name")
    ap.add_argument("--root", default=None)
    a = ap.parse_args()
    root = os.path.expanduser(a.root or config()["projects_root"])
    name = nfc(re.sub(r'[\\/:*?"<>|]', "_", a.name.strip()))
    proj = os.path.join(root, name)
    made = []
    for top, subs in SUB.items():
        for d in [top] + [os.path.join(top, s) for s in subs]:
            p = os.path.join(proj, d)
            if not os.path.isdir(p):
                os.makedirs(p)
                made.append(d)
    info = os.path.join(proj, WORK, "프로젝트정보.json")
    if not os.path.exists(info):
        save_json({"name": name, "answers": {}, "_설명": "STEP 0 질문 7개 답을 answers에 적는다"}, info)
    print(f"새로 만든 폴더 {len(made)}개" if made else "이미 있는 프로젝트 — 빠진 폴더 없음")
    print(proj)


if __name__ == "__main__":
    main()
