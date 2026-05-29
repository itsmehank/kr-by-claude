# FREEZE 최소판 — 분류 입력 스냅샷 보존 (Phase 0 Step 4)

> **상태**: 사용자 v3 지시 (2026-05-29) 반영. 최소판 — 메커니즘 골격 + 분류 단계만 우선.
>
> **다음**: 본 사이클 종료 후 → Step 5 (SCOPE) → 잔여 5종목 → **Phase 1** (룰 강화, 프로젝트의 실제 목표).

## 0. 방향 (가장 중요)

GUARD (Step 3) 까지 끝나 데이터 오염은 *이미 막혔다* — B+B+ 단일 소스 + GUARD 빌드 가드.
이중 회귀에 필요한 **원본 패키지 (005850 + 037760) 도 이미 보유**. 따라서:

> **FREEZE 는 "범용 메커니즘 골격 + 분류만 우선" 으로 가볍게 닫고, Phase 0 잔여를
> 처리한 뒤 곧바로 Phase 1 (룰 강화) 로 진입한다.** 완전한 스냅샷 인프라는 Phase 1~3
> 종료 후 별도 사이클.

근거: FREEZE 는 분류를 한 건도 바꾸지 않는다 (= 미래 검증 *공정성* 인프라). 스크린을
실제로 개선하는 건 Phase 1 이다. 풀 FREEZE 를 미뤄도 정합성·동작·회귀에 문제 없다.
단 **"저장은 하는데 retention 이 없는" 어중간한 상태만은 금지** (무한 누적).

## 1. 크기 — 실측 기준

```
실측 (037760 패키지): 종목당 ZIP ≈ 270KB.
  - 텍스트 (payload·prompt·CSV) gzip 후 ≈ 29KB
  - PNG 차트 2장 ≈ 240KB  ← 지배적. PNG 는 이미 압축돼 gzip 거의 안 먹음.
연간 ≈ 270KB × 2,400 종목 × 250 거래일 ≈ 150GB/년.
```

**픽셀 vs 데이터 분기 — 결정**: 차트는 verify 프롬프트가 강조하는 1차 입력이므로
PNG 통째 저장 (픽셀 동일성). 텍스트만 저장 + 차트 재생성은 9× 절감이지만 *렌더 코드
변경 시 공정성 흠집* — 채택 안 함.

## 2. 범위 — 이번 사이클

| 항목 | 결정 |
|------|------|
| 단계 | **분류 (weekend + daily_delta) 만**. entry_params/pivot 은 후속 사이클 — 단 *메커니즘 범용화* 로 후속 추가가 한 줄이 되게 설계만 열어둠 |
| 저장 시점 | `build_analysis_zip` 직후 (integrity guard 통과 후, LLM 호출 전) |
| 저장 매체 | **로컬 디스크**. 단 `zip_path` 를 *URI 추상화* (`file:///abs/path` 또는 `s3://bucket/key` 등) 로 저장해 나중 S3 이행이 주소 교체만으로 되게 |
| DB 스키마 | **신규 테이블 `classification_freezes`**. `classification_id` nullable + `stage` 컬럼으로 entry_params freeze 후속 추가가 한 줄이 되게 |
| BLOB-in-Postgres | 금지 (백업·vacuum 부하). DB 엔 path + 해시만 |
| 재현 UX | verify endpoint 가 frozen 우선. frozen 없을 때만 재빌드 fallback + "원본 아님 (재빌드됨)" 경고 명시 |

## 3. 저장 레이아웃

```
data/freezes/
  weekend/
    2026-05/
      005850_20260529_014312.zip       # ticker_YYYYMMDD_HHMMSS.zip
      037760_20260529_014508.zip
      ...
    2026-06/
      ...
  daily_delta/
    2026-05/
      ...
```

- 월별 디렉토리 → cron prune 시 월 단위로 큰 덩어리 빠르게 정리 가능.
- 단계별 최상위 분리 → 후속 `entry_params/` 추가 시 cron 정책 단계별 분리 가능.
- `zip_path` 는 `file:///Users/.../data/freezes/weekend/2026-05/005850_20260529_014312.zip`
  형태의 URI. 코드에서 scheme 분기 → 현재는 `file://` 만 구현, 나중 `s3://` 추가
  지점만 명확히.

## 4. DB 스키마

```sql
CREATE TABLE classification_freezes (
    id              BIGSERIAL PRIMARY KEY,
    classification_id BIGINT REFERENCES classifications(id),  -- nullable: entry_params freeze 등 후속
    ticker          TEXT NOT NULL,
    stage           TEXT NOT NULL,  -- 'weekend' | 'daily_delta' | (후속) 'entry_params' | 'pivot'
    frozen_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    zip_uri         TEXT NOT NULL,  -- 'file:///...' or 's3://...'
    zip_sha256      TEXT NOT NULL,
    zip_size_bytes  BIGINT NOT NULL,
    CONSTRAINT classification_freezes_uri_unique UNIQUE (zip_uri)
);

CREATE INDEX classification_freezes_ticker_frozen_at_idx
  ON classification_freezes(ticker, frozen_at DESC);

CREATE INDEX classification_freezes_classification_id_idx
  ON classification_freezes(classification_id)
  WHERE classification_id IS NOT NULL;
```

`stage` 가 있고 `classification_id` 가 nullable 이므로 entry_params freeze 후속 추가 시
스키마 변경 없이 같은 테이블 사용.

## 5. Retention — cron + 활성 보호

