import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading, queue, sys, io, time, json, re, subprocess
import os
import pandas as pd
import datetime as dt
import requests  # ← 1단계 순차탐색에서 requests 사용
from tkinter import ttk
import asyncio
import httpx
from bs4 import BeautifulSoup
from asyncio import Semaphore  # Semaphore 추가

from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED # 두 번째 코드에서 추가된 import


# ──────────────────────────────
#   GUI: stdout → Tkinter Text
# ──────────────────────────────
import os

TOSS_BLUE   = "#3182F6"
BG_WHITE    = "#FFFFFF"
GREY_TEXT   = "#4F4F4F"
LIGHT_GREY  = "#F5F6F8"
FONT_FAMILY = "Spoqa Han Sans Neo"  

# 현재 파이썬 파일이 위치한 폴더
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print("📁 data 폴더 생성 완료! 위치:", DATA_DIR)

JOBB_CSV     = os.path.join(DATA_DIR, "job.csv")
CODESS_CSV   = os.path.join(DATA_DIR, "codes.csv" )
DETAILSS_CSV = os.path.join(DATA_DIR, "details.csv")
CODES_CSV = CODESS_CSV 

class TextRedirector(io.TextIOBase):
    def __init__(self, widget, queue_):
        self.widget = widget
        self.queue = queue_
    def write(self, s):
        self.queue.put(s)
    def flush(self):
        pass

def setup_toss_style(root: tk.Tk):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Horizontal.TProgressbar",
           troughcolor=LIGHT_GREY,      # 바깥 회색
        background="green"           # 내부 녹색 (윈도우 기본 스타일 느낌)
    )

    # base
    style.configure(".",
        background=BG_WHITE,
        foreground=GREY_TEXT,
        font=(FONT_FAMILY, 11)
    )

    # button
    style.configure("TButton",
        background=TOSS_BLUE,
        foreground="#fff",
        borderwidth=0,
        padding=(12,5),
        font=(FONT_FAMILY, 11, "bold")
    )
    style.map("TButton",
        background=[("active", "#1671F3"), ("disabled", LIGHT_GREY)],
        foreground=[("disabled", "#9E9E9E")]
    )

    # label
    style.configure("TLabel", background=BG_WHITE, foreground=GREY_TEXT)

   
    # scrolled text
    style.configure("TFrame", background=BG_WHITE)


