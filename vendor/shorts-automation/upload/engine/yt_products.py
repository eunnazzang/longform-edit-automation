"""유튜브 스튜디오 '제품 태그' 자동화 (쇼핑 제휴 상품을 영상에 태그).

공식 API에 제품 태그 필드가 없어, 로그인된 스튜디오 프로필로 세부정보 화면을 직접 조작한다.
UI 개편 시 선택자 수정이 필요할 수 있다. 실패하면 logs/ 에 스크린샷이 남는다.

선택자(2026-07 실측):
 - 제품 태그 편집 트리거: #shopping-toolbar-edit (aria: '제품 수정')
 - 다이얼로그 검색창 placeholder: '제품을 검색하거나 제품 링크를 붙여넣으세요.'
 - 결과 카드: ytshopping-product-* 계열, 각 카드에 추가(+) 버튼
 - 다이얼로그 확정: '완료' / 취소: '취소'
 - 페이지 저장: #save

제품은 config.json 의 "products" 로 지정한다:
  "products": [{"query": "검색어", "exact": "제품 제목 전체", "price": "₩738,620", "prefix": false}]
exact(제목 완전일치) + price 로 유사 리스팅(같은 가격의 다른 판매글)을 걸러 정확히 한 건만 태그한다.
prefix=true 면 제목 앞부분 일치로 매칭(제목이 매우 긴 상품용).
"""
from __future__ import annotations

import time
from datetime import datetime

from settings import CONFIG_DIR, LOGS_DIR, get_logger
from yt_uploader import UploadResult

PROFILE_DIR = CONFIG_DIR / "youtube_studio_profile"
EDIT_URL = "https://studio.youtube.com/video/{vid}/edit"

# 그림자 DOM까지 훑어 id/aria-label 로 찾아 클릭
_JS_CLICK = """(sel)=>{const f=(r)=>{for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])){
 if(e.id===sel||e.getAttribute('aria-label')===sel)return e;
 if(e.shadowRoot){const x=f(e.shadowRoot);if(x)return x;}}return null;};
 const el=f(document); if(!el)return 'notfound';
 el.scrollIntoView({block:'center'}); el.click(); return 'ok';}"""

_JS_CLICK_TEXT = """(txt)=>{const f=(r)=>{
 for(const e of (r.querySelectorAll?r.querySelectorAll('button,ytcp-button,tp-yt-paper-button,[role=button]'):[]))
   if((e.innerText||'').trim()===txt && !e.hasAttribute('disabled'))return e;
 for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])) if(e.shadowRoot){const x=f(e.shadowRoot);if(x)return x;}
 return null;}; const el=f(document); if(!el)return 'notfound';
 el.scrollIntoView({block:'center'}); el.click(); return 'ok';}"""

# 검색창에 질의어 입력(React 스타일 value setter 사용)
_JS_SEARCH = """(q)=>{const f=(r)=>{
 for(const e of (r.querySelectorAll?r.querySelectorAll('input'):[]))
   if((e.placeholder||'').includes('제품을 검색')) return e;
 for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])) if(e.shadowRoot){const x=f(e.shadowRoot);if(x)return x;}
 return null;}; const el=f(document); if(!el)return 'notfound';
 const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
 el.focus(); set.call(el,''); el.dispatchEvent(new Event('input',{bubbles:true}));
 set.call(el,q); el.dispatchEvent(new Event('input',{bubbles:true}));
 el.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:13,bubbles:true}));
 el.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',keyCode:13,bubbles:true}));
 return 'ok';}"""

