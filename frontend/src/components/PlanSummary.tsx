import type { SessionPlan, SessionType } from "../api/client";
import Chips from "./Chips";

/** What the interview will cover, from the saved plan. */
export default function PlanSummary({ type, plan }: { type: SessionType; plan: SessionPlan | null }) {
  if (!plan) return <p className="soft">The interviewer will pick the topics as you go.</p>;
  if (type === "system_design") {
    return (
      <div className="plan">
        <p className="plan-title">{plan.problem_title}</p>
        {plan.problem_statement && <p className="spoken plan-statement">“{plan.problem_statement}”</p>}
        {(plan.deep_dives?.length ?? 0) > 0 && (
          <>
            <h4>Likely deep dives</h4>
            <Chips items={plan.deep_dives ?? []} tone="quiet" />
          </>
        )}
      </div>
    );
  }
  if (type === "technical") {
    const source = plan.stack_source === "job" ? "from the job posting" : plan.stack_source === "resume" ? "from your resume" : "";
    return (
      <div className="plan">
        <h4>Stack {source}</h4>
        <Chips items={plan.stack ?? []} empty="Your main backend stack — the interviewer will ask" />
        {(plan.areas?.length ?? 0) > 0 && (
          <>
            <h4>Areas</h4>
            <Chips items={plan.areas ?? []} tone="quiet" />
          </>
        )}
      </div>
    );
  }
  return (
    <div className="plan">
      {(plan.themes?.length ?? 0) > 0 && (
        <>
          <h4>Themes</h4>
          <Chips items={(plan.themes ?? []).slice(0, 5)} tone="quiet" />
        </>
      )}
      {(plan.anchor_projects?.length ?? 0) > 0 && (
        <>
          <h4>Stories from your projects</h4>
          <ul className="plan-projects">
            {plan.anchor_projects!.map((p, i) => (
              <li key={i}>{p.name}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
