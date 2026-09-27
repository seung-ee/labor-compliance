"""답변 템플릿과 인용 검증 게이트.

법률 서비스에서 환각은 버그가 아니라 사고다. 그래서 답변이 인용한 조문을
로컬 정본과 대조하고, 5인 미만 적용 여부를 강제로 병기한다.

안전한 것은 "법령을 찾아서 보여주는 것"이고,
위험한 것은 "당신 사안에 이 조항이 적용됩니다"라고 판단해주는 것이다.
이 모듈은 앞쪽만 한다.
"""
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from payroll import 적용되나, matrix

HERE = os.path.dirname(os.path.abspath(__file__))
DISCLAIMER = ('이 답변은 법령 내용을 찾아서 안내하는 것입니다. '
              '개별 사안에 대한 법률 판단이나 노무 대행이 아닙니다.')
# 이 표현이 답변에 있으면 규제 경계를 넘는다. 설계 단계에서 배제한 것들이다.
금지표현 = ['대행해', '대리해', '신고해드', '처리해드', '해결해드']


def corpus():
    return json.load(open(os.path.join(HERE, 'data/corpus.json')))


def article(c, 법령, 조, 항=None):
    """조문 원문. 항을 주면 그 항만 잘라낸다."""
    txt = (c.get(법령) or {}).get(f'{조}-0')
    if txt is None or 항 is None:
        return txt
    marks = [chr(0x245F + n) for n in range(1, 21)]
    i = txt.find(marks[항 - 1])
    if i < 0:
        return None
    j = min([p for p in (txt.find(m, i + 1) for m in marks[항:]) if p > 0] or [len(txt)])
    return txt[i:j].strip()


def split_ho(text):
    """호(1. 2. 3.)를 줄로 나눈다.

    앞 글자만 봐서는 못 가른다. "통상임금의 100분의 502. 8시간을"에서 502가 아니라
    50 + 호2다. **호 번호가 1부터 순차라는 성질**을 써서 앞에서부터 차례로 찾는다."""
    pos, n = [], 1
    at = text.find(f'{n}. ')
    while at > 0:
        pos.append(at)
        n += 1
        at = text.find(f'{n}. ', at + 1)
    out, prev = [], 0
    for p in pos:
        out.append(text[prev:p])
        prev = p
    out.append(text[prev:])
    return [x for x in out if x.strip()]


def verify(인용들, 상시근로자수, c=None):
    """인용 검증 게이트. 통과하지 못하면 답변을 내보내지 않는다.

    ⚠ 적용 판정은 반드시 적용되나(조, 항, 소규모)를 거친다. 매트릭스를 직접 읽으면
    5인 이상 사업장까지 미적용으로 판정한다."""
    c = c or corpus()
    소규모 = 상시근로자수 < 5
    문제, 판정 = [], []
    for q in 인용들:
        법령, 조, 항 = q['법령'], q['조'], q.get('항')
        label = f"{법령} 제{조}조" + (f'제{항}항' if 항 else '')
        본문 = article(c, 법령, 조, 항)
        if 본문 is None:
            문제.append(f'{label} — 정본에 없다. 조문번호가 틀렸거나 항이 없다')
            continue
        if 법령 != '근로기준법':
            판정.append({**q, 'label': label, '본문': 본문, '적용': True, '비고': '근로기준법 외'})
            continue
        ok = 적용되나(f'제{조}조', 항, 소규모)
        if ok is None:
            문제.append(f'{label} — 일부만 적용되는 조문이다. 항을 특정해야 판정된다')
            continue
        판정.append({**q, 'label': label, '본문': 본문, '적용': ok})
    return (not 문제), 문제, 판정