# 결과 카드를 '제목 완전일치'로 찾아 클릭 → 세부정보 모달 열기
_JS_OPEN = """(spec)=>{
 const norm=(s)=>(s||'').replace(/\\s+/g,'').toLowerCase();
 const want=norm(spec.exact), price=norm(spec.price||''), seller=norm(spec.seller||'');
 const cards=[];
 const walk=(r)=>{ for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])){
   const t=e.tagName.toLowerCase();
   if(t.startsWith('ytshopping')&&/card|item|row|result/.test(t)) cards.push(e);
   if(e.shadowRoot) walk(e.shadowRoot); } };
 walk(document);
 let hit=null, seen=[];
 for(const c of cards){
   const lines=(c.innerText||'').trim().split('\\n').map(x=>x.trim()).filter(Boolean);
   if(!lines.length) continue;
   const title=norm(lines[0]);
   if(lines.length<=6) seen.push(lines[0].slice(0,50));
   const titleOk = spec.prefix ? title.startsWith(want) : title===want;
   if(!titleOk) continue;
   const body=norm(c.innerText);
   if(price && !body.includes(price)) continue;
   if(seller && !body.includes(seller)) continue;
   if(!hit || (c.innerText||'').length < (hit.innerText||'').length) hit=c;
 }
 if(!hit) return {ok:false, why:'제목 완전일치 없음', seen:[...new Set(seen)].slice(0,8)};
 hit.scrollIntoView({block:'center'});
 const clickable=hit.querySelector('img,ytcp-button,button,[role=button]')||hit;
 clickable.click();
 return {ok:true, title:(hit.innerText||'').split('\\n')[0]};
}"""

# 세부정보 모달에서 '태그' 버튼 클릭(모달 제목으로 대상 재확인)
_JS_TAG_MODAL = """(spec)=>{
 const norm=(s)=>(s||'').replace(/\\s+/g,'').toLowerCase();
 const want=norm(spec.exact);
 let modal=null;
 const walk=(r)=>{ for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])){
   const t=e.tagName.toLowerCase();
   if((t.includes('dialog')||t.includes('product-details'))&&(e.innerText||'').includes('세부정보')) modal=modal||e;
   if(e.shadowRoot) walk(e.shadowRoot); } };
 walk(document);
 const scope=modal||document;
 const txt=norm(scope.innerText||'');
 const okTitle = spec.prefix ? txt.includes(want.slice(0,20)) : txt.includes(want);
 if(!okTitle) return {ok:false, why:'모달 제목 불일치'};
 if(spec.seller && !txt.includes(norm(spec.seller))) return {ok:false, why:'모달 판매처 불일치'};
 let btn=null;
 const bwalk=(r)=>{ for(const e of (r.querySelectorAll?r.querySelectorAll('button,ytcp-button,[role=button]'):[]))
   { if((e.innerText||'').trim()==='태그'){ btn=btn||e; } }
   for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])) if(e.shadowRoot) bwalk(e.shadowRoot); };
 bwalk(scope);
 if(!btn) return {ok:false, why:'태그 버튼 없음'};
 const off = btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled')==='true'
             || (btn.className||'').toString().includes('disabled');
 if(off) return {ok:false, why:'이미태그됨'};
 btn.scrollIntoView({block:'center'}); btn.click();
 return {ok:true};
}"""

# 세부정보 모달이 열려 있는가
_JS_MODAL_OPEN = """()=>{let open=false;
 const w=(r)=>{ for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])){
   const t=e.tagName.toLowerCase();
   if(t.includes('dialog')&&(e.innerText||'').includes('세부정보')&&e.offsetParent!==null) open=true;
   if(e.shadowRoot) w(e.shadowRoot); } };
 w(document); return open;}"""

# 태그된 제품 전체 삭제(재태그 시)
_JS_CLEAR = """()=>{let n=0;
 const walk=(r)=>{ for(const e of (r.querySelectorAll?r.querySelectorAll('button,ytcp-button,[role=button]'):[]))
   { if((e.innerText||'').trim()==='삭제'){ e.click(); n++; } }
   for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])) if(e.shadowRoot) walk(e.shadowRoot); };
 walk(document); return n;}"""

# 우측 '태그된 제품' 패널 요약
_JS_TAGGED = """()=>{const f=(r)=>{for(const e of (r.querySelectorAll?r.querySelectorAll('*'):[])){
 const t=e.tagName.toLowerCase();
 if(t.includes('product-picker')||t.includes('product-tagging-toolbar')){
   const m=(e.innerText||'').match(/태그된 제품[^\\n]*/); if(m) return m[0]; }
 if(e.shadowRoot){const x=f(e.shadowRoot);if(x)return x;}}return null;}; return f(document)||'';}"""


