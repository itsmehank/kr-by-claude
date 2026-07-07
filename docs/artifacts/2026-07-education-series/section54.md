<details data-doc-meta style="box-sizing:border-box;margin:0;padding:10px 24px;background:#0f172a;color:#e2e8f0;font-family:'Pretendard','Apple SD Gothic Neo',-apple-system,sans-serif;font-size:14px;line-height:1.75;border-bottom:3px solid #f59e0b;">
<summary style="cursor:pointer;font-weight:700;color:#fbbf24;outline:none;">📌 이 문서는 왜 만들어졌나 — 목적 · 연관 문서 · 이력 (클릭해서 펼치기)</summary>
<div style="max-width:880px;margin:14px auto 8px;">
<p style="margin:0 0 12px;color:#94a3b8;font-size:13px;">생성: 2026-07-04 14:48 · 최종 업데이트: 2026-07-04 14:48 (KST) · 출처: Claude Code 세션 기록 기반 복원</p>
<h3 style="margin:0 0 6px;font-size:15px;color:#fbbf24;">이 문서의 목적 (실제 요청 근거)</h3>
<p>시나리오에 장면별 이미지 프롬프트가 [스타일]+[캐릭터]+[장소] 조각으로 나뉘어 있어 조합이 번거롭다는
피드백에서 나온 파일. 사용자 요청 원문: "이미지 프롬프트를 <b>내가 바로 복사해서 사용할 수 있도록</b>
네가 직접 조합해서 복사 가능하게 코드 블록 형태로 만들어줘."</p>
<p>시나리오 §5.4(장면별 완성 프롬프트)만 분리한 것으로, 컷마다 스타일·캐릭터·장소 정의가 전부 조합된
완성본 프롬프트가 코드 블록으로 담겨 있다. 사용자는 이 프롬프트로 외부 AI에서 삽화를 생성해
~/Downloads/1~17.jpg로 전달했고, 그 삽화가 소설 본문에 임베드됐다.</p>
<h3 style="margin:16px 0 6px;font-size:15px;color:#fbbf24;">연관 문서</h3>
<ul style="margin:0;padding-left:20px;"><li style="margin:4px 0;"><a href="./wuxia-scenario.md" style="color:#7dd3fc;text-decoration:underline;">「반석의 검」 시나리오 + 삽화 이미지 프롬프트</a><span style='color:#94a3b8;'> — 모문서 — 시나리오의 §5.4를 분리한 것</span></li><li style="margin:4px 0;"><a href="./banseok-sword-illustrated.html" style="color:#7dd3fc;text-decoration:underline;">반석의 검 — 청암문 이레의 기록 (삽화판)</a><span style='color:#94a3b8;'> — 이 프롬프트로 생성한 삽화 17컷이 임베드된 소설 본문</span></li></ul>
</div>
</details>



### 5.4 장면별 완성 프롬프트 (15컷 — 그대로 복사해서 사용)

> 아래 각 블록은 **[STYLE]+[캐릭터]+[장소]가 이미 전부 조합된 완성본**이다.
> 코드 블록 하나를 통째로 복사해 이미지 도구에 붙여넣으면 된다. (5.1~5.3은 수정·변형 시 참고용)

**컷 01 · 전사 — 대붕괴의 밤**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Night scene of a martial sect in flames under heavy rain. A young sect leader in a torn rain-soaked white mourning robe kneels among scattered broken swords and fallen banners, clutching two ancient scrolls to his chest, grief-stricken but resolute face. Fire and rain reflected in puddles, low camera angle, mood of tragedy and quiet resolve.
```

**컷 02 · 서장 — 새벽의 청암문**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Dawn establishing shot of a mountain sect built on a massive flat granite outcrop, tiered stone halls with dark tile roofs, pine valleys and a sea of morning mist below. First light touching the highest hall roof, a single lantern still burning at the gatehouse, serene and disciplined mood, extreme wide shot.
```

**컷 03 · 1장 — 철면수문장과 팔관**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A towering gatekeeper in dark iron lamellar armor with a smooth featureless iron mask with narrow eye slits, massive immovable build, holding a bronze measuring staff, standing motionless before a narrow stone corridor of eight successive bronze mechanical gates, each archway fitted with rotating measurement rings and engraved numerals, cold blue-grey light. A line of nervous martial applicants waits in the corridor as the first gate's bronze rings rotate and lock. Cold mechanical atmosphere, symmetrical composition.
```

**컷 04 · 1장 — 서열비석의 68**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A wiry swordsman in his late 20s with a slightly unkempt topknot and patched ochre robe kneels in despair before the eighth bronze mechanical gate of a cold stone corridor. Above his head a tall dark rank stone glows with the carved number 68. Behind him, the silhouette of a towering gatekeeper in dark iron armor with a featureless iron mask. Despair lit by cold blue stone-light, dramatic low-key lighting.
```

**컷 05 · 2장 — 혜안의 대심사**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. An elderly female sect elder with silver hair in a loose bun, sharp amber eyes, deep-green scholar robe, holding a long thin smoking pipe, seated at the head of a vast wooden examination hall. She slowly unrolls a very long scroll painted with abstract brush-stroke candlestick patterns. Pipe smoke curls upward through a beam of window light while rows of kneeling disciples await judgment. High lattice windows, solemn atmosphere.
```

**컷 06 · 2장 — 주화입마의 금족**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A trembling young disciple wreathed in unstable vertical flame-like qi rising too fast around his body, eyes wide with fevered excitement. An elderly female sect elder with silver hair, deep-green scholar robe and a long thin pipe calmly points her pipe downward in a sealing gesture, as a black wooden tag descends toward the disciple. Ominous red-orange palette against a dark hall.
```