def render(질의, 답변, 인용들, 상시근로자수, 기준일, 법령시행일=None):
    ok, 문제, 판정 = verify(인용들, 상시근로자수, corpus())
    if not ok:
        raise ValueError('인용 검증 실패 — 답변을 내보내지 않는다:\n  ' + '\n  '.join(문제))
    for w in 금지표현:
        if w in 답변:
            raise ValueError(f'금지 표현 "{w}" — 대행·대리를 약속하면 규제 경계를 넘는다')

    소규모 = 상시근로자수 < 5
    out = [f'Q. {질의}', '', 답변, '', '─' * 60, '근거 조문', '']
    for r in 판정:
        if r.get('비고') == '근로기준법 외':
            뱃지 = '[규모 무관]'
        else:
            뱃지 = '[5인 미만 적용]' if (소규모 and r['적용']) else \
                   '[5인 미만 미적용]' if 소규모 else '[적용]'
        out.append(f"■ {r['label']}  {뱃지}")
        if 소규모 and not r['적용']:
            out.append('   → 시행령 [별표 1]에 열거되지 않았다. 상시 4명 이하 사업장에는 적용되지 않는다.')
        # 코퍼스는 항 사이에 공백이 없다. ①②③ 앞에서 끊어야 읽힌다.
        본문 = re.sub(r'(?<!^)(?=[①-⑳])', '\n', r['본문'])
        for line in 본문.splitlines():
            if not line.strip():
                continue
            parts = split_ho(line)
            out.append('   ' + parts[0].rstrip())
            for p in parts[1:]:
                out.append('      ' + p.rstrip())
        out.append('')
    out += [f'기준 · 상시 {상시근로자수}명 사업장, {기준일} 질의'
            + (f' (시행 {법령시행일} 법령)' if 법령시행일 else ''),
            '출처 · 법제처 국가법령정보', '', f'※ {DISCLAIMER}']
    return '\n'.join(out)


COMPOSE_SYSTEM = """너는 5인 미만 사업장 사장님에게 노무 관련 법령을 찾아서 알려주는 도우미다.

절대 규칙
1. 아래 <조문>에 주어진 조문만 근거로 쓴다. 없는 조문을 지어내지 않는다.
2. **법령을 찾아서 보여주는 것까지만 한다.** "당신 사안에 이 조항이 적용됩니다" 같은
   개별 판단을 하지 않는다. 대행·대리·신고 대행을 약속하지 않는다.
3. 각 조문에 [적용] 또는 [미적용]이 표시돼 있다. **미적용 조문을 적용되는 것처럼 쓰지 않는다.**
   미적용이면 왜 해당하지 않는지 설명한다.
4. 답변은 3~5문장. 사장님이 읽는 글이므로 법률 용어를 풀어 쓴다.

출력 형식 — 이 형식만 지킨다.
<답변>
(답변 본문)
</답변>
<근거>
법령명 제N조
법령명 제N조제M항
</근거>"""

CITE = re.compile(r'^\s*([가-힣ㆍ\s]+?)\s*제(\d+)조(?:의(\d+))?(?:제(\d+)항)?\s*$')


def parse_compose(text):
    """모델 출력에서 답변 본문과 근거 목록을 꺼낸다."""
    body = re.search(r'<답변>(.*?)</답변>', text, re.S)
    ref = re.search(r'<근거>(.*?)</근거>', text, re.S)
    인용 = []
    for line in (ref.group(1) if ref else '').splitlines():
        m = CITE.match(line)
        if m:
            q = {'법령': m.group(1), '조': int(m.group(2))}
            if m.group(4):
                q['항'] = int(m.group(4))
            인용.append(q)
    return (body.group(1).strip() if body else text.strip()), 인용


def compose(질의, 후보들, 상시근로자수, client=None, model='claude-opus-5', c=None):
    """후보 조문의 원문만 컨텍스트에 넣고 답변을 만든다.

    컨텍스트에는 **확정된 원문만** 들어간다. 모델이 조문을 기억에서 꺼내 쓰지 못하게
    하는 것이 목적이다. 조문마다 5인 미만 적용 여부를 붙여서 준다."""
    import anthropic, os
    c = c or corpus()
    소규모 = 상시근로자수 < 5
    blocks = []
    for q in 후보들:
        본문 = article(c, q['법령'], q['조'])
        if 본문 is None:
            continue
        ok = 적용되나(f"제{q['조']}조", None, 소규모) if q['법령'] == '근로기준법' else True
        tag = '[적용]' if ok else '[미적용]' if ok is False else '[항에 따라 다름]'
        blocks.append(f"{q['법령']} 제{q['조']}조 {tag}\n{본문}")
    if not blocks:
        raise ValueError('후보 조문을 정본에서 찾지 못했다')

    client = client or anthropic.Anthropic()
    r = client.messages.create(
        model=model, max_tokens=2000,
        system=[{'type': 'text', 'text': COMPOSE_SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content':
                   f"상시근로자 {상시근로자수}명 사업장이다.\n\n"
                   f"<조문>\n" + '\n\n'.join(blocks) + "\n</조문>\n\n질문: {}".format(질의)}],
    )
    text = '\n'.join(b.text for b in r.content if b.type == 'text')
    본문, 인용 = parse_compose(text)
    return 본문, 인용, r.usage


