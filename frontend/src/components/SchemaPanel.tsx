/**
 * "Show the schema": the bird's-eye view of the whole graph, with the path of the selected email's
 * run lit up.
 *
 * WHAT HAPPENS WHEN ...
 *  - the person clicks "Show the schema": this panel opens over the page and draws every node of the
 *    graph: the trunk (read_email, classify, decide_route), the three branches (each a LangGraph
 *    subgraph, drawn as a frame), the human route, then approval and action.
 *  - an email has been processed: the nodes its run went through are lit in red, the arrows between
 *    them too, and everything else fades. Example for #3 (the booking quote):
 *      read_email -> classify -> decide_route -> booking_branch > extract_request -> check_availability
 *      -> price_stay -> quote_reply -> approval (pulsing while it waits for a person)
 *    For #7 the agent's loop lights up: agent <-> search_step, then check_agent_answer -> answer_reply.
 *  - Escape or the Close button: the panel closes.
 *
 * Where the drawing comes from: schema.json, one box per REAL node name (the same names as the step
 * log) and the graph's real edges. A backend test compares them with the compiled LangGraph graphs.
 *
 * SVG (the browser's vector drawing format): <rect> = a box, <text> = a label, <path d="M x,y V y2 H x2"> =
 * a line: M = move to, V = go down/up to y, H = go across to x. marker-end = the arrowhead at the end.
 */

// React:
import { useEffect } from "react";

// OURS:
import schema from "../schema.json";

// Who does the work in a node (its colour):
//   llm    = ONE Claude call that fills in a fixed form (classify, the two extract nodes). NOT an agent:
//            the model chooses nothing, the code decides what happens next.
//   agent  = Claude in a loop with a tool, deciding itself to search again or answer. The only agent.
//   search = Voyage + pgvector;  code = plain Python;  person = the human approval (LangGraph interrupt).
type Who = "llm" | "agent" | "search" | "code" | "person";

// One box, its position worked out: x/y = top-left corner, w/h = size, cx/cy = centre.
// Two lines inside: the node's name, and under it the note (what it does, or WHEN the path goes there).
type Box = { id: string; label: string; who: Who; note: string; x: number; y: number; w: number; h: number;
             cx: number; cy: number };

const BOX_HEIGHT = 44;
const NAME_CHAR = 7.6;            // Courier Prime at 12.5px: every letter is the same width
const NOTE_CHAR = 6.2;            // Jost italic at 12px: an average letter (proportional font)

// The boxes, computed once from schema.json.
// Shape: { "read_email": Box, "booking_branch > price_stay": Box, ... } plus the group frames, keyed by their id.
const boxes: Record<string, Box> = {};
for (const node of schema.nodes) {
  const label = node.id.split(" > ").pop() as string;           // "booking_branch > price_stay" -> "price_stay"
  const w = Math.max(100, label.length * NAME_CHAR, node.note.length * NOTE_CHAR) + 26;
  const x = "cx" in node && node.cx !== undefined ? node.cx - w / 2 : (node as { x: number }).x;
  boxes[node.id] = { id: node.id, label, who: node.who as Who, note: node.note, x, y: node.y - BOX_HEIGHT / 2, w,
                     h: BOX_HEIGHT, cx: x + w / 2, cy: node.y };
}
for (const group of schema.groups) {
  boxes[group.id] = { id: group.id, label: group.id, who: "code", note: "", x: group.x, y: group.y, w: group.w, h: group.h,
                      cx: group.x + group.w / 2, cy: group.y + group.h / 2 };
}

const isGroup = (id: string) => schema.groups.some((group) => group.id === id);

// The x of the agent's loop line (search_step -> back up to agent): just right of the wider box.
const loopX = (from: Box, to: Box) => Math.max(from.x + from.w, to.x + to.w) + 16;

// The two "bus" lines: the horizontal line above the branch frames (decide_route fans out from it)
// and the one below them (every branch joins it on the way to approval).
const FRAMES_TOP = Math.min(...schema.groups.map((group) => group.y));
const FRAMES_BOTTOM = Math.max(...schema.groups.map((group) => group.y + group.h));
const BUS_TOP = FRAMES_TOP - 18;
const BUS_BOTTOM = FRAMES_BOTTOM + 22;

