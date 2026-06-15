# analyze_chart_v3 인라인 전환 — 되돌리기(스위치백) 절차

2026-06-15 병합(`fef63a1`): analyze_chart_v3 입력을 **ZIP 첨부 → 텍스트 인라인 + 차트 PNG 첨부**로 전환.

## 핵심 — 안전한 되돌리기

이 변경은 **전송 방식만** 바꾼 것이다. 프롬프트 본문(`prompts/analyze_chart_v3.md`)·verdict 로직·임계는 **일절 불변**. 따라서 되돌리기 = LLM 입력 전송을 다시 ZIP 빌더로 스위치백하면 끝이며, 분류 의미론은 그대로다.

**ZIP 빌더(`api/services/zip_builder.py`)는 제거하지 않고 보존**되어 있다(`build_analysis_zip`). 스위치백은 호출부만 되돌리면 된다.

## 언제 되돌리나

`scripts/monitor_classification_drift.py` 가 플래그를 낼 때:
- ignore 비율이 zip 기준선 밴드(mean−2σ) 아래로 체계적 하락(워치리스트 비대화), 또는
- entry 비율이 기준선 밴드를 벗어남.
검토 후 원인이 전송 전환으로 판단되면 스위치백.

## 스위치백 절차 (3개 호출 경로)

대상: `kr_pipeline/llm_runner/{weekend,daily_delta,backfill}.py` 의 `_process_one`.

각 파일에서 인라인 블록을 ZIP 블록으로 되돌린다:

```python
# 되돌릴 현재(인라인):
inline_text, png_paths, freeze_bytes = build_analysis_inline(conn, symbol, on_date=as_of)
png_dir = str(Path(png_paths[0]).parent)
try:
    result = call_claude(prompt_file="analyze_chart_v3.md",
                         attachments=png_paths, payload_inline=inline_text, dry_run=dry_run)
finally:
    shutil.rmtree(png_dir, ignore_errors=True)

# 스위치백(ZIP):
zip_bytes = build_analysis_zip(conn, symbol, on_date=as_of, include_prior_analysis=False)
with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
    f.write(zip_bytes); zip_path = f.name
try:
    result = call_claude(prompt_file="analyze_chart_v3.md",
                         attachments=[zip_path], dry_run=dry_run)
finally:
    Path(zip_path).unlink(missing_ok=True)
```

함께 되돌릴 것:
- import: `build_analysis_inline` → `build_analysis_zip`, `import shutil` 제거·`import tempfile` 복원.
- weekend/daily_delta 의 `save_freeze(artifact_bytes=freeze_bytes, ...)` → `artifact_bytes=zip_bytes`.
- `call_claude` 의 `payload_inline: dict|str` 시그니처와 str 분기는 **그대로 둬도 무방**(하위호환). 굳이 되돌릴 필요 없음.

가장 간단한 전체 되돌리기: `git revert fef63a1` (전송 전환 커밋 단일 되돌리기). `build_analysis_inline` 모듈은 남겨도 무해(미사용).

## 가드/정합성

ZIP·인라인 양쪽 모두 `check_data_integrity`(daily_prices ↔ daily_indicators divergence GUARD)를 빌더 진입 시 호출한다. 스위치백해도 가드는 유지된다.
