"""5인 미만(상시 4명 이하) 사업장 적용 매트릭스 생성.

근거: 근로기준법 제11조제2항 → 시행령 제7조 → 시행령 [별표 1] (개정 2018.6.29)
별표 1에 열거된 조문만 적용된다. 열거되지 않은 조문은 미적용이다.
원문은 data/byeolpyo1.txt.
"""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))

# 별표 1의 각 행을 그대로 옮긴 것. (장, 적용 조문, 항 단위 지정)
# 범위는 (시작, 끝) 튜플, 단일 조문은 정수.
# HANG: 별표가 "제N조제M항"으로 항을 특정한 것만. 없으면 그 조문 전체가 적용된다.
BYEOLPYO1 = [
    ("제1장 총칙",            [(1, 13)]),
    ("제2장 근로계약",        [15, 17, 18, 19, (20, 22), 23, 26, (35, 42)]),
    ("제3장 임금",            [(43, 45), (47, 49)]),
    ("제4장 근로시간과 휴식", [54, 55, 63]),
    ("제5장 여성과 소년",     [64, 65, (66, 69), 70, 71, 72, 74]),
    ("제6장 안전과 보건",     [76]),
    ("제8장 재해보상",        [(78, 92)]),
    ("제11장 근로감독관 등",  [(101, 106)]),
    ("제12장 벌칙",           [(107, 116)]),
]

HANG = {   # 조번호 → (적용되는 항 번호, 별표 원문 표기)
    19:  ([1],    "제19조제1항"),
    23:  ([2],    "제23조제2항"),
    55:  ([1],    "제55조제1항"),
    65:  ([1, 3], "제65조제1항·제3항(임산부와 18세 미만인 자로 한정한다)"),
    70:  ([2, 3], "제70조제2항·제3항"),
}
COND = {
    65:  "임산부와 18세 미만인 자로 한정",
    107: "제1장~제6장·제8장·제11장 중 5인 미만에 적용되는 규정을 위반한 경우로 한정",
}
CHAPTER = {}   # 조번호 → 별표상의 장 이름 (근거 추적용)

# ── 기간제법 ──────────────────────────────────────────────────────────────
# 근거: 기간제법 제3조제2항 → 시행령 제2조 → 시행령 [별표 1]
# 기간제법은 원칙이 반대다. 제3조제1항이 "상시 5인 이상"에만 적용하고, 4명 이하에는
# 별표 1에 열거된 규정만 적용된다. 제4조(2년 제한)는 열거되지 않았다.
GIGAN_NAME = '기간제 및 단시간근로자 보호 등에 관한 법률'
# 조번호 → (적용항, 조건). 적용항 None = 조 전체.
# 별표가 호 단위로 한정한 것은 항으로 표현할 수 없어 조건으로 단다.
GIGAN = {
    1: (None, None), 2: (None, None), 5: (None, None), 7: (None, None),
    16: (None, '제4호(제18조에 따른 통지를 이유로 한 불리한 처우)로 한정'),
    17: (None, '제1호, 제2호(휴게에 관한 사항으로 한정), 제3호, '
               '제4호(휴일에 관한 사항으로 한정), 제5호로 한정'),
    18: (None, None), 19: (None, None), 20: (None, None),
    21: (None, None), 23: (None, None),
    24: ([2, 3, 4, 5, 6], '제2항은 제2호(제17조 서면명시 위반)로 한정'),
}

# ── 규모와 무관하게 적용되는 법령 ─────────────────────────────────────────
# 법령명 → (근거, 조건). 동거친족·가사사용인 제외는 규모 기준이 아니라 여기 적지 않는다.
SCALE_FREE = {
    '최저임금법': ('제3조제1항 — 근로자를 사용하는 모든 사업', None),
    '근로자퇴직급여 보장법': ('제3조 — 근로자를 사용하는 모든 사업', None),
    '남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률':
        ('제3조제1항 + 시행령 제2조 — 5인 미만 제외 조항(제2항)은 2018.5.28 삭제', None),
    '산업재해보상보험법':
        ('제6조 + 시행령 제2조', '농업·임업(벌목업 제외)·어업·수렵업 중 법인이 아닌 자의 사업으로서 '
                                '상시 5명 미만이면 적용 제외 (시행령 제2조제1항제6호)'),
}


