import { EvidenceLocation, ImpactItem, TestRecommendation } from "../../types";
import { escapeHtml as esc } from "../state";

export const impactCard = (item: ImpactItem): string => `<button class="card impact" data-entity="${esc(item.entityId)}" data-file="${esc(item.file)}" data-line="${item.line || ""}"><strong>${esc(item.label)}</strong><span>${esc(item.reason || item.kind)}</span><small>${esc(item.file || "")}${item.line ? `:${item.line}` : ""} · ${esc(item.confidence)}</small></button>`;
export const evidenceCard = (item: EvidenceLocation): string => `<li>${esc(item.file || "Unknown location")}${item.line ? `:${item.line}` : ""}${item.text ? ` — ${esc(item.text)}` : ""}${item.provenance ? ` (${esc(item.provenance)})` : ""}</li>`;
export const testCard = (item: TestRecommendation, index: number, run: string): string => `<article class="card"><strong>${esc(item.file || item.symbol)}</strong><span>${esc(item.reason)}</span><small>${esc(item.confidence)}${item.argv ? ` · ${esc(item.argv.join(" "))}` : " · needs a manual command"}</small>${item.argv ? `<button class="secondary" data-test="${index}">${esc(run)}</button>` : ""}</article>`;
