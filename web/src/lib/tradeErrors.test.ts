import { describe, expect, it } from "vitest";
import { errorMessage } from "./tradeErrors";

describe("errorMessage", () => {
  it("maps known toss codes to Korean", () => {
    expect(errorMessage("insufficient-buying-power", "")).toContain("매수 가능 금액");
    expect(errorMessage("order-hours-closed", "")).toContain("주문 접수 불가 시간");
    expect(errorMessage("opposite-pending-order-exists", "")).toContain("반대 방향");
    expect(errorMessage("edge-blocked", "")).toContain("허용 IP");
  });
  it("maps guard codes", () => {
    expect(errorMessage("guard/tick-size", "")).toContain("호가 단위");
    expect(errorMessage("guard/preview-required", "")).toContain("미리보기");
    expect(errorMessage("guard/max-daily-amount", "")).toContain("1일");
  });
  it("falls back to code · message for unknown codes", () => {
    expect(errorMessage("brand-new-code", "서버 메시지")).toBe("brand-new-code · 서버 메시지");
    expect(errorMessage("brand-new-code", "")).toBe("brand-new-code");
  });
});