**컷 07 · 3장 — 다섯 목패 수여식**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Five disciples stand in a solemn row receiving small wooden tags, group-portrait style, eye-level frontal composition: a small teenage disciple with wide curious eyes in a plain undyed trainee robe (tag carved 未); a burly hot-tempered swordsman with thick arms, sleeveless dark robe and short bristly beard (tag carved 過); a quiet lean young swordsman in a neat dark-blue training robe with a patient composed expression (tag carved 待); a proud athletic young swordsman in a deep-crimson training robe with sharp eyebrows and intense defiant eyes (tag carved 亂); a wiry swordsman with an unkempt topknot and patched ochre robe wearing a nervous crooked grin (tag carved 境). Each tag catches the light showing its carved character.
```

**컷 08 · 3장 — 남궁진과 봉화**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Close-up of a proud young swordsman in his early 20s in a deep-crimson training robe, sharp eyebrows, intense defiant eyes, jaw clenched, fist clenched white at his side, a small wooden tag carved 亂 swaying at his belt. Behind him through an open window, out of focus, a red signal beacon burns atop a distant astronomical tower against darkening clouds. Suppressed fury, shallow depth of field.
```

**컷 09 · 4장 — 새벽의 재시험, 하산**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Grey dawn, high angle shot. A lone disciple with a travel pack walks down long stone mountain steps away from a sect built on a granite outcrop, morning mist swallowing the path below him. Above at the gate, a towering gatekeeper in dark iron armor with a featureless iron mask stands facing forward, not watching him go. Quiet melancholy.
```

**컷 10 · 5장 — 폭풍 속의 순찰**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Storm at night. A slender night patrolman in a charcoal-grey hooded robe, face half-hidden in shadow, glides between walled training yards under driving rain, a small brass lantern in one hand the only warm light, a bundle of wooden notice tags rattling at his belt. A flash of lightning briefly reveals rows of yard gates, each with a single carved line glowing faintly across its stone threshold. Horror-adjacent tension, he leaves no footprints in the wet stone.
```

**컷 11 · 5장 — 두 개의 돌파 (대칭컷)**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Split symmetrical composition of two adjacent walled training yards in a night storm. Left: a quiet lean young swordsman in a dark-blue training robe (wooden tag carved 待 at his belt) mid sword-draw, his qi crossing a glowing carved line on his gate threshold. Right: a proud athletic young swordsman in a deep-crimson robe (wooden tag carved 亂 at his belt) crossing his own identical glowing line at the exact same instant. One lightning bolt overhead unites both frames. Dynamic motion, rain streaking sideways.
```

**컷 12 · 5장 — 감찰전의 두 문**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Inside a solemn tribunal hall lit by two bronze braziers, with twin identical doors at the far end — the left door open to a raging storm outside, the right door barred shut. A stern middle-aged inspector in a black-and-white formal robe with a jade belt sits at a central desk with an open rulebook. A quiet young swordsman in a dark-blue robe (tag 待) walks out through the open left door into rain and darkness, while a proud young swordsman in a deep-crimson robe (tag 亂) stands rigid before the barred right door. Brazier light casts long twin shadows.
```

**컷 13 · 5장 — 대치**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Over-the-shoulder framing from behind a stern middle-aged inspector in a black-and-white formal robe seated at his desk. A proud young swordsman in a deep-crimson training robe leans forward with both fists planted on the desk, shouting, sharp eyebrows drawn, wooden tag carved 亂 at his belt. Between them an open rulebook lit by brazier fire. Extreme tension, embers drifting in the air.
```

**컷 14 · 6장 — 군사의 장부**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. A small candlelit strategy room with wall maps, stacked ledgers and an ink stone, rain streaking the paper windows. A quiet young swordsman in a dark-blue training robe (wooden tag carved 待 at his belt) holds a brush with a barely visible tremor, about to sign an open campaign ledger. Across the desk a pragmatic strategist in a plain brown robe with sleeves tied up and ink-stained fingers quietly grinds ink, pretending not to notice the tremor. Intimate warm candlelight against the cold rainy night.
```

**컷 15 · 종장 — 유심의 새벽**
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. First golden light of dawn after a storm. A small teenage disciple with wide curious eyes in a plain undyed trainee robe (wooden tag carved 未 at his belt) practices a sword form alone in his walled training yard with utmost seriousness, a wooden practice sword in his hands. Across his gate's stone threshold, a carved line is only half-finished. Soft golden backlight, wet stone glistening, hopeful quiet ending, wide shot.
```

**보너스 컷 · 종장 — 장로회의** (필요시)
```text
Korean wuxia webtoon illustration, cinematic ink-wash aesthetic blended with muted watercolor, dramatic chiaroscuro lighting, traditional East Asian mountain-sect architecture, hanbok-influenced martial robes, atmospheric mist, film-still composition, wide 2:1 aspect ratio, no text, no watermark. Late night council around a low round table lit by candles: an elderly female elder with silver hair and a long thin pipe in a deep-green robe; a stern middle-aged inspector in black-and-white formal robe; a pragmatic strategist in a brown robe with ink-stained fingers; and a hunched old scribe with a wispy white beard writing a single line into a thick ledger. Heavy thoughtful silence, smoke curling above the candle flames.
```
