// Demo prompts per persona, keyed by actor id. Mirrors the "Questions to ask" table in
// backend/seed/corpus/README.md; keep the two in sync when the seed stories change.

const SAMPLE_QUESTIONS: Readonly<Record<string, readonly string[]>> = {
  "john.tan": [
    "What is the plan for the Rail-B cutover?",
    "What is the payment rail failover procedure and the KYC refresh cycle?",
    "What were the Q3 board deck revenue figures?",
  ],
  "mei.chen": [
    "What were the Q3 board deck revenue figures?",
    "What is the Rail-B rehearsal plan?",
  ],
  "ravi.kumar": ["What is our negotiating position for the Orionix renewal?"],
  "daniel.wong": [
    "Did Finance approve the Rail-B cutover and on what conditions?",
  ],
  "sam.lee": ["How many STRs were filed in Q3?"],
  "alex.tan": [
    "What is our negotiating position for the Orionix renewal?",
    "Who do we escalate Rail-A incidents to?",
    "What happened in the September Rail-A SEV-2 incident?",
  ],
};

export function sampleQuestionsFor(actorId: string): readonly string[] {
  return SAMPLE_QUESTIONS[actorId] ?? [];
}