/**
 * The line for one edge, as an SVG path. Four cases:
 *   decide_route -> a branch:      down to a "bus" line, across, down into the branch's frame
 *   a branch -> approval:          down out of the frame, across, down into approval
 *   back up (search_step -> agent): out to the right, up, back in from the right (the agent's loop)
 *   inside a branch:               an elbow from the parent's left side down and into the child, like a file tree
 */
function edgePath(from: Box, to: Box): string {
  if (from.id === "decide_route") {
    return `M ${from.cx},${from.y + from.h} V ${BUS_TOP} H ${to.cx} V ${to.y}`;
  }
  if (to.id === "approval") {
    return `M ${from.cx},${from.y + from.h} V ${BUS_BOTTOM} H ${to.cx} V ${to.y}`;
  }
  if (Math.abs(from.cx - to.cx) < 1) {
    return `M ${from.cx},${from.y + from.h} V ${to.y}`;                      // straight down
  }
  if (to.cy < from.cy) {
    const right = loopX(from, to);                                           // the loop back
    return `M ${from.x + from.w},${from.cy} H ${right} V ${to.cy} H ${to.x + to.w}`;
  }
  const spine = from.x + 14;
  if (to.x - spine < 6) {
    return `M ${spine},${from.y + from.h} V ${to.y}`;                       // child right below
  }
  return `M ${spine},${from.y + from.h} V ${to.cy} H ${to.x}`;              // elbow into the child
}

type Props = {
  steps: string[];                 // the selected run's step names, e.g. ["read_email", "classify", "booking_branch > price_stay", ...]
  waiting: boolean;                // the run is paused at approval
  emailSubject: string | null;     // shown in the title when a run is lit
  onClose: () => void;
};

export function SchemaPanel({ steps, waiting, emailSubject, onClose }: Props) {
  // Escape closes the panel. useEffect: add the key listener when the panel opens, remove it when it closes.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const visited = new Set(steps);
  const hasRun = steps.length > 0;
  // Is this node / frame on the run's path?
  const lit = (id: string): boolean => {
    if (id === "approval") return visited.has(id) || waiting;
    if (isGroup(id)) return steps.some((step) => step.startsWith(`${id} > `));
    return visited.has(id);
  };

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="The schema of the graph" onClick={onClose}>
      {/* stopPropagation: a click inside the sheet must not reach the overlay (which closes it). */}
      <div className="schema-sheet" onClick={(event) => event.stopPropagation()}>
        <div className="schema-head">
          <h2 className="schema-title">The schema</h2>
          <p className="schema-sub">
            {hasRun
              ? `Lit up: the path “${emailSubject ?? "this email"}” took through the graph.`
              : "Every email goes down ONE of these paths. Process an email, then open this again to see its path light up."}
          </p>
          <button className="secondary-button" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="schema-body">
          <svg viewBox={`0 0 ${schema.width} ${schema.height}`} role="img" aria-label="Graph of the email workflow">
            <defs>
              {/* The arrowheads: one plain, one red for the lit path. */}
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#963821" />
              </marker>
              <marker id="arrow-lit" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="#e03c31" />
              </marker>
            </defs>

            {/* The branch frames (subgraphs), behind everything else. */}
            {schema.groups.map((group) => {
              const on = !hasRun || lit(group.id) || (group.id === "human route" && visited.has("human_review"));
              return (
                <g key={group.id} className={on ? "schema-group" : "schema-group faded"}>
                  <rect x={group.x} y={group.y} width={group.w} height={group.h} rx={10} />
                  <text x={group.x + 12} y={group.y + 20} className="schema-group-name">{group.id}</text>
                  <text x={group.x + 12} y={group.y + 35} className="schema-group-kind">{group.kind}</text>
                  {group.id === "human route" &&
                    // The human route's explanation: SVG text doesn't wrap, so one <text> per line.
                    schema.human_note.map((line, index) => (
                      <text key={index} x={group.x + 20} y={group.y + 95 + index * 17} className="schema-note">{line}</text>
                    ))}
                </g>
              );
            })}

            {/* The arrows. Dashed = a conditional edge: a routing function in code picks ONE of them. */}
            {schema.edges.map((edge) => {
              const on = lit(edge.from) && lit(edge.to);
              const className = ["schema-edge", edge.conditional ? "conditional" : "", on ? "lit" : "", hasRun && !on ? "faded" : ""]
                .join(" ");
              return (
                <path key={`${edge.from}->${edge.to}`} d={edgePath(boxes[edge.from], boxes[edge.to])}
                      className={className} markerEnd={on ? "url(#arrow-lit)" : "url(#arrow)"} />
              );
            })}

            {/* The nodes, named as in the code. */}
            {schema.nodes.map((node) => {
              const box = boxes[node.id];
              const on = lit(node.id);
              const classes = ["schema-node", `who-${box.who}`, on && hasRun ? "lit" : "", hasRun && !on ? "faded" : "",
                               node.id === "approval" && waiting ? "paused" : ""].join(" ");
              return (
                <g key={node.id} className={classes}>
                  <rect x={box.x} y={box.y} width={box.w} height={box.h} rx={12} />
                  <text x={box.cx} y={box.cy - 4} textAnchor="middle" className="schema-name">{box.label}</text>
                  <text x={box.cx} y={box.cy + 13} textAnchor="middle" className="schema-note">{box.note}</text>
                </g>
              );
            })}
          </svg>

          <WhyThisArchitecture />
        </div>

        <div className="schema-legend">
          <span>
            <span className="legend-chip who-llm-chip" />
            <b>LLM call</b>: Claude fills in a fixed form, once (what kind of email; copy the invoice; read the
            dates). Not an agent: the code decides what happens next.
          </span>
          <span>
            <span className="legend-chip who-agent-chip" />
            <b>Agent</b>: Claude in a loop with a search tool, deciding itself to search again or answer. The only
            agent in the system.
          </span>
          <span>
            <span className="legend-chip who-search-chip" />
            <b>RAG search</b>: finds the right passages in the hotel's documents (Voyage embeddings, pgvector,
            reranker) for the agent to answer from
          </span>
          <span><span className="legend-chip who-code-chip" />plain code</span>
          <span><span className="legend-chip who-person-chip" />a person decides (LangGraph interrupt)</span>
          <span>- - - a routing function in code picks one arrow</span>
          <span>Any step that fails (except approval/action) → its error handler → a note to the front desk → approval.</span>
        </div>
      </div>
    </div>
  );
}

