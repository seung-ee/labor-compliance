# 5인 미만 노무 컴플라이언스

5인 미만 사업장 사장님에게 이번 달 챙겨야 할 노무 항목과 그 근거 법령 조문을 알려준다.
알바 중심 소규모 사업장(카페·술집 등)이 대상이다.

법령 데이터는 [법제처 국가법령정보 OPEN API](https://open.law.go.kr)에서 받는다.

## 빠른 시작

```bash
python3 -m venv .venv
./.venv/bin/pip install anthropic sentence-transformers

ln -sf ../../scripts/pre-commit .git/hooks/pre-commit   # 비밀값 커밋 차단 (필수)
cp .env.example .env.local     # LAW_OC(법제처), ANTHROPIC_API_KEY 채우기
./.venv/bin/python update_laws.py --init    # 법령 스냅샷 수집 (~2분)
./.venv/bin/python build_matrix.py          # 5인 미만 적용 매트릭스 생성
./.venv/bin/python build_rates.py           # 최저임금 고시 수집
```

`data/`는 저장소에 없다. 위 명령들로 재생성된다.

| 디렉터리 | 내용 | 저장소 |
|---|---|---|
| `data/` | 기계가 받아오거나 만들어낸 것 (법령 스냅샷, 매트릭스, 최저임금) | 제외 |
| `config/` | **사람이 손으로 채우는 것** (4대보험 요율, 간이세액표) | 포함 |

`config/`는 재생성이 안 된다. `data/`에 두면 클론할 때 사라진다.

생성하는 JSON은 **들여쓰기를 준다.** 사람이 열어서 읽는 파일이다.
한 줄로 쓰면 조문 하나 보려고 8천 칸짜리 줄을 가로로 스크롤해야 한다.

`data/*.npy`는 NumPy 바이너리라 에디터로 못 연다. 내용을 보려면:

```bash
./.venv/bin/python measure_embed.py --peek
```

## 스크립트

| 파일 | 하는 일 |
|---|---|
| `update_laws.py` | 법령 스냅샷 수집·갱신. 주 1회 실행하면 개정을 감지해 diff를 낸다 |
| `build_matrix.py` | 시행령 [별표 1]을 근거로 5인 미만 적용 매트릭스 생성 (항 단위) |
| `build_rates.py` | 최저임금 고시 수집 (법제처 행정규칙 → PDF 파싱 → 검산) |
| `payroll.py` | 급여 계산. 항목마다 근거 조문·적용 여부·미적용 사유를 단다 |
| `answer.py` | 답변 템플릿 + 인용 검증 게이트. 정본에 없는 조문을 인용하면 차단한다 |
| `measure.py` | 법제처 API 3경로 라우팅 성능 측정 |
| `measure_embed.py` | 자체 임베딩(BGE-M3) 라우팅 성능 측정 |
| `measure_route.py` | 조문 제목 인덱스 + LLM 라우팅 성능 측정 |

모두 `--test`로 자체검증이 돌아간다. 고치기 전에 한 번 돌려볼 것.

```bash
for f in build_matrix build_rates payroll answer update_laws measure measure_embed measure_route; do
  ./.venv/bin/python $f.py --test
done
```

## 비밀값 관리

공개 저장소다. `.gitignore`만 믿지 않는다.

- `.env.local`에만 키를 둔다. `.env*`는 `.gitignore`가 막는다 (`.env.example` 제외)
- `scripts/pre-commit`이 `git add` 한 뒤에도 막는다 — `.env` 계열 파일,
  `sk-ant-…`·`ghp_…`·AWS 키·개인키 패턴, 그리고 `.env.local`의 `LAW_OC` 값이
  커밋 내용에 섞였는지 검사한다
- **법제처 API는 응답 URL에 `OC` 키를 그대로 넣어 돌려준다.** 로그나 JSON을
  커밋할 때 새기 쉬운 경로라서 훅이 이것도 본다

클론한 뒤 위 `ln -sf` 한 줄을 꼭 실행할 것. 훅은 저장소에 따라오지 않는다.

## 설계 맥락

`CLAUDE.md`에 있다. 확정된 결정, 기각한 대안과 그 근거, 법제처 API의 함정,
규제 경계, 미해결 과제가 정리돼 있다. **코드를 고치기 전에 읽을 것.**

## 데이터를 커밋하지 않는 이유

1. **재생성된다** — `update_laws.py --init` 한 번이면 된다
2. **시점이 박혀 있다** — 스냅샷은 특정 시행일 기준이라 금방 낡는다
3. **재배포 쟁점** — 법제처 데이터를 저장소에 싣는 것은 재배포에 해당할 수 있다.
   상업 이용 문의 전까지는 싣지 않는다

## 주의

이 저장소의 코드는 법령을 **찾아서 보여주는 것**까지만 한다.
특정 사안에 대한 법률 판단이나 노무 대행을 하지 않는다. 설계 근거는 `CLAUDE.md`의
"규제 경계" 절에 있다.
