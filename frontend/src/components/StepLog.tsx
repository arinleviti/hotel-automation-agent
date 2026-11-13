/**
 * The live log of the graph (middle column): ONE LINE PER NODE, under the node's real name in the
 * code, appearing as each node finishes. Clicking a line opens what that node added to the state.
 *
 * Example for email #3 (each line appears while the run is still going):
 *   ✓ read_email                          code    Read the email from Sarah Mitchell <...>       0.0 s
 *   ✓ classify                            LLM call  Claude classified it: booking (0.97)        1.9 s
 *   ✓ decide_route                        code    Route chosen in code: booking                   0.0 s
 *   ✓ booking_branch › extract_request    LLM call  Claude read the request; code checked it: ... 2.3 s
 *   ✓ booking_branch › check_availability code    Availability checked in code: available         0.1 s
 *   ✓ booking_branch › price_stay         code    Price calculated in code: $1,440.72             0.1 s
 *   ✓ booking_branch › quote_reply        code    Draft written (reply_to_sender) for Sarah ...   0.0 s
 *   ⏸ approval                                    Paused: waiting for a person to approve, edit or reject
 *
 * The tag says WHO did the work (same colours as the schema):
 *   "LLM call" = ONE Claude call filling a fixed form (classify, extract_request, extract_invoice): not an agent
 *   "agent"    = the question agent's turn: Claude deciding to search again or answer (the only agent)
 *   "RAG"      = the document search (Voyage embeddings + pgvector + reranker);  "code" = plain Python
 * It is the project's rule made visible: the model judges, code calculates.
 * The seconds are measured by the page: time between this line and the one before.
 */

// React:
import { useState } from "react";

// OURS:
import type { StepEvent } from "../api";
import { DetailView } from "./DetailView";

/** One line of the log: the step as the stream sent it, plus how long it took (measured by the page). */
export type LoggedStep = StepEvent & { seconds: number };

/** Where the run stands: running (lines still coming), waiting (paused at approval), or failed. */
export type RunState = "running" | "waiting" | "finished" | "error";

// The nodes that make one Claude call, the agent, and the one that searches. Every other node is plain code.
const LLM_NODES = new Set(["classify", "extract_request", "extract_invoice"]);
const AGENT_NODES = new Set(["agent"]);
const SEARCH_NODES = new Set(["search_step"]);

type Props = {
  steps: LoggedStep[];
  state: RunState;
  error?: string;
};

export function StepLog({ steps, state, error }: Props) {
  // Which lines are open. Shape: { 1: true, 5: true }  (key = the line's position; missing = closed)
  const [open, setOpen] = useState<Record<number, boolean>>({});

  return (
    <ol className="step-log">
      {steps.map((step, index) => {
        // "booking_branch > price_stay" -> branch "booking_branch", node "price_stay"; "classify" -> no branch
        const parts = step.step.split(" > ");
        const node = parts[parts.length - 1];
        const branch = parts.length > 1 ? parts[0] : null;
        // who: the tag's text; whoClass: its colour (CSS class who-llm, who-agent, who-search, who-code)
        let who = "code";
        let whoClass = "code";
        if (LLM_NODES.has(node)) {
          who = "LLM call";
          whoClass = "llm";
        }
        if (AGENT_NODES.has(node)) {
          who = "agent";
          whoClass = "agent";
        }
        if (SEARCH_NODES.has(node)) {
          who = "RAG";
          whoClass = "search";
        }
        const isOpen = open[index] === true;
        return (
          <li key={index} className={branch ? "step in-branch" : "step"}>
            <button
              className="step-line"
              aria-expanded={isOpen}
              onClick={() => setOpen({ ...open, [index]: !isOpen })}
            >
              <span className="step-mark" aria-hidden="true">{node === "error_handler" ? "!" : "✓"}</span>
              <span className="step-name">
                {branch && <span className="step-branch">{branch} › </span>}
                {node}
              </span>
              <span className={`step-who who-${whoClass}`}>{who}</span>
              <span className="step-label">{step.label}</span>
              <span className="step-time">{step.seconds.toFixed(1)} s</span>
            </button>
            {isOpen && (
              <div className="step-detail">
                <div className="step-detail-title">What {node} added to the state</div>
                <DetailView value={step.detail} top />
              </div>
            )}
          </li>
        );
      })}

      {state === "running" && (
        <li className="step pending">
          <span className="step-mark spinner" aria-hidden="true" />
          <span className="step-label">Running the next step…</span>
        </li>
      )}
      {state === "waiting" && (
        <li className="step paused">
          <span className="step-mark" aria-hidden="true">⏸</span>
          <span className="step-name">approval</span>
          <span className="step-label">
            Paused (LangGraph interrupt): waiting for a person to approve, edit or reject. The run is saved in
            Postgres and resumes when someone decides.
          </span>
        </li>
      )}
      {state === "error" && (
        <li className="step failed">
          <span className="step-mark" aria-hidden="true">✗</span>
          <span className="step-label">The run stopped: {error}</span>
        </li>
      )}
    </ol>
  );
}