class CrawlerGUI:
    def __init__(self, root):
        # ── 기본 셋업 ─────────────────────────────
        self.root = root
        root.title("FC Online 크롤러 GUI")
        root.geometry("495x150")
        self.stop_event = threading.Event()

        top = ttk.Frame(root, padding=10)
        top.pack(fill="x")
        self.stage_pcts = [0, 0, 0, 0, 0]  # 5단계 진행률 저장

        # ── 버튼들 ───────────────────────────────
        self.btn_start = ttk.Button(top, text="시작", command=self.start)
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ttk.Button(top, text="중지", state="disabled", command=self.stop)
        self.btn_stop.pack(side="left", padx=5)

        self.btn_settings = ttk.Button(top, text="설정", command=self.show_settings_popup)
        self.btn_settings.pack(side="left", padx=5)

        self.btn_log = ttk.Button(top, text="로그", command=self.show_log_popup)
        self.btn_log.pack(side="left", padx=5)

        self.lbl_status = ttk.Label(top, text="대기중")
        self.lbl_status.pack(side="left", padx=20)

       
        # ── 단계·총 진행률 Progressbar 두 줄 ──────
        # ── ① progress_box 만들던 부분 주석 처리 ─────────────────────────
        # progress_box = ttk.Frame(top)
        # progress_box.pack(side="left", padx=10, pady=5)

        # ── ② 창 맨 아래에 새 프레임 하나 만들고 ─────────────────────
        bottom = ttk.Frame(root, padding=10)
        bottom.pack(side="bottom", fill="x")   # ← 핵심! 'bottom'으로, 가로 꽉 차게

        # ── ③ progress_box를 bottom 안에 다시 만들기 ──────────────────
        progress_box = ttk.Frame(bottom)
        progress_box.pack(fill="x")
        self.time_label_3     = ttk.Label(bottom)                # 3단계 타이머 더미
        self.time_labels      = {i: ttk.Label(bottom) for i in range(1, 6)}  # 단계별 더미
        self.total_time_label = ttk.Label(bottom)            # 원하는 위치·여백 맞춰 조절 가능

        # 위쪽: 현재 단계
        self.stage_var = tk.DoubleVar()
        self.stage_pb = ttk.Progressbar(
            progress_box, orient="horizontal", length=300,
            mode="determinate", variable=self.stage_var,
            style="Horizontal.TProgressbar"
        )
        self.stage_pb.pack(fill="x")
        self.stage_label = ttk.Label(progress_box, text="단계: 0%")
        self.stage_label.pack(anchor="e")

        # 아래쪽: 전체
        self.total_var = tk.DoubleVar()
        self.total_pb = ttk.Progressbar(
            progress_box, orient="horizontal", length=300,
            mode="determinate", variable=self.total_var,
            style="Horizontal.TProgressbar"  
        )
        self.total_pb.pack(fill="x", pady=(4, 0))
        self.total_label = ttk.Label(progress_box, text="전체: 0%")
        self.total_label.pack(anchor="e")

        # ── 단계별 소요 시간 라벨(1~5) ─────────────
       

        # ── 로그 출력 창 (숨김) ────────────────────
        self.log = scrolledtext.ScrolledText(root, state="disabled", font=("Consolas", 10))

        # ── 내부 상태 변수 ────────────────────────
        self.queue = queue.Queue()
        self.proc_thread = None
        self.running = False

        # ── 시작 옵션 선택 ────────────────────────
        if not os.path.exists(JOBB_CSV):
            self.startup_choice = "new"
            print("💡 job.csv 없음 → 새 시즌 모드")
        else:
            self.startup_choice = None
            self.show_startup_dialog()

        self.root.after(100, self.update_log)  # 로그 폴링

    # ─────────────────────────────────────────────
    #   진행률 업데이트 메서드
    # ─────────────────────────────────────────────
    def update_stage_progress(self, done, total, stage_idx):

        pct = int(100 * done / total) if total else 0
        self.stage_var.set(pct)
        self.stage_label.config(text=f"단계: {pct}% ({done}/{total})")
        self.stage_pcts[stage_idx] = pct
        self.update_weighted_overall_progress(self.stage_pcts)

    def update_total_progress(self, done, total):
        pct = int(100 * done / total) if total else 0
        self.total_var.set(pct)
        self.total_label.config(text=f"전체: {pct}% ({done}/{total})")

    def update_weighted_overall_progress(self, pct_list):
        weights = [12, 0, 18, 70, 0]  # 1~4단계 가중치 (총 100), 5단계는 0
        total_pct = sum(p * w for p, w in zip(pct_list, weights)) // sum(weights)
        self.total_var.set(total_pct)
        self.total_label.config(text=f"전체: {total_pct}%")    

    # 기존 코드 호환용 (3단계에서 호출)
    def update_progress(self, done, total,stage_idx=2):
        self.update_stage_progress(done, total,stage_idx)

    # ─────────────────────────────────────────────
    #   3단계 타이머
    # ─────────────────────────────────────────────
    def start_3_timer(self):
        self._3_start_time = time.time()
        self._update_3_timer = True
        self.update_3_timer()

    def update_3_timer(self):
        if not getattr(self, "_update_3_timer", False):
            return
        elapsed = time.time() - self._3_start_time
        self.time_label_3.config(text=f"3단계 진행 시간: {elapsed:.1f}초")
        self.root.after(500, self.update_3_timer)

    def stop_3_timer(self):
        self._update_3_timer = False

    # ─────────────────────────────────────────────
    #   시작 / 중지 버튼 로직
    # ─────────────────────────────────────────────
    def start(self):
        if self.running:
            return
        self.running = True
        self.btn_start["state"] = "disabled"
        self.btn_stop["state"] = "normal"
        self.lbl_status["text"] = "실행 중…🚀"

        # 기본 파라미터
        salary_min = getattr(self, "salary_min", 5)
        salary_max = getattr(self, "salary_max", 50)
        salary_range = range(salary_max, salary_min - 1, -1)
        max_workers = getattr(self, "max_workers", 15)
        max_con = getattr(self, "max_con", 20)

        # 전체 타이머 초기화
        self.overall_start_time = time.time()
        for lbl in self.time_labels.values():
            lbl.config(text="0.0초")
        self.total_time_label.config(text="총 시간: 0.0초")

        # stdout ↔️ GUI redirect
        sys.stdout = TextRedirector(self.log, self.queue)
        sys.stderr = TextRedirector(self.log, self.queue)

        # 실 작업 스레드 시작
        self.proc_thread = threading.Thread(
            target=self.run_crawler_wrapper,
            args=(salary_range, max_workers, self.startup_choice, max_con),
            daemon=True,
        )
        self.proc_thread.start()

    def stop(self):
        if self.running and self.proc_thread and self.proc_thread.is_alive():
            self.stop_event.set()
            self.lbl_status["text"] = "중지 요청됨"
            messagebox.showinfo("중지", "작업을 중단합니다…")
            os._exit(0)  # 전체 프로세스 종료
        else:
            self.lbl_status["text"] = "대기중"

    # ─────────────────────────────────────────────
    #   크롤러 래퍼
    # ─────────────────────────────────────────────
    def run_crawler_wrapper(self, salary_range, max_workers, startup_choice, max_con):
        self.stop_event.clear()

        run_crawler_with_timer(
            salary_range,
            max_workers,
            gui=self,
            startup_choice=startup_choice,
            max_con=max_con,
            stop_event=self.stop_event,
            time_labels=self.time_labels,
            total_time_label=self.total_time_label,
            overall_start_time=self.overall_start_time,
        )

        try:
            self.queue.put("\n🎉 작업 완료!\n")
        except Exception as e:
            self.queue.put(f"\n❌ 예외 발생: {e}\n")
        finally:
            self.stop_3_timer()
            self.running = False
            elapsed_total = time.time() - self.overall_start_time
            self.root.after(
                0,
                lambda: self.total_time_label.config(text=f"총 시간: {elapsed_total:.1f}초"),
            )

    # ─────────────────────────────────────────────
    #   로그 창 실시간 업데이트
    # ─────────────────────────────────────────────
    def update_log(self):
        lines = []
        for _ in range(50):
            try:
                lines.append(self.queue.get_nowait())
            except queue.Empty:
                break

        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "".join(lines))
            self.log.see("end")
            self.log.configure(state="disabled")

        self.root.after(100, self.update_log)

    # ─────────────────────────────────────────────
    #   팝업들 (시작옵션 / 설정 / 로그)
    # ─────────────────────────────────────────────
    def show_startup_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("시작 옵션 선택")
        dlg.geometry("320x140")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.protocol("WM_DELETE_WINDOW", self.root.destroy)  # X 누르면 앱 종료

        ttk.Label(
            dlg,
            text="💾 복원 또는 🆕 새 시즌 추가\n원하는 옵션을 선택하세요.",
            justify="center",
        ).pack(pady=10)

        frm = ttk.Frame(dlg)
        frm.pack(pady=5, fill="x", padx=20)

        ttk.Button(
            frm,
            text="🔄 백업 복원",
            width=15,
            command=lambda: self._set_choice(dlg, "restore"),
        ).pack(side="left", padx=5)
        ttk.Button(
            frm,
            text="🆕 새 시즌 추가",
            width=15,
            command=lambda: self._set_choice(dlg, "new"),
        ).pack(side="right", padx=5)

        self.root.wait_window(dlg)

    def _set_choice(self, dlg, choice):
        self.startup_choice = choice
        dlg.destroy()
        if choice == "restore":
            self.start()

    def show_settings_popup(self):
        popup = tk.Toplevel(self.root)
        popup.title("설정")
        popup.geometry("280x210")
        popup.transient(self.root)
        popup.grab_set()

        salary_min = getattr(self, "salary_min", 5)
        salary_max = getattr(self, "salary_max", 50)
        max_workers = getattr(self, "max_workers", 15)
        max_con = getattr(self, "max_con", 20)

        entries = {}
        for i, (label_txt, default) in enumerate(
            [
                ("급여 최소:", salary_min),
                ("급여 최대:", salary_max),
                ("max_workers:", max_workers),
                ("max_con:", max_con),
            ]
        ):
            ttk.Label(popup, text=label_txt).grid(row=i, column=0, sticky="e", padx=5, pady=5)
            ent = ttk.Entry(popup, width=8)
            ent.insert(0, str(default))
            ent.grid(row=i, column=1, pady=5)
            entries[label_txt] = ent

        def save_and_close():
            try:
                self.salary_min = int(entries["급여 최소:"].get())
                self.salary_max = int(entries["급여 최대:"].get())
                self.max_workers = int(entries["max_workers:"].get())
                self.max_con = int(entries["max_con:"].get())
            except ValueError:
                messagebox.showerror("오류", "모든 값을 숫자로 입력해야 합니다.")
                return
            popup.destroy()

        ttk.Button(popup, text="저장", command=save_and_close).grid(
            row=4, column=0, columnspan=2, pady=15
        )

        popup.protocol("WM_DELETE_WINDOW", popup.destroy)

    def show_log_popup(self):
        popup = tk.Toplevel(self.root)
        popup.title("로그창")
        popup.geometry("500x600")
        popup.transient(self.root)
        popup.grab_set()

        log_text = scrolledtext.ScrolledText(popup, font=("Consolas", 10))
        log_text.pack(fill="both", expand=True, padx=10, pady=10)
        log_text.configure(state="disabled")

        prev_log = [""]

        def update_log_in_popup():
            if not popup.winfo_exists():
                return
            current_log = self.log.get("1.0", "end")
            if current_log == prev_log[0]:
                popup.after(1000, update_log_in_popup)
                return

            at_bottom = log_text.yview()[1] == 1.0
            new_part = current_log[len(prev_log[0]) :]

            log_text.configure(state="normal")
            log_text.insert("end", new_part)
            log_text.configure(state="disabled")

            prev_log[0] = current_log
            if at_bottom:
                popup.after_idle(lambda: log_text.see("end"))

            popup.after(1000, update_log_in_popup)

        update_log_in_popup()
        popup.protocol("WM_DELETE_WINDOW", popup.destroy)



