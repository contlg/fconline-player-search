"""
salary 5~50 전체 수집 테스트. v1 기준 41,289명 초과 확인용.
"""
import asyncio, threading, time, json, os, sys, types
import aiohttp, pandas as pd

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

v2.DETAILS_CSV     = os.path.join(v2.DATA_DIR, "details_full_test.csv")
v2.FINAL_CSV       = os.path.join(v2.DATA_DIR, "all_player_detail_full_test.csv")
v2.CHECKPOINT_JSON = os.path.join(v2.DATA_DIR, "checkpoint_full_test.json")

async def main():
    stop_event   = threading.Event()
    salary_range = range(50, 4, -1)   # salary 5~50

    t0 = time.time()
    print("Phase 1: OVR 탐색 (salary 5~50)")
    ovr_results = await v2.run_phase1(salary_range, max_con=50,
                                      stop_event=stop_event,
                                      progress_cb=lambda d,t: None)
    print(f"OVR 결과: {json.dumps({k: ovr_results[k] for k in sorted(ovr_results.keys(), key=int) if ovr_results[k]}, ensure_ascii=False)}")
    print(f"Phase 1: {time.time()-t0:.1f}초\n")

    print("Phase 2: 수집 시작")
    t1 = time.time()
    await v2.run_phase2(ovr_results, salary_range, max_con=100,
                        n_workers=2,
                        stop_event=stop_event,
                        progress_cb=lambda d,t: None)
    print(f"Phase 2: {time.time()-t1:.1f}초\n")

    v2.finalize()

    df = pd.read_csv(v2.DETAILS_CSV, on_bad_lines="skip")
    df["salary"] = pd.to_numeric(df["salary"], errors="coerce")

    print("\n📊 급여별 결과 (v1 기준)")
    v1_counts = {5:17267,6:1666,7:1011,8:885,9:954,10:889,11:782,12:751,
                 13:726,14:738,15:717,16:676,17:658,18:636,19:634,20:580,
                 21:567,22:535,23:520,24:497,25:494,26:467,27:449,28:429,
                 29:424,30:399,31:385,32:373,33:353,36:306,37:296,38:283,
                 39:271,40:258,41:248,42:237,43:220}
    print(f"{'급여':>4} | {'v1':>6} | {'v2':>6} | {'차이':>6}")
    print("-"*32)
    total_v1 = total_v2 = 0
    for sal in sorted(v1_counts.keys()):
        cnt_v2 = len(df[df["salary"]==sal])
        cnt_v1 = v1_counts[sal]
        diff = cnt_v2 - cnt_v1
        total_v1 += cnt_v1; total_v2 += cnt_v2
        print(f"  {sal:3d} | {cnt_v1:6d} | {cnt_v2:6d} | {diff:+6d}")
    print("-"*32)
    print(f"  합계 | {total_v1:6d} | {total_v2:6d} | {total_v2-total_v1:+6d}")
    print(f"\n전체 v2 수집 수: {len(df)}명")

    dupes = df.duplicated(subset=["player_code"]).sum()
    print(f"중복 player_code: {dupes}개")
    print(f"총 소요: {time.time()-t0:.1f}초")

asyncio.run(main())

for f in [v2.DETAILS_CSV, v2.FINAL_CSV, v2.CHECKPOINT_JSON]:
    if os.path.exists(f): os.remove(f)
print("테스트 파일 정리 완료")
