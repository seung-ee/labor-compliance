"""요율 데이터 수집.

최저임금은 법제처 행정규칙(고시)에서 자동으로 받는다.
4대보험 요율과 근로소득 간이세액표는 공단·국세청 소관이라 법제처에 없다. 수동이다.
수동 입력물은 재생성이 불가능하므로 config/ 에 두고 저장소에 남긴다.
data/ 는 gitignore 대상이라 거기 두면 클론할 때 사라진다.

  python build_rates.py          최저임금 수집 → data/rates/minimum-wage.json
  python build_rates.py --test   자체검증
"""
import io, json, os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure as m

HERE = os.path.dirname(os.path.abspath(__file__))
# 자동 수집물은 data/ (gitignore 대상, 재생성 가능).
# 사람이 손으로 채우는 값은 config/ (저장소에 남긴다 — 재생성이 안 되므로 잃으면 끝이다).
RATES = os.path.join(HERE, 'data/rates')
CONFIG = os.path.join(HERE, 'config/rates')
HDRS = {'Referer': 'https://www.law.go.kr/',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/130.0'}


def despace(txt):
    """PDF 추출이 숫자 사이에 공백을 끼워 넣는다. '1 0 ,7 0 0원' → '10,700원'."""
    return re.sub(r'(?<=[\d,])\s+(?=[\d,])', '', txt)


def parse_notice(txt):
    """고시 본문에서 시간급·월환산액·적용기간을 뽑는다."""
    t = despace(txt)
    wage = re.search(r'모\s*든\s*산\s*업\s*([\d,]+)\s*원', t)
    monthly = re.search(r'월\s*환산액\s*([\d,]+)\s*원', t)
    hours = re.search(r'월\s*환산\s*기준시간\s*수?\s*(\d+)\s*시간', t)
    period = re.search(r'적용\s*기간\s*:?\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.'
                       r'\s*~\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.', t)
    if not (wage and monthly and hours and period):
        raise ValueError(f'고시 파싱 실패 — 시간급{bool(wage)} 월액{bool(monthly)} '
                         f'기준시간{bool(hours)} 기간{bool(period)}')
    hourly = int(wage.group(1).replace(',', ''))
    mon = int(monthly.group(1).replace(',', ''))
    h = int(hours.group(1))
    # 자체 검산. 파싱이 어긋나면 여기서 걸린다.
    if hourly * h != mon:
        raise ValueError(f'검산 실패: {hourly} × {h} = {hourly*h} ≠ {mon}')
    g = period.groups()
    return {'시간급': hourly, '월환산액': mon, '월환산기준시간': h,
            '적용기간': [f'{g[0]}-{int(g[1]):02d}-{int(g[2]):02d}',
                         f'{g[3]}-{int(g[4]):02d}-{int(g[5]):02d}']}


def pdf_text(url):
    from pypdf import PdfReader
    req = urllib.request.Request(url.replace('http://', 'https://'), headers=HDRS)
    raw = urllib.request.urlopen(req, timeout=30).read()
    return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)


def minimum_wage():
    """'○○년 적용 최저임금 고시'를 전부 받는다.
    ⚠ '최저임금안 고시'(심의 단계의 안)는 제외한다. 확정 고시가 아니다."""
    d = m.api(target='admrul', query='적용 최저임금 고시', display=30).get('AdmRulSearch', {})
    out = {}
    for r in m.listify(d.get('admrul')):
        name = r.get('행정규칙명', '')
        if '최저임금안' in name or not re.match(r'\d{4}년 적용 최저임금 고시$', name):
            continue
        svc = m.svc(target='admrul', ID=r['행정규칙일련번호'])['AdmRulService']
        info, att = svc['행정규칙기본정보'], svc.get('첨부파일') or {}
        pairs = list(zip(m.listify(att.get('첨부파일링크')), m.listify(att.get('첨부파일명'))))
        main = next((u for u, fn in pairs if '이유서' not in fn), None)
        if not main:
            print(f'  {name}: 본문 첨부 없음 — 건너뜀'); continue
        try:
            rec = parse_notice(pdf_text(main))
        except Exception as e:
            print(f'  {name}: {e}'); continue
        year = name[:4]
        rec['근거'] = {'고시': f"고용노동부 고시 제{info['발령번호']}호",
                       '발령일': info['발령일자'], '시행일': info['시행일자'],
                       '행정규칙일련번호': info['행정규칙일련번호'],
                       '첨부': main.replace('http://', 'https://')}
        out[year] = rec
        print(f"  {year}년  시간급 {rec['시간급']:,}원  월환산 {rec['월환산액']:,}원"
              f"  ({rec['근거']['고시']})")
        time.sleep(0.3)
    return out


MANUAL_TEMPLATE = {
    '_주의': '법제처 API에 없다. 공단·국세청 고시를 사람이 확인해 채운다. 매년 바뀐다.',
    '_확인방법': {
        '4대보험': 'https://www.4insure.or.kr 또는 각 공단 고시',
        '근로소득 간이세액': 'https://www.nts.go.kr 근로소득 간이세액표',
    },
    '_상태': '미기입',
    '갱신일': None,
    '연도': {},
}


def main():
    os.makedirs(RATES, exist_ok=True)
    print('최저임금 (법제처 행정규칙 — 자동)')
    mw = minimum_wage()
    json.dump({'갱신시각': time.strftime('%Y-%m-%dT%H:%M:%S'),
               '출처': '법제처 국가법령정보 OPEN API — target=admrul',
               '연도': dict(sorted(mw.items()))},
              open(os.path.join(RATES, 'minimum-wage.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'  → data/rates/minimum-wage.json ({len(mw)}개 연도)\n')

    os.makedirs(CONFIG, exist_ok=True)
    for fn, label in [('insurance.json', '4대보험 요율'), ('withholding.json', '근로소득 간이세액')]:
        p = os.path.join(CONFIG, fn)
        if os.path.exists(p):
            print(f'{label}: 이미 있음 — 건드리지 않음'); continue
        json.dump({**MANUAL_TEMPLATE, '_항목': label}, open(p, 'w'), ensure_ascii=False, indent=1)
        print(f'{label}: 빈 템플릿 생성 → config/rates/{fn}  ⚠ 사람이 채워야 한다')


def test():
    assert 'config' in CONFIG and 'data' in RATES, '수동 입력물과 자동 수집물의 자리가 달라야 한다'
    assert despace('1 0 ,7 0 0원') == '10,700원'
    assert despace('209시간') == '209시간'
    sample = """1. 최저임금액
결정단위
업 종 시 간 급
모 든 산 업 1 0 ,7 0 0원
 ◈ 월 환산액 2,236,300 원: 주 소정근로 40시간을 근무할 경우,
월 환산 기준시간 수 209시간(주당 유급주휴 8시간 포함) 기준
3. 최저임금 적용 기간 : 2027. 1. 1. ~ 2027. 12. 31."""
    r = parse_notice(sample)
    assert r['시간급'] == 10700 and r['월환산액'] == 2236300 and r['월환산기준시간'] == 209, r
    assert r['적용기간'] == ['2027-01-01', '2027-12-31'], r['적용기간']

    # 검산이 실제로 작동하는지 — 시간급을 틀리게 바꾸면 걸려야 한다
    bad = sample.replace('1 0 ,7 0 0원', '9 ,9 0 0원')
    try:
        parse_notice(bad); raise AssertionError('검산이 오류를 놓쳤다')
    except ValueError as e:
        assert '검산 실패' in str(e), e
    print('ok: 고시 파싱 + 검산 정상')


if __name__ == '__main__':
    test() if '--test' in sys.argv else main()
