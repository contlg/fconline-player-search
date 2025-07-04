# 🕵️‍♂️ 피온탐색기 (FC온라인 선수 검색기)

FC온라인 선수들의 능력치, 시즌, 포지션, 팀컬러, 강화, 가격 등을  
**빠르게 검색하고 필터링**할 수 있는 고급 검색 도구입니다.

> 🚀 GUI 기반이라 누구나 쉽게 사용할 수 있어요.

---

## 🧩 주요 기능

- 🔍 이름, 시즌, 포지션, 팀컬러별 고급 필터링  
- 💰 강화별 가격 자동 조회  
- 📈 능력치 평균 비교 및 정렬  
- 🖥️ Tkinter 기반의 직관적인 인터페이스  
- ⚡ 빠른 검색 속도 (비동기 + 캐싱 지원)

## 🖥️ 실행 파일 다운로드 (.exe)

파이썬이 없어도 바로 실행 가능!  
⬇️ 아래 링크에서 다운로드:

👉 [Releases 탭에서 .exe 받기](https://github.com/contlg/fconline-player-search/releases)

---


## 🖼️ 프로그램 미리보기

### 📌 기본 검색 화면
![main_ui](.github/images/main.png)

### 🎯 고급 검색 필터 기능
- 다양한 스탯, 시즌, 팀컬러, 급여 조건을 동시에 조합 가능

![search_1](.github/images/f1.png) 

![search_2](.github/images/f2.png)  

![search_3](.github/images/f3.png)

### 🎯 실전처럼 조합된 필터 예시
- 다양한 스탯, 시즌, 팀컬러, 급여 조건을 동시에 조합 가능

![search_1](.github/images/wf1.png)  

![search_2](.github/images/wf2.png) 

![search_3](.github/images/wf3.png)

### 📋 고급 검색 결과 창
- 필터에 맞는 검색결과를 보여줍니다

![search_3](.github/images/ws1.png)

---

## 🛠️ 설치 방법

### ✅ 1. 파이썬 설치
- Python 3.10 이상 필요: [https://www.python.org/](https://www.python.org/)

### ✅ 2. 필수 라이브러리 설치
```bash
pip install -r requirements.txt
```

또는 수동 설치:
```bash
pip install requests beautifulsoup4 pandas aiohttp httpx
```

### ✅ 3. 실행 방법
```bash
python 피온탐색기V2-1.py
```

---

## 🖥️ 실행 파일 다운로드 (.exe)

파이썬이 없어도 바로 실행 가능!  
⬇️ 아래 링크에서 다운로드:

👉 [Releases 탭에서 .exe 받기](https://github.com/contlg/fconline-player-search/releases)

---

## 📂 폴더 구조 예시

```
fconline-player-search/
│
├── 피온탐색기py             # 메인 실행 파일
├── FCDataMaker.py          # 데이터 수집 스크립트
├── README.md               # 이 설명서
├── requirements.txt        # 패키지 리스트

├── data/
│   └── details.csv        # 선수 스탯 정보
├────── codes.csv          # 백업 및 복원 파일
├────── jobs.csv           # 백업 및 복원 파일
└── 
```

---

## 📜 라이선스

이 프로젝트는 MIT 라이선스를 따릅니다.  
자유롭게 수정/배포하되, 출처를 남겨주세요! 🙏

---

## 👨‍💻 개발자

- **김태영**  
- GitHub: [@contlg](https://github.com/contlg)
-  연락처
  ty2004107@naver.com

---

> ⚽ FC온라인 팬이라면 필수 도구!
