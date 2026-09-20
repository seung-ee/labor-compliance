"""측정 1 — 조문 제목 인덱스 라우팅.

493개 조문 제목만 캐시된 프롬프트에 넣고, 구어체 질의로 정답 조문을 지목하게 한다.
2단계 설계(제목 인덱스 → 로컬 원문)가 성립하는지 보는 것이 목적.
ponytail: 일회성 측정. 결과가 임베딩 여부를 가르면 버린다.
"""
import json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure import parse_queries, norm  # 질의는 마크다운 표 하나에서만 읽는다

import anthropic

HERE = os.path.dirname(os.path.abspath(__file__))

# 키는 .env.local(커밋 제외)에서도 읽는다. 환경변수가 있으면 그쪽이 우선.
if not os.environ.get('ANTHROPIC_API_KEY'):
    _env = os.path.join(HERE, '.env.local')
    if os.path.exists(_env):
        for _l in open(_env):
            if _l.startswith('ANTHROPIC_API_KEY='):
                os.environ['ANTHROPIC_API_KEY'] = _l.split('=', 1)[1].strip()
MODEL = 'claude-haiku-4-5'  # 실서비스 라우터로 쓸 티어. --model로 올려가며 잰다
INDEX = open(os.path.join(HERE, 'data/title-index.txt')).read()

SYSTEM = f"""아래는 5인 미만 사업장 노무 관련 법령 6개의 조문 제목 전체 목록이다.

<index>
{INDEX}</index>

사용자 질의에 답하려면 어떤 조문을 봐야 하는지, 위 목록에서 최대 5개 고른다.
가장 관련 높은 것부터 한 줄에 하나씩, 아래 형식으로만 출력한다.

법령명 제N조
법령명 제N조의M

설명이나 답변은 쓰지 않는다. 조문 줄만 출력한다."""

LINE = re.compile(r'^\s*([가-힣ㆍ\s]+?)\s*제(\d+)조(?:의(\d+))?\s*$')


def pick(client, q, effort, model):
    # Haiku 4.5는 output_config.effort를 지원하지 않는다(400). 4.6+ 계열에만 붙인다.
    extra = {} if 'haiku' in model else {'output_config': {'effort': effort}}
    r = client.messages.create(
        model=model,
        max_tokens=4000,
        system=[{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': q}],
        **extra,
    )
    text = '\n'.join(b.text for b in r.content if b.type == 'text')
    out = []
    for line in text.splitlines():
        m = LINE.match(line)
        if m:
            out.append((norm(m.group(1)), int(m.group(2)), int(m.group(3) or 0)))
    return out, r.usage


def main():
    effort = sys.argv[sys.argv.index('--effort') + 1] if '--effort' in sys.argv else 'low'
    model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else MODEL
    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('ANTHROPIC_API_KEY 없음. .env.local에 넣거나 환경변수로 주세요.')
    client = anthropic.Anthropic()
    qs = [q for q in parse_queries(os.path.join(HERE, 'docs/measurement-queries.md')) if q[2]]
    print(f'측정 1 — 제목 인덱스 라우팅 ({model}, effort={effort}, 질의 {len(qs)}건, 조문 493개)\n')
    ranks, cached = {}, 0
    for num, q, law, jo, ji in qs:
        picks, usage = pick(client, q, effort, model)
        rank = next((i for i, p in enumerate(picks, 1) if p == (norm(law), jo, ji)), 0)
        ranks[num] = rank
        cached += usage.cache_read_input_tokens
        top = f'{picks[0][0]} 제{picks[0][1]}조' if picks else '(없음)'
        print(f'{num:2d} {q[:30]:<32} {rank or "-":>2}위  1순위:{top:<22} ← {law} 제{jo}조'
              + (f'의{ji}' if ji else ''))
        time.sleep(0.2)
    n = len(qs)
    hits = [r for r in ranks.values() if r]
    print(f'\nhit@1 {sum(r == 1 for r in hits)/n:.0%}  '
          f'hit@3 {sum(r <= 3 for r in hits)/n:.0%}  hit@5 {len(hits)/n:.0%}')
    print(f'실패: {sorted(k for k, v in ranks.items() if not v)}')
    print(f'캐시 읽은 토큰 {cached:,} (캐시 작동: {"예" if cached else "아니오"})')
    json.dump(ranks, open(os.path.join(HERE, f'docs/result-route-{model}-{effort}.json'), 'w'), indent=1)


def test():
    assert LINE.match('근로기준법 제55조').groups() == ('근로기준법', '55', None)
    assert LINE.match('근로기준법 제76조의3').groups() == ('근로기준법', '76', '3')
    assert LINE.match('근로자퇴직급여 보장법 제4조').groups()[0] == '근로자퇴직급여 보장법'
    assert LINE.match('산업재해보상보험법 제6조') is not None
    assert LINE.match('설명: 이 질의는') is None
    assert '제56조 연장ㆍ야간 및 휴일 근로' in INDEX
    print(f'ok: 파싱/인덱스 정상, 인덱스 {len(INDEX):,}자')


if __name__ == '__main__':
    test() if '--test' in sys.argv else main()