/**
 * Under the drawing: why the system is built this way (the decisions in CLAUDE.md, sections 3 and 6),
 * in plain words for a visitor. Each point names what you can see in the drawing above.
 */
function WhyThisArchitecture() {
  return (
    <section className="schema-why">
      <h3 className="schema-why-title">Why this architecture</h3>
      <div className="schema-why-grid">
        <article>
          <h4>A workflow, not a team of agents</h4>
          <p>
            An invoice or a booking always goes through the same steps, so <b>code decides the order</b>: the
            dashed arrows are routing functions, not a model choosing. That makes every run predictable, cheap and
            testable. A supervisor with several agents would make the order unpredictable for no gain.
          </p>
        </article>
        <article>
          <h4>One agent, only where the path is open</h4>
          <p>
            Answering a guest's question may take one search or three: nobody knows in advance. That is the
            only place where Claude decides what happens next (search again, or answer), with a limit of 4
            searches set in code. The more control the model has over the next step, the more agentic a system
            is; here it gets that control in one place only.
          </p>
        </article>
        <article>
          <h4>The model judges, code calculates</h4>
          <p>
            Claude does what needs language: reading an email, copying a messy invoice, reading dates from free
            text. Prices, availability, totals and contract checks are plain code, and replies that contain money
            or dates are fixed templates filled by code, so a number is never invented.
          </p>
        </article>
        <article>
          <h4>A person approves everything</h4>
          <p>
            Every path ends at <b>approval</b>: the graph pauses (a LangGraph interrupt), the run is saved in
            Postgres, and nothing is sent until someone approves, edits or rejects it, even after a restart.
          </p>
        </article>
        <article>
          <h4>Every claim shows its evidence</h4>
          <p>
            Each draft comes with why: the invoice lines ✓ / ⚠ / ✗, the dates as read, the document passages
            and their scores. When the answer isn't in the documents, the agent says so and the email goes to a
            person: it never makes things up.
          </p>
        </article>
        <article>
          <h4>Failures go to a person, not a crash</h4>
          <p>
            Each branch is its own subgraph, tested alone and in 10 end-to-end evals. If any step fails (a model
            timeout, an unreadable PDF), its error handler writes a note to the front desk and the run still
            reaches approval.
          </p>
        </article>
      </div>
    </section>
  );
}
