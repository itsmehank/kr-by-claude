import { TABLES } from "../../data/llm-pipeline/tables";
import { ListFold } from "./ListFold";

interface Props {
  names: string[];     // 표시할 테이블 이름들 (예: ["daily_indicators", "stocks"])
  label: string;       // 예: "입력 테이블" or "출력 테이블"
}

/**
 * 카드 안 입출력 테이블을 '칩 + 한 줄 친절 설명' 으로 표시.
 * 각 테이블은 ListFold (subtle) 로 컬럼 상세 확장 가능.
 */
export function TableExplainerList({ names, label }: Props) {
  return (
    <div>
      <div className="caps text-faint mb-2">{label}</div>
      <ul className="space-y-2">
        {names.map((name) => {
          const t = TABLES[name];
          if (!t) {
            return (
              <li key={name} className="text-data-xs text-faint">
                <span className="num bg-tint-stone text-muted px-2 py-0.5 rounded">{name}</span>
                {" "}(설명 없음 — tables.ts 추가 필요)
              </li>
            );
          }
          return (
            <li key={name} className="text-data-xs">
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="num bg-tint-stone text-muted px-2 py-0.5 rounded shrink-0">
                  {t.name}
                </span>
                <span className="text-data text-ink">{t.short}</span>
              </div>
              <ListFold
                label="컬럼 상세 보기"
                variant="subtle"
              >
                <div className="space-y-1">
                  <div>{t.details}</div>
                  <div className="text-faint">
                    Primary key: <span className="num">{t.pkey}</span>
                  </div>
                </div>
              </ListFold>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
