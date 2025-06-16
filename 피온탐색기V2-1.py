import requests
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import messagebox, ttk
import json

import csv
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import webbrowser
import os
import pandas as pd    
import aiohttp
import asyncio
import sys    # ← 새로 추가
# -------------------------------------------------------------------



# (나머지 ENCHANT_DELTAS, calc_enchanted_stats, player_by_spid 로드 등 상단 코드는 동일)
# --- CSV 파일 경로 및 스탯 컬럼 정의 ---
if getattr(sys, 'frozen', False):
    # EXE로 실행될 때
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # PY로 실행될 때
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
csv_path = os.path.join(DATA_DIR, "details.csv")
 # 수정

CSV_STAT_COLUMNS = [
    '속력', '가속력', '골 결정력', '슛 파워', '중거리 슛', '위치 선정', '발리슛', '페널티 킥',
    '짧은 패스', '시야', '크로스', '긴 패스', '프리킥', '커브','볼 컨트롤',
    '민첩성', '밸런스', '반응 속도', '대인 수비', '태클', '가로채기', '헤더', '슬라이딩 태클',
    '몸싸움', '스태미너', '적극성', '점프', '침착성', 'GK 다이빙', 'GK 핸들링', 'GK 킥',
    'GK 반응속도', 'GK 위치 선정'
]

ENCHANT_DELTAS = {
    1:0, 2:1, 3:2, 4:4, 5:6,
    6:8, 7:11,8:15,9:17,10:19,
    11:21,12:24,13:27
}

def parse_team_colors(x):
    if isinstance(x, str) and x.startswith('['):
        try:
            return json.loads(x)
        except json.JSONDecodeError:
            return []
    return []

def calc_enchanted_stats(base_stats, level):
    delta = ENCHANT_DELTAS.get(level, 0)
    enchanted_stats = {}
    for stat_name in CSV_STAT_COLUMNS:
        enchanted_stats[stat_name] = base_stats.get(stat_name, 0) + delta
    return enchanted_stats

# --- CSV에서 선수명, PID, 시즌, 스탯 로드 ---
# --- CSV → pandas DataFrame 로드 -----------------------------------
dtype_map = {col: 'int16' for col in CSV_STAT_COLUMNS}
dtype_map.update({
    'player_code': 'string', 'player_name': 'string',
    'season': 'string', 'position': 'string',
    'salary': 'int8', 'ovr': 'int8',
    'height': 'int16', 'weight': 'int16',
    'skill': 'int8', 'left_foot': 'int8', 'right_foot': 'int8',
    'traits': 'string','team_colors': 'string'
})

 # --- CSV → pandas DataFrame 로드 -----------------------------------
try:
    df = pd.read_csv(csv_path, dtype=dtype_map, encoding='utf-8-sig')
    df.set_index('player_code', inplace=True)     # PID → 인덱스
except FileNotFoundError:
    messagebox.showerror("파일 오류", f"CSV 파일을 찾을 수 없습니다:\n{csv_path}")
    exit()
except Exception as e:
    messagebox.showerror("CSV 로드 오류", f"CSV 로드 중 오류 발생: {e}")
    exit()
# --- pandas 로드 후, player_by_spid/ALL_PLAYERS_LIST 재생성 📦 ---
player_by_spid = {}
for pid, row in df.iterrows():
    stats = {col: int(row[col]) for col in CSV_STAT_COLUMNS}
    player_by_spid[pid] = {
        'pid': pid,
        'seasonid': row['season'],
        'name': row['player_name'],
        'salary': str(row['salary']),
        'position': row['position'],
        'ovr': str(row['ovr']),
        'height': str(row['height']),
        'weight': str(row['weight']),
        'skill': str(row['skill']),
        'left_foot': str(row['left_foot']),
        'right_foot': str(row['right_foot']),
        'traits': row['traits'],
        'team_colors': row['team_colors'],
        'stats': stats
        
    }
ALL_PLAYERS_LIST = list(player_by_spid.values())
 # -------------------------------------------------------------------
  # 아래 로직 호환
# -------------------------------------------------------------------

player_details_cache = {}
player_price_cache = {}
stop_search_flag = threading.Event()

POSITIONS = ['GK','CB','SW','LB','LWB','RB','RWB','CDM','LM','CM','RM','CAM','LW','RW','LF','CF','RF','ST']
ALL_SEASONS = sorted(list({p['seasonid'] for p in ALL_PLAYERS_LIST}), reverse=True)
COLUMN_STATS = [
    ['속력','가속력','골 결정력','슛 파워','중거리 슛','위치 선정','발리슛','페널티 킥','짧은 패스','시야','크로스','긴 패스'],
    ['프리킥','커브','볼 컨트롤','민첩성','밸런스','반응 속도','대인 수비','태클','가로채기','헤더','슬라이딩 태클'],
    ['몸싸움','스태미너','적극성','점프','침착성','GK 다이빙','GK 핸들링','GK 킥','GK 반응속도','GK 위치 선정']
]
ALL_STATS   = [s for sub in COLUMN_STATS for s in sub]

def fetch_player_ability_page(spid, n1_strong):
    if stop_search_flag.is_set():
        return None
    cache_key = (spid, n1_strong)
    if cache_key in player_details_cache:
        return player_details_cache[cache_key]
    url = 'https://fconline.nexon.com/datacenter/PlayerAbility'
    headers = {'User-Agent': 'Mozilla/5.0'}
    payload = {'spid': spid, 'n1strong': n1_strong}
    try:
        resp = requests.post(url, headers=headers, data=payload, timeout=7)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        pos_tag = soup.select_one('div.playerCardWrap div.position')
        ovr_tag = soup.select_one('div.ovr.value')
        position = pos_tag.text.strip().upper() if pos_tag else 'N/A'
        ovr = ovr_tag.text.strip() if ovr_tag else 'N/A'
        player_details_cache[cache_key] = {'position': position, 'ovr': ovr}
        return player_details_cache[cache_key]
    except:
        player_details_cache[cache_key] = None
        return None

