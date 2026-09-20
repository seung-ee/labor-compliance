"""용어 격차 측정. docs/measurement-queries.md의 질의를 법제처 3경로에 돌려 hit rate를 낸다.
ponytail: 일회성 측정 스크립트. 결과로 임베딩 여부만 결정하면 버린다."""
import json, os, re, sys, time, urllib.parse, urllib.request

OC = next((l.split('=', 1)[1].strip() for l in open(
    os.path.join(os.path.dirname(__file__), '.env.local')) if l.startswith('LAW_OC=')), '')
HDRS = {'Referer': 'https://www.law.go.kr/',  # 필수. 없으면 "사용자 정보 검증 실패"
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/130.0 Safari/537.36'}
N = 20


def api(_ep='lawSearch.do', **params):
    url = f'https://www.law.go.kr/DRF/{_ep}?' + urllib.parse.urlencode(
        {'OC': OC, 'type': 'JSON', **params})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=20) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'_err': str(e)}


def listify(v):
    return v if isinstance(v, list) else [v] if v else []


def norm(s):
    return re.sub(r'\s+', '', s or '')


def parse_queries(path):
    """마크다운 표에서 (번호, 질의, 법령명, 조번호, 가지번호)를 뽑는다. 질의를 두 곳에 쓰지 않으려고."""
    out = []
    for line in open(path):
        c = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(c) < 3 or not c[0].isdigit():
            continue
        m = re.match(r'(.+?)\s*제(\d+)조(?:의(\d+))?$', c[2])
        if not m:
            out.append((int(c[0]), c[1], None, None, None))  # 조문 특정 안 되는 질의(#25)
            continue
        out.append((int(c[0]), c[1], m.group(1), int(m.group(2)), int(m.group(3) or 0)))
    return out


def rank_ai(q, law, jo, ji):
    """aiSearch: 조문 단위 반환. (법령명, 조문번호, 가지번호) 일치 순위."""
    d = api(target='aiSearch', query=q, display=N).get('aiSearch', {})
    for i, r in enumerate(listify(d.get('법령조문')), 1):
        if (norm(r.get('법령명')) == norm(law) and int(r.get('조문번호', -1)) == jo
                and int(r.get('조문가지번호') or 0) == ji):
            return i
    return 0


def rank_law_body(q, law, jo, ji):
    """target=law&search=2: 본문 검색. 법령 단위라 조문은 못 짚는다 → 법령명만 채점."""
    d = api(target='law', search=2, query=q, display=N).get('LawSearch', {})
    for i, r in enumerate(listify(d.get('law')), 1):
        if norm(r.get('법령명한글')) == norm(law):
            return i
    return 0


def svc(**params):
    """lawService.do. 연계 조회는 lawSearch.do가 아니라 여기 있고, query 대신 MST를 받는다."""
    return api(_ep='lawService.do', **params)


_dly_cache = {}


def dlytrm(token):
    """일상용어 사전 조회. 토큰당 1회만 때린다."""
    if token not in _dly_cache:
        d = api(target='dlytrm', query=token, display=5).get('dlytrmSearch', {})
        _dly_cache[token] = [(t.get('일상용어명'), re.search(r'MST=(\d+)', t.get('용어간관계링크', '') or ''))
                             for t in listify(d.get('일상용어'))]
        time.sleep(0.25)
    return [(n, m.group(1)) for n, m in _dly_cache[token] if m]


JOSA = re.compile(r'(은|는|이|가|을|를|에|의|도|만|와|과|으로|로|한테|에게|부터|까지|라도|이나|나)$')


def tokens(q):
    """구어체 문장에서 사전에 두드려 볼 후보 명사. 사전은 문장 전체를 못 받는다.
    ponytail: 조사 뭉치 제거로 끝낸다. 형태소 분석기는 히트율이 여기서 막힐 때 넣는다."""
    out = []
    for w in re.findall(r'[가-힣]{2,}', q):
        for cand in (w, JOSA.sub('', w)):
            if len(cand) >= 2 and cand not in out:
                out.append(cand)
    return out


def rank_dly_chain(q, law, jo, ji):
    """일상용어 → 법령용어 → 조문 3단 연계. 사전에 있으면 조문 원문까지 정확히 짚는다.
    순위 개념이 없어 hit이면 1, 아니면 0."""
    for tok in tokens(q):
        for name, mst in dlytrm(tok):
            r = svc(target='dlytrmRlt', MST=mst)
            for rel in listify((r.get('dlytrmRltService', {}).get('일상용어') or {}).get('연계용어')):
                m = re.search(r'MST=(\d+)', rel.get('조문간관계링크', '') or '')
                if not m:
                    continue
                j = svc(target='lstrmRltJo', MST=m.group(1))
                for art in listify((j.get('lstrmRltJoService', {}).get('법령용어') or {}).get('연계법령')):
                    if (norm(art.get('법령명')) == norm(law) and int(art.get('조번호', -1)) == jo
                            and int(art.get('조가지번호') or 0) == ji):
                        return 1
                time.sleep(0.2)
    return 0


PATHS = [('A law&search=2 (법령단위)', rank_law_body),
         ('B aiSearch (조문단위)', rank_ai),
         ('C dlytrm 3단연계 (조문단위)', rank_dly_chain)]


def main():
    qs = parse_queries(os.path.join(os.path.dirname(__file__), 'docs/measurement-queries.md'))
    scorable = [q for q in qs if q[2]]
    print(f'질의 {len(qs)}건 (채점가능 {len(scorable)}건), top-{N}\n')
    ranks = {name: {} for name, _ in PATHS}
    for num, q, law, jo, ji in scorable:
        print(f'{num:2d} {q[:34]:<36}', end='', flush=True)
        for name, fn in PATHS:
            r = fn(q, law, jo, ji)
            ranks[name][num] = r
            print(f'  {name[0]}:{r or "-":>3}', end='', flush=True)
            time.sleep(0.3)  # 남의 API다
        print(f'   ← {law} 제{jo}조' + (f'의{ji}' if ji else ''))
    print()
    for name, _ in PATHS:
        rs = [r for r in ranks[name].values() if r]
        n = len(scorable)
        print(f'{name:<26} hit@1 {sum(r == 1 for r in rs)/n:5.0%}  '
              f'hit@5 {sum(r <= 5 for r in rs)/n:5.0%}  hit@{N} {len(rs)/n:5.0%}')
    miss = [num for num in ranks[PATHS[1][0]]
            if not any(ranks[nm][num] for nm, _ in PATHS)]
    print(f'\n전 경로 실패 {len(miss)}건: {miss}  ← phrase_map 시드 / 임베딩 평가셋')
    json.dump(ranks, open(os.path.join(os.path.dirname(__file__), 'docs/measurement-result.json'),
                          'w'), ensure_ascii=False, indent=1)


def test():
    assert parse_queries.__doc__
    qs = parse_queries(os.path.join(os.path.dirname(__file__), 'docs/measurement-queries.md'))
    assert len(qs) == 25, len(qs)
    assert qs[0][1:] == ('직원 4명인데 연차 줘야 하나요', '근로기준법', 60, 0), qs[0]
    assert (22, '직장 내 괴롭힘 신고당했는데 어떻게 해야 하나요', '근로기준법', 76, 3) in qs
    assert qs[24][2] is None, '#25는 조문 특정 불가 → 채점 제외'
    assert norm(' 근로자퇴직급여 보장법 ') == '근로자퇴직급여보장법'
    print('ok: 표 파싱 25건, 가지번호/채점제외 처리 정상')


if __name__ == '__main__':
    test() if '--test' in sys.argv else main()
