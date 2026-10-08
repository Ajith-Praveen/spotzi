export type CaseStatus = "Candidate" | "In review" | "Needs information" | "Closed";
export type Severity = "Critical" | "High" | "Medium";

export interface Evidence {
  id: string;
  label: string;
  detail: string;
  strength: "Strong" | "Moderate" | "Context";
  source: string;
}

export interface Explanation {
  title: string;
  kind: "Suspicious" | "Legitimate" | "Uncertain";
  support: number;
  summary: string;
}

export interface ClaimCase {
  id: string;
  provider: string;
  specialty: string;
  category: string;
  family: string;
  status: CaseStatus;
  severity: Severity;
  priority: number;
  risk: number;
  exposure: number;
  members: number;
  age: number;
  evidenceQuality: number;
  forecasts: Record<30 | 60 | 90, number>;
  summary: string;
  evidence: Evidence[];
  explanations: Explanation[];
  check: {
    title: string;
    reason: string;
    minutes: number;
    result: string;
    impact: string;
  };
  network: { name: string; role: string; tone: "primary" | "signal" | "neutral" }[];
}

export interface Decision {
  caseId: string;
  outcome: string;
  reason: string;
  reviewer: string;
  decidedAt: string;
}