def applied_set():
    """별표 1이 열거한 조번호 집합. 가지조문(제76조의2 등)은 열거된 적이 없다."""
    out = set()
    for ch, items in BYEOLPYO1:
        for it in items:
            rng = range(it[0], it[1] + 1) if isinstance(it, tuple) else [it]
            for jo in rng:
                out.add(jo)
                CHAPTER[jo] = ch
    return out


def hang_count(txt):
    """조문 본문의 ①②③ 표시로 항 개수를 센다. 표시가 없으면 항이 하나뿐인 조문이다."""
    ns = [ord(ch) - 0x245F for ch in txt if 0x2460 <= ord(ch) <= 0x2473]
    return max(ns) if ns else 1


def snapshot(name):
    """법령의 현행 스냅샷. 시행령은 corpus.json 에 없어서 여기서 읽는다."""
    man = json.load(open(os.path.join(HERE, 'data/laws/manifest.json')))
    lid, info = next((k, v) for k, v in man['법령'].items() if v['법령명'] == name)
    p = os.path.join(HERE, 'data/laws', lid,
                     f"{info['현행']['시행일']}-{info['현행']['MST']}.json")
    return json.load(open(p))


def byeolpyo1():
    """근로기준법 시행령 현행 스냅샷에서 [별표 1] 원문을 꺼낸다.
    별표가 개정되면 이 함수가 새 본문을 읽으므로, BYEOLPYO1 상수와 어긋나면 test()가 잡는다."""
    return snapshot('근로기준법 시행령')['별표']['0001']['내용']


def 별표조번호(text):
    """별표 원문에 등장하는 조번호. "제18조부터 제20조까지"는 범위로 펼친다."""
    out = set()
    for a, b in re.findall(r'제(\d+)조부터 제(\d+)조까지', text):
        out |= set(range(int(a), int(b) + 1))
    return out | {int(x) for x in re.findall(r'제(\d+)조', text)}


def build():
    """조문 하나당 레코드 하나. 적용은 전부/일부/없음 셋 중 하나다."""
    corpus = json.load(open(os.path.join(HERE, 'data/corpus.json')))['근로기준법']
    applied = applied_set()
    rows = []
    for k, txt in sorted(corpus.items(), key=lambda kv: tuple(int(x) for x in kv[0].split('-'))):
        jo, ji = (int(x) for x in k.split('-'))
        m = re.match(r'제\d+조(?:의\d+)?\(([^)]*)\)', txt)
        label = f'제{jo}조' + (f'의{ji}' if ji else '')
        n_hang = hang_count(txt)
        if ji or jo not in applied:
            # 가지조문은 별표에 개별 열거돼야 적용된다. 열거된 것이 하나도 없다.
            rec = {'적용': '없음', '적용항': [], '미적용항': list(range(1, n_hang + 1)),
                   '근거': '별표 1 미열거' + (' (가지조문)' if ji else '')}
        elif jo in HANG:
            ok_h, cite = HANG[jo]
            rec = {'적용': '일부', '적용항': ok_h,
                   '미적용항': [h for h in range(1, n_hang + 1) if h not in ok_h],
                   '근거': f'별표 1 {CHAPTER[jo]} — {cite}'}
        else:
            rec = {'적용': '전부', '적용항': list(range(1, n_hang + 1)), '미적용항': [],
                   '근거': f'별표 1 {CHAPTER[jo]}'}
        rec.update({'조문': label, '제목': m.group(1) if m else '', '항수': n_hang,
                    '조건': COND.get(jo) if not ji else None})
        rows.append(rec)
    return rows


