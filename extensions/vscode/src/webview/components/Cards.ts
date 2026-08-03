import { EvidenceLocation, ImpactItem, TestRecommendation } from "../../types";
import { escapeHtml as esc } from "../state";

export const impactCard = (item: ImpactItem, labels: { confirmed: string; likely: string; possible: string; confidenceLow: string; reason: string; confidenceLikely: string; confidenceConfirmed: string }): string => {const possible=item.tier==="possible";const tier=possible?labels.possible:item.tier==="likely"?labels.likely:labels.confirmed;const confidence=item.confidence === "likely" ? labels.confidenceLikely : item.confidence === "confirmed" ? labels.confidenceConfirmed : item.confidence;const location=`${item.file || ""}${item.line ? `:${item.line}` : ""} · ${possible?labels.confidenceLow:confidence}`;return `<button class="result-card impact-card impact-card--${esc(item.tier)}" data-entity="${esc(item.entityId)}" data-file="${esc(item.file)}" data-line="${item.line || ""}"><span class="result-card__kind">${esc(tier)} · ${esc(item.kind)}</span><strong>${esc(item.label)}</strong><span class="result-card__reason">${possible?`${esc(labels.reason)}: `:""}${esc(item.reason || item.kind)}</span><small title="${esc(location)}">${esc(location)}</small></button>`;};

export const evidenceCard = (item: EvidenceLocation): string => `<li><strong>${esc(item.file || "Unknown location")}${item.line ? `:${item.line}` : ""}</strong>${item.text ? `<span>${esc(item.text)}</span>` : ""}${item.provenance ? `<em>${esc(item.provenance)}</em>` : ""}</li>`;

export const testCard = (item: TestRecommendation, index: number, run: string, language: "ru" | "en" = "en"): string => {
  const advisory = language === "ru" ? "рекомендация · ограниченное покрытие" : "recommendation · limited coverage";
  const commandHint = language === "ru" ? "нужна команда вручную" : "a manual command is needed";
  const category = item.advisory ? advisory : (language === "ru" ? "рекомендуемый тест" : "recommended test");
  const detail = `${item.confidence}${item.argv ? ` · ${item.argv.join(" ")}` : ` · ${commandHint}`}`;
  const reason = language === "ru" && item.reason === "no exact targeted test was found" ? "Точный целевой тест не найден" : item.reason;
  return `<article class="test-card"><div><span class="result-card__kind">${esc(category)}</span><strong title="${esc(item.file || item.symbol)}">${esc(item.file || item.symbol)}</strong><p>${esc(reason)}</p><small title="${esc(detail)}">${esc(detail)}</small></div>${item.argv ? `<button class="button button--secondary" data-test="${index}">${esc(run)}</button>` : ""}</article>`;
};