def test():
    c = corpus()
    a = article(c, '근로기준법', 55, 1)
    assert a and '유급휴일' in a and '공휴일' not in a, a
    b = article(c, '근로기준법', 55, 2)
    assert b and '대통령령으로 정하는 휴일' in b, b
    assert article(c, '근로기준법', 9999) is None

    # 5인 미만: 제55조제1항 적용 / 제2항 미적용
    ok, prob, j = verify([{'법령': '근로기준법', '조': 55, '항': 1}], 4)
    assert ok and j[0]['적용'] is True
    ok, prob, j = verify([{'법령': '근로기준법', '조': 55, '항': 2}], 4)
    assert ok and j[0]['적용'] is False, j
    # 5인 이상은 둘 다 적용
    ok, prob, j = verify([{'법령': '근로기준법', '조': 55, '항': 2}], 9)
    assert ok and j[0]['적용'] is True, '5인 이상에 미적용이 나오면 래퍼가 빠진 것'

    # 항을 안 주면 판정 불가 → 차단
    ok, prob, _ = verify([{'법령': '근로기준법', '조': 55}], 4)
    assert not ok and '항을 특정' in prob[0], prob

    # 없는 조문 = 환각 → 차단
    ok, prob, _ = verify([{'법령': '근로기준법', '조': 9999}], 4)
    assert not ok and '정본에 없다' in prob[0], prob

    # 금지 표현 차단
    try:
        render('q', '신고해드리겠습니다', [{'법령': '근로기준법', '조': 54}], 4, '2026-09-20')
        raise AssertionError('금지 표현을 놓쳤다')
    except ValueError as e:
        assert '금지 표현' in str(e)

    # 미적용 조문도 렌더는 되지만 반드시 표시된다
    t = render('추석에 일한 알바 수당', '5인 미만 사업장이라 공휴일은 유급휴일이 아닙니다.',
               [{'법령': '근로기준법', '조': 55, '항': 2}], 4, '2026-09-20')
    assert '[5인 미만 미적용]' in t and '별표 1' in t and DISCLAIMER in t
    # 항이 여럿인 조문은 항마다 줄이 나뉘어야 한다
    t2 = render('가산수당', '5인 미만은 적용되지 않습니다.',
                [{'법령': '근로기준법', '조': 56}], 4, '2026-09-20')
    assert t2.count('\n   ①') == 1 and t2.count('\n   ②') == 1 and t2.count('\n   ③') == 1, \
        '항이 한 줄로 뭉쳤다'
    줄 = [l.strip() for l in t2.splitlines()]
    assert any(l.startswith('1. 8시간 이내의 휴일근로') for l in 줄), '호1이 안 나뉨'
    assert any(l.startswith('2. 8시간을 초과한 휴일근로') for l in 줄), '호2가 안 나뉨'
    # 앞 글자가 숫자여도 갈려야 한다. '100분의 502.' 는 502가 아니라 50 + 호2다.
    assert split_ho('다음 각 호 1. 가나 100분의 502. 다라') == \
        ['다음 각 호 ', '1. 가나 100분의 50', '2. 다라'], split_ho('다음 각 호 1. 가나 100분의 502. 다라')
    assert split_ho('호가 없는 문장이다') == ['호가 없는 문장이다']
    # 생성 출력 파싱
    b, q = parse_compose("""<답변>
추석은 법정 유급휴일이 아닙니다.
</답변>
<근거>
근로기준법 제55조제2항
근로기준법 제56조
설명 줄은 버린다
</근거>""")
    assert b == '추석은 법정 유급휴일이 아닙니다.', b
    assert q == [{'법령': '근로기준법', '조': 55, '항': 2},
                 {'법령': '근로기준법', '조': 56}], q
    # 태그가 없으면 전체를 본문으로 본다 (형식을 안 지킨 출력도 버리지 않는다)
    b2, q2 = parse_compose('그냥 텍스트')
    assert b2 == '그냥 텍스트' and q2 == []
    print('ok: 인용 검증(환각·항누락·규모분기) + 금지표현 + 병기 강제 + 생성 파싱 정상')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
    else:
        print(render(
            '알바가 추석에 일했는데 수당 더 줘야 하나요?',
            '상시 4명 이하 사업장에는 공휴일 유급휴일 규정과 휴일근로 가산수당 규정이 적용되지 않습니다.\n'
            '추석은 법정 유급휴일이 아니므로 평일과 같이 실제 근로한 시간에 대한 임금을 지급하면 됩니다.',
            [{'법령': '근로기준법', '조': 55, '항': 2}, {'법령': '근로기준법', '조': 56}],
            상시근로자수=4, 기준일='2026-09-20', 법령시행일='2026-08-20'))
