"""질의 → 후보 조문 라우팅.

조문 제목 인덱스(493개, 8,050토큰)를 캐시한 프롬프트에 넣고 LLM이 후보를 고른다.
임베딩·벡터DB를 쓰지 않는다. 같은 평가셋에서 임베딩 hit@5 71% vs 제목 인덱스 96%.

⚠ 측정 하네스(measure_route.py)와 API가 이 모듈을 공유한다.
   갈라지면 측정 결과가 실제 동작을 보증하지 못한다.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = 'claude-haiku-4-5'   # 실서비스 라우터. 질의당 1.5원.

# 키는 .env.local(커밋 제외)에서도 읽는다. 환경변수가 있으면 그쪽이 우선.
if not os.environ.get('ANTHROPIC_API_KEY'):
    _env = os.path.join(HERE, '.env.local')
    if os.path.exists(_env):
        for _l in open(_env):
            if _l.startswith('ANTHROPIC_API_KEY='):
                os.environ['ANTHROPIC_API_KEY'] = _l.split('=', 1)[1].strip()


def index():
    return open(os.path.join(HERE, 'data/title-index.txt')).read()


SYSTEM_TMPL = """아래는 5인 미만 사업장 노무 관련 법령 6개의 조문 제목 전체 목록이다.

<index>
{index}</index>

사용자 질의에 답하려면 어떤 조문을 봐야 하는지, 위 목록에서 최대 5개 고른다.
가장 관련 높은 것부터 한 줄에 하나씩, 아래 형식으로만 출력한다.

법령명 제N조
법령명 제N조의M

설명이나 답변은 쓰지 않는다. 조문 줄만 출력한다."""

LINE = re.compile(r'^\s*([가-힣ㆍ\s]+?)\s*제(\d+)조(?:의(\d+))?\s*$')


def parse(text):
    """모델 출력에서 조문 줄만 건진다. 설명이 섞여 와도 버린다."""
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            out.append({'법령': m.group(1), '조': int(m.group(2)),
                        '가지': int(m.group(3) or 0)})
    return out


def route(질의, client=None, model=MODEL, effort='low'):
    """질의 → 후보 조문 목록. 최대 5개, 관련도 순."""
    import anthropic
    if not os.environ.get('ANTHROPIC_API_KEY'):
        raise RuntimeError('ANTHROPIC_API_KEY 없음. .env.local 에 넣거나 환경변수로 주세요.')
    client = client or anthropic.Anthropic()
    # Haiku 4.5는 output_config.effort를 지원하지 않는다(400). 4.6+ 계열에만 붙인다.
    extra = {} if 'haiku' in model else {'output_config': {'effort': effort}}
    r = client.messages.create(
        model=model, max_tokens=4000,
        system=[{'type': 'text', 'text': SYSTEM_TMPL.format(index=index()),
                 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': 질의}],
        **extra,
    )
    text = '\n'.join(b.text for b in r.content if b.type == 'text')
    return parse(text), r.usage


def test():
    assert LINE.match('근로기준법 제55조').groups() == ('근로기준법', '55', None)
    assert LINE.match('근로기준법 제76조의3').groups() == ('근로기준법', '76', '3')
    assert LINE.match('근로자퇴직급여 보장법 제4조').groups()[0] == '근로자퇴직급여 보장법'
    assert LINE.match('설명: 이 질의는') is None, '설명 줄은 걸러야 한다'

    p = parse('근로기준법 제55조\n설명은 버린다\n근로기준법 제76조의3\n')
    assert p == [{'법령': '근로기준법', '조': 55, '가지': 0},
                 {'법령': '근로기준법', '조': 76, '가지': 3}], p

    idx = index()
    assert '제56조 연장ㆍ야간 및 휴일 근로' in idx
    assert idx.count('## ') == 6, f"법령 6개여야 한다: {idx.count('## ')}"
    print(f'ok: 라우팅 파싱 정상, 인덱스 {len(idx):,}자 / 법령 6개')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
    else:
        q = ' '.join(a for a in sys.argv[1:] if not a.startswith('--')) or '알바 자르려면 며칠 전에 말해야 해요'
        picks, u = route(q)
        print(f'Q. {q}\n')
        for i, p in enumerate(picks, 1):
            print(f"  {i}. {p['법령']} 제{p['조']}조" + (f"의{p['가지']}" if p['가지'] else ''))
        print(f"\n  캐시읽기 {u.cache_read_input_tokens:,} / 입력 {u.input_tokens} / 출력 {u.output_tokens}")
