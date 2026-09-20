"""법령 스냅샷 수집·갱신 잡.

법은 바뀐다. 스냅샷은 가만히 있는다. 그 간극을 메우는 것이 이 스크립트다.

  data/laws/manifest.json        법령별 현행 MST·시행일, 시행예정 목록
  data/laws/<법령ID>/<시행일>.json  시행일별 조문 스냅샷

주 1회 돌린다. 새 시행일이 잡히면 스냅샷을 미리 받아두고 diff를 뽑아
무엇이 깨지는지(제목 인덱스 캐시, 매트릭스, 평가셋) 알려준다.

  python update_laws.py --init    최초 수집
  python update_laws.py           갱신 확인 + diff 리포트
"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure as m

HERE = os.path.dirname(os.path.abspath(__file__))
LAWS = os.path.join(HERE, 'data/laws')
MANIFEST = os.path.join(LAWS, 'manifest.json')

# 이 서비스가 다루는 법령. 이름은 법제처 표기 그대로.
TARGETS = ['근로기준법', '최저임금법', '근로자퇴직급여 보장법',
           '산업재해보상보험법', '기간제 및 단시간근로자 보호 등에 관한 법률',
           '남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률',
           # 시행령. 5인 미만 매트릭스의 근거인 [별표 1]이 근로기준법 시행령에 있다.
           # 이걸 안 보면 별표가 바뀌어도 매트릭스가 낡은 채로 남는다.
           '근로기준법 시행령']

# 답변에 쓰는 법령(조문 인용 대상). 시행령은 근거 추적용이라 코퍼스에서 뺀다.
CORPUS_LAWS = TARGETS[:6]


def article_text(a):
    """조문 본문. 항과 호는 조문내용 뒤에 이어 붙는다."""
    s = a.get('조문내용') or ''
    for h in m.listify(a.get('항')):
        s += h.get('항내용') or ''
        for ho in m.listify(h.get('호')):
            s += ho.get('호내용') or ''
    return s


def versions(name):
    """한 법령의 현행 + 시행예정 목록. eflaw는 시행예정까지 준다."""
    d = m.api(target='eflaw', query=name, display=20).get('LawSearch', {})
    out = []
    for r in m.listify(d.get('law')):
        if r.get('법령명한글') != name:
            continue
        out.append({'MST': r.get('법령일련번호'), '시행일': r.get('시행일자'),
                    '공포번호': r.get('공포번호'), '공포일자': r.get('공포일자'),
                    '상태': r.get('현행연혁코드'), '법령ID': r.get('법령ID')})
    return sorted(out, key=lambda x: x['시행일'])


def fetch(name, v):
    """그 시행일에 **실제로 시행 중인** 조문. 별표도 같이 받는다 (매트릭스가 별표 1에 달려 있다).

    ⚠ target=law 로 받으면 안 된다. 그건 '공포 전문'이라 아직 시행되지 않은 조문까지
    들어 있다. 한 공포가 조문별로 단계적으로 시행되는 경우가 흔해서
    (근로기준법 MST 285279 → 2026-10-08과 12-08에 나눠 시행) 둘은 실제로 다르다.
    시행 전 조문을 근거로 답하면 법률 서비스에서는 사고다."""
    j = m.svc(target='eflaw', MST=v['MST'], efYd=v['시행일'])
    law = j.get('법령', {})
    arts = [a for a in m.listify((law.get('조문') or {}).get('조문단위'))
            if a.get('조문여부') == '조문']
    def flat(x):
        if isinstance(x, str): yield x
        elif isinstance(x, list):
            for i in x: yield from flat(i)
    byl = {b.get('별표번호'): {'제목': b.get('별표제목'),
                              '내용': '\n'.join(s.rstrip() for s in flat(b.get('별표내용') or []))}
           for b in m.listify((law.get('별표') or {}).get('별표단위'))}
    return {**v, '법령명': name,
            '조문': {f"{int(a['조문번호'])}-{int(a.get('조문가지번호') or 0)}": article_text(a)
                     for a in arts},
            '별표': byl}


def snap_path(law_id, ef, mst):
    """같은 시행일에 서로 다른 공포가 둘 이상 걸리는 경우가 실제로 있다.
    (근로기준법 2027-01-01) 시행일만으로 파일명을 지으면 한쪽이 조용히 덮어써진다."""
    return os.path.join(LAWS, law_id, f'{ef}-{mst}.json')


def save(snap):
    os.makedirs(os.path.join(LAWS, snap['법령ID']), exist_ok=True)
    with open(snap_path(snap['법령ID'], snap['시행일'], snap['MST']), 'w') as f:
        json.dump(snap, f, ensure_ascii=False)


def diff(old, new):
    """두 스냅샷 사이의 조문 변화. 무엇이 깨지는지 판단하는 재료다."""
    a, b = old['조문'], new['조문']
    changed = [k for k in set(a) & set(b) if a[k] != b[k]]
    return {'신설': sorted(set(b) - set(a)), '삭제': sorted(set(a) - set(b)),
            '변경': sorted(changed),
            '별표변경': sorted(k for k in set(old.get('별표', {})) & set(new.get('별표', {}))
                               if old['별표'][k] != new['별표'][k])}


def impact(d):
    """diff가 무엇을 깨뜨리는지. 사람이 읽고 대응할 목록."""
    out = []
    if d['신설'] or d['삭제']:
        out.append('제목 인덱스 변경 → **프롬프트 캐시 프리픽스 무효화**. 갱신 직후 비용이 튄다')
    if d['변경']:
        out.append('조문 본문 변경 → 인용 검증 게이트의 정본 대조 기준이 바뀐다')
    if d['별표변경']:
        out.append('**별표 변경 → 5인 미만 매트릭스 재생성 필요** (build_matrix.py)')
    if d['신설'] or d['삭제'] or d['변경']:
        out.append('평가셋 정답 라벨과 phrase_map이 여전히 유효한지 확인')
    return out


def rebuild_views():
    """현행 스냅샷들을 합쳐 corpus.json과 title-index.txt를 다시 만든다.
    기존 측정 스크립트들이 이 둘을 읽으므로 항상 현행과 일치시킨다."""
    import re
    man = json.load(open(MANIFEST))
    corpus, idx = {}, []
    for lid, info in man['법령'].items():
        if info['법령명'] not in CORPUS_LAWS:
            continue
        snap = json.load(open(snap_path(lid, info['현행']['시행일'], info['현행']['MST'])))
        corpus[info['법령명']] = snap['조문']
        idx.append(f"## {info['법령명']}")
        for k, txt in sorted(snap['조문'].items(), key=lambda kv: tuple(int(x) for x in kv[0].split('-'))):
            jo, ji = k.split('-')
            t = re.match(r'제\d+조(?:의\d+)?\(([^)]*)\)', txt)
            idx.append(f"제{jo}조" + (f"의{ji}" if ji != '0' else '') + (f" {t.group(1)}" if t else ''))
        idx.append('')
    json.dump(corpus, open(os.path.join(HERE, 'data/corpus.json'), 'w'), ensure_ascii=False)
    open(os.path.join(HERE, 'data/title-index.txt'), 'w').write('\n'.join(idx))
    n = sum(len(v) for v in corpus.values())
    print(f'  corpus.json / title-index.txt 재생성 — 법령 {len(corpus)}개, 조문 {n}개')


def run(init=False):
    os.makedirs(LAWS, exist_ok=True)
    man = json.load(open(MANIFEST)) if os.path.exists(MANIFEST) else {'법령': {}}
    alerts = []
    for name in TARGETS:
        vs = versions(name)
        if not vs:
            print(f'  {name}: 조회 실패'); continue
        lid = vs[0]['법령ID']
        cur = [v for v in vs if v['상태'] != '시행예정'][-1]
        future = [v for v in vs if v['상태'] == '시행예정']
        prev = man['법령'].get(lid, {})
        fresh = prev.get('현행', {}).get('MST') != cur['MST']

        for v in [cur] + future:
            if init or not os.path.exists(snap_path(lid, v['시행일'], v['MST'])):
                save(fetch(name, v)); time.sleep(0.3)

        # 시행예정이 새로 잡혔거나 현행이 바뀌었으면 diff를 낸다
        if future:
            old = json.load(open(snap_path(lid, cur['시행일'], cur['MST'])))
            for v in future:
                new = json.load(open(snap_path(lid, v['시행일'], v['MST'])))
                d = diff(old, new)
                if any(d.values()):
                    alerts.append((name, cur['시행일'], v['시행일'], d))
        dup = {v['시행일'] for v in future if sum(1 for x in future if x['시행일'] == v['시행일']) > 1}
        if dup:
            print(f"     ※ 같은 시행일에 공포 둘 이상: {sorted(dup)} — 어느 쪽이 정본인지 확인 필요")
        man['법령'][lid] = {'법령명': name, '현행': cur, '시행예정': future}
        flag = ' ← 현행 변경' if fresh and not init else ''
        print(f"  {name:<34} 현행 {cur['시행일']} (MST {cur['MST']})"
              f"{', 시행예정 ' + ', '.join(v['시행일'] for v in future) if future else ''}{flag}")

    man['갱신시각'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    json.dump(man, open(MANIFEST, 'w'), ensure_ascii=False, indent=1)
    rebuild_views()

    if alerts:
        print('\n' + '=' * 72)
        for name, a, b, d in alerts:
            print(f'\n■ {name}  {a} → {b}')
            for kind in ('신설', '삭제', '변경', '별표변경'):
                if d[kind]:
                    v = d[kind]
                    print(f'   {kind}: {len(v)}건  {v[:8]}{" …" if len(v) > 8 else ""}')
            for line in impact(d):
                print(f'   ⚠ {line}')
    else:
        print('\n변경 없음.')


def test():
    assert article_text({'조문내용': '제1조(목적)', '항': [{'항내용': '① 가', '호': [{'호내용': '1. 나'}]}]}) \
        == '제1조(목적)① 가1. 나'
    assert snap_path('001872', '20270101', '286771').endswith('20270101-286771.json'), \
        '같은 시행일 두 공포가 덮어쓰지 않아야 한다'
    old = {'조문': {'1-0': 'a', '2-0': 'b'}, '별표': {'0001': 'x'}}
    new = {'조문': {'1-0': 'a', '2-0': 'B', '3-0': 'c'}, '별표': {'0001': 'y'}}
    d = diff(old, new)
    assert d == {'신설': ['3-0'], '삭제': [], '변경': ['2-0'], '별표변경': ['0001']}, d
    imp = impact(d)
    assert any('캐시' in x for x in imp) and any('매트릭스' in x for x in imp)
    assert impact({'신설': [], '삭제': [], '변경': [], '별표변경': []}) == []
    print('ok: 조문 추출 / diff / 영향 판정 정상')


if __name__ == '__main__':
    if '--test' in sys.argv: test()
    else: run(init='--init' in sys.argv)