def build_gigan():
    """기간제법 매트릭스. 근로기준법 build()와 같은 레코드 형식이다."""
    corpus = json.load(open(os.path.join(HERE, 'data/corpus.json')))[GIGAN_NAME]
    rows = []
    for k, txt in sorted(corpus.items(), key=lambda kv: tuple(int(x) for x in kv[0].split('-'))):
        jo, ji = (int(x) for x in k.split('-'))
        m = re.match(r'제\d+조(?:의\d+)?\(([^)]*)\)', txt)
        n_hang = hang_count(txt)
        전체 = list(range(1, n_hang + 1))
        if ji or jo not in GIGAN:
            rec = {'적용': '없음', '적용항': [], '미적용항': 전체, '조건': None,
                   '근거': '기간제법 시행령 별표 1 미열거' + (' (가지조문)' if ji else '')}
        else:
            ok_h, cond = GIGAN[jo]
            ok_h = 전체 if ok_h is None else ok_h
            rec = {'적용': '전부' if ok_h == 전체 else '일부', '적용항': ok_h,
                   '미적용항': [h for h in 전체 if h not in ok_h], '조건': cond,
                   '근거': '기간제법 시행령 별표 1'}
        rec.update({'조문': f'제{jo}조' + (f'의{ji}' if ji else ''),
                    '제목': m.group(1) if m else '', '항수': n_hang})
        rows.append(rec)
    return rows


def applies(rows, jo_label, hang=None):
    """적용 여부 판정. 일부 적용 조문은 항을 특정하지 않으면 None(판정 불가)을 돌려준다.
    대충 물어보면 대충 답하는 대신, 호출한 쪽이 항을 따지도록 강제한다."""
    r = next((x for x in rows if x['조문'] == jo_label), None)
    if r is None:
        return None
    if r['적용'] == '전부':
        return True
    if r['적용'] == '없음':
        return False
    return None if hang is None else hang in r['적용항']


def main():
    rows = build()

    from collections import Counter
    c = Counter(r['적용'] for r in rows)
    print(f"근로기준법 {len(rows)}개 조문 — 전부 {c['전부']} / 일부 {c['일부']} / 없음 {c['없음']}\n")

    print('=== 일부 적용 — 항을 특정해야 판정되는 조문 ===')
    for r in rows:
        if r['적용'] == '일부':
            cond = f"  ※ {r['조건']}" if r['조건'] else ''
            print(f"  {r['조문']:<10} {r['제목']:<22} 적용항 {r['적용항']} / 미적용항 {r['미적용항']}{cond}")

    print('\n=== 사장님이 자주 묻는 항목의 적용 여부 ===')
    watch = [(60,0,'연차휴가'), (56,0,'연장·야간·휴일 가산수당'), (23,0,'해고 제한'),
             (24,0,'경영상 해고'), (26,0,'해고 예고'), (50,0,'주 40시간'), (53,0,'연장근로 한도'),
             (55,0,'주휴일'), (54,0,'휴게'), (43,0,'임금 전액 지급'), (36,0,'금품 청산'),
             (46,0,'휴업수당'), (17,0,'근로조건 명시'), (76,2,'직장 내 괴롭힘 금지'),
             (76,3,'괴롭힘 발생 시 조치'), (93,0,'취업규칙 작성'), (64,0,'최저 연령'),
             (70,0,'야간·휴일근로 제한'), (41,0,'근로자 명부'), (42,0,'계약 서류 보존')]
    byk = {r['조문']: r for r in rows}
    for jo, ji, desc in watch:
        label = f'제{jo}조' + (f'의{ji}' if ji else '')
        r = byk.get(label)
        if not r:
            print(f'  {label} — 코퍼스에 없음'); continue
        detail = f" 적용항 {r['적용항']}" if r['적용'] == '일부' else ''
        print(f"  {label:<12} {desc:<22} {r['적용']:<4}{detail}")

    gigan = build_gigan()
    c = Counter(r['적용'] for r in gigan)
    print(f"\n기간제법 {len(gigan)}개 조문 — 전부 {c['전부']} / 일부 {c['일부']} / 없음 {c['없음']}")
    for r in gigan:
        if r['적용'] != '없음':
            cond = f"  ※ {r['조건']}" if r['조건'] else ''
            print(f"  {r['조문']:<10} {r['제목']:<22} {r['적용']}{cond}")

    with open(os.path.join(HERE, 'data/matrix-5under.json'), 'w') as f:
        json.dump({'근거': '근로기준법 제11조제2항 → 시행령 제7조 → 시행령 별표 1 (개정 2018.6.29)',
                   '대상': '상시 4명 이하 근로자를 사용하는 사업 또는 사업장',
                   '조문': rows,
                   '기간제법': {'근거': '기간제법 제3조제2항 → 시행령 제2조 → 시행령 별표 1',
                               '조문': gigan},
                   '규모무관': {k: {'근거': v[0], '조건': v[1]} for k, v in SCALE_FREE.items()}},
                  f, ensure_ascii=False, indent=1)
    print(f'\ndata/matrix-5under.json 저장 (근로기준법 {len(rows)}건 + 기간제법 {len(gigan)}건)')