async def async_get_price(pid, n1):
    url = 'https://fconline.nexon.com/datacenter/PlayerPriceGraph'
    headers = {'User-Agent': 'Mozilla/5.0'}
    data = {'spid': pid, 'n1strong': n1}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=7) as resp:
                resp.raise_for_status()
                text = await resp.text()
        soup = BeautifulSoup(text, 'html.parser')
        strong = soup.select_one('div.add_info strong')
        if strong and 'title' in strong.attrs:
            return int(strong['title'].replace(',', ''))
    except:
        return None

def get_price(pid, n1):
    return asyncio.run(async_get_price(pid, n1))


def on_listbox_double_click(event, listbox, pid_list):
    selection_indices = listbox.curselection()
    if not selection_indices:
        return
    selected_index = selection_indices[0]
    pid = pid_list[selected_index]
    url = f"https://fconline.nexon.com/datacenter/PlayerInfo?spid={pid}" 
    webbrowser.open_new_tab(url)

# <changes> 전역 변수 선언 (오류 해결)
# search_button, stop_button, progress_label, pb 뿐만 아니라
# 고급 검색 위젯들도 전역으로 선언해줘야 해!
search_button = None
stop_button = None
progress_label = None
pb = None
name_entry = None # <changes> 추가
pos_list = None # <changes> 추가
season_list = None # <changes> 추가
stat_filters = [] # <changes> 추가 (리스트이므로 초기화)
min_enchant_sel = None # <changes> 추가
max_enchant_sel = None # <changes> 추가
min_price_entry = None # <changes> 추가
max_price_entry = None # <changes> 추가
min_salary_entry = None
max_salary_entry = None
skill_min_sel = None
skill_max_sel = None
height_min_entry = None
height_max_entry = None
weight_min_entry = None
weight_max_entry = None
trait_entry = None
ovr_min_sel = None
trait_entry = None
ALL_TRAITS = [
    '선호포지션 고집', '장거리 스로잉', '파울 유도 선호', '유리몸', '강철몸', '주발 선호', '슬라이딩 태클 선호',
    '개인 플레이 선호', '트러블 메이커', '얼리 크로스 선호', '예리한 감아차기', '화려한 개인기',
    '긴 패스 선호', '중거리 슛 선호', '스피드 드리블러', '플레이 메이커', 'GK 공격 가담',
    'GK 능숙한 펀칭', 'GK 멀리 던지기', '파워 헤더', 'GK 침착한 1:1 수비', '초 장거리 스로인',
    '아웃사이드 슈팅/크로스', '패스마스터', '승부욕', '화려한 걷어내기', '칩슛 선호',
    '테크니컬 드리블러', '스위퍼 키퍼', 'GK 소극적 크로스 수비', 'GK 적극적 크로스 수비'
]

# </changes>

