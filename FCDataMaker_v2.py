import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading, queue, sys, io, time, json, re
import os, asyncio, aiohttp
import pandas as pd
from bs4 import BeautifulSoup
from dataclasses import dataclass

# ── 색상 / 폰트 ──────────────────────────────────────────
TOSS_BLUE  = "#3182F6"
BG_WHITE   = "#FFFFFF"
GREY_TEXT  = "#4F4F4F"
LIGHT_GREY = "#F5F6F8"
FONT_FAMILY = "Spoqa Han Sans Neo"

# ── 경로 상수 ────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

DETAILS_CSV     = os.path.join(DATA_DIR, "details.csv")
FINAL_CSV       = os.path.join(DATA_DIR, "all_player_detail.csv")
CHECKPOINT_JSON = os.path.join(DATA_DIR, "checkpoint.json")

# ── Nexon 엔드포인트 ─────────────────────────────────────
URL_LIST   = "https://fconline.nexon.com/datacenter/PlayerList"
URL_DETAIL = "https://fconline.nexon.com/datacenter/PlayerAbility"
HEADERS    = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fconline.nexon.com/datacenter/",
}

# ── 선수 스탯 컬럼 순서 (v1 동일) ────────────────────────
STAT_NAMES = [
    "속력", "가속력", "골 결정력", "슛 파워", "중거리 슛", "위치 선정", "발리슛",
    "페널티 킥", "짧은 패스", "시야", "크로스", "긴 패스", "프리킥", "커브",
    "드리블", "볼 컨트롤", "민첩성", "밸런스", "반응 속도", "대인 수비", "태클",
    "가로채기", "헤더", "슬라이딩 태클", "몸싸움", "스태미너", "적극성", "점프",
    "침착성", "GK 다이빙", "GK 핸들링", "GK 킥", "GK 반응속도", "GK 위치 선정",
]

POSITION_DICT = {
    "FW": ",24,25,26,20,21,22,27,23,",
    "MF": ",13,14,15,17,18,19,9,10,11,16,12,",
    "DF": ",1,4,5,6,3,7,2,8,",
    "GK": ",0,",
}

FINAL_COLUMNS = (
    ["player_code", "player_name", "season", "position", "ovr",
     "height", "weight", "skill", "left_foot", "right_foot", "traits"]
    + STAT_NAMES
)


# ══════════════════════════════════════════════════════════
#   Section 2 — 유틸리티
# ══════════════════════════════════════════════════════════

def atomic_write_csv(df: pd.DataFrame, path: str, **kwargs) -> None:
    tmp = path + ".tmp"
    df.to_csv(tmp, **kwargs)
    os.replace(tmp, path)


def save_checkpoint(data: dict) -> None:
    tmp = CHECKPOINT_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, CHECKPOINT_JSON)