# ─── 백업/복원 함수 ───
BACKUP_FILE = "crawler_backup.json"

def save_backup(stage, data):
    # 현재 프로젝트에서는 백업 기능을 OFF 해두었지만
    # 향후 확장 대비해 빈 함수 대신 파일 덮어쓰기 구조 유지
    pass


def load_backup():
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 백업 읽기 실패: {e}")
    return None


# ──────────[ 비동기 크롤러 도움 함수 ]──────────
BACKUP_FILE = "crawler_backup.json"

URL_LIST = "https://fconline.nexon.com/datacenter/PlayerList"
URL_DETAIL = "https://fconline.nexon.com/datacenter/PlayerAbility"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fconline.nexon.com/datacenter/",
}
STAT_NAMES = [
    "속력",
    "가속력",
    "골 결정력",
    "슛 파워",
    "중거리 슛",
    "위치 선정",
    "발리슛",
    "페널티 킥",
    "짧은 패스",
    "시야",
    "크로스",
    "긴 패스",
    "프리킥",
    "커브",
    "드리블",
    "볼 컨트롤",
    "민첩성",
    "밸런스",
    "반응 속도",
    "대인 수비",
    "태클",
    "가로채기",
    "헤더",
    "슬라이딩 태클",
    "몸싸움",
    "스태미너",
    "적극성",
    "점프",
    "침착성",
    "GK 다이빙",
    "GK 핸들링",
    "GK 킥",
    "GK 반응속도",
    "GK 위치 선정",
]

async def fetch_codes(session, sem:Semaphore, job):
    async with sem:
        try:
            resp = await session.post(URL_LIST, data={
                "strPlayerName":"","strSeason":"","strPosition":job['pos_code'],
                "n4SalaryMin":job['salary'],"n4SalaryMax":job['salary'],
                "n4OvrMin":job['ovr'],"n4OvrMax":job['ovr']
            }, timeout=10)
            soup = BeautifulSoup(resp.text, "html.parser")
            codes = [m.group(1) for m in map(
                lambda t: re.search(r"\.val\('(\d+)'\)", t.get("onclick","")),
                soup.select("div.tr")) if m]
            return codes
        except Exception as e:

            
            import traceback, pprint
            print("❌ 3단계 job 에러:", pprint.pformat(job))
            print("   ▶ 예외 타입 :", type(e).__name__)
            print("   ▶ 예외 repr :", repr(e))
            traceback.print_exc()      # 전체 스택트레이스 표시
            # HTTP 상태코드도 찍기 (가능한 경우)
            if hasattr(e, "response") and e.response is not None:
                print("   ▶ HTTP status :", e.response.status_code)
                print("   ▶ 응답 일부   :", e.response.text[:200])
            return []

            print(f"❌ 3단계 job 에러 {job}: {e}")
            return []

