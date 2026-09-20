"""측정 2 — 자체 임베딩 베이스라인 (BGE-M3).

493개 조문을 로컬에서 임베딩하고 같은 구어체 질의 24건으로 top-k recall을 잰다.
측정 1(제목 인덱스 라우팅)과 같은 평가셋이라 숫자가 직접 비교된다.
전문 임베딩과 제목 임베딩을 둘 다 재서, 신호가 어디서 오는지 분리한다.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from measure import parse_queries, norm

HERE = os.path.dirname(os.path.abspath(__file__))
N = 20


def load_articles():
    """(법령명, 조번호, 가지번호, 전문, '법령명 제N조(제목)') 493건."""
    import re
    c = json.load(open(os.path.join(HERE, 'data/corpus.json')))
    out = []
    for law, arts in c.items():
        for k, txt in arts.items():
            jo, ji = (int(x) for x in k.split('-'))
            m = re.match(r'제\d+조(?:의\d+)?\(([^)]*)\)', txt)
            label = f'{law} 제{jo}조' + (f'의{ji}' if ji else '') + (f' {m.group(1)}' if m else '')
            out.append((law, jo, ji, txt, label))
    return out


def main():
    from sentence_transformers import SentenceTransformer
    arts = load_articles()
    qs = [q for q in parse_queries(os.path.join(HERE, 'docs/measurement-queries.md')) if q[2]]
    print(f'조문 {len(arts)}개, 질의 {len(qs)}건. BGE-M3 로드 중...', flush=True)
    m = SentenceTransformer('BAAI/bge-m3')
    qv = m.encode([q[1] for q in qs], normalize_embeddings=True, show_progress_bar=False)

    results = {}
    for name, texts in [('전문', [a[3] for a in arts]), ('제목', [a[4] for a in arts])]:
        print(f'\n=== {name} 임베딩 ===', flush=True)
        av = m.encode(texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
        ranks = {}
        for i, (num, q, law, jo, ji) in enumerate(qs):
            order = (qv[i] @ av.T).argsort()[::-1][:N]
            rank = next((r for r, j in enumerate(order, 1)
                         if norm(arts[j][0]) == norm(law) and arts[j][1] == jo and arts[j][2] == ji), 0)
            ranks[num] = int(rank)
            top = arts[order[0]][4]
            print(f'{num:2d} {q[:28]:<30} {rank or "-":>3}위  1순위:{top[:30]:<32}'
                  f' ← {law} 제{jo}조' + (f'의{ji}' if ji else ''), flush=True)
        n = len(qs)
        hits = [r for r in ranks.values() if r]
        print(f'{name}: hit@1 {sum(r==1 for r in hits)/n:.0%}  hit@5 {sum(r<=5 for r in hits)/n:.0%}  '
              f'hit@{N} {len(hits)/n:.0%}  실패 {sorted(k for k,v in ranks.items() if not v)}')
        results[name] = ranks
    json.dump(results, open(os.path.join(HERE, 'docs/result-embed.json'), 'w'), indent=1)


def peek():
    """.npy 는 NumPy 바이너리다. 에디터로 열면 깨진다. 내용을 보려면 이걸 쓴다."""
    import numpy as np
    for name in ('vec-queries', 'vec-articles'):
        p = os.path.join(HERE, f'data/{name}.npy')
        if not os.path.exists(p):
            print(f'{name}.npy 없음 — measure_embed.py 실행 필요'); continue
        v = np.load(p)
        print(f'{name}.npy  {v.shape[0]}개 × {v.shape[1]}차원  {v.dtype}  '
              f'{os.path.getsize(p)//1024}KB')
        print(f'  첫 벡터 앞 5개: {np.round(v[0][:5], 4).tolist()}')
        print(f'  노름(정규화 확인): {float(np.linalg.norm(v[0])):.4f}')


def test():
    arts = load_articles()
    assert len(arts) == 493, len(arts)
    a55 = [a for a in arts if a[0] == '근로기준법' and a[1] == 55][0]
    assert a55[4] == '근로기준법 제55조 휴일', a55[4]
    assert '유급휴일' in a55[3]
    assert any(a[1] == 76 and a[2] == 3 for a in arts), '제76조의3 가지번호 처리'
    print('ok: 조문 493건 로드, 라벨/가지번호 정상')


if __name__ == '__main__':
    if '--test' in sys.argv: test()
    elif '--peek' in sys.argv: peek()
    else: main()
