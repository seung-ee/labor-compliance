"""HTTP API — Next.js가 부르는 파이썬 런타임.

질의 처리 플로우(CLAUDE.md) 1~6단계를 잇는다. 판정 로직은 route·answer·payroll에
있고 여기서 새로 판정하지 않는다. 7단계 query_log는 Postgres를 붙일 때 넣는다.

실행: ./.venv/bin/uvicorn api:app --reload
"""
import datetime, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from route import route
from answer import compose, verify, corpus, 미인용, 금지표현, DISCLAIMER
from payroll import calc

app = FastAPI()
시도 = 2   # 게이트에 막히면 한 번 다시 생성한다. 질의당 최대 ~88원.


class Ask(BaseModel):
    질의: str = Field(min_length=1)
    상시근로자수: int = Field(ge=1)


class Payroll(BaseModel):
    시급: int = Field(gt=0)
    주소정근로시간: float = Field(ge=0)
    실근로시간: float = Field(ge=0)
    상시근로자수: int = Field(ge=1)
    기준일: datetime.date
    야간시간: float = Field(0, ge=0)
    휴일시간: float = Field(0, ge=0)
    개근: bool = True


def gate(답변, 인용, 상시근로자수, c):
    """answer.render()와 같은 게이트. 텍스트 대신 판정 목록을 돌려준다.

    근거 없는 답변도 막는다. verify()는 빈 인용을 통과시키는데, 출력에 근거 조문
    원문을 붙이는 것이 필수라서 근거가 0개면 내보낼 수 없다."""
    _, 문제, 판정 = verify(인용, 상시근로자수, c)
    if not 인용:
        문제.append('근거 조문이 없다. 근거 없는 답변은 내보내지 않는다')
    문제 += [f'{x} — 본문에서 언급했지만 근거에 없다' for x in 미인용(답변, 인용)]
    문제 += [f'금지 표현 "{w}" — 대행·대리를 약속하면 규제 경계를 넘는다'
             for w in 금지표현 if w in 답변]
    return 문제, 판정


# async가 아니다. Anthropic SDK 호출이 블로킹이라 FastAPI 스레드풀에서 돌게 둔다.
@app.post('/ask')
def ask(req: Ask):
    후보, _ = route(req.질의)
    c = corpus()
    for _ in range(시도):
        try:
            답변, 인용, _ = compose(req.질의, 후보, req.상시근로자수, c=c)
        except ValueError as e:     # 후보 조문이 정본에 하나도 없다
            raise HTTPException(422, {'문제': [str(e)]})
        문제, 판정 = gate(답변, 인용, req.상시근로자수, c)
        if not 문제:
            return {'답변': 답변, '근거': 판정, '고지문': DISCLAIMER,
                    '기준일': str(datetime.date.today())}
    raise HTTPException(422, {'문제': 문제})


@app.post('/payroll')
def payroll(req: Payroll):
    return calc(**req.model_dump(mode='json'))


def test():
    """route·compose를 가짜로 바꿔 돌린다. API 비용 0원."""
    from fastapi.testclient import TestClient
    cl = TestClient(app)
    g = globals()
    g['route'] = lambda q: ([{'법령': '근로기준법', '조': 55, '가지': 0}], None)

    def fake(*출력):
        it = iter(출력)
        return lambda *a, **k: (*next(it), None)

    body = {'질의': '추석에 일한 알바 수당 더 줘야 하나요', '상시근로자수': 4}
    좋은 = ('5인 미만 사업장은 공휴일이 유급휴일이 아닙니다.', [{'법령': '근로기준법', '조': 55, '항': 2}])
    환각 = ('제9999조에 따라 줘야 합니다.', [{'법령': '근로기준법', '조': 9999}])
    대행 = ('신고해드리겠습니다.', [{'법령': '근로기준법', '조': 55, '항': 2}])
    무근거 = ('줘야 합니다.', [])
    본문만 = ('제27조는 5인 미만에 적용되지 않습니다.', [{'법령': '근로기준법', '조': 55, '항': 2}])

    for 출력, 기대 in [(환각, '정본에 없다'), (대행, '금지 표현'), (무근거, '근거 조문이 없다'),
                       (본문만, '근거에 없다')]:
        g['compose'] = fake(출력, 출력)
        r = cl.post('/ask', json=body)
        assert r.status_code == 422, (기대, r.json())
        assert 기대 in ' '.join(r.json()['detail']['문제']), (기대, r.json())

    # 첫 생성이 막혀도 재생성이 통과하면 내보낸다
    g['compose'] = fake(환각, 좋은)
    r = cl.post('/ask', json=body)
    assert r.status_code == 200, r.json()
    j = r.json()
    assert j['답변'] == 좋은[0] and j['고지문'] == DISCLAIMER
    assert j['근거'][0]['적용'] is False and '대통령령으로 정하는 휴일' in j['근거'][0]['본문'], j

    # 후보가 정본에 없으면 생성하지 않고 422
    def 없음(*a, **k):
        raise ValueError('후보 조문을 정본에서 찾지 못했다')
    g['compose'] = 없음
    assert cl.post('/ask', json=body).status_code == 422

    # 입력 검증
    assert cl.post('/ask', json={'질의': '', '상시근로자수': 4}).status_code == 422
    assert cl.post('/ask', json={'질의': 'q', '상시근로자수': 0}).status_code == 422

    # 급여: 같은 입력, 규모만 다르면 합계가 갈린다 (5시간 연장 × 50%)
    p = dict(시급=12000, 주소정근로시간=40, 실근로시간=45, 기준일='2026-06-01')
    소 = cl.post('/payroll', json={**p, '상시근로자수': 4}).json()
    대 = cl.post('/payroll', json={**p, '상시근로자수': 5}).json()
    assert 대['합계'] - 소['합계'] == 30000, (소['합계'], 대['합계'])
    assert cl.post('/payroll', json={**p, '상시근로자수': 4, '기준일': '6월 1일'}).status_code == 422
    print('ok: 인용 게이트(환각·금지표현·무근거·본문 미인용) + 재생성 + 입력 검증 + 급여 규모 분기 정상')


if __name__ == '__main__':
    if '--test' in sys.argv:
        test()