def load_checkpoint() -> dict:
    try:
        with open(CHECKPOINT_JSON, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


async def fetch_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    data: dict,
    extra_headers: dict | None = None,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> str | None:
    hdrs = {**HEADERS, **(extra_headers or {})}
    for attempt in range(max_retries + 1):
        try:
            async with session.post(
                url, data=data, headers=hdrs,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    return await r.text()
                print(f"  HTTP {r.status} (시도 {attempt + 1}/{max_retries + 1})")
        except asyncio.TimeoutError:
            print(f"  타임아웃 (시도 {attempt + 1}/{max_retries + 1})")
        except aiohttp.ClientError as e:
            print(f"  네트워크 에러 (시도 {attempt + 1}/{max_retries + 1}): {e}")
        if attempt < max_retries:
            await asyncio.sleep(base_delay * (2 ** attempt))
    return None


# ══════════════════════════════════════════════════════════
#   Section 3 — HTML 파싱 / 비동기 HTTP
# ══════════════════════════════════════════════════════════

def parse_player_html(spid: str, html: str) -> dict | None:
    """BeautifulSoup으로 PlayerAbility HTML 파싱. 순수 함수 (I/O 없음)."""
    try:
        soup = BeautifulSoup(html, "lxml")

        tdef = soup.select_one("div.tdefault")
        team_colors = []
        if tdef:
            team_colors = [
                a.get_text(strip=True)
                for a in tdef.select("div.selector_list ul li a.selector_item")
                if a.get_text(strip=True) not in ("소속 팀컬러", "단일팀")
            ]

        get_txt = lambda sel: (
            soup.select_one(sel).text.strip() if soup.select_one(sel) else ""
        )

        name = get_txt("div.nameWrap div.name, .info_line.info_name div.name")

        season = ""
        pcw = soup.select_one("div.playerCardWrap")
        if pcw:
            for cls in pcw.get("class", []):
                if cls.startswith("_"):
                    season = cls[1:]
                    break
        if not season:
            img = soup.select_one(
                "div.nameWrap div.season img[alt], "
                "div.info_line.info_name div.season img[alt]"
            )
            season = img["alt"].strip() if img and img.has_attr("alt") else ""

        position = get_txt(
            "div.content_header div.position, "
            ".info_line.info_ab span.position .txt"
        )
        ovr = get_txt("div.content_header .ovr.value, .info_line.info_ab span.value")

        to_int = lambda s: int("".join(filter(str.isdigit, s))) if s else 0
        salary_tag = (
            soup.select_one("div.playerCardInfoSide div.pay span")
            or soup.select_one("div.side_utils div.pay_side")
        )
        salary = int(salary_tag.text.strip()) if salary_tag else 0

        height = to_int(get_txt("span.etc.height"))
        weight = to_int(get_txt("span.etc.weight"))

        skill_text = get_txt("span.etc.skill span")
        skill = skill_text.count("★")

        foot_text = get_txt("span.etc.foot")
        m = re.search(r"L(\d)\s*[-–]\s*R(\d)", foot_text)
        left_foot, right_foot = (int(m[1]), int(m[2])) if m else (0, 0)

        traits = ",".join(
            t.text.strip()
            for t in soup.select("div.skill_wrap span.desc")
            if t.text.strip()
        )

        stat: dict = {nm: 0 for nm in STAT_NAMES}
        for li in soup.select("ul.data_wrap_playerinfo li.ab"):
            nm_tag  = li.select_one("div.txt")
            val_tag = li.select_one("div.value")
            if nm_tag and val_tag:
                nm  = nm_tag.text.strip()
                val = val_tag.text.strip().split(" ")[0]
                if nm in stat:
                    stat[nm] = to_int(val)

        return {
            "player_code": str(spid),
            "player_name": name,
            "salary": salary,
            "season": season,
            "position": position,
            "ovr": ovr,
            "height": height,
            "weight": weight,
            "skill": skill,
            "left_foot": left_foot,
            "right_foot": right_foot,
            "traits": traits,
            "team_colors": json.dumps(team_colors, ensure_ascii=False),
            **stat,
        }
    except Exception as e:
        print(f"❌ HTML 파싱 에러 {spid}: {e}")
        return None


async def fetch_detail_for_code(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    spid: str,
) -> dict | None:
    async with sem:
        extra = {"Referer": f"https://fconline.nexon.com/datacenter/PlayerInfo?spid={spid}"}
        pld = {
            "spid": spid, "n1Strong": 1, "n1Grow": 0,
            "n4TeamColorId": 0, "n4TeamColorLv": 0, "n1Change": 0,
            "strPlayerImg": (
                f"https://fo4.dn.nexoncdn.co.kr/live/externalAssets/"
                f"common/playersAction/p{spid}.png"
            ),
            "rd": "0",
        }
        html = await fetch_with_retry(session, URL_DETAIL, pld, extra_headers=extra)
        if html is None:
            print(f"⚠️ 상세정보 실패 (재시도 소진): {spid}")
            return None
        return parse_player_html(spid, html)


async def fetch_codes_for_job(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    job: dict,
) -> list[str]:
    async with sem:
        pld = {
            "strPlayerName": "", "strSeason": "",
            "strPosition": job["pos_code"],
            "n4SalaryMin": job["salary"], "n4SalaryMax": job["salary"],
            "n4OvrMin": job["ovr"],        "n4OvrMax": job["ovr"],
        }
        html = await fetch_with_retry(session, URL_LIST, pld)
        if html is None:
            return []
        soup = BeautifulSoup(html, "lxml")
        codes = [
            m.group(1)
            for tr in soup.select("div.tr")
            for m in [re.search(r"\.val\('(\d+)'\)", tr.get("onclick", ""))]
            if m
        ]
        return codes


# ── OVR 범위 탐색 (Phase 1용) ──────────────────────────

async def _get_ovr_info(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    salary: int,
    ovr_max: int,
) -> tuple[int, int | None, int | None]:
    """(cnt, max_ovr, min_ovr) 반환. 선수 없으면 (0, None, None)."""
    async with sem:
        pld = {
            "strPlayerName": "", "strSeason": "", "strPosition": "",
            "n4SalaryMin": salary, "n4SalaryMax": salary,
            "n4OvrMin": 0, "n4OvrMax": ovr_max,
        }
        html = await fetch_with_retry(session, URL_LIST, pld)
    if html is None:
        return 0, None, None
    soup = BeautifulSoup(html, "lxml")
    ovrs = []
    for tr in soup.select("div.tr"):
        m = re.search(r"\.val\('([0-9]+)'\)", tr.get("onclick", ""))
        if not m:
            continue
        code = m.group(1)
        val_tag = tr.select_one(f"span.skillData_{code}")
        if val_tag:
            try:
                ovrs.append(int(val_tag.get_text(strip=True)))
            except ValueError:
                pass
    if not ovrs:
        return 0, None, None
    return len(ovrs), max(ovrs), min(ovrs)


async def discover_ovr_for_salary(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    salary: int,
) -> dict | None:
    """이진탐색으로 (max_ovr, min_ovr) 반환. 선수 없으면 None."""
    cnt, max_ovr, _ = await _get_ovr_info(session, sem, salary, 200)
    if cnt == 0 or max_ovr is None:
        return None

    lo, hi = 0, max_ovr
    min_ovr = None
    while lo <= hi:
        mid = (lo + hi) // 2
        cnt_m, _, cur_min = await _get_ovr_info(session, sem, salary, mid)
        if cnt_m == 0:
            lo = mid + 1
        else:
            if cur_min is not None:
                min_ovr = cur_min if min_ovr is None else min(min_ovr, cur_min)
            hi = mid - 1

    if min_ovr is None:
        return None
    return {"max_ovr": max_ovr, "min_ovr": min_ovr}


# ══════════════════════════════════════════════════════════
#   Section 4 — 파이프라인
# ══════════════════════════════════════════════════════════

async def run_phase1(
    salary_range: range,
    max_con: int,
    stop_event: threading.Event,
    progress_cb,
) -> dict:
    """모든 salary의 OVR 범위를 동시에 탐색. 체크포인트 캐시 활용."""
    checkpoint  = load_checkpoint()
    ovr_results: dict = checkpoint.get("ovr_results", {})

    pending = [s for s in salary_range if str(s) not in ovr_results]
    total   = len(salary_range)

    if not pending:
        print("⏩ Phase 1 체크포인트 완료 → 건너뜀")
        return ovr_results

    print(f"=== [Phase 1] OVR 탐색: {len(pending)}개 급여 ===")
    sem = asyncio.Semaphore(max_con)

    async with aiohttp.ClientSession() as session:

        async def do_salary(salary: int) -> None:
            if stop_event.is_set():
                return
            result = await discover_ovr_for_salary(session, sem, salary)
            if result:
                ovr_results[str(salary)] = result
                print(f"✅ 급여 {salary} → max={result['max_ovr']}, min={result['min_ovr']}")
            else:
                print(f"⚠️ 급여 {salary}: 선수 없음 → 스킵")
            save_checkpoint({"ovr_results": ovr_results})
            progress_cb(len(ovr_results), total)

        await asyncio.gather(*[do_salary(s) for s in pending])

    return ovr_results


def generate_all_jobs(ovr_results: dict, salary_range: range) -> list[dict]:
    jobs = []
    for salary in salary_range:
        r = ovr_results.get(str(salary))
        if not r:
            continue
        for ovr in range(r["max_ovr"], r["min_ovr"] - 1, -1):
            for pos_name, pos_code in POSITION_DICT.items():
                jobs.append({
                    "salary": salary, "ovr": ovr,
                    "pos_code": pos_code, "pos_name": pos_name,
                })
    return jobs


def load_done_codes() -> set[str]:
    """details.csv에서 이미 수집된 player_code 집합을 로드."""
    if not os.path.exists(DETAILS_CSV):
        return set()
    try:
        df = pd.read_csv(DETAILS_CSV, usecols=["player_code"], on_bad_lines="skip")
        return set(df["player_code"].astype(str))
    except Exception as e:
        print(f"⚠️ details.csv 읽기 실패: {e}")
        return set()


def flush_buffer(buf: list, write_lock_dummy=None) -> None:
    """버퍼를 details.csv에 원자적으로 추가."""
    if not buf:
        return
    df_new = pd.DataFrame(buf)
    mode, header = ("a", False) if os.path.exists(DETAILS_CSV) else ("w", True)
    tmp = DETAILS_CSV + ".tmp_append"
    df_new.to_csv(tmp, index=False, mode="w", header=True, encoding="utf-8-sig")
    if mode == "a":
        with open(tmp, encoding="utf-8-sig") as f:
            rows = f.read().split("\n", 1)[1]
        with open(DETAILS_CSV, "a", encoding="utf-8-sig") as f:
            f.write(rows)
        os.remove(tmp)
    else:
        os.replace(tmp, DETAILS_CSV)


def finalize() -> None:
    """details.csv → all_player_detail.csv 최종 출력 (Bug 1 수정)."""
    if not os.path.exists(DETAILS_CSV):
        print(f"❌ {DETAILS_CSV} 없음 — 최종 파일 생성 불가")
        return
    df = pd.read_csv(DETAILS_CSV, on_bad_lines="skip")
    for col in STAT_NAMES:
        if col not in df.columns:
            df[col] = 0
    existing_cols = [c for c in FINAL_COLUMNS if c in df.columns]
    final_df = df[existing_cols]
    atomic_write_csv(final_df, FINAL_CSV, index=False, encoding="utf-8-sig")
    print(f"✅ 최종 파일 저장: {FINAL_CSV} ({len(final_df)}명)")


async def run_phase2(
    ovr_results: dict,
    salary_range: range,
    max_con: int,
    stop_event: threading.Event,
    progress_cb,
) -> None:
    """
    단일 세션 스트리밍 파이프라인.
    - done_codes:   이미 details.csv에 저장된 코드
    - queued_codes: 이미 detail 요청을 보낸 코드 (done_codes의 상위 집합)
                    → 여러 job이 같은 코드를 발견해도 중복 요청 방지
    - 단일 ClientSession + TCPConnector 로 연결 풀 공유
    - create_task 로 코드 발견 즉시 detail 요청 시작 (스트리밍)
    """
    done_codes:   set[str] = load_done_codes()
    queued_codes: set[str] = set(done_codes)
    q_lock   = asyncio.Lock()
    buf_lock = asyncio.Lock()
    buffer:   list = []
    jobs_done = [0]

    all_jobs   = generate_all_jobs(ovr_results, salary_range)
    total_jobs = len(all_jobs)

    if not all_jobs:
        print("⚠️ 수집할 job이 없습니다.")
        return

    print(f"=== [Phase 2] 스트리밍 수집 시작 ===")
    print(f"  job 수: {total_jobs}, max_con: {max_con}")
    print(f"  이미 완료: {len(done_codes)}명 스킵")

    code_con   = max(5, max_con // 5)
    detail_con = max_con
    connector = aiohttp.TCPConnector(limit=detail_con + code_con)
    async with aiohttp.ClientSession(connector=connector) as session:
        code_sem   = asyncio.Semaphore(code_con)
        detail_sem = asyncio.Semaphore(detail_con)
        pending_details: set = set()

        async def fetch_and_save(code: str) -> None:
            detail = await fetch_detail_for_code(session, detail_sem, code)
            if detail:
                async with buf_lock:
                    buffer.append(detail)
                    done_codes.add(code)
                    if len(buffer) >= 50:
                        flush_buffer(buffer[:])
                        buffer.clear()
                        print(f"💾 {len(done_codes)}명 저장")

        async def process_job(job: dict) -> None:
            if stop_event.is_set():
                return
            codes = await fetch_codes_for_job(session, code_sem, job)
            async with q_lock:
                new_codes = [c for c in codes if c not in queued_codes]
                queued_codes.update(new_codes)
            for code in new_codes:
                t = asyncio.create_task(fetch_and_save(code))
                pending_details.add(t)
                t.add_done_callback(pending_details.discard)
            jobs_done[0] += 1
            if jobs_done[0] % 20 == 0 or jobs_done[0] == total_jobs:
                print(f"  job {jobs_done[0]}/{total_jobs} | 수집: {len(done_codes)}명")
            progress_cb(jobs_done[0], total_jobs)

        await asyncio.gather(*[process_job(j) for j in all_jobs])
        if pending_details:
            await asyncio.gather(*list(pending_details), return_exceptions=True)
        async with buf_lock:
            if buffer:
                flush_buffer(buffer[:])
                buffer.clear()

    print(f"✅ Phase 2 완료 — 총 {len(done_codes)}명 수집")


async def run_pipeline_async(
    salary_range: range,
    max_con: int,
    stop_event: threading.Event,
    gui_queue: queue.Queue,
) -> None:

    def progress_cb(done: int, total: int) -> None:
        gui_queue.put(("progress", done, total))

    t0 = time.time()

    ovr_results = await run_phase1(
        salary_range, max_con, stop_event,
        lambda d, t: (progress_cb(d, t), None)[1],
    )
    if stop_event.is_set():
        return

    save_checkpoint({"ovr_results": ovr_results})

    await run_phase2(
        ovr_results, salary_range, max_con, stop_event,
        lambda d, t: (progress_cb(d, t), None)[1],
    )
    if stop_event.is_set():
        return

    finalize()
    print(f"\n✨ 총 소요 시간: {time.time() - t0:.1f}초 ✨")
    gui_queue.put(("done", True))


def run_pipeline(salary_range, max_con, stop_event, gui_queue):
    asyncio.run(run_pipeline_async(salary_range, max_con, stop_event, gui_queue))


# ══════════════════════════════════════════════════════════
#   Section 5 — GUI
# ══════════════════════════════════════════════════════════

class TextRedirector(io.TextIOBase):
    def __init__(self, log_queue: queue.Queue):
        self._q = log_queue
    def write(self, s: str) -> int:
        self._q.put(s)
        return len(s)
    def flush(self) -> None:
        pass


def setup_toss_style(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Horizontal.TProgressbar",
                    troughcolor=LIGHT_GREY, background="green")
    style.configure(".",
                    background=BG_WHITE, foreground=GREY_TEXT,
                    font=(FONT_FAMILY, 11))
    style.configure("TButton",
                    background=TOSS_BLUE, foreground="#fff",
                    borderwidth=0, padding=(12, 5),
                    font=(FONT_FAMILY, 11, "bold"))
    style.map("TButton",
              background=[("active", "#1671F3"), ("disabled", LIGHT_GREY)],
              foreground=[("disabled", "#9E9E9E")])
    style.configure("TLabel", background=BG_WHITE, foreground=GREY_TEXT)
    style.configure("TFrame", background=BG_WHITE)


@dataclass
class _ProgressMsg:
    done: int
    total: int


class CrawlerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("FC Online 크롤러 v2")
        root.geometry("520x185")
        self.stop_event  = threading.Event()
        self._log_queue  = queue.Queue()
        self._gui_queue  = queue.Queue()
        self.running     = False
        self.startup_choice: str | None = None

        # ── 버튼 행 ──────────────────────────────────────
        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")

        self.btn_start = ttk.Button(top, text="시작", command=self.start)
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ttk.Button(top, text="중지", state="disabled",
                                   command=self.stop)
        self.btn_stop.pack(side="left", padx=5)

        self.btn_settings = ttk.Button(top, text="설정",
                                       command=self._show_settings)
        self.btn_settings.pack(side="left", padx=5)

        self.btn_log = ttk.Button(top, text="로그", command=self._show_log)
        self.btn_log.pack(side="left", padx=5)

        self.lbl_status = ttk.Label(top, text="대기중")
        self.lbl_status.pack(side="left", padx=20)

        # ── 진행률 ───────────────────────────────────────
        bottom = ttk.Frame(root, padding=(10, 0, 10, 10))
        bottom.pack(side="bottom", fill="x")

        self.stage_var = tk.DoubleVar()
        ttk.Progressbar(bottom, orient="horizontal", length=300,
                        mode="determinate", variable=self.stage_var,
                        style="Horizontal.TProgressbar").pack(fill="x")
        self.stage_label = ttk.Label(bottom, text="Phase: 0%")
        self.stage_label.pack(anchor="e")

        self.total_var = tk.DoubleVar()
        ttk.Progressbar(bottom, orient="horizontal", length=300,
                        mode="determinate", variable=self.total_var,
                        style="Horizontal.TProgressbar").pack(fill="x", pady=(4, 0))
        self.total_label = ttk.Label(bottom, text="전체: 0%")
        self.total_label.pack(anchor="e")

        self.time_label = ttk.Label(bottom, text="")
        self.time_label.pack(anchor="w")

        # ── 로그 텍스트 (숨김) ────────────────────────────
        self.log = scrolledtext.ScrolledText(
            root, state="disabled", font=("Consolas", 10))

        # ── 기본값 ───────────────────────────────────────
        self.salary_min  = 5
        self.salary_max  = 50
        self.max_con     = 50

        # ── 시작 모드 결정 ────────────────────────────────
        if os.path.exists(CHECKPOINT_JSON) or os.path.exists(DETAILS_CSV):
            self._show_startup_dialog()
        else:
            self.startup_choice = "new"

        sys.stdout = TextRedirector(self._log_queue)
        sys.stderr = TextRedirector(self._log_queue)

        self.root.after(100, self._poll)

    # ── 폴링: GUI queue + log queue 처리 (메인 스레드 전용) ──

    def _poll(self) -> None:
        # 로그 갱신
        lines = []
        for _ in range(50):
            try:
                lines.append(self._log_queue.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "".join(lines))
            self.log.see("end")
            self.log.configure(state="disabled")

        # GUI 메시지 처리
        while True:
            try:
                msg = self._gui_queue.get_nowait()
            except queue.Empty:
                break
            if msg[0] == "progress":
                _, done, total = msg
                pct = int(100 * done / total) if total else 0
                self.stage_var.set(pct)
                self.stage_label.config(text=f"Phase: {pct}% ({done}/{total})")
                # 전체 진행률: phase 1은 10%, phase 2는 90% 가중
                self.total_var.set(pct)
                self.total_label.config(text=f"전체: {pct}%")
            elif msg[0] == "phase":
                self.lbl_status.config(text=msg[1])
            elif msg[0] == "done":
                self._on_done(success=msg[1])
            elif msg[0] == "time":
                self.time_label.config(text=msg[1])

        # 타이머 갱신 (실행 중이면)
        if self.running and hasattr(self, "_start_time"):
            elapsed = time.time() - self._start_time
            self.time_label.config(text=f"경과: {elapsed:.0f}초")

        self.root.after(100, self._poll)

    # ── 시작 / 중지 ──────────────────────────────────────

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._start_time = time.time()
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text="실행 중… 🚀")
        self.stop_event.clear()

        salary_range = range(self.salary_max, self.salary_min - 1, -1)

        t = threading.Thread(
            target=run_pipeline,
            args=(salary_range, self.max_con,
                  self.stop_event, self._gui_queue),
            daemon=True,
        )
        t.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.lbl_status.config(text="중단 요청됨…")
        self.btn_stop.config(state="disabled")

    def _on_done(self, success: bool) -> None:
        self.running = False
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_status.config(text="완료 ✅" if success else "중단됨")
        self.stage_var.set(100 if success else self.stage_var.get())

    # ── 팝업들 ───────────────────────────────────────────

    def _show_startup_dialog(self) -> None:
        dlg = tk.Toplevel(self.root)
        dlg.title("시작 옵션")
        dlg.geometry("320x140")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", self.root.destroy)

        ttk.Label(
            dlg,
            text="💾 복원 또는 🆕 새 시즌 추가\n원하는 옵션을 선택하세요.",
            justify="center",
        ).pack(pady=10)

        frm = ttk.Frame(dlg)
        frm.pack(pady=5, fill="x", padx=20)

        ttk.Button(frm, text="🔄 백업 복원", width=15,
                   command=lambda: self._set_choice(dlg, "restore")
                   ).pack(side="left", padx=5)
        ttk.Button(frm, text="🆕 새 시즌 추가", width=15,
                   command=lambda: self._set_choice(dlg, "new")
                   ).pack(side="right", padx=5)

        self.root.wait_window(dlg)

    def _set_choice(self, dlg: tk.Toplevel, choice: str) -> None:
        self.startup_choice = choice
        if choice == "new":
            for f in (CHECKPOINT_JSON, DETAILS_CSV, FINAL_CSV):
                if os.path.exists(f):
                    os.remove(f)
            print("🆕 새 시즌 모드: 기존 데이터 초기화")
        else:
            print("🔄 복원 모드: 체크포인트 + details.csv 이어받기")
        dlg.destroy()

    def _show_settings(self) -> None:
        popup = tk.Toplevel(self.root)
        popup.title("설정")
        popup.geometry("280x180")
        popup.transient(self.root)
        popup.grab_set()

        fields = [
            ("급여 최소:", "salary_min",  self.salary_min),
            ("급여 최대:", "salary_max",  self.salary_max),
            ("max_con:",   "max_con",     self.max_con),
        ]
        entries: dict = {}
        for i, (lbl, key, default) in enumerate(fields):
            ttk.Label(popup, text=lbl).grid(row=i, column=0, sticky="e", padx=5, pady=5)
            ent = ttk.Entry(popup, width=8)
            ent.insert(0, str(default))
            ent.grid(row=i, column=1, pady=5)
            entries[key] = ent

        def save() -> None:
            try:
                self.salary_min = int(entries["salary_min"].get())
                self.salary_max = int(entries["salary_max"].get())
                self.max_con    = int(entries["max_con"].get())
            except ValueError:
                messagebox.showerror("오류", "모든 값은 숫자여야 합니다.")
                return
            popup.destroy()

        ttk.Button(popup, text="저장", command=save).grid(
            row=len(fields), column=0, columnspan=2, pady=15)
        popup.protocol("WM_DELETE_WINDOW", popup.destroy)

    def _show_log(self) -> None:
        popup = tk.Toplevel(self.root)
        popup.title("로그창")
        popup.geometry("560x620")
        popup.transient(self.root)

        log_text = scrolledtext.ScrolledText(popup, font=("Consolas", 10))
        log_text.pack(fill="both", expand=True, padx=10, pady=10)
        log_text.configure(state="disabled")

        prev: list = [""]

        def _refresh() -> None:
            if not popup.winfo_exists():
                return
            cur = self.log.get("1.0", "end")
            if cur != prev[0]:
                at_bottom = log_text.yview()[1] == 1.0
                new_part  = cur[len(prev[0]):]
                log_text.configure(state="normal")
                log_text.insert("end", new_part)
                log_text.configure(state="disabled")
                prev[0] = cur
                if at_bottom:
                    popup.after_idle(lambda: log_text.see("end"))
            popup.after(500, _refresh)

        _refresh()
        popup.protocol("WM_DELETE_WINDOW", popup.destroy)


# ══════════════════════════════════════════════════════════
#   Entry Point
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    root = tk.Tk()
    setup_toss_style(root)
    CrawlerGUI(root)
    root.mainloop()
