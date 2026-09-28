# GitHub 업로드와 Streamlit 공개 배포 따라 하기

이 문서는 처음 배포하는 사람을 위한 순서표다. 이미 `--source live` 결과가 폴더에 들어 있으므로, 배포 서버에서 원자료를 다시 수집하지 않는다.

## 0. 업로드 전 결과 확인

PowerShell에서 압축을 푼 프로젝트 폴더를 연 뒤 다음을 한 줄씩 실행한다.

```powershell
python -m unittest discover -s tests -v
python -c "import json; m=json.load(open('outputs/metrics.json', encoding='utf-8')); print(m['source_mode'], m['monthly_complete_observations'], m['period'])"
```

정상이면 단위검사 7개가 `ok`이고, 둘째 명령은 `live`, `140`, `2015-01-31~2026-08-31`을 보여준다.

`python analysis.py --source sample`을 다시 실행하면 실제 결과가 가상자료로 덮어써지므로 제출 직전에는 실행하지 않는다.

## 1. 비밀정보가 빠졌는지 확인

```powershell
git check-ignore .env
git ls-files .env
```

- 첫 명령에 `.env`가 나오면 무시 설정이 정상이다.
- 둘째 명령은 아무것도 출력되지 않아야 한다.
- `.env`, KRX 아이디·비밀번호, 토큰, API 키, 개인 이메일이 문서나 화면 캡처에 없는지 직접 한 번 더 확인한다.

## 2. GitHub에서 빈 저장소 만들기

1. 브라우저에서 <https://github.com/>에 로그인한다.
2. 오른쪽 위 `+`를 누르고 `New repository`를 누른다.
3. Repository name에 `hanwha-life-timeseries-analysis`를 입력한다.
4. 공개 제출용이면 `Public`을 선택한다.
5. `Add a README`, `.gitignore`, `license`는 체크하지 않는다. 이 프로젝트에 이미 파일이 있다.
6. `Create repository`를 누른다.
7. 새 화면에 표시된 본인의 주소 `https://github.com/아이디/hanwha-life-timeseries-analysis.git`를 복사한다.

## 3. 프로젝트를 GitHub에 올리기

처음 한 번만 본인 이름과 이메일을 설정한다.

```powershell
git config --global user.name "본인 이름 또는 GitHub 아이디"
git config --global user.email "GitHub에 등록한 이메일"
```

그다음 프로젝트 폴더에서 아래를 한 줄씩 실행한다. `<본인아이디>`를 실제 값으로 바꾼다.

```powershell
git init
git add .
git status
git commit -m "Complete Hanwha Life live time-series analysis"
git branch -M main
git remote add origin https://github.com/<본인아이디>/hanwha-life-timeseries-analysis.git
git push -u origin main
```

`git status`에서 `.env`가 보이면 커밋 전에 멈춘다. `data/raw/`는 라이선스와 재배포 주의를 위해 기본적으로 제외되지만, 검산 가능한 처리 CSV·JSON·그래프·출처 문서는 올라간다.

### 자주 나오는 Git 오류

- `remote origin already exists`: `git remote -v`로 주소를 확인하고, 틀렸다면 `git remote set-url origin 실제주소`를 실행한다.
- 로그인 창이 뜸: GitHub 브라우저 로그인 또는 Git Credential Manager 안내를 따른다. 비밀번호를 코드나 README에 쓰지 않는다.
- `rejected` 오류: GitHub 저장소를 정말 빈 상태로 만들었는지 확인한다. 다른 파일이 이미 있다면 무리하게 강제 푸시하지 말고 새 빈 저장소를 만드는 편이 안전하다.

## 4. GitHub 화면에서 제출물 확인

저장소 새로고침 후 다음 파일이 열리는지 확인한다.

- `analysis.py`, `dashboard.py`, `requirements.txt`, `requirements-lock.txt`
- `README.md`, `REPORT.md`, `DATA_SOURCES.md`, `VERIFICATION.md`, `FINAL_AUDIT.md`
- `data/processed/monthly_analysis.csv`, `data/processed/quarterly_auxiliary.csv`
- `outputs/source_manifest.json`, `outputs/metrics.json`, `outputs/forecast.csv`, `outputs/cross_check_points.csv`
- `outputs/figures/06_baseline_forecast.png`를 포함한 PNG 7개

GitHub 주소를 로그아웃 창에서 열어도 보여야 한다.

## 5. Streamlit Community Cloud에 배포하기

1. <https://share.streamlit.io/>를 연다.
2. GitHub 계정으로 로그인하고 저장소 접근을 허용한다.
3. `Create app` 또는 `New app`을 누른다.
4. Repository에서 `<본인아이디>/hanwha-life-timeseries-analysis`를 선택한다.
5. Branch는 `main`을 선택한다.
6. Main file path에는 `dashboard.py`를 입력한다.
7. App URL 이름을 정한다. 예: `hanwha-life-timeseries-analysis`.
8. `Deploy`를 누른다.
9. 빌드 로그에서 `Running on local URL` 또는 앱 화면이 나올 때까지 기다린다.

이 대시보드는 커밋된 처리 CSV를 읽으므로 Streamlit Secrets에 KRX 비밀번호나 API 키를 넣지 않는다.

## 6. 공개 대시보드 시험

배포 URL을 시크릿 브라우저에서 열고 다음을 확인한다.

1. 관측 월이 기본값으로 140개인지 확인한다.
2. 기간 시작일과 종료일을 바꿔 그래프가 갱신되는지 본다.
3. 비교 변수를 `보험업 시장 대용변수`, `KOSPI`, `원/달러`로 바꿔 본다.
4. 시장 조건을 금리 상승·하락, 원화 강세·약세로 바꿔 본다.
5. 예측 그래프와 CSV 다운로드 버튼이 작동하는지 확인한다.

화면에 오류가 나면 Streamlit의 `Manage app → Logs`에서 첫 번째 빨간 오류를 확인한다. 대부분 누락된 파일 또는 패키지 문제이므로 GitHub에 처리 CSV와 `requirements.txt`가 있는지 먼저 본다.

## 7. 두 URL을 문서에 기록하고 마지막으로 푸시

`README.md`의 `18. 제출 URL 기록란`과 `REPORT.md`의 `13. 제출 링크`에 실제 주소를 넣는다.

```text
GitHub 저장소 URL: https://github.com/<본인아이디>/hanwha-life-timeseries-analysis
공개 대시보드 URL: https://<본인앱이름>.streamlit.app
```

그다음 아래를 실행한다.

```powershell
git add README.md REPORT.md FINAL_AUDIT.md
git commit -m "Add public repository and dashboard URLs"
git push
```

`analysis.py`에는 현재 공개 URL이 기본값으로 들어 있어 재실행해도 `REPORT.md`의 URL이 유지된다. 저장소나 앱 주소가 바뀐 경우에는 `--github-url`과 `--dashboard-url` 옵션으로 새 주소를 넘긴다.

## 8. 제출 직전 최종 확인

- GitHub URL이 로그아웃 상태에서도 열린다.
- Streamlit URL이 시크릿 창에서 열리고 필터가 작동한다.
- GitHub에 `.env`가 없다.
- `REPORT.md`가 `실제 공개자료`, 140개 관측치라고 표시한다.
- `FINAL_AUDIT.md`의 17개 평가문항과 두 보너스 항목이 모두 `통과`인지 확인한다.
