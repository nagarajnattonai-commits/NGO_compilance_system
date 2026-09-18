// Keep consistent with the server lifecycle classification.
export const closedComplianceStates = new Set(["COMPLETED", "CANCELLED", "NOT_APPLICABLE"]);
export const isOpenCompliance = (status: string) => !closedComplianceStates.has(status);
export const countsTowardCompletion = (status: string) => !["CANCELLED", "NOT_APPLICABLE"].includes(status);