def open_advanced_search():
    global TEAM_COLOR_CHOICES
    global trait_entry, name_entry, pos_list, season_list 
    global stat_filters,height_min_entry, height_max_entry
    global weight_min_entry, weight_max_entry
    dlg = tk.Toplevel(root)
    dlg.title('⚙️ 고급검색')
    dlg.geometry('550x750')
    dlg.configure(bg='#f9fafb')
    dlg.resizable(False, False)
    stop_search_flag.clear()
    
    # 폰트 스타일 적용 (맑은 고딕으로 가정)
    global default_font, title_font, small_font, button_font
    default_font = ('Malgun Gothic', 11)
    title_font = ('Malgun Gothic', 14, 'bold')
    small_font = ('Malgun Gothic', 9)
    button_font = ('Malgun Gothic', 10, 'bold')



    dlg.grid_columnconfigure(0, weight=1) # 컬럼 0에 대한 가중치

    # 스크롤 가능한 영역을 위한 Canvas와 Frame 설정 시작
    canvas = tk.Canvas(dlg, bg='#f9fafb', highlightthickness=0) # Canvas는 자체 테두리 없애기
    canvas.pack(side='top', fill='both', expand=True, padx=15, pady=0) # Canvas가 창의 대부분을 차지

    scrollbar = ttk.Scrollbar(dlg, orient='vertical', command=canvas.yview)
    scrollbar.pack(side='right', fill='y')

    canvas.configure(yscrollcommand=scrollbar.set)
    # Canvas 크기 변경 시 스크롤 영역 업데이트 (이벤트 바인딩)
    def on_frame_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))
    
    # 모든 검색 위젯들이 들어갈 프레임
    scrollable_frame = tk.Frame(canvas, bg='#f9fafb')
    # 이 프레임이 크기 변경될 때마다 on_frame_configure 함수 호출
    scrollable_frame.bind("<Configure>", on_frame_configure)

    # Canvas에 스크롤 가능한 프레임을 윈도우로 추가
    canvas.create_window((0, 0), window=scrollable_frame, anchor='nw')

    # scrollable_frame에 컬럼 설정 (이전의 dlg.grid_columnconfigure 대신)
    scrollable_frame.grid_columnconfigure(1, weight=1)
    # 스크롤 가능한 영역 설정 끝

    row_idx = 0 # 이제 row_idx를 여기서 다시 시작

    # 모든 위젯들을 이제 scrollable_frame에 배치
    # 선수명 입력
    # <changes> name_entry를 전역 변수로 선언하고 할당
    global name_entry 
    # </changes>
    tk.Label(scrollable_frame, text='선수명 ', bg='#f9fafb', font=default_font, anchor='e').grid(row=row_idx, column=0, padx=5, pady=5, sticky='e')
    name_entry = tk.Entry(scrollable_frame, bd=0, font=default_font, relief='flat', bg='#ffffff', 
                           highlightbackground='#e0e0e0', highlightthickness=1) # 테두리 추가
    name_entry.grid(row=row_idx, column=1, columnspan=3, padx=5, pady=5, sticky='we')
    row_idx += 1

    # 포지션 섹션 프레임 (구분선 느낌)
    pos_section_frame = tk.LabelFrame(scrollable_frame, text="포지션", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    pos_section_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')
    
    pos_frame = tk.Frame(pos_section_frame, bg='#f9fafb')
    pos_frame.pack(fill='x', padx=5, pady=5) # 내부 프레임
    
    pos_list_frame = tk.Frame(pos_frame, bg='#ffffff', highlightbackground='#e0e0e0', highlightthickness=1, bd=0) # 리스트박스 테두리
    pos_list_frame.pack(side='left', padx=(0, 10), fill='y')

    # <changes> pos_list를 전역 변수로 선언하고 할당
    global pos_list
    # </changes>
    pos_list = tk.Listbox(pos_list_frame, selectmode='multiple', exportselection=False, height=6, width=15, 
                          font=small_font, bd=0, relief='flat', # 리스트박스 자체의 테두리는 제거
                          selectbackground='#007bff', selectforeground='white') # 선택 하이라이트 색상
    for pos in POSITIONS: pos_list.insert(tk.END, pos)
    pos_list.pack(side='left', fill='y', padx=1, pady=1) # 프레임 안에서 패딩

    btn_frame_pos = tk.Frame(pos_frame, bg='#f9fafb')
    btn_frame_pos.pack(side='left', fill='y')
    tk.Button(btn_frame_pos, text="전체선택", command=lambda: pos_list.select_set(0, tk.END), font=small_font, bg='#e5e7eb', fg='#374151', relief='flat', padx=8, pady=4).pack(padx=2, pady=2, fill='x')
    tk.Button(btn_frame_pos, text="선택해제", command=lambda: pos_list.select_clear(0, tk.END), font=small_font, bg='#e5e7eb', fg='#374151', relief='flat', padx=8, pady=4).pack(padx=2, pady=2, fill='x')
    row_idx += 1

    # 시즌 섹션 프레임
    season_section_frame = tk.LabelFrame(scrollable_frame, text="시즌", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    season_section_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')

    season_frame = tk.Frame(season_section_frame, bg='#f9fafb')
    season_frame.pack(fill='x', padx=5, pady=5)
    
    season_list_frame = tk.Frame(season_frame, bg='#ffffff', highlightbackground='#e0e0e0', highlightthickness=1, bd=0) # 리스트박스 테두리
    season_list_frame.pack(side='left', padx=(0, 10), fill='y')

    # <changes> season_list를 전역 변수로 선언하고 할당
    global season_list
    # </changes>
    season_list = tk.Listbox(season_list_frame, selectmode='multiple', exportselection=False, height=5, width=15, 
                             font=small_font, bd=0, relief='flat', # 리스트박스 자체의 테두리 제거
                             selectbackground='#007bff', selectforeground='white') # 선택 하이라이트 색상
    for s in ALL_SEASONS: season_list.insert(tk.END, s)
    season_list.pack(side='left', fill='y', padx=1, pady=1)

    btn_frame_season = tk.Frame(season_frame, bg='#f9fafb')
    btn_frame_season.pack(side='left', fill='y')
    tk.Button(btn_frame_season, text="전체선택", command=lambda: season_list.select_set(0, tk.END), font=small_font, bg='#e5e7eb', fg='#374151', relief='flat', padx=8, pady=4).pack(side='left', padx=2)
    tk.Button(btn_frame_season, text="선택해제", command=lambda: season_list.select_clear(0, tk.END), font=small_font, bg='#e5e7eb', fg='#374151', relief='flat', padx=8, pady=4).pack(side='left', padx=2)
    row_idx += 1

    # 스탯 필터 섹션 프레임
    stat_section_frame = tk.LabelFrame(scrollable_frame, text="스탯 필터", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    stat_section_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')

    stat_container = tk.Frame(stat_section_frame, bg='#f9fafb')
    stat_container.pack(fill='x', padx=5, pady=5)
    # <changes> stat_filters를 전역 변수로 선언
    global stat_filters
    stat_filters = [] # open_advanced_search가 호출될 때마다 초기화되도록 여기에 배치
    # </changes>

    # 스탯 필터 추가/삭제 시 스크롤 영역 업데이트
    def add_stat_filter():
        var = tk.StringVar(value=ALL_STATS[0])
        frame = tk.Frame(stat_container, bg='#ffffff', highlightbackground='#e0e0e0', highlightthickness=1, bd=0, padx=5, pady=2) # 스탯 필터 각 줄에 테두리
        
        # OptionMenu 스타일링
        option_menu = tk.OptionMenu(frame, var, *ALL_STATS)
        option_menu.config(font=small_font, bg='#ffffff', activebackground='#e0e0e0', relief='flat', bd=0)
        option_menu['menu'].config(font=small_font, bg='#ffffff', activebackground='#007bff', activeforeground='white') # 드롭다운 메뉴 스타일
        option_menu.pack(side='left', padx=(0, 5))

        tk.Label(frame, text='>=', bg='#ffffff', font=small_font).pack(side='left', padx=(5,0))
        ent = tk.Entry(frame, width=5, bd=0, relief='flat', bg='#f0f0f0', font=small_font, justify='center') # 입력창 배경색 약간 다르게
        ent.insert(0, '0'); ent.pack(side='left')
        tk.Button(frame, text='x', command=lambda f=frame: remove_filter(f), font=small_font, bg='#e5e7eb', fg='#374151', relief='flat', padx=5, pady=1).pack(side='left', padx=5)
        frame.pack(anchor='w', pady=3) # 각 스탯 필터 줄 간격
        stat_filters.append((var, ent, frame))
        
        # 스탯 필터 추가될 때 스크롤 영역 업데이트
        dlg.update_idletasks() # 위젯이 배치된 후 크기 계산
        canvas.config(scrollregion=canvas.bbox("all"))

    def remove_filter(frame):
        # <changes> stat_filters가 global로 선언되었으므로, 이 리스트를 수정할 때 global 키워드가 필요 없음 (리스트 자체를 재할당하는 게 아니니까)
        # 하지만 명확성을 위해 global 선언은 유지하는게 좋아
        # global stat_filters # 이 줄은 필요 없음 (리스트의 내용은 변경하지만, 리스트 자체를 재할당하는 것이 아니므로)
        # </changes>
        stat_filters[:] = [f for f in stat_filters if f[2] != frame] # 리스트 내용 수정
        frame.destroy()
        # 스탯 필터 삭제될 때 스크롤 영역 업데이트
        dlg.update_idletasks() # 위젯이 사라진 후 크기 계산
        canvas.config(scrollregion=canvas.bbox("all"))

    add_stat_filter_button_frame = tk.Frame(stat_section_frame, bg='#f9fafb')
    add_stat_filter_button_frame.pack(pady=5, anchor='e') # 오른쪽 정렬
    tk.Button(add_stat_filter_button_frame, text='+ 스탯 필터 추가', command=add_stat_filter, font=small_font, bg='#007bff', fg='#ffffff', relief='flat', padx=10, pady=5).pack(side='left', padx=5)
    
    row_idx += 1

    # (open_advanced_search 함수 내, row_idx += 1 부분 다음쯤에 추가)

    # 1) 전체 팀컬러 후보 뽑기 (리스트로)
    import json
    all_team_colors = set()
    for p in ALL_PLAYERS_LIST:
        try:
            if p['team_colors']:
                for c in json.loads(p['team_colors']):
                    if c and c != '단일팀':   # '단일팀' 빼고!
                        all_team_colors.add(c)
        except Exception:
            continue
    TEAM_COLOR_CHOICES = sorted(all_team_colors)

    # 2) 팀컬러 리스트박스 추가
    teamcolor_frame = tk.LabelFrame(scrollable_frame, text="팀컬러", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    teamcolor_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')

    global teamcolor_listbox
    teamcolor_listbox = tk.Listbox(teamcolor_frame, selectmode='multiple', height=8, width=25, font=small_font)
    for color in TEAM_COLOR_CHOICES:
        teamcolor_listbox.insert(tk.END, color)
    teamcolor_listbox.pack(side='left', fill='y', padx=5, pady=2)
    btn_frame_tc = tk.Frame(teamcolor_frame, bg='#f9fafb')
    btn_frame_tc.pack(side='left', fill='y')
    tk.Button(btn_frame_tc, text="전체선택", command=lambda: teamcolor_listbox.select_set(0, tk.END), font=small_font, bg='#e5e7eb', relief='flat', padx=7).pack(padx=2, pady=2)
    tk.Button(btn_frame_tc, text="선택해제", command=lambda: teamcolor_listbox.select_clear(0, tk.END), font=small_font, bg='#e5e7eb', relief='flat', padx=7).pack(padx=2, pady=2)
    row_idx += 1


    # 강화 단계 섹션 프레임
    enchant_section_frame = tk.LabelFrame(scrollable_frame, text="강화 단계", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    enchant_section_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')
    
    level_frame = tk.Frame(enchant_section_frame, bg='#f9fafb'); level_frame.pack(fill='x', padx=5, pady=5)
    # <changes> min_enchant_sel, max_enchant_sel을 전역 변수로 선언하고 할당
    global min_enchant_sel, max_enchant_sel
    # </changes>
    min_enchant_sel = tk.IntVar(value=1)
    tk.Label(level_frame, text='최소:', bg='#f9fafb', font=default_font).pack(side='left')
    min_option = tk.OptionMenu(level_frame, min_enchant_sel, *range(1, 14))
    min_option.config(font=small_font, bg='#ffffff', activebackground='#e0e0e0', relief='flat', bd=0)
    min_option['menu'].config(font=small_font, bg='#ffffff', activebackground='#007bff', activeforeground='white')
    min_option.pack(side='left', padx=(0,10))

    max_enchant_sel = tk.IntVar(value=1)
    tk.Label(level_frame, text='최대:', bg='#f9fafb', font=default_font).pack(side='left')
    max_option = tk.OptionMenu(level_frame, max_enchant_sel, *range(1, 14))
    max_option.config(font=small_font, bg='#ffffff', activebackground='#e0e0e0', relief='flat', bd=0)
    max_option['menu'].config(font=small_font, bg='#ffffff', activebackground='#007bff', activeforeground='white')
    max_option.pack(side='left')
    row_idx += 1

    # 급여 필터 섹션 프레임
    
    global min_salary_sel, max_salary_sel
    min_salary_sel = tk.IntVar(value=5)
    max_salary_sel = tk.IntVar(value=50)
    salary_frame = tk.LabelFrame(scrollable_frame, text="급여 필터", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    salary_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')
    tk.Label(salary_frame, text='최소 급여 (5~50):', bg='#f9fafb', font=small_font).grid(row=0, column=0, padx=5, pady=5, sticky='e')
    tk.OptionMenu(salary_frame, min_salary_sel, *range(5,51)).grid(row=0, column=1, padx=5, pady=5, sticky='w')
    tk.Label(salary_frame, text='최대 급여 (5~50):', bg='#f9fafb', font=small_font).grid(row=0, column=2, padx=5, pady=5, sticky='e')
    tk.OptionMenu(salary_frame, max_salary_sel, *range(5,51)).grid(row=0, column=3, padx=5, pady=5, sticky='w')
    row_idx += 1
    # --- 스킬 등급 필터 (1~5) ---
    global skill_min_sel, skill_max_sel
    skill_min_sel = tk.IntVar(value=1)
    skill_max_sel = tk.IntVar(value=5)
    skill_frame = tk.LabelFrame(scrollable_frame, text="스킬 등급 필터", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    skill_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')
    tk.Label(skill_frame, text='스킬 등급:', bg='#f9fafb', font=small_font).grid(row=0, column=0, padx=5, pady=5, sticky='e')
    tk.OptionMenu(skill_frame, skill_min_sel, *range(1,6)).grid(row=0, column=1, sticky='w')
    tk.Label(skill_frame, text='~', bg='#f9fafb', font=small_font).grid(row=0, column=2)
    tk.OptionMenu(skill_frame, skill_max_sel, *range(1,6)).grid(row=0, column=3, sticky='w')
    row_idx += 1

    # --- 키/몸무게 필터 ---
    body_frame = tk.LabelFrame(scrollable_frame, text="신체(키/몸무게) 필터", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    body_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')
    tk.Label(body_frame, text='키 범위(cm):', bg='#f9fafb', font=small_font).grid(row=0, column=0, sticky='e', padx=5)
    height_min_entry = tk.Entry(body_frame, width=5, font=small_font); height_min_entry.grid(row=0, column=1)
    tk.Label(body_frame, text='~', bg='#f9fafb', font=small_font).grid(row=0, column=2)
    height_max_entry = tk.Entry(body_frame, width=5, font=small_font); height_max_entry.grid(row=0, column=3)
    tk.Label(body_frame, text='몸무게 범위(kg):', bg='#f9fafb', font=small_font).grid(row=1, column=0, sticky='e', padx=5)
    weight_min_entry = tk.Entry(body_frame, width=5, font=small_font); weight_min_entry.grid(row=1, column=1)
    tk.Label(body_frame, text='~', bg='#f9fafb', font=small_font).grid(row=1, column=2)
    weight_max_entry = tk.Entry(body_frame, width=5, font=small_font); weight_max_entry.grid(row=1, column=3)
    row_idx += 1

    
    # --- 특성 필터 (부분 문자열) ---
    global trait_listbox  # <--- 반드시 전역변수로 선언! (필터에서 접근 위해)
    trait_frame = tk.LabelFrame(scrollable_frame, text="특성 다중 선택", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    trait_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')
    trait_listbox = tk.Listbox(trait_frame, selectmode='multiple', height=8, width=20, font=small_font)
    for trait in ALL_TRAITS:
        trait_listbox.insert(tk.END, trait)
    trait_listbox.pack(side='left', fill='y', padx=5, pady=2)
    btn_frame_trait = tk.Frame(trait_frame, bg='#f9fafb')
    btn_frame_trait.pack(side='left', fill='y')
    tk.Button(btn_frame_trait, text="전체선택", command=lambda: trait_listbox.select_set(0, tk.END), font=small_font, bg='#e5e7eb', relief='flat', padx=7).pack(padx=2, pady=2)
    tk.Button(btn_frame_trait, text="선택해제", command=lambda: trait_listbox.select_clear(0, tk.END), font=small_font, bg='#e5e7eb', relief='flat', padx=7).pack(padx=2, pady=2)
    row_idx += 1

    
        # 가격 필터 섹션 프레임
    price_section_frame = tk.LabelFrame(scrollable_frame, text="가격 필터 (억 단위)", font=default_font, bg='#f9fafb', fg='#333', padx=10, pady=10, bd=1, relief='solid', highlightbackground='#e0e0e0')
    price_section_frame.grid(row=row_idx, column=0, columnspan=4, padx=5, pady=10, sticky='nsew')

    price_frame = tk.Frame(price_section_frame, bg='#f9fafb'); price_frame.pack(fill='x', padx=5, pady=5)
    tk.Label(price_frame, text='최소:', bg='#f9fafb', font=default_font).pack(side='left')
    # <changes> min_price_entry, max_price_entry를 전역 변수로 선언하고 할당
    global min_price_entry, max_price_entry
    # </changes>
    min_price_entry = tk.Entry(price_frame, width=10, bd=0, relief='flat', bg='#ffffff', font=default_font, highlightbackground='#e0e0e0', highlightthickness=1); min_price_entry.pack(side='left', padx=(0,10))
    tk.Label(price_frame, text='최대:', bg='#f9fafb', font=default_font).pack(side='left')
    max_price_entry = tk.Entry(price_frame, width=10, bd=0, relief='flat', bg='#ffffff', font=default_font, highlightbackground='#e0e0e0', highlightthickness=1); max_price_entry.pack(side='left')
    row_idx += 1

    # 진행 상황 및 버튼들을 캔버스 바깥에 배치하여 항상 보이게 함
    # Canvas가 pack(expand=True) 되어 있어서, Canvas 다음에 pack되는 위젯들은 Canvas 아래에 위치
    
    # 7. 진행상황
    # <changes> 전역 변수를 참조하도록 global 키워드 사용 (이미 위에 선언했으므로 다시 할 필요는 없지만, 명확성을 위해)
    global progress_label, pb, search_button, stop_button
    # </changes>
    progress_label = tk.Label(dlg, text="진행: 0/0", bg='#f9fafb', font=default_font, fg='#555')
    progress_label.pack(pady=(15,5))
    pb = ttk.Progressbar(dlg, length=400, mode='determinate', style='Custom.Horizontal.TProgressbar') # 길이 조정
    pb.pack(pady=5)

    # ttk.Style을 사용하여 프로그레스바 색상 변경
    style = ttk.Style()
    style.theme_use('default')
    style.configure('Custom.Horizontal.TProgressbar', background='#007bff', troughcolor='#e0e0e0', thickness=10, borderwidth=0) # borderwidth=0 추가


    # 8. 버튼들 (검색, 중단)
    btn_frame_bottom = tk.Frame(dlg, bg='#f9fafb')
    btn_frame_bottom.pack(pady=20)

    # ⭐ 여기서 변수에 직접 할당 → 전역 변수로 이미 선언되었으므로 새로운 생성 아님
    search_button = tk.Button(btn_frame_bottom, text='🔍 검색', command=lambda: start_search_thread(), font=button_font, bg='#007bff', fg='#ffffff', relief='flat', padx=20, pady=10)
    search_button.pack(side='left', padx=10, fill='x', expand=True)

    stop_button = tk.Button(btn_frame_bottom, text='⛔ 중단', command=lambda: stop_search_flag.set(), font=button_font, bg='#e5e7eb', fg='#374151', relief='flat', padx=20, pady=10)
    stop_button.pack(side='left', padx=10, fill='x', expand=True)
    stop_button.config(state='disabled')
    
    # 스크롤바가 작동하도록 Canvas의 scrollregion을 초기 업데이트
    dlg.update_idletasks() # 모든 위젯이 배치된 후 프레임 크기를 정확히 계산
    canvas.config(scrollregion=canvas.bbox("all"))

    # 마우스 휠 스크롤 이벤트 바인딩
    def _on_mousewheel(event):
        # 윈도우와 리눅스/맥의 마우스 휠 이벤트 처리 방식이 다름
        if event.num == 5 or event.delta == -120: # 스크롤 다운
            canvas.yview_scroll(1, "unit")
        elif event.num == 4 or event.delta == 120: # 스크롤 업
            canvas.yview_scroll(-1, "unit")

    # 고급 검색 창에만 스크롤 휠 이벤트를 바인딩하도록 변경
    # canvas.bind_all 대신 dlg에 바인딩
    canvas.bind("<MouseWheel>", _on_mousewheel) # 윈도우
    canvas.bind("<Button-4>", _on_mousewheel) # 리눅스
    canvas.bind("<Button-5>", _on_mousewheel) # 리눅스

# --- 최적화된 검색 로직 ---
def start_search_thread():
    global search_button, stop_button
    search_button.config(state='disabled')
    stop_button.config(state='normal')
    stop_search_flag.clear()
    player_price_cache.clear()
    threading.Thread(target=do_advanced_search, daemon=True).start()

def prefilter_df(
    name_q, sel_seasons, selected_team_colors,
    sel_positions,
    min_salary, max_salary,
    skill_min, skill_max,
    h_min, h_max, w_min, w_max,
    selected_traits,
    stat_filters, min_lv, max_lv,
):
    q = df
    q = df.copy()  # 원본 DataFrame을 복사하여 사용
    q['team_colors'] = q['team_colors'].apply(
    lambda x: json.loads(x) if pd.notnull(x) and x.startswith('[') else [])

    if selected_team_colors:
        q = q[q['team_colors'].apply(lambda arr: any(tc in arr for tc in selected_team_colors))]
        

    if name_q:
        q = q[q['player_name'].str.lower().str.contains(name_q)]

    if sel_seasons:
        q = q[q['season'].isin(sel_seasons)]

    if sel_positions:
        q = q[q['position'].isin(sel_positions)]

    q = q[q['salary'].between(min_salary, max_salary)]
    q = q[q['skill'].between(skill_min, skill_max)]
    q = q[q['height'].between(h_min, h_max)]
    q = q[q['weight'].between(w_min, w_max)]

    if selected_traits:
        pattern = '|'.join(selected_traits)
        q = q[q['traits'].str.contains(pattern)]

    if selected_team_colors:
        
        def teamcolor_ok(s):
            try:
                arr = json.loads(s) if isinstance(s, str) else s
                # 모두 포함해야만 통과 (AND)
                return all(tc in arr for tc in selected_team_colors)
            except Exception:
                return False
        q = q[q['team_colors'].apply(teamcolor_ok)]


    
    if stat_filters:
        base = q[CSV_STAT_COLUMNS]
        ok = pd.Series(False, index=base.index)
        for lv in range(min_lv, max_lv + 1):
            boosted = base + ENCHANT_DELTAS.get(lv, 0)
            cond = pd.Series(True, index=base.index)
            for stat, min_v in stat_filters:
                cond &= boosted[stat] >= min_v
            ok |= cond
        q = q[ok]

    return q

def do_advanced_search():
    global name_entry, pos_list, season_list, stat_filters, \
           min_enchant_sel, max_enchant_sel, min_price_entry, max_price_entry, \
           progress_label, pb, search_button, stop_button

    name_q = name_entry.get().strip().lower()
    sel_seasons = [ALL_SEASONS[i] for i in season_list.curselection()] if season_list.curselection() else []
    sel_positions = [POSITIONS[i] for i in pos_list.curselection()] if pos_list.curselection() else []
    # 팀컬러 선택값 읽기
    selected_team_colors = [TEAM_COLOR_CHOICES[i] for i in teamcolor_listbox.curselection()]


    # 1단계: pandas 기반 사전 필터링 → DataFrame index로 dict 복원 🚀
    filtered_df = prefilter_df(
    name_q,
    sel_seasons,
    selected_team_colors,       # ← 무조건 여기!
    sel_positions,
    min_salary_sel.get(), max_salary_sel.get(),
    skill_min_sel.get(), skill_max_sel.get(),
    int(height_min_entry.get() or 0), int(height_max_entry.get() or 999),
    int(weight_min_entry.get() or 0), int(weight_max_entry.get() or 999),
    [ALL_TRAITS[i] for i in trait_listbox.curselection()],
    [(var.get(), int(ent.get())) for var, ent, _ in stat_filters],
    min_enchant_sel.get(), max_enchant_sel.get()
)


    filtered_ids = filtered_df.index.tolist()
    pre_filtered = [player_by_spid[pid] for pid in filtered_ids]

    if not pre_filtered:
        root.after(0, lambda: messagebox.showinfo('검색 결과','조건에 맞는 선수가 없어요. 😥'))
        root.after(0, lambda: search_button.config(state='normal'))
        root.after(0, lambda: stop_button.config(state='disabled'))
        return

    # 2단계: 가격만 크롤링
    total = len(pre_filtered)
    root.after(0, lambda: pb.config(maximum=total, value=0))
    root.after(0, lambda: progress_label.config(text=f"진행: 0/{total}"))
    results = []
    with ThreadPoolExecutor(max_workers=13) as ex:
        futures = {ex.submit(check_player, p): p for p in pre_filtered}
        done = 0
        for fut in as_completed(futures):
            if stop_search_flag.is_set(): break
            done += 1
            root.after(0, lambda d=done: (pb.config(value=d), progress_label.config(text=f"진행: {d}/{total}")))
            res = fut.result()
            if res:
                results.extend(res)

    root.after(0, lambda: show_results(results))
    root.after(0, lambda: search_button.config(state='normal'))
    root.after(0, lambda: stop_button.config(state='disabled'))


def check_player(player):
    if stop_search_flag.is_set(): return None
    pid = player['pid']
    base = player['stats']
    matched = []

    for lvl in range(min_enchant_sel.get(), max_enchant_sel.get()+1):
        if stop_search_flag.is_set(): return None
        stats_lv = calc_enchanted_stats(base, lvl)
        criteria = [(var.get(), int(ent.get())) for var, ent, _ in stat_filters]
        if not all(stats_lv[s] >= v for s, v in criteria):
            continue

        price = get_price(pid, lvl)
        if price is None: continue
        mi = min_price_entry.get().strip()
        ma = max_price_entry.get().strip()
        if (mi and price < int(mi)*100000000) or (ma and price > int(ma)*100000000):
            continue

        # CSV 정보 그대로 쓰기
        pos = player['position']
        ovr = player['ovr']
        filtered = {s: stats_lv[s] for s, _ in criteria}
        matched.append((player, lvl, pos, price, ovr, filtered))

    return matched if matched else None


from tkinter import ttk

def show_results(results):
    if not results:
        messagebox.showinfo('검색 결과', '조건에 맞는 선수가 없어요. 😥')
        return

    columns = ("name", "season", "enhance", "pos", "ovr", "salary","price", "stat")
    col_titles = {
        "name":"선수명", "season":"시즌", "enhance":"강화", "pos":"포지션",
        "ovr":"OVR(1카기준)", "salary":"급여", "price":"가격(억)", "stat":"주요스탯"
    }

    res_dlg = tk.Toplevel(root)
    res_dlg.title(f'검색 결과 ({len(results)}명) (더블클릭해서 상세 정보 확인! 👆)')
    res_dlg.geometry('1100x650')
    res_dlg.configure(bg='#f9fafb') # 배경색 통일
    frame_results = tk.Frame(res_dlg, bg='#f9fafb')
    frame_results.pack(padx=10, pady=10, fill='both', expand=True)

    # Treeview 스타일 적용
    style = ttk.Style()
    style.theme_use("default") # 기본 테마 사용
    style.configure("Treeview.Heading", font=('Malgun Gothic', 10, 'bold'), background='#e5e7eb', foreground='#374151') # 맑은 고딕
    style.configure("Treeview", font=('Malgun Gothic', 10), rowheight=25, background='#ffffff', fieldbackground='#ffffff', foreground='#333') # 맑은 고딕
    style.map("Treeview", background=[('selected', '#007bff')]) # 선택 시 파란색

    tree = ttk.Treeview(frame_results, columns=columns, show="headings", height=30, style="Treeview")
    for col in columns:
        tree.heading(col, text=col_titles[col], command=lambda _col=col: sortby(tree, _col, False))
    # 컬럼 넓이 설정 (원하는 대로 조정 가능)
    tree.column("name", width=120, anchor='w')
    tree.column("season", width=130, anchor='w')
    tree.column("salary", width=45, anchor="center")

    tree.column("enhance", width=45, anchor="center")
    tree.column("pos", width=60, anchor="center")
    tree.column("ovr", width=50, anchor="center")
    tree.column("price", width=90, anchor="e")
    tree.column("stat", width=180, anchor="w") # 좀 더 넓게

    scrollbar = ttk.Scrollbar(frame_results, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)

    result_pids = []

    # 원본 rows 저장
    # 여기서 results를 직접 tree에 insert하는 방식으로 변경 (sortby 함수가 인메모리 정렬이 아니므로)
    result_pid_lvls = []
    for p, lvl, pos, price, ovr, filtered_stats in results:
        price_str = f"{price / 100000000:,.2f}" if price is not None else 'N/A'
        stat_info_str = ", ".join(f"{k}:{v}" for k, v in filtered_stats.items())
        tree.insert('', tk.END, values=(p['name'], p['seasonid'], f"{lvl}강", pos, ovr,  p['salary'],price_str, stat_info_str))
        result_pids.append((p['pid'],lvl)) # PID만 따로 저장하여 더블클릭 시 사용
    # 컬럼 정렬 함수
    def sortby(tree, col, descending):
        """트리뷰 컬럼 정렬(오름/내림차순 토글)"""
        # 모든 아이템 가져와서 values로 정렬
        data = [(tree.set(child, col), child) for child in tree.get_children('')]
        # 가격/OVR/강화 등 숫자 컬럼은 숫자로 정렬!
        if col in ["ovr", "price", "enhance"]:
            def num(v):
                # 강화는 '1강' -> 1, 가격은 1,100,000.00 → 1100000.0
                if col == "enhance":
                    try: return int(v.replace("강", ""))
                    except: return 0
                if col == "price":
                    try: return float(v.replace(",", ""))
                    except: return 0
                try: return int(v)
                except: return 0
            data.sort(key=lambda t: num(t[0]), reverse=descending)
        else:
            data.sort(key=lambda t: t[0], reverse=descending) # 문자열 정렬
        
        # 기존 순서대로 다시 insert
        for idx, (val, child) in enumerate(data):
            tree.move(child, '', idx)
        # 다음 클릭 시 반대방향 정렬
        tree.heading(col, command=lambda: sortby(tree, col, not descending))

    # 더블클릭 이벤트 그대로
    def on_row_double_click(event):
        item_id = tree.selection()  # 선택된 트리뷰 행의 ID 가져오기
        if not item_id:
            return

    # 트리뷰에서 행의 모든 values를 가져옴
        row_values = tree.item(item_id[0])["values"]
    # 선수명/시즌/강화/포지션 등 원하는 값이 들어있음

    # 예시: PID와 강화 찾기 (너는 result_pids 말고, row_values에서 추출해야 함)
    # 만약 PID가 트리뷰 values에 없으면, 선수명+시즌+포지션+강화로 ALL_PLAYERS_LIST에서 찾을 수도 있음

        player_name = row_values[0]
        season_id   = row_values[1]
        enhance     = row_values[2]
    # 필요에 따라 더 뽑기

    # result_pids 대신 트리뷰에서 직접 찾은 값으로 검색
        pid, lvl = None, None
    # ALL_PLAYERS_LIST 등에서 값 매칭 (혹은 PID를 트리뷰에 같이 넣어놔도 됨)
        for p in ALL_PLAYERS_LIST:
           if (
               p['name'] == player_name
               and p['seasonid'] == season_id
            ):
               pid = p['pid']
               break

        if pid:
        # 강화는 예: '8강' → 숫자 추출
            lvl = int(''.join([ch for ch in enhance if ch.isdigit()]))
            url = f"https://fconline.nexon.com/Datacenter/PlayerInfo?spid={pid}&n1Strong={lvl}"
            webbrowser.open_new_tab(url)
    tree.bind("<Double-1>", on_row_double_click)


# --- 단일 조회 (기존과 동일) ---
def on_search():
    name_q = entry.get().strip().lower()
    if not name_q:
        messagebox.showwarning('입력 오류','선수명을 입력해주세요! 😅'); return
    matches = [p for p in ALL_PLAYERS_LIST if name_q in p['name'].lower()]
    if not matches:
        messagebox.showinfo('검색 결과','선수를 찾을 수 없어요. 😥'); return
    
    res = tk.Toplevel(root)
    res.title('조회 결과 (더블클릭해서 상세 정보 확인! 👆)')
    res.geometry('800x600')
    res.configure(bg='#f9fafb') # 배경색 통일
    
    frame_results = tk.Frame(res, bg='#f9fafb')
    frame_results.pack(padx=10, pady=10, fill='both', expand=True)
    
    lb  = tk.Listbox(frame_results, width=100, height=25, font=('Malgun Gothic', 10), bd=0, relief='flat', selectbackground='#007bff', selectforeground='white') # 폰트 및 스타일 적용
    scrollbar = tk.Scrollbar(frame_results, orient="vertical", command=lb.yview)
    lb.config(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    lb.pack(side="left", fill="both", expand=True)
    
    result_pids = []
    selected_enchant_level = enchant.get()
    
    # 진행 상황 표시
    progress_label_single = tk.Label(res, text="정보 로딩 중...", bg='#f9fafb', font=('Malgun Gothic', 9), fg='#555')
    progress_label_single.pack(pady=5)
    
    # 롱런 태스크를 위한 헬퍼 함수
    def _do_single_search():
        processed_count = 0
        total_matches = len(matches)
        for p in matches:
            if stop_search_flag.is_set(): # 단일 검색에서도 중단 가능하게 (고급 검색과 통일성)
                break
            try:
                formatted_line, pid_val = fetch_and_format_single_player_info(p, selected_enchant_level)
                if formatted_line:
                    root.after(0, lambda line=formatted_line: lb.insert(tk.END, line))
                    result_pids.append(pid_val)
            except Exception as exc:
                root.after(0, lambda name=p['name']: lb.insert(tk.END, f"{name} | 정보 로드 실패 😔"))
                result_pids.append(p['pid']) # 실패해도 PID는 추가해서 더블클릭 가능하게
            processed_count += 1
            root.after(0, lambda count=processed_count, total=total_matches: progress_label_single.config(text=f"정보 로딩 중: {count}/{total}"))
        
        root.after(0, lambda: res.title(f'조회 결과 ({len(result_pids)}명) (더블클릭해서 상세 정보 확인! 👆)'))
        root.after(0, lambda: progress_label_single.config(text="로딩 완료! 😊"))
        lb.bind("<Double-1>", lambda event: on_listbox_double_click(event, lb, result_pids))

    # 스레드로 실행
    threading.Thread(target=_do_single_search, daemon=True).start()


def fetch_and_format_single_player_info(player, level):
    pid = player['pid']
    season = player['seasonid']
    pos = 'N/A'
    ovr = 'N/A'
    web_details = fetch_player_ability_page(pid, level)
    if web_details:
        pos = web_details['position']
        ovr = web_details['ovr']
    web_price = get_price(pid, level)
    price_str = f"{web_price / 100000000:,.2f}억" if web_price is not None else 'N/A'
    formatted_line = f"선수명: {player['name']} | 시즌:{season} | 강화:{level} | 포지션:{pos} | OVR:{ovr} | 가격:{price_str}"
    return formatted_line, pid

# --- 메인 윈도우 ---
root = tk.Tk()
root.title('✨ FC온라인 선수 능력치 & 가격 조회기')
root.geometry('500x400')
root.configure(bg='#f9fafb')  # 토스 느낌 밝은 회색 톤
root.resizable(False, False)

# 모던한 폰트 스타일 지정
default_font = ('Malgun Gothic', 11)
title_font = ('Malgun Gothic', 14, 'bold')
small_font = ('Malgun Gothic', 9) # 고급 검색용으로 추가
button_font = ('Malgun Gothic', 10, 'bold')

# 메인 프레임 설정
main_frame = tk.Frame(root, bg='#f9fafb')
main_frame.pack(expand=True, fill='both')

# 제목 라벨 (약간 크게, 진하게)
title_label = tk.Label(main_frame, text="🔍 선수 조회하기", font=title_font, bg='#f9fafb', fg='#333')
title_label.pack(pady=(20,10))

# 선수명 입력 프레임 (둥근 느낌)
entry_frame = tk.Frame(main_frame, bg='#ffffff', highlightbackground='#e0e0e0', highlightthickness=1, bd=0) # bd=0 추가
entry_frame.pack(pady=10, ipady=5, ipadx=5)
entry = tk.Entry(entry_frame, bd=0, font=default_font, justify='center')
entry.pack(ipady=5, padx=10)

# 강화 버튼 프레임
enchant_frame = tk.Frame(main_frame, bg='#f9fafb')
enchant_frame.pack(pady=10)

enchant = tk.IntVar(value=1)
buttons = []

def set_level(i):
    enchant.set(i)
    for idx, btn in enumerate(buttons, 1):
        btn.configure(bg='#ffffff' if idx != i else '#007bff', fg='#000' if idx != i else '#ffffff', relief='flat') # relief='flat' 추가
        if idx == i:
            btn.config(font=('Malgun Gothic', 9, 'bold'), borderwidth=0)
        else:
            btn.config(font=('Malgun Gothic', 9), borderwidth=0) # 선택 안된 버튼 폰트도 일반 폰트로
        
for i in range(1, 14):
    btn = tk.Button(enchant_frame, text=str(i), font=('Malgun Gothic', 9), # 초기 폰트 일반으로
                     bg='#ffffff', fg='#000', bd=0, relief='flat', width=3,
                     command=lambda i=i: set_level(i))
    btn.grid(row=0, column=i, padx=2, pady=2)
    buttons.append(btn)
set_level(1)  # 1강 기본 선택

# 버튼 프레임
btn_frame = tk.Frame(main_frame, bg='#f9fafb')
btn_frame.pack(pady=20)

search_btn = tk.Button(btn_frame, text='🔍 조회', font=default_font, bg='#007bff', fg='#ffffff',
                        relief='flat', padx=15, pady=8, command=on_search)
search_btn.pack(side='left', padx=10)

adv_search_btn = tk.Button(btn_frame, text='⚙️ 고급검색', font=default_font, bg='#e5e7eb', fg='#374151',
                            relief='flat', padx=15, pady=8, command=open_advanced_search)
adv_search_btn.pack(side='left', padx=10)

entry.bind('<Return>', lambda e: on_search())

root.mainloop()