import { CockpitState } from "../types";

export const isFirstRun = (state: CockpitState): boolean => state.review.status === "idle" && state.runtime.status === "unchecked";
export const riskTone = (value: string): string => /critical|high/iu.test(value) ? "danger" : /medium/iu.test(value) ? "warn" : /unknown|unresolved|not fully determined|не удалось определить полностью/iu.test(value) ? "neutral" : "good";
export const escapeHtml = (value: unknown): string => String(value ?? "").replace(/[&<>"']/gu, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character] as string));