async def async_collect_codes(jobs, max_con=20, stop_event=None):
    sem = Semaphore(max_con)
    
    async with httpx.AsyncClient(headers=HEADERS) as session:
        # (df_idx, future) 리스트로 태스크 생성
        tasks = [
            (job["df_idx"], asyncio.create_task(fetch_codes(session, sem, job)))
            for job in jobs
        ]
        total = len(tasks)

        finished_idx_batch, finished_code_batch = [], set()

        for i, (df_idx, fut) in enumerate(tasks, 1): # 여기서 df_idx와 fut를 바로 언팩
            if stop_event and stop_event.is_set():      # 중단 요청 체크
                print("🔴 중단 요청 감지, 3단계 코드 수집 중단")
                for _, t in tasks: # 남은 태스크 취소
                    if not t.done():
                        t.cancel()
                break

            try:
                codes = await fut                      # ← 오류 패치: 그냥 await fut
            except Exception as e:
                print(f"❌ 3단계 job 에러 idx={df_idx}: {e}")
                codes = []

            finished_idx_batch.append(df_idx)
            finished_code_batch.update(codes)

            # 50개마다—or 마지막—yield
            if len(finished_idx_batch) >= 50 or i == total:
                yield finished_idx_batch, finished_code_batch
                finished_idx_batch, finished_code_batch = [], set()


async def fetch_detail(session, sem:Semaphore, spid):
    async with sem:
        try:
            hdr = {"User-Agent":"Mozilla/5.0",
                   "Referer":f"https://fconline.nexon.com/datacenter/PlayerInfo?spid={spid}"}
            pld = {"spid":spid,"n1Strong":1,"n1Grow":0,"n4TeamColorId":0,
                   "n4TeamColorLv":0,"n1Change":0,
                   "strPlayerImg":f"https://fo4.dn.nexoncdn.co.kr/live/externalAssets/common/playersAction/p{spid}.png","rd":"0"}
            resp = await session.post(URL_DETAIL, headers=hdr, data=pld, timeout=10)
            resp.raise_for_status() # HTTP 오류 발생 시 예외 발생
            soup = BeautifulSoup(resp.text, "html.parser")


            ability_tag = None
            for a in soup.select("a.ability"):
                if "소속 팀컬러" in a.get_text(strip=True):
                    ability_tag = a
                    break

            tdef = soup.select_one("div.tdefault")
            team_colors = []
            if tdef:
                team_colors = [
                    a.get_text(strip=True)
                    for a in tdef.select("div.selector_list ul li a.selector_item")
                ]
                # "소속 팀컬러"와 "단일팀" 모두 제외
                team_colors = [
                    name for name in team_colors
                    if name not in ("소속 팀컬러", "단일팀")
             ]




            get_txt = lambda sel: (soup.select_one(sel).text.strip()
                                   if soup.select_one(sel) else "")
            name   = get_txt("div.nameWrap div.name, .info_line.info_name div.name")

            season = ""
            pcw    = soup.select_one("div.playerCardWrap")
            if pcw:
                for cls in pcw.get('class', []): # .get('class', [])로 오류 방지
                    if cls.startswith('_'): season = cls[1:]; break
            if not season:
                img = soup.select_one("div.nameWrap div.season img[alt], \
                                     div.info_line.info_name div.season img[alt]")
                season = img['alt'].strip() if img and img.has_attr('alt') else ""

            position = get_txt("div.content_header div.position, \
                                 .info_line.info_ab span.position .txt")
            ovr = get_txt("div.content_header .ovr.value, .info_line.info_ab span.value")

            to_int = lambda s: int(''.join(filter(str.isdigit,s))) if s else 0
            salary_tag = soup.select_one("div.playerCardInfoSide div.pay span") or soup.select_one("div.side_utils div.pay_side")
            salary = int(salary_tag.text.strip()) if salary_tag else 0

            height = to_int(get_txt("span.etc.height"))
            weight = to_int(get_txt("span.etc.weight"))

            skill_text = get_txt("span.etc.skill span")
            skill = skill_text.count("★")

            foot_text = get_txt("span.etc.foot")
            m = re.search(r"L(\d)\s*[-–]\s*R(\d)", foot_text)
            left_foot, right_foot = (int(m[1]), int(m[2])) if m else (0,0)

            traits = ','.join([t.text.strip() for t in soup.select("div.skill_wrap span.desc") if t.text.strip()]) # 빈 특성 제거

            stat = {nm:0 for nm in STAT_NAMES}
            for li in soup.select("ul.data_wrap_playerinfo li.ab"):
                nm_tag = li.select_one("div.txt")
                val_tag = li.select_one("div.value")
                if nm_tag and val_tag: # 태그가 모두 존재하는지 확인
                    nm = nm_tag.text.strip()
                    val = val_tag.text.strip().split(" ")[0] # 숫자만 추출
                    if nm in stat: stat[nm] = to_int(val)

            return {"player_code": str(spid), "player_name": name, "salary": salary,"season": season,
                    "position": position, "ovr": ovr, "height": height, "weight": weight,
                    "skill": skill, "left_foot": left_foot, "right_foot": right_foot,
                    "traits": traits,"team_colors": json.dumps(team_colors, ensure_ascii=False), **stat}
        except httpx.HTTPStatusError as e:
            print(f"❌ HTTP 오류 {spid}: {e.response.status_code} - {e.response.text[:100]}")
            return None
        except Exception as e:
            print(f"❌ 4단계 에러 {spid}: {e}")
            return None