방식: **분리된 cron** (주간 housekeeping, performance 단계급). **lazy cleanup 금지**
(분석 경로 결합 → cleanup 실패가 분석 실패 유발. Phase 0 에서 제거한 결합 재도입).

**삭제 기준 (AND)**:
1. `frozen_at < NOW() - INTERVAL '90 days'`
2. AND NOT (현재 활성 watch/entry 분류) — `classification_id` 가 가리키는
   classifications.status 가 archive/ignore 상태일 것
3. AND NOT (종목별 가장 최근 freeze — 최소 1건 보존)

**근거 (정정)**: "90일 = 형성 기간 중간값" 은 **틀림** (형성은 49~455일).
올바른 근거 = "**활성 watch/entry 는 criterion 2 로 무기한 보호되므로, 90일은
ignore/대체본에만 적용된다**." 형성-기간 논리는 오히려 활성 건 장기 보존을 지지하고
그건 이미 criterion 2 가 함.

**실행**: `kr_pipeline/llm_runner/freeze_cleanup.py` (또는 동급). pipeline_runs 에
`freeze_cleanup` 단계 등록. 주 1회 (예: 일요일 03:00). dry-run 모드 지원.

## 6. 재현 UX — verify endpoint frozen 우선

```python
# api/routers/prompts.py — /api/prompts/{ticker}.zip?mode=verify
if mode == 'verify':
    frozen = fetch_latest_freeze(conn, ticker, stage='weekend')  # or 'daily_delta'
    if frozen:
        return read_zip_from_uri(frozen.zip_uri), warning=None
    else:
        rebuilt_zip = build_analysis_zip(conn, ticker)
        warning = "원본 아님 (재빌드됨) — 분류 시점 데이터가 freeze 되어 있지 않습니다."
        return rebuilt_zip, warning=warning
```

UI (PromptPage) 가 warning 을 표시 — 검증자가 *원본 vs 재빌드본* 을 명시적으로 인지.

## 7. 메커니즘 범용화

`api/services/freeze_store.py` 신규:

```python
def save_freeze(
    conn, *,
    zip_bytes: bytes,
    ticker: str,
    stage: str,                       # 'weekend' | 'daily_delta' | ...
    classification_id: int | None,    # weekend/daily_delta 는 채움, 후속 stage 는 None 가능
) -> ClassificationFreeze:
    ...

def fetch_latest_freeze(
    conn, ticker: str, stage: str,
) -> ClassificationFreeze | None:
    ...

def read_zip_from_uri(uri: str) -> bytes:
    \"\"\"file:// scheme 만 현재 구현. s3:// 는 NotImplementedError + 후속 사이클에서 한 줄 추가.\"\"\"
    ...
```

호출처:
- `weekend.py` / `daily_delta.py` 의 ZIP 빌드 직후 → `save_freeze(stage='weekend' or 'daily_delta')`
- `prompts.py` verify mode → `fetch_latest_freeze` 우선
- (후속) `entry_params.py` → `save_freeze(stage='entry_params', classification_id=None)`
  한 줄 추가 — 구현 안 함.

## 8. Phase 0 잔여 (FREEZE 직후)

1. **Step 5 (SCOPE)**: B+B+ 적용 후 5/28 배치 2,416 종목 분류 결과의 신뢰성 / 재실행
   필요 여부 판단. 이미 후속처리 (시그널·entry_params) 된 게 있으면 영향 범위 산정.
2. **잔여 5 종목 mismatch**: 원인 확인 (정정 stuck vs 거래정지 등 정당 사유).
   분석 유니버스 (트렌드템플릿 통과군) 포함 여부 확인 — 포함 시 회귀 전 해결.

## 9. → Phase 1 진입 (프로젝트의 *실제 목표*)

Phase 0 닫으면 brainstorming → spec 진입. 검증자 v2 §7 미해결 3 결정:

1. **handle 결함 인코딩**: (b) `handle_quality` 신설 vs (c') `faulty_pivot` 과 분리한
   sub-label. *불변식*: `faulty_pivot` 하나가 "핸들 불량" + "돌파 실패" 를 라벨 없이
   동시 의미 금지.
2. **2-E two-tier**: Tier 1 (faulty handle 단독 → soft watch, 승격 시 conf ≤ 0.6) +
   Tier 2 (faulty handle AND extended → hard watch) 복원.
3. **2-F**: failed_breakout 무결성 체크 K 값 (3~5) 확정.

이후 2-B (wide_and_loose) · 2-C (분배 클러스터) · 2-D (RS divergence) 적용 → Phase 2
(verify sync) → Phase 3 (이중 회귀, 보유 원본 005850 + 037760 으로) → Phase 4 (ROADMAP).

## 10. Non-goals (이번 사이클 *안 하는 것*)

- entry_params / pivot freeze 실제 구현 (메커니즘 한 줄 후속 추가 가능하게만)
- S3 백엔드 (URI 추상화로 인터페이스만 열어둠)
- BLOB-in-Postgres (영구히 안 함)
- Lazy cleanup (분석 경로 결합 금지)
- UI 의 frozen 데이터 *diff 시각화* (그건 별도 audit 페이지 후속 사이클)

## 11. 한 줄

데이터 청소 (Phase 0) 는 거의 끝났다. FREEZE 를 최소판으로 닫고 잔여를 정리한 뒤,
**아직 시작도 안 한 진짜 목표 — 분석 룰 강화 (Phase 1) — 로 넘어간다.**
