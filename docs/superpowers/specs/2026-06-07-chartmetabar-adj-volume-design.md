# ChartMetaBar 주간 누적거래량 adjusted 전환 설계

날짜: 2026-06-07
대상: `web/src/components/ChartMetaBar.tsx`

## 문제

`ChartMetaBar` 의 "이번주 누적 거래량"(`weekVolume`, :119-126)이 **raw `d.volume`** 을 합산한다. 이를 **`avg_volume_10w`(주간 평균, adj_volume 기반)** 와 나눠 진행도 %(`weekProgress`)를 그린다 → raw누적 ÷ adj평균. 분할 종목에서 두 값의 눈금이 달라 **진행도 막대가 틀린다**(차트 거래량은 P3 에서 adj 로 전환됨 — 표시도 불일치).

## 변경

`weekVolume` 의 `d.volume` → `d.adj_volume` (null 체크 + reduce 합산 둘 다). `adj_volume` 은 P3 에서 이미 `DailyIndicator` 타입·API 응답에 존재(`number | null`).

```ts
const week = sb.filter((d) => d.date >= monday && d.adj_volume != null);
const sum = week.reduce((acc, d) => acc + (d.adj_volume ?? 0), 0);
```

## 효과

이번주 누적 거래량 = adj → ① 차트 거래량 막대(adj)와 일치, ② 진행도 % = adj누적 ÷ adj평균으로 정합(분할 종목 정확).

## 비목표

다른 ChartMetaBar 지표(가격 등락은 이미 adj_close 기반)·다른 파일 무변경.

## 테스트

프론트 테스트 러너 없음 → `cd web && npm run build`(tsc 타입체크, `adj_volume: number | null` 이라 통과) + 수동 확인(분할 종목에서 진행도 막대가 차트 거래량과 정합). 회귀: 백엔드 무관(프론트 전용).