async def async_fetch_details(
    code_list, max_con=20, flush_every=50, file_csv=DETAILSS_CSV,
    stop_event=None, gui=None
):
    sem = Semaphore(max_con)
    details_buffer = []
    mode = "a" if os.path.exists(file_csv) and os.path.getsize(file_csv) > 0 else "w"
    write_header = not os.path.exists(file_csv) or os.path.getsize(file_csv) == 0

    total_tasks = len(code_list)
    processed_count = 0

    async with httpx.AsyncClient(headers=HEADERS) as session:
        tasks = [asyncio.create_task(fetch_detail(session, sem, cid)) for cid in code_list]

        for i, task in enumerate(asyncio.as_completed(tasks), 1):
            if stop_event and stop_event.is_set():
                print("🔴 중단 요청 감지, 4단계 종료")
                for t in tasks:
                    if not t.done(): t.cancel()
                break

            inf = await task
            if inf:
                details_buffer.append(inf)
                processed_count += 1

            # --- 진행률 갱신 ---
            if gui and (i % 5 == 0 or i == total_tasks):  # 5개마다 혹은 마지막에!
                gui.update_progress(i, total_tasks,3)
            # -------------------

            # flush/save
            if len(details_buffer) >= flush_every:
                df_to_save = pd.DataFrame(details_buffer)
                df_to_save.to_csv(
                    file_csv,
                    index=False,
                    mode=mode,
                    header=write_header,
                    encoding="utf-8-sig"
                )
                write_header = False
                mode = "a"
                details_buffer.clear()
                print(f"🔒 {file_csv}에 {processed_count}명까지 임시 저장")

            if i % 100 == 0 or i == total_tasks:
                print(f"상세 {i}/{total_tasks} 완료")

    # 남은 데이터 flush
    if details_buffer:
        df_to_save = pd.DataFrame(details_buffer)
        df_to_save.to_csv(
            file_csv,
            index=False,
            mode=mode,
            header=write_header,
            encoding="utf-8-sig"
        )
        print(f"🔒 {file_csv} 최종 남은 데이터 저장")

    # --- 마지막에 100%로 맞추기! ---
    if gui:
        gui.update_progress(total_tasks, total_tasks,3)


