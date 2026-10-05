"use client";

import { useState } from "react";
import s from "./page.module.css";

// api.py 응답 형식. 판정은 전부 서버가 한다 — 여기서 새로 판정하지 않는다.
type 근거 = { label: string; 본문: string; 적용: boolean; 비고?: string; 조건?: string };
type 답 = { 답변: string; 근거: 근거[]; 고지문: string; 기준일: string };
type 급여항목 = { 항목: string; 금액: number; 근거: string; 적용: boolean; 산식?: string; 사유?: string };
type 급여 = { 합계: number; 항목: 급여항목[]; 경고: string[] };

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`/api/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => null);
  if (r.ok) return j as T;
  // 422 는 둘 중 하나다. 인용 검증 게이트가 막았거나({문제: [...]}), 입력이 틀렸거나.
  if (r.status === 422 && j?.detail?.문제)
    throw new Error(["검증을 통과하지 못해 답변을 내보내지 않았습니다.", ...j.detail.문제].join("\n· "));
  if (r.status === 422) throw new Error("입력을 확인해 주세요.");
  throw new Error(`서버 오류 (${r.status})`);
}

// answer.render() 의 뱃지와 같은 규칙.
function 뱃지(g: 근거, 소규모: boolean) {
  if (g.비고 === "규모 무관") return "규모 무관";
  if (!소규모) return "적용";
  return g.적용 ? "5인 미만 적용" : "5인 미만 미적용";
}

export default function Home() {
  const [인원, set인원] = useState(4);
  const 소규모 = 인원 < 5;

  const [질의, set질의] = useState("");
  const [답변, set답변] = useState<답 | null>(null);

  const [시급, set시급] = useState(10320);
  const [주소정, set주소정] = useState(20);
  const [실근로, set실근로] = useState(20);
  const [기준일, set기준일] = useState(() => new Date().toISOString().slice(0, 10));
  const [급여결과, set급여결과] = useState<급여 | null>(null);

  const [오류, set오류] = useState("");
  const [대기, set대기] = useState(false);

  async function run<T>(f: () => Promise<T>, set: (v: T) => void) {
    set오류("");
    set대기(true);
    try {
      set(await f());
    } catch (e) {
      set오류((e as Error).message);
    } finally {
      set대기(false);
    }
  }

  return (
    <main className={s.main}>
      <h1>5인 미만 노무 안내</h1>

      <label className={s.row}>
        상시근로자 수
        <input type="number" min={1} value={인원} onChange={(e) => set인원(+e.target.value)} />
        명
      </label>

      <section>
        <h2>법령 질문</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            run(() => post<답>("ask", { 질의, 상시근로자수: 인원 }), (v) => { set답변(v); set급여결과(null); });
          }}
        >
          <textarea
            rows={3}
            placeholder="예: 알바 자르려면 며칠 전에 말해야 해요"
            value={질의}
            onChange={(e) => set질의(e.target.value)}
          />
          <button disabled={대기 || !질의.trim()}>{대기 ? "찾는 중…" : "질문하기"}</button>
        </form>
      </section>

      <section>
        <h2>주급 계산 (세전)</h2>
        <form
          className={s.grid}
          onSubmit={(e) => {
            e.preventDefault();
            run(
              () => post<급여>("payroll", {
                시급, 주소정근로시간: 주소정, 실근로시간: 실근로, 상시근로자수: 인원, 기준일,
              }),
              (v) => { set급여결과(v); set답변(null); },
            );
          }}
        >
          <label>시급 <input type="number" value={시급} onChange={(e) => set시급(+e.target.value)} /></label>
          <label>주 소정근로시간 <input type="number" value={주소정} onChange={(e) => set주소정(+e.target.value)} /></label>
          <label>실제 근로시간 <input type="number" value={실근로} onChange={(e) => set실근로(+e.target.value)} /></label>
          <label>기준일 <input type="date" value={기준일} onChange={(e) => set기준일(e.target.value)} /></label>
          <button disabled={대기}>계산하기</button>
        </form>
      </section>

      {오류 && <p className={s.error}>{오류}</p>}

      {답변 && (
        <section className={s.result}>
          <p className={s.answer}>{답변.답변}</p>
          <h3>근거 조문</h3>
          {답변.근거.map((g) => (
            <article key={g.label} className={s.cite}>
              <header>
                <strong>{g.label}</strong>
                <span className={g.적용 ? s.on : s.off}>{뱃지(g, 소규모)}</span>
              </header>
              {g.조건 && <p className={s.cond}>한정: {g.조건}</p>}
              {/* 코퍼스는 항 사이에 줄바꿈이 없다. ①②③ 앞에서 끊어야 읽힌다. */}
              <p className={s.text}>{g.본문.split(/(?=[①-⑳])/).join("\n")}</p>
            </article>
          ))}
          <p className={s.meta}>기준 · 상시 {인원}명 사업장, {답변.기준일} 질의 · 출처 · 법제처 국가법령정보</p>
          {/* 고지문은 접을 수 없게 항상 노출한다 (CLAUDE.md 규제 경계). */}
          <p className={s.notice}>※ {답변.고지문}</p>
        </section>
      )}

      {급여결과 && (
        <section className={s.result}>
          <table className={s.table}>
            <tbody>
              {급여결과.항목.map((x) => (
                <tr key={x.항목} className={x.적용 ? "" : s.offRow}>
                  <td>{x.항목}</td>
                  <td className={s.num}>{x.금액.toLocaleString()}원</td>
                  <td>
                    {x.근거}
                    {x.산식 && <div className={s.meta}>{x.산식}</div>}
                    {x.사유 && <div className={s.meta}>→ {x.사유}</div>}
                  </td>
                </tr>
              ))}
              <tr>
                <th>합계</th>
                <th className={s.num}>{급여결과.합계.toLocaleString()}원</th>
                <td className={s.meta}>세전, 공제 전</td>
              </tr>
            </tbody>
          </table>
          {급여결과.경고.map((w) => <p key={w} className={s.cond}>⚠ {w}</p>)}
        </section>
      )}
    </main>
  );
}