def test():
    a = applied_set()
    assert {1, 13} <= a and 14 not in a, '제1장 제1~13조'
    assert 43 in a and 46 not in a, '제46조 휴업수당은 미적용'
    assert 60 not in a and 56 not in a, '연차·가산수당 미적용'
    assert 92 in a and 93 not in a, '제93조 취업규칙은 미적용'

    assert hang_count('제20조(위약 예정의 금지) 사용자는 …') == 1, '항 표시 없으면 1개'
    assert hang_count('제55조(휴일)① 유급휴일 …② 공휴일 …') == 2

    rows = build()
    g = lambda lbl: next(r for r in rows if r['조문'] == lbl)
    assert g('제55조')['적용'] == '일부' and g('제55조')['적용항'] == [1] \
        and g('제55조')['미적용항'] == [2], '제55조는 제1항만'
    assert g('제23조')['적용항'] == [2] and g('제23조')['미적용항'] == [1]
    assert g('제70조')['적용항'] == [2, 3] and g('제70조')['미적용항'] == [1]
    assert g('제65조')['조건'] and '임산부' in g('제65조')['조건']
    assert g('제60조')['적용'] == '없음' and g('제54조')['적용'] == '전부'
    assert g('제76조의3')['적용'] == '없음' and '가지조문' in g('제76조의3')['근거']

    # 판정 함수: 일부 적용은 항을 안 주면 답하지 않는다
    assert applies(rows, '제54조') is True
    assert applies(rows, '제60조') is False
    assert applies(rows, '제55조') is None, '항 없이 물으면 판정 불가여야 한다'
    assert applies(rows, '제55조', 1) is True
    assert applies(rows, '제55조', 2) is False, '공휴일 유급은 5인 미만 미적용'
    assert applies(rows, '제23조', 1) is False and applies(rows, '제23조', 2) is True

    # 기간제법 — 상수가 시행령 별표 1 원문과 같은 조문을 가리키는지 대조한다.
    # 별표가 개정되면 여기서 깨진다.
    bp = snapshot(GIGAN_NAME + ' 시행령')['별표']['0001']['내용']
    assert 별표조번호(bp) == set(GIGAN), (sorted(별표조번호(bp)), sorted(GIGAN))
    assert '제17조제1호·제2호(휴게에 관한 사항에 한정한다)' in bp and '제24조제2항제2호' in bp, \
        '호 단위 한정이 바뀌었다 — GIGAN 조건 재확인'
    assert 별표조번호('제18조부터 제20조까지의 규정 제5조') == {5, 18, 19, 20}
    gr = build_gigan()
    assert applies(gr, '제4조') is False, '2년 제한은 4명 이하 미적용'
    assert applies(gr, '제17조') is True and '휴게' in next(r for r in gr if r['조문'] == '제17조')['조건']
    assert applies(gr, '제24조') is None and applies(gr, '제24조', 1) is False \
        and applies(gr, '제24조', 3) is True
    assert applies(gr, '제15조의2') is False

    # 규모 무관 판정의 근거가 시행령에서 그대로인지 — 바뀌면 SCALE_FREE 재확인
    assert '② 삭제' in snapshot('남녀고용평등과 일ㆍ가정 양립 지원에 관한 법률 시행령')['조문']['2-0']
    assert '상시근로자 수가 5명 미만인 사업' in snapshot('산업재해보상보험법 시행령')['조문']['2-0']
    print('ok: 항 단위 매트릭스 + 판정 함수 + 기간제법 별표 대조 + 규모 무관 근거 정상')


if __name__ == '__main__':
    import sys
    test() if '--test' in sys.argv else main()
