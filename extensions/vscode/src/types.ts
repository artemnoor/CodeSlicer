export type RuntimeStatus="unchecked"|"found"|"not-configured"|"install-unavailable"|"incompatible"|"error";
export interface RuntimeState{status:RuntimeStatus;executable?:string;version:string;diagnostic:string}
export type UiLanguage="auto"|"ru"|"en";
export type ReviewSourceMode="current-changes"|"compare"|"diff-file"|"github-pr";
export interface ReviewSourceState{mode:ReviewSourceMode;diffFile?:string;baseRef?:string;label?:string}
export interface ReviewHistoryEntry{createdAt:string;source:ReviewSourceMode;risk:string;affected:number}
export interface ProjectState{workspace?:string;branch?:string;baseRef?:string;baseCandidates?:string[];baseStatus?:string;graphStatus:"unknown"|"present"|"missing";freshness:string;graphifyAvailable:boolean;graphifyPath?:string}
export interface IntegrationState{githubTokenConfigured:boolean;githubAuthenticated?:boolean;githubStatus?:string}
export interface EvidenceLocation{file?:string;line?:number;text?:string;provenance?:string}
export interface ImpactItem{entityId:string;label:string;kind:string;confidence:string;file?:string;line?:number;reason:string;evidence:EvidenceLocation[]}
export interface EvidenceChain{nodeIds:string[];edgeIds:string[];evidence:EvidenceLocation[];confidence?:string}
export interface TestRecommendation{file?:string;symbol:string;category:string;confidence:string;reason:string;command?:string[];fallbackStatus?:string;argv?:string[];cwd?:string;runner?:string;safety?:string}
export interface ReviewState{status:"idle"|"ready"|"error";riskLevel:string;riskConfidence:string;riskReasons:string[];impacts:ImpactItem[];chains:EvidenceChain[];tests:TestRecommendation[];warnings:string[];limitations:string[];localDiffNotice:string}
export interface CockpitState{runtime:RuntimeState;project:ProjectState;integration:IntegrationState;reviewSource:ReviewSourceState;history:ReviewHistoryEntry[];review:ReviewState}
export const INITIAL_STATE:CockpitState={runtime:{status:"unchecked",version:"Not checked",diagnostic:"Run Refresh to validate a local CodeSlicer executable."},project:{graphStatus:"unknown",freshness:"Not checked",graphifyAvailable:false},integration:{githubTokenConfigured:false},reviewSource:{mode:"current-changes"},history:[],review:{status:"idle",riskLevel:"—",riskConfidence:"—",riskReasons:[],impacts:[],chains:[],tests:[],warnings:[],limitations:[],localDiffNotice:"Analyzes a local Git diff only; GitHub metadata, comments, and checks are not read."}};