class ProductTagger:
    """영상 하나에 지정 제품들을 태그한다(이미 태그된 제품은 건드리지 않음)."""

    def __init__(self, products: list):
        self.log = get_logger()
        self.products = products
        self._pw = None
        self.context = None
        self.page = None

    def connected(self) -> bool:
        return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())

    def _launch(self):
        if self.context:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1440, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
            locale="ko-KR",
        )
        try:
            self.context = self._pw.chromium.launch_persistent_context(channel="chrome", **kwargs)
        except Exception:
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        # 프로필에 남아있던 다른 사이트 탭(메타 로그인 등)을 잡으면 조작이 엉뚱한 곳에 간다.
        # 스튜디오 탭이 있으면 재사용하고, 없으면 새 탭을 연다.
        page = None
        for p_ in self.context.pages:
            try:
                if "studio.youtube.com" in (p_.url or ""):
                    page = p_
                    break
            except Exception:
                continue
        self.page = page or self.context.new_page()
        # 저장 안 한 변경사항 이탈 경고가 뜨면 자동 수락(다음 영상으로 넘어가기 위함)
        self.page.on("dialog", lambda d: d.accept())

    def _shot(self, tag: str) -> str:
        name = f"제품태그오류_{tag}_{datetime.now():%H%M%S}.png"
        try:
            self.page.screenshot(path=str(LOGS_DIR / name))
            return f" (스크린샷: logs/{name})"
        except Exception:
            return ""

    def tag(self, video_id: str, dry_run: bool = False, retag: bool = False) -> UploadResult:
        if not self.connected():
            return UploadResult(False, "스튜디오 미연결 — setup/5_유튜브스튜디오_연결.command 실행 필요.")
        try:
            self._launch()
        except Exception as e:
            return UploadResult(False, f"브라우저 실행 실패: {e}")

        page = self.page
        try:
            page.goto(EDIT_URL.format(vid=video_id), wait_until="domcontentloaded", timeout=60_000)
            time.sleep(8)
            if "accounts.google.com" in page.url or "/signin" in page.url:
                return UploadResult(False, "스튜디오 로그인이 풀렸습니다. 재연결 필요.")
            if video_id not in (page.url or ""):     # 다른 사이트/탭이면 한 번 더 이동
                page.goto(EDIT_URL.format(vid=video_id), wait_until="domcontentloaded", timeout=60_000)
                time.sleep(8)
                if video_id not in (page.url or ""):
                    return UploadResult(False, f"편집 화면 진입 실패(현재 {page.url[:60]})")

            before = ""
            for _ in range(3):                      # 툴바 로딩이 늦으면 '없음'으로 오판된다
                before = page.evaluate(_JS_TAGGED) or ""
                if before and "없음" not in before:
                    break
                time.sleep(3)
            if not retag and "태그된 제품" in before and "없음" not in before:
                # 이미 태그가 있는 영상은 건드리지 않는다(덮어쓰기 방지)
                self.log.info(f"  이미 태그됨({before}) — 건너뜀: {video_id}")
                return UploadResult(True, f"이미태그됨({before})", f"https://youtu.be/{video_id}")

            if page.evaluate(_JS_CLICK, "shopping-toolbar-edit") != "ok":
                return UploadResult(False, "제품 태그 항목 없음(쇼핑 미지원 영상)." + self._shot(f"항목_{video_id}"))
            time.sleep(6)
            if retag:
                removed = page.evaluate(_JS_CLEAR)
                if removed:
                    self.log.info(f"  기존 태그 {removed}건 삭제 후 재태그: {video_id}")
                    time.sleep(3)

            added, failed, already = [], [], []
            for p in self.products:
                nick = p["exact"][:14]
                if page.evaluate(_JS_SEARCH, p["query"]) != "ok":
                    failed.append(f"{nick}:검색창없음"); continue
                time.sleep(7)
                spec = {"exact": p["exact"], "price": p.get("price", ""),
                        "seller": p.get("seller", ""), "prefix": bool(p.get("prefix"))}
                r = page.evaluate(_JS_OPEN, spec)
                if not r.get("ok"):
                    # 결과 로딩이 늦으면 매칭이 빈다 — 한 번 더 검색해 재시도
                    time.sleep(5)
                    r = page.evaluate(_JS_OPEN, spec)
                if not r.get("ok"):
                    page.evaluate(_JS_SEARCH, p["query"]); time.sleep(9)
                    r = page.evaluate(_JS_OPEN, spec)
                if not r.get("ok"):
                    failed.append(f"{nick}:{r.get('why')}"); continue
                time.sleep(4)
                m = page.evaluate(_JS_TAG_MODAL, spec)
                if m.get("ok"):
                    added.append(r.get("title", nick)[:28]); time.sleep(4)
                elif m.get("why") == "이미태그됨":
                    already.append(nick)
                    page.keyboard.press("Escape"); time.sleep(2)
                else:
                    failed.append(f"{nick}:{m.get('why')}")
                    page.keyboard.press("Escape"); time.sleep(2)
                # 모달이 남아 있으면 확정 버튼이 가려진다 — 반드시 닫고 진행
                for _ in range(3):
                    if not page.evaluate(_JS_MODAL_OPEN):
                        break
                    page.keyboard.press("Escape"); time.sleep(2)
            state = page.evaluate(_JS_TAGGED) or ""

            if dry_run:
                page.evaluate(_JS_CLICK_TEXT, "취소"); time.sleep(2)
                return UploadResult(True, f"[모의] 추가 {len(added)} / 실패 {failed} / 상태 {state}")

            if not added:
                page.evaluate(_JS_CLICK_TEXT, "취소"); time.sleep(2)
                if already and not failed:
                    return UploadResult(True, f"이미태그됨(전체 {len(already)}개)", f"https://youtu.be/{video_id}")
                return UploadResult(False, f"제품 매칭 실패: {failed}" + self._shot(f"매칭_{video_id}"))

            # 다이얼로그 확정 — 쇼츠: '완료' 1단계 / 롱폼: '다음' → 타임스탬프 화면 → '완료'
            if page.evaluate(_JS_CLICK_TEXT, "완료") != "ok":
                if page.evaluate(_JS_CLICK_TEXT, "다음") != "ok":
                    now = page.evaluate(_JS_TAGGED) or ""
                    page.evaluate(_JS_CLICK_TEXT, "취소"); time.sleep(2)
                    if "태그된 제품" in now and "없음" not in now:
                        # 이미 전부 태그돼 있어 저장할 변경이 없는 경우(확정 버튼 비활성)
                        self.log.info(f"  이미 태그됨({now}) — 변경 없음: {video_id}")
                        return UploadResult(True, f"이미태그됨({now})", f"https://youtu.be/{video_id}")
                    return UploadResult(False, "확정 버튼(완료/다음)을 찾지 못했습니다." + self._shot(f"확정_{video_id}"))
                time.sleep(6)
                # 타임스탬프 추가(선택사항) — 지정 없이 완료
                if page.evaluate(_JS_CLICK_TEXT, "완료") != "ok":
                    return UploadResult(False, "타임스탬프 단계 완료 실패." + self._shot(f"타임_{video_id}"))
            time.sleep(5)

            if page.evaluate(_JS_CLICK, "save") != "ok":
                page.evaluate(_JS_CLICK_TEXT, "저장")
            time.sleep(6)

            after = page.evaluate(_JS_TAGGED) or ""
            ok = ("태그된 제품" in after and "없음" not in after)
            partial = (len(added) + len(already)) < len(self.products)
            msg = (f"부분태그 {len(added)}/{len(self.products)}" if partial else f"제품 {len(added)}개 태그")
            msg += f"({after or state})" + (f" 실패:{failed}" if failed else "")
            if ok:
                self.log.info(f"  제품 태그 완료: {video_id} — {msg}")
                return UploadResult(True, msg, f"https://youtu.be/{video_id}")
            return UploadResult(False, f"저장 후 확인 실패({after})" + self._shot(f"확인_{video_id}"))
        except Exception as e:
            return UploadResult(False, f"제품 태그 자동화 오류: {e}" + self._shot(f"예외_{video_id}"))

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self.context = self._pw = self.page = None
