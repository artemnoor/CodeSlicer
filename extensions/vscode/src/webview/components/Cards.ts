import { EvidenceLocation, ImpactItem, TestRecommendation } from "../../types";
import { escapeHtml as esc } from "../state";

export const impactCard = (item: ImpactItem): string => `<button class="result-card impact-card" data-entity="${esc(item.entityId)}" data-file="${esc(item.file)}" data-line="${item.line || ""}"><span class="result-card__kind">${esc(item.kind)}</span><strong>${esc(item.label)}</strong><span class="result-card__reason">${esc(item.reason || item.kind)}</span><small>${esc(item.file || "")}${item.line ? `:${item.line}` : ""} · ${esc(item.confidence)}</small></button>`;

export const evidenceCard = (item: EvidenceLocation): string => `<li><strong>${esc(item.file || "Unknown location")}${item.line ? `:${item.line}` : ""}</strong>${item.text ? `<span>${esc(item.text)}</span>` : ""}${item.provenance ? `<em>${esc(item.provenance)}</em>` : ""}</li>`;

export const testCard = (item: TestRecommendation, index: number, run: string): string => `<article class="test-card"><div><span class="result-card__kind">${esc(item.category)}</span><strong>${esc(item.file || item.symbol)}</strong><p>${esc(item.reason)}</p><small>${esc(item.confidence)}${item.argv ? ` · ${esc(item.argv.join(" "))}` : " · needs a manual command"}</small></div>${item.argv ? `<button class="button button--secondary" data-test="${index}">${esc(run)}</button>` : ""}</article>`;
