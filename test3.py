"""
salary 5~10 수집 테스트. v1 기준과 비교.
v1 기준: 5=17267, 6=1666, 7=1011, 8=885, 9=954, 10=889 → 합계 22,672명
"""
import asyncio, threading, time, json, re, os, sys, types
import aiohttp, pandas as pd
from bs4 import BeautifulSoup

# tkinter 모킹
for mod in ["tkinter","tkinter.ttk","tkinter.scrolledtext","tkinter.messagebox"]:
    if mod not in sys.modules:
        m = types.ModuleType(mod)
        for attr in ["Tk","Toplevel","Frame","Label","Button","Entry","Style",
                     "Progressbar","DoubleVar","StringVar","ScrolledText"]:
            setattr(m, attr, object)
        sys.modules[mod] = m
import tkinter as tk
if not hasattr(tk, "Toplevel"): tk.Toplevel = object

sys.path.insert(0, os.path.dirname(__file__))
import FCDataMaker_v2 as v2

v2.DETAILS_CSV     = os.path.join(v2.DATA_DIR, "details_test3.csv")
v2.FINAL_CSV       = os.path.join(v2.DATA_DIR, "all_player_detail_test3.csv")
v2.CHECKPOINT_JSON = os.path.join(v2.DATA_DIR, "checkpoint_test3.json")

async def main():
    stop_event   = threading.Event()
    salary_range = range(10, 4, -1)   # salary 5~10

    t0 = time.time()
    print("Phase 1: OVR 탐색 (salary 5~10)")
    ovr_results = await v2.run_phase1(salary_range, max_con=20,
                                      stop_event=stop_event,
                                      progress_cb=lambda d,t: None)
    print(f"OVR 결과: {json.dumps(ovr_results, ensure_ascii=False)}")
    print(f"Phase 1: {time.time()-t0:.1f}초\n")

    print("Phase 2: 수집 시작")
    t1 = time.time()
    await v2.run_phase2(ovr_results, salary_range, max_con=20,
                        stop_event=stop_event,
                        progress_cb=lambda d,t: None)
    print(f"Phase 2: {time.time()-t1:.1f}초\n")

    v2.finalize()

    df = pd.read_csv(v2.DETAILS_CSV, on_bad_lines="skip")
    df["ovr"] = pd.to_numeric(df["ovr"], errors="coerce")
    df["salary"] = pd.to_numeric(df["salary"], errors="coerce")

    print("\n📊 급여별 결과")
    print(f"{'급여':>4} | {'v1':>6} | {'v2':>6} | {'차이':>6}")
    print("-"*32)
    v1_counts = {5:17267, 6:1666, 7:1011, 8:885, 9:954, 10:889}
    total_v1 = total_v2 = 0
    for sal in range(5, 11):
        cnt_v2 = len(df[df["salary"]==sal])
        cnt_v1 = v1_counts[sal]
        diff = cnt_v2 - cnt_v1
        total_v1 += cnt_v1; total_v2 += cnt_v2
        print(f"  {sal:3d} | {cnt_v1:6d} | {cnt_v2:6d} | {diff:+6d}")
    print("-"*32)
    print(f"  합계 | {total_v1:6d} | {total_v2:6d} | {total_v2-total_v1:+6d}")

    dupes = df.duplicated(subset=["player_code"]).sum()
    print(f"\n중복 player_code: {dupes}개")
    print(f"총 소요: {time.time()-t0:.1f}초")

asyncio.run(main())

for f in [v2.DETAILS_CSV, v2.FINAL_CSV, v2.CHECKPOINT_JSON]:
    if os.path.exists(f): os.remove(f)
print("테스트 파일 정리 완료")