# ──────────[ 메인 크롤러 ]──────────
# 🕒 run_crawler 이름을 run_crawler_with_timer로 변경하고 타이머 관련 인자 추가
def run_crawler_with_timer(salary_range, max_workers, gui=None, startup_choice="new", max_con=20, stop_event=None, time_labels=None, total_time_label=None, overall_start_time=None):
    import pandas as pd
    JOB_CSV = JOBB_CSV
    backup = load_backup() or {}
    # run_crawler_with_timer 함수 내부, 1단계 시작 전에!
    salary_min = getattr(gui, "salary_min", 5) if gui else 5
    salary_max = getattr(gui, "salary_max", 50) if gui else 50
    salary_total = salary_max - salary_min + 1

    start_stage = backup.get("stage", 1)
    max_ovr_dict = backup.get("max_ovr_dict", {})
    min_ovr_dict = backup.get("min_ovr_dict", {})
    all_codes = set(backup.get("all_codes", []))

    if startup_choice == "restore":
    # job.csv에서 done3==0인 게 하나도 없으면 바로 4단계부터!
        if os.path.exists(JOBB_CSV):
            df_jobs = pd.read_csv(JOBB_CSV)
            if "done3" in df_jobs.columns and df_jobs["done3"].sum() == len(df_jobs):
                print("💡 job.csv의 done3이 전부 1 → 4단계부터 시작")
                start_stage = 4
            else:
                print("💡 job.csv에 미완료 작업 존재 → 3단계부터 시작")
                start_stage = 3
        else:
            print("💡 job.csv 없음 → 1단계부터 시작")
            start_stage = 1


    position_dict = {
        "FW": ",24,25,26,20,21,22,27,23,",
        "MF": ",13,14,15,17,18,19,9,10,11,16,12,",
        "DF": ",1,4,5,6,3,7,2,8,",
        "GK": ",0,",
    }

    JOB_CSV = JOBB_CSV

    # ---------- 1단계 (급여별 OVR 범위 탐색: "순차탐색" 버전) ----------
    def crawl_players_sync(salary, ovr_max=200): # 이름 변경: requests 사용하는 동기 함수
        try:
            payload = {
                "strPlayerName": "",
                "strSeason": "",
                "strPosition": "",
                "n4SalaryMin": salary,
                "n4SalaryMax": salary,
                "n4OvrMin": 0,
                "n4OvrMax": ovr_max,
            }
            # requests 사용
            r = requests.post(URL_LIST, headers=HEADERS, data=payload, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            raw_players = soup.select("div.tr")
            players = []
            for tr in raw_players:
                m = re.search(r"\.val\('([0-9]+)'\)", tr.get("onclick", ""))
                code = m.group(1) if m else None
                if not code:
                    continue
                ovr_by_pos = {}
                for pt in tr.select("span.position"):
                    pos_tag = pt.select_one("span.txt")
                    val_tag = pt.select_one(f"span.skillData_{code}")
                    if pos_tag and val_tag:
                        pos = pos_tag.get_text(strip=True)
                        try:
                            ovr_by_pos[pos] = int(val_tag.get_text(strip=True))
                        except ValueError:
                            pass
                if ovr_by_pos:
                    players.append(ovr_by_pos)
            return players, len(players)
        except requests.exceptions.RequestException as e:
            print(f"❌ 1단계 HTTP/네트워크 에러 (급여 {salary}, OVR {ovr_max}): {e}")
            return [], 0
        except Exception as e:
            print(f"❌ 1단계 파싱/알 수 없는 에러 (급여 {salary}, OVR {ovr_max}): {e}")
            return [], 0


    def get_players_and_min_ovr_sync(salary, ovr_max=200): # 이름 변경
        players, raw_count = crawl_players_sync(salary, ovr_max)
        if raw_count == 0 or not players:
            return players, raw_count, None, None
        main_ovrs = [list(d.values())[0] for d in players if d]
        if not main_ovrs:
            return players, raw_count, None, None
        return players, raw_count, max(main_ovrs), min(main_ovrs)
    print_lock = threading.Lock()
    # --- 기존 1단계 while True 부분을 함수로 분리 ---
    # ───────────────────────────────────────────────
    #  1단계  -  linear vs binary  실시간 경쟁 모드
    # ───────────────────────────────────────────────
    # ── A. 두 알고리즘 각각 구현 ────────────────────
    def _linear_min_ovr(salary):
        import time
        
        """현재 쓰던 cur_min-1 선형 축소 버전"""
        
        ovr_max, prev_min = 200, None
        max_ovr = min_ovr = None
        while True:
            players, cnt, cur_max, cur_min = get_players_and_min_ovr_sync(salary, ovr_max)
            if cnt == 0 or cur_min is None: break       # 선수 없음
            if max_ovr is None: max_ovr = cur_max
            if cnt < 200:                                # 200명 미만 → 최소 확정
                min_ovr = cur_min
                break
            # 계속 축소 (선형 방식)
            ovr_max = cur_min - 1
            if ovr_max <= 0: break
            prev_min = cur_min
        return max_ovr, min_ovr
        
#----------------------선형탐색 끝-------------

#------------------ 이진탐색 시작 -----------------
    def _binary_min_ovr(salary: int):
    
        # --- 1단계: 전체 0~200 요청 → max OVR 얻기
        _, cnt_all, max_ovr, _ = get_players_and_min_ovr_sync(salary, 200)
        if cnt_all == 0 or max_ovr is None:      # 급여 구간 자체에 선수 없음
            return None, None                    # 승부 자체 무효

        # --- 2단계: min OVR 이진탐색
        lo, hi = 0, max_ovr          # hi = 실제 최고 OVR
        min_ovr = None

        while lo <= hi:
            mid = (lo + hi) // 2
            _, cnt, _, cur_min = get_players_and_min_ovr_sync(salary, mid)

            if cnt == 0:
                # mid까지는 선수 없음 → 최소 OVR은 mid+1 이상
                lo = mid + 1
            else:
                # mid 구간에 선수 존재 → cur_min 후보 갱신, hi 내려서 더 낮은 구간 탐색
                min_ovr = cur_min if (min_ovr is None or cur_min < min_ovr) else min_ovr
                hi = mid - 1

        return max_ovr, min_ovr






    def _runner(salary, mode):
        """ThreadPoolExecutor 에서 실행될 래퍼"""
        if mode == "linear":
            maxo, mino = _linear_min_ovr(salary)
        else:  # "binary"
            maxo, mino = _binary_min_ovr(salary)
        return salary, maxo, mino, mode

    # ── B. 경쟁 실행 ────────────────────────────────
    if start_stage <= 1:
        print("=== [1단계] 급여별 최소 OVR 탐색 : linear vs binary 경쟁 모드 ===")
        start_time_stage_1 = time.time()
        pair = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for sal in salary_range:
                f_lin = pool.submit(_runner, sal, "linear")
                f_bin = pool.submit(_runner, sal, "binary")
                pair[sal] = {"linear": f_lin, "binary": f_bin}

            salary_total = len(pair)   # 실제 salary 개수!
            salary_done_set = set()  

            pending = {f for p in pair.values() for f in p.values()}
            while pending:
                if stop_event and stop_event.is_set():
                    print("🔴 중단 요청 감지, 1단계 종료")
                    for fut in pending:
                        fut.cancel()
                    break

                done, pending = wait(pending, return_when=FIRST_COMPLETED, timeout=0.1)
                if not done:
                    continue

                for fut in done:
                    handled = False  # 이 salary가 카운트됐는지 추적
                    if fut.cancelled():
                        try:
                            salary, maxo, mino, mode = fut.result()
                            print(f"[{mode} CANCELLED] salary={salary}, max={maxo}, min={mino}")
                        except Exception:
                            print("[Cancelled] Future 취소 또는 결과 없음")
                        handled = True
                    else:
                        try:
                            salary, maxo, mino, mode = fut.result()
                        except Exception as e:
                            print(f"❌ 1단계 퓨처 결과 처리 중 오류: {e}")
                            handled = True

                        # 이미 해당 급여에 대해 결과가 처리되었는지 확인
                        if not handled and salary in max_ovr_dict and salary in min_ovr_dict:
                            handled = True

                        if not handled:
                            other_mode = "binary" if mode == "linear" else "linear"
                            other_fut  = pair[salary][other_mode]
                            if not other_fut.done():
                                other_fut.cancel()

                            if maxo is None or mino is None:
                                print(f"⚠️ 급여 {salary} 선수 없음 → 스킵")
                                handled = True
                            else:
                                # 승자 결과 기록
                                max_ovr_dict[salary] = maxo
                                min_ovr_dict[salary] = mino
                                print(f"🏆 급여 {salary} → {mode} 승!    max={maxo}, min={mino}")
                                handled = True

                    # --- salary_done 무조건 증가 ---
                    if salary not in salary_done_set:
                        salary_done_set.add(salary)
                        salary_done = len(salary_done_set)
                        if gui:
                            gui.update_stage_progress(salary_done, salary_total,stage_idx=0)

    # ... 이하 생략 ...




    # ---------- 2단계 ----------
    JOB_CSV = JOBB_CSV # 2단계, 3단계에서 사용
    if start_stage <= 2:
        start_time_stage_2 = time.time() # 🕒 2단계 시작 시간 기록
        if stop_event and stop_event.is_set():
            print("🔴 중단 요청 감지, 2단계 종료")
            elapsed_2 = time.time() - start_time_stage_2
            if time_labels: time_labels[2].config(text=f"2단계: {elapsed_2:.1f}초 (중단)")
            if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
            return
        print("\n=== [2단계] job 리스트 생성 ===")
        jobs = []
        for salary in salary_range:
            if stop_event and stop_event.is_set():
                print("🔴 중단 요청 감지, 2단계 종료")
                elapsed_2 = time.time() - start_time_stage_2
                if time_labels: time_labels[2].config(text=f"2단계: {elapsed_2:.1f}초 (중단)")
                if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
                return
            if salary not in max_ovr_dict or salary not in min_ovr_dict:
                continue
            for ovr in range(max_ovr_dict[salary], min_ovr_dict[salary]-1, -1):
                if stop_event and stop_event.is_set():
                    print("🔴 중단 요청 감지, 2단계 종료")
                    elapsed_2 = time.time() - start_time_stage_2
                    if time_labels: time_labels[2].config(text=f"2단계: {elapsed_2:.1f}초 (중단)")
                    if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
                    return
                for pos_name, pos_code in position_dict.items():
                    if stop_event and stop_event.is_set():
                        print("🔴 중단 요청 감지, 2단계 종료")
                        elapsed_2 = time.time() - start_time_stage_2
                        if time_labels: time_labels[2].config(text=f"2단계: {elapsed_2:.1f}초 (중단)")
                        if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
                        return
                    jobs.append({"salary": salary, "ovr": ovr, "pos_code": pos_code, "pos_name": pos_name})
        print(f"총 job 개수: {len(jobs)}")
        df_jobs = pd.DataFrame(jobs)
        df_jobs["done3"] = 0        # 0 = 3단계 미완료
        df_jobs["cnt"] = 0
        df_jobs["ts3"] = None
        df_jobs.to_csv(JOB_CSV, index=False, encoding="utf-8-sig")
        print(f"✅ {JOB_CSV} 저장 ({len(df_jobs)} rows)")
        save_backup(3, {"max_ovr_dict": max_ovr_dict, "min_ovr_dict": min_ovr_dict})
        elapsed_2 = time.time() - start_time_stage_2 # 🕒 2단계 소요 시간
        if time_labels: time_labels[2].config(text=f"2단계: {elapsed_2:.1f}초")
        print(f"✅ 2단계 완료! 소요 시간: {elapsed_2:.1f}초")
    else:
        print("⏩ 2단계 건너뛰기")

    current_jobs_for_async_stages = []
    if os.path.exists(JOB_CSV):
        df_jobs = pd.read_csv(JOB_CSV)
        # async_collect_codes에 job의 인덱스도 함께 전달하기 위해 df_idx 컬럼 추가
        # to_dict(orient='records') 할 때 인덱스를 포함시키기 위해 reset_index() 사용
        current_jobs_for_async_stages = df_jobs[df_jobs["done3"] == 0].reset_index().rename(columns={'index':'df_idx'}).to_dict(orient='records')
        print(f"Loaded {len(current_jobs_for_async_stages)} incomplete jobs from {JOB_CSV}")
    elif start_stage >= 3:
        print(f"❌ '{JOB_CSV}' 파일이 없습니다. 1단계부터 다시 시작해야 합니다.")
        return


    # ---------- 3단계 (비동기) ----------
    if start_stage <= 3:
        start_time_stage_3 = time.time()
        if stop_event and stop_event.is_set():
            print("🔴 중단 요청 감지, 3단계 종료")
            elapsed_3 = time.time() - start_time_stage_3
            if time_labels: time_labels[3].config(text=f"3단계: {elapsed_3:.1f}초 (중단)")
            if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
            return

        print("\n=== [3단계] 1차 player_code 수집 (비동기) ===")
        if gui: gui.start_3_timer()

        # df_jobs를 최신 상태로 로드 (2단계에서 생성되었거나, restore 모드에서 로드된 것)
        df_jobs = pd.read_csv(JOB_CSV)
        all_codes_3 = set()  # 3단계에서 새로 얻는 코드 누적용

        async def run_async_collection():
            nonlocal all_codes_3, df_jobs
            if os.path.exists(CODES_CSV):
                all_codes_3 |= set(pd.read_csv(CODES_CSV)["player_code"].astype(str))
            batch_counter = 0
            # async_collect_codes에 jobs와 df_idx를 함께 전달 (위에서 이미 처리)
            async for batch_indices, batch_codes in async_collect_codes(
                current_jobs_for_async_stages, max_con=max_con, stop_event=stop_event
            ):
                for df_idx in batch_indices:  # 받은 df_idx를 사용하여 업데이트
                    df_jobs.loc[df_idx, "done3"] = 1
                all_codes_3.update(batch_codes)
                batch_counter += 1
                if batch_counter % 1 == 0:  # yield 할 때마다 저장되도록 변경 (50개 배치)
                    df_jobs.to_csv(JOB_CSV, index=False, encoding="utf-8-sig")
                    print(f"✅ job.csv {len(batch_indices)}개 done3=1로 변경 저장! (누적 코드 {len(all_codes_3)})")

                    combined = all_codes_3  # 이미 기존+신규 합침
                    pd.DataFrame({"player_code": list(combined)}).to_csv(
                        CODES_CSV, index=False, encoding="utf-8-sig"
                    )
                    print(f"💾 codes.csv 임시 저장! 총 {len(combined)}명")

                # --------------- 여기 추가! ---------------
                # 진행률 표시
                num_done = df_jobs["done3"].sum()
                total_jobs = len(df_jobs)
                if gui:
                    gui.update_progress(num_done, total_jobs,2)
                # ----------------------------------------

        asyncio.run(run_async_collection())

        # 3단계 종료 후 최종 저장 (혹시 남은 배치가 있을 경우)
        df_jobs.to_csv(JOB_CSV, index=False, encoding="utf-8-sig")

        if gui: gui.stop_3_timer()
        elapsed_3 = time.time() - start_time_stage_3  # 🕒 3단계 소요 시간
        if time_labels:
            time_labels[3].config(text=f"3단계: {elapsed_3:.1f}초")
        print(f"✅ 3단계 완료! 소요 시간: {elapsed_3:.1f}초")

        # 👉 3단계 결과 codes.csv 저장
        all_codes.update(all_codes_3)
        pd.DataFrame({"player_code": list(all_codes)}).to_csv(
            CODES_CSV, index=False, encoding="utf-8-sig"
        )
        print(f"💾 codes.csv 저장 완료! 총 {len(all_codes)}명")


        # 여기서 all_codes는 3단계 이전까지의 코드 + 이번에 얻은 코드 모두 포함해야 함!
        all_codes.update(all_codes_3)
        save_backup(4, {
            "max_ovr_dict": max_ovr_dict,
            "min_ovr_dict": min_ovr_dict,
            "all_codes": list(all_codes)
        })
       

    else:
        print("⏩ 3단계 건너뛰기")
        if not all_codes:
            print("❌ 3단계 백업 데이터(all_codes)가 없습니다. 1단계부터 다시 시작하거나 job.csv와 백업 파일을 확인하세요.")
           

        

    # ---------- 4단계 (비동기) ----------
    
    # 👉 codes.csv 기반 복구 (backup all_codes가 비어있을 때)
        # ---------- 4단계 (비동기) ----------
    DETAILS_CSV = DETAILSS_CSV

    # 🟢 무조건 codes.csv에서 복구 (항상 최신 기준)
    if os.path.exists(CODES_CSV):
        all_codes = set(pd.read_csv(CODES_CSV)["player_code"].astype(str))
        print(f"🔄 codes.csv에서 {len(all_codes)}개 코드를 복구")
    else:
        print("❌ codes.csv가 없어요! 3단계부터 다시 돌려야 해.")
        return

    if start_stage <= 4:
        start_time_stage_4 = time.time() # 🕒 4단계 시작 시간 기록
        if stop_event and stop_event.is_set():
            print("🔴 중단 요청 감지, 4단계 종료")
            elapsed_4 = time.time() - start_time_stage_4
            if time_labels: time_labels[4].config(text=f"4단계: {elapsed_4:.1f}초 (중단)")
            if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
            return

        print("\n=== [4단계] 상세정보 크롤링 (비동기) ===")
        done_set = set()
        if os.path.exists(DETAILS_CSV):
            try:
                tmp_df = pd.read_csv(DETAILS_CSV, on_bad_lines="skip", engine="python")
                done_set = set(tmp_df["player_code"].astype(str))
            except Exception as e:
                print("⚠️ details.csv 깨짐, 일단 스킵만 하고 이어서 진행")
                done_set = set()


        print(f"⏩ 이미 상세 완료 {len(done_set)}명 skip")
        remaining_codes = [c for c in all_codes if c not in done_set]
        print(f"🆕 상세 크롤링 대상 {len(remaining_codes)}명")

        asyncio.run(async_fetch_details(
            remaining_codes,
            max_con=max_con,
            file_csv=DETAILS_CSV,
            stop_event=stop_event,
            gui=gui
        ))

        if stop_event and stop_event.is_set():
            print("🔴 중단 요청 감지, 4단계 종료")
            elapsed_4 = time.time() - start_time_stage_4
            if time_labels: time_labels[4].config(text=f"4단계: {elapsed_4:.1f}초 (중단)")
            if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
            return

        print("✅ 4단계 완료! details.csv 저장 끝")

        elapsed_4 = time.time() - start_time_stage_4 # 🕒 4단계 소요 시간
        if time_labels: time_labels[4].config(text=f"4단계: {elapsed_4:.1f}초")
        print(f"✅ 4단계 완료! 소요 시간: {elapsed_4:.1f}초")

        save_backup(5, {"max_ovr_dict": max_ovr_dict, "min_ovr_dict": min_ovr_dict, "all_codes": list(all_codes), "fetched_codes": list(done_set)})
    else:
        print("⏩ 4단계 건너뛰기")

    # ---------- 5단계 ----------
    if start_stage <= 5:
        start_time_stage_5 = time.time() # 🕒 5단계 시작 시간 기록
        if stop_event and stop_event.is_set():
            print("🔴 중단 요청 감지, 5단계 종료")
            elapsed_5 = time.time() - start_time_stage_5
            if time_labels: time_labels[5].config(text=f"5단계: {elapsed_5:.1f}초 (중단)")
            if total_time_label: total_time_label.config(text=f"총 시간: {time.time() - overall_start_time:.1f}초")
            return
        print("\n=== [5단계] 최종 데이터 정리 및 저장 ===")
        fn="all_player_detail.csv"
        fnames=["player_code","player_name","season","position","ovr","height","weight","skill",
                "left_foot","right_foot","traits"]+STAT_NAMES

        final_df = pd.DataFrame()
        if os.path.exists(DETAILS_CSV):
            final_df = pd.read_csv(DETAILS_CSV)
            for stat_name in STAT_NAMES:
                if stat_name not in final_df.columns:
                    final_df[stat_name] = 0
            final_df = final_df[fnames]
            
            
        else:
            print(f"❌ {DETAILS_CSV} 파일이 없어 최종 파일을 생성할 수 없습니다.")

        if os.path.exists(DETAILS_CSV):
            final_done_codes = set(pd.read_csv(DETAILS_CSV)["player_code"].astype(str))
        else:
            final_done_codes = set()
        save_backup(6, {"max_ovr_dict": max_ovr_dict, "min_ovr_dict": min_ovr_dict, "all_codes": list(all_codes), "fetched_codes": list(final_done_codes)})
        elapsed_5 = time.time() - start_time_stage_5 # 🕒 5단계 소요 시간
        if time_labels: time_labels[5].config(text=f"5단계: {elapsed_5:.1f}초")
        print(f"✅ 5단계 완료! 소요 시간: {elapsed_5:.1f}초")
    else:
        print("⏩ 5단계 건너뛰기")

    # 🕒 전체 크롤링 시간 출력
    if overall_start_time is not None:
        elapsed_total = time.time() - overall_start_time
        if total_time_label: total_time_label.config(text=f"총 시간: {elapsed_total:.1f}초")
        print(f"\n✨ 총 크롤링 소요 시간: {elapsed_total:.1f}초 ✨")


# ─────────────────────────────────────────────────────────────
#   GUI 실행 스위치
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    setup_toss_style(root) 
    CrawlerGUI(root)
    root.mainloop()