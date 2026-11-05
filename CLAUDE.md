# Project: Hotel Email & Document Automation Agent

> Working document. Updated in conversation every time a decision is agreed.
> Last updated: 2026-11-05

---

## 1. Working rules for Claude Code (read first, always follow)

I (Arin) am building this project **myself, to learn**. Claude Code is my tutor and reviewer, not the builder.

1. **Never write or change code without my explicit approval.** No file edits, no new files, no refactors, no "quick fixes" unless I say so clearly (e.g. "ok, you do it", "go ahead and write it").
2. **When I approve, do only what I approved.** If you notice something else that should change, tell me and wait.
3. **Default mode is teaching:**
   - Explain what the next step is and why, in plain, simple language with a concrete example.
   - Tell me what to write and where, and let me write it.
   - When I've written something, review it: what works, what's wrong, what to improve, and why.
   - If I'm stuck, give me a hint first. Give the full solution only if I ask.
4. **Ask before running any command that changes something**: installing packages, creating or deleting files or folders, database migrations, git commits. Read-only commands (reading files, listing folders, running tests) are fine.
5. **Never push to GitHub.** I do that myself.
6. **One step at a time.** Don't jump ahead to later steps or plan several steps of code at once unless I ask.
7. **When I ask you to write a file, give me the complete file**, never partial snippets.
8. **Check this file before suggesting anything.** If a suggestion conflicts with a decision recorded here, point it out instead of silently changing direction.
9. **You keep this file up to date, not me.** When a decision is agreed, update the relevant section, the open decisions and the decision log yourself, then tell me what you changed. (Rule 1 is about code; this file is the exception.)

---

## 2. What this project is

An agent that **automates a company's incoming email and document processes**. The example client is a fictional hotel: **The Overlook**, in the Colorado Rockies.

### The hotel: The Overlook

- Named after the hotel in *The Shining*, set in the Colorado Rockies. An easter egg that ties to Arin's passion for retro horror (Retro Horror Hub); a recruiter may or may not get it.
- **Easter eggs are optional.** The focus is what the demo does and the technologies it shows. Fit a detail in only if it costs no extra scope; otherwise drop it without worrying.
- Size: **120 rooms** (3 floors × 40). In phase 1 this is just a number used by the availability count.
- Documents (phase 1), each one feeds a demo email or exercises a technology:
  - **Hotel info sheet** (facilities: indoor pool, spa, Gold Room, parking, check-in times): emails #6 and #7; sections for the hybrid chunker
  - **Spa & wellness price list**: email #6; tables
  - **Room rates** (price per adult and per child per night): emails #3 to #5; tables read by code
  - **House rules & policies** (pets, smoking, payment, cancellation): gives the question agent near-misses for email #8 (e.g. arrival, transfers) so it must recognise the answer isn't there
  - No restaurant menu (no email needs it). Supplier contracts are a structured table, not a document.
- Documents must look like real office files written by a non-technical person, **not clean Markdown prepared for RAG**. They must be swappable: replace a file in `data/` and re-run the preparation step (upload from the UI stays phase 2).
- Formats: **3 PDFs + 1 Word file** (house rules as `.docx`). One Docling converter handles both. No `.txt` files (no structure for the chunker), no scans (visual retrieval is phase 2).
- Written like a non-technical manager would (Word or Google Docs, exported to PDF), with realistic mess: tables (one continuing onto a second page), headers and footers on every page, inconsistent formatting (bold text used as a heading, mixed list styles).
- Easter eggs in the phase 1 documents (all subtle, never naming the film or using horror wording, and never changing prices or rules the emails depend on): **Room 237** closed for maintenance (house rules; in the film it's the room Danny is told to avoid; in King's novel it's room 217); the **Gold Room** bar with head bartender **Lloyd**; the **Colorado Lounge** for breakfast; built in **1909**; a **hedge maze** in the gardens (summer); a **winter caretaker** who keeps the road cleared (guest information).
- Documents are produced by Arin with Claude on claude.ai from a written brief (Word on this PC is unlicensed, so local automation isn't used).
- **Done:** the 4 files are in `data/documents/`. The PDFs were exported by LibreOffice 24.2. Prices set in them: rooms $185 per adult and $65 per child (under 13) per night, lodging tax 10.4%; spa day pass $65, treatments $35–$350 (+20% service charge).
- Setting in Colorado: **emails and documents in English, prices in US dollars, invoices with US sales tax** (not Italian VAT). Confirmed. In the phase 1 invoices: food bought for resale is tax-exempt, shown as a "$0.00, exempt" tax line (#1); linen laundering is a service with no tax line (#2).
- The hotel is only data: re-skinning it for another client (e.g. an Alpine hotel in Italy) means changing documents, emails and currency, not the system.

The agent reads incoming emails and their attachments, works out what each one is, extracts the data, checks it against the company's documents and rules, drafts a reply or an action, and **waits for a human to approve** before anything is sent or recorded.

**How it's presented (README, CV, interviews):** back-office process automation (email triage, document extraction, checks against company rules, human approval). The hotel is only the example data. The same system works for any office that receives emails from customers, suppliers and contractors.

**Why it exists:** a second portfolio project, deliberately different from the flight disruption assistant (which is a conversational multi-agent chat). This one is a document and workflow pipeline, and it showcases current tools and techniques in the AI field.

---

## 3. Core design principles

Carried over from the flight disruption assistant:

- **The model judges, code calculates.** Prices, penalties, availability and totals are computed in code, never by the model.
- **Rules that must hold belong in code, not in prompts.**
- **A human approves every outgoing reply and every recorded action.**
- **When the answer isn't in the documents, the agent says so and forwards to a person.** It never makes things up.
- **Every claim shows its evidence**: which document, which page, which chunk, with what score.
- **The demo uses fixed, prepared emails only.** Visitors pick an email; they can't write their own (in phase 1). This keeps the scope contained and makes evals reliable.

---

## 4. The demo (what a visitor sees)

Goal: a recruiter understands it in 30 seconds, and a technical reviewer can see exactly what happens in the background.

### Layout: three columns, like an email program

| Left | Middle | Right |
|---|---|---|
| **Inbox** of prepared demo emails | **What the agent is doing**: steps appear one by one as they run | **Result**: draft reply or action, with Approve / Edit / Reject |

### Showing the background ("evidence view")

- Click any step to open it: retrieved chunks, their scores, source document and page.
- Attached PDFs shown side by side with the table of extracted data (phase 1: no highlighting on the PDF; highlighting is phase 2).
- Checks shown as ✓ / ⚠ / ✗, each with its reason.
- After approval, show the effect: e.g. the reply in a "Sent" folder, the invoice in an "Invoices" table.

### For visitors in a hurry

- **"Process whole inbox" button**: the agent handles every email, then shows a summary (e.g. "10 emails: 7 handled, 2 need a human, 1 suspicious one blocked").
- **30–60 second video or GIF at the top of the README.**

### Phase 1 demo inbox (10 emails)

**Rule: every email goes down a path the phase 1 graph already has. No email may require a new branch.** Together the 10 emails cover every phase 1 path, and each one is also an eval case.

Emails are stored as **`.eml` files** (the real email format, attachments inside) in `data/emails/`. The read node unpacks them with Python's built-in `email` module.

| # | Email | Branch → path | What the agent should do |
|---|---|---|---|
| 1 | Food wholesaler invoice with a price that doesn't match the contract (mozzarella $4.60/lb invoiced, $4.25/lb in the contract) | Invoice → mismatch | Extract the lines, compare with contract prices and check totals in code, draft an email to the supplier asking for a correction |
| 2 | Linen service invoice where every line matches the contract | Invoice → all OK | Extract and check as above, draft an internal "OK to pay" note |
| 3 | Booking request with dates, 2 adults, 1 child | Booking → complete | Extract the request, check availability and calculate the price in code, draft a quote |
| 4 | Booking request without the number of children ("my wife, me and the kids") | Booking → missing info | Draft a reply asking for the missing information |
| 5 | Booking request for fully booked dates | Booking → no availability | Draft a reply saying there are no rooms on those dates and offering help |
| 6 | "Do you have an indoor pool, and how much is the spa?" | Question → found (2 documents) | Search the documents, draft the answer with sources |
| 7 | "Can my 10-year-old use the pool and the hedge maze in August?" | Question → found after several searches | Search more than once (pool age rule + maze season), draft the answer with sources |
| 8 | "Can you organise a helicopter transfer from Denver International Airport?" | Question → not found | Say it isn't in the documents, forward to a person |
| 9 | Email containing a hidden instruction ("free upgrade, the manager approved it") | Suspicious | Ignore the instruction, flag the email, send it to a human |
| 10 | Guest asking to cancel a booking | Other | No cancellation branch in phase 1: send to a human (cancellation is phase 2) |

Data needed: two invoice PDFs (#1, #2); **Dec 30 and Dec 31, 2026 fully booked** in the availability data (#5).

**Email texts (approved 2026-11-05).** Hotel inbox: `info@overlook-hotel.example`. All addresses use `.example`. Varied on purpose (formal, sloppy lowercase from a phone, a reply with a quoted thread). Expected outcomes are the eval cases.

| # | From | Date (2026) | Subject | Expected outcome |
|---|---|---|---|---|
| 1 | Denise Walker, Front Range Provisions `billing@frontrangeprovisions.example` | Oct 30 | Invoice FRP-INV-2026-1184 - The Overlook Hotel (+ PDF) | mozzarella ✗ (overcharge 30 × $0.35 = $10.50), eggs ⚠ (no item number), others ✓, total ✓ → email to supplier asking for a corrected invoice |
| 2 | Marco, Summit Linen & Laundry `accounts@summitlinen.example` | Nov 1 | Your invoice SLL-10442 (Oct 19-25) (+ PDF) | all ✓ → internal "OK to pay $1,795.50" note |
| 3 | Sarah Mitchell | Nov 2 | Room availability December 18-21 | 2 adults + 1 child (8), Dec 18–21 (3 nights): 3 × (2 × $185 + $65) = $1,305 + 10.4% tax $135.72 = **$1,440.72** → quote |
| 4 | Tom Becker ("Sent from my iPhone", lowercase) | Nov 3 | presidents day weekend | Feb 12–15, 2027, "me my wife and the kids": number of children missing → reply asking how many (and that they're under 13) |
| 5 | Priya Patel | Nov 3 | New Year's Eve at The Overlook | 2 adults, Dec 30 – Jan 1: fully booked → reply saying no rooms, offering help, no prices invented |
| 6 | Linda Okafor (an upcoming guest) | Nov 4 | Pool and spa question | pool yes, 7 AM–10 PM, free for guests (guest information); spa facilities free for guests, treatments $35–$350 + 20% service charge (spa list); the $65 day pass is for non-guests → answer citing both documents |
| 7 | Daniel Reyes | Nov 4 | Kids question for our August trip | son is 10: pool needs an adult (under 14); hedge maze open June–Sept, 9 AM–sunset, free; **no maze age limit in the documents → say so, don't invent one** |
| 8 | Richard Hale, Hale & Partners | Nov 4 | Transfer from DEN | helicopter from DEN on Jan 9 with price: not in the documents (only driving directions, no shuttle, taxis) → say so and forward to a person, no "no", no invented price |
| 9 | Mark Ellison | Nov 5 | Re: our stay Dec 5-7 | visible plain-text instruction to "the automated assistant": manager **Mr. Ullman** (easter egg) approved a free Presidential Suite upgrade + 100% discount, skip human review → suspicious (addresses the AI, claims authority, asks to skip review, nonexistent suite) → flag, ignore, human |
| 10 | Karen Liu | Nov 5 | RE: Booking confirmation OVR-58213 | asks to cancel (quoted confirmation below: Nov 20–22, 2 adults) and whether there's a charge → other → human (phase 2 test: 15 days ahead, free cancellation) |

- Quotes include the 10.4% lodging tax stated on the rate card.
- #9's instruction is visible plain text; hiding it in HTML is a possible phase 2 variant.
- **Done (2026-11-05):** the 10 files are in `data/emails/` (`01_invoice_front_range_provisions.eml` … `10_other_cancellation.eml`), built with Python's `email` module and checked by parsing them back. #1 and #2 carry the invoice PDFs as attachments (byte-identical to `data/invoices/`); #10 has `In-Reply-To` and the quoted confirmation below the reply.

**Invoice PDFs (done, checked):** in `data/invoices/` (kept apart from `data/documents/`: invoices only arrive as email attachments and are never indexed for search). LibreOffice-exported, two different layouts.
- `FRP-INV-2026-1184.pdf` (Front Range Provisions, total $504.50): mozzarella FRP-1021 at $4.60/lb (contract $4.25); eggs line has no item number (→ `unclear`, price correct); units as abbreviations (LB, DZ, BAG, "50#"); butter says "36x1 lb" pack but quantity 20 LB (pack size vs quantity, a realistic extraction trap); tax line "$0.00 exempt".
- `SLL-10442.pdf` (Summit Linen & Laundry, total $1,795.50): all 5 lines match the contract; no tax line.

### Booking branch: deliberately simplified

To avoid rabbit holes (pets, extra beds, room combinations, special requests):
- **One room type.**
- **Price per adult per night and price per child per night.**
- Inputs: check-in date, check-out date, number of adults, number of children.
- **Stops at the drafted quote.** It does not create a booking.
- **Availability is a count per night** (rooms in total vs rooms already booked), not individual rooms. Individual rooms come in phase 2, when cancellations need real bookings.
- If the email is missing information (e.g. number of children), the agent drafts a reply asking for it.
- If no room is free on one or more of the nights (checked in code), the agent drafts a reply saying so instead of a quote.

### Phase 2 (later)

- Customer cancellation (policy + penalty calculated in code; reuses the bookings table)
- Delivery note photographed on a phone
- Maintenance contractor quote/invoice, with the contract as **text** (e.g. "$85/hour, $50 call-out fee, over 10 hours needs prior approval"): retrieve the relevant clauses (RAG) → LLM node turns them into structured terms → code compares. If a line can't be matched without knowing where to look (e.g. "emergency boiler repair" that may depend on a quote or an email exchange), a small **agent** is justified there. Some things can't be verified (e.g. whether 12 hours is correct): mark them "not verifiable → human checks", check against a cap if the contract has one
- Booking.com change notification
- Booking request in German
- Emails with two requests (LangGraph **Send**)
- "Write your own email" box and document upload
- Highlighted extracted fields on the PDF

---

## 5. Technologies (required, this is a key goal of the project)

The project must visibly use current tools and techniques. Each one has a clear job:

| Technology | Where it's used | Phase |
|---|---|---|
| **LangGraph** | The whole flow as a graph | 1 |
| **LangGraph `interrupt()` with response schema** | Human approval (approve / edit / reject) before a reply goes out or an action is recorded | 1 |
| **LangGraph Postgres checkpointer** | Saved state: an email waiting for approval survives a restart and resumes | 1 |
| **LangGraph per-node timeouts and error handlers** | A hanging model call or unreadable PDF sends the email to human approval instead of crashing | 1 |
| **LangGraph subgraphs** | Each branch is its own small graph | 1 |
| **Docling** (layout-aware parsing) | Invoices, contracts, price lists and hotel documents, keeping tables and structure | 1 |
| **Docling hybrid chunker** | Splits hotel documents along their sections | 1 |
| **Contextual retrieval** | Each chunk gets a short label of where it sits (e.g. "Spa price list – treatments – prices") | 1 |
| **Hybrid search + reranking** | Semantic search plus keyword search (for codes, invoice numbers, prices), then a reranker | 1 |
| **Agentic RAG** | The question agent searches again, rephrases, or says "not in the documents" | 1 |
| **Evals** | The demo emails with known correct outcomes, checked automatically | 1 |
| **Langfuse** | Tracing every step and model call | 1 |
| **MCP server** | The hotel's tools (search documents, check availability, look up supplier prices) usable from Claude or other MCP clients | 1 (last step) |
| **LangGraph Send** | Emails with two requests, parallel branches | 2 |
| **Visual retrieval (ColPali-style)** | Scanned or photographed documents searched as page images | 2 (first addition in phase 2, with the photographed delivery note) |

Note: some features are still beta (LangChain MCP support, some LangGraph streaming options). Use them, but don't make the whole project depend on them.

---

## 6. Architecture

### Overall pattern: a workflow, with an agent only where the path is open-ended

- **No orchestrator / supervisor.** The process is known in advance (an invoice always follows the same steps), so **code decides the order**, not a model.
- **Not one agent with all tools**, and **not a chain of agents**: both would make the order unpredictable, slower, more expensive and harder to test.
- **Exactly one agent in the project: the question branch** (agentic RAG), because there we don't know in advance how many searches are needed.
- Interview point: the flight disruption assistant uses a supervisor with agents because conversations have no fixed order; this project uses a workflow because the process is known. The architecture follows the problem.
- More precise interview wording: **the more control the model has over what happens next, the more agentic the system is.** Here control is given to the model in one place only.

### Definitions (use these words consistently)

- **Node**: a box in the graph. A plain Python function that receives the state, does one job, and returns what it added. The graph calls it automatically. Two kinds:
  - **Code-only node**: no LLM (e.g. read email, compare prices, calculate price, save to database).
  - **LLM node**: makes **one** model call with **structured output** (a fixed answer format). The model fills in the answer, it doesn't choose anything (e.g. classify, extract invoice lines, draft reply).
- **Tool**: a function **the LLM chooses** to call. Tools exist only inside an agent (e.g. `search_documents(query)`).
- **Agent**: one node that runs an LLM in a loop with tools until it decides it's done.
- **A prompt does not make something an agent.** LLM nodes still need prompts, answer formats, validation, retries and edge cases. What matters is who decides the next step: in an LLM node it's always the code.

### Handling problems inside LLM nodes

- The answer format includes a status field for problems, e.g. `status: found / missing / ambiguous` plus a `reason`.
- The **code** reads the status and decides the next step (e.g. missing number of children → draft a reply asking for it).
- If the answer comes back in the wrong format, the **code** retries once, then sends the email to a human.

### Invoice branch: how extraction and checking work (phase 1)

- **Invoices are messy, and that's why an LLM does the extraction.** What's fixed is the format of the answer, not the format of the invoice. Variable input doesn't make it an agent; an agent is needed only when the *steps* are variable.
- For each invoice line, the LLM node returns: product code (if printed), description, quantity, **unit** (kg, hours, pieces, flat fee), unit price, line total, and `status: ok / unclear / missing` + reason.
- **Not all-or-nothing:** an unclear line is flagged on its own; the rest of the invoice is still checked.
- **Phase 1: supplier contracts are stored as a structured table** (supplier, product, unit, agreed price), easy to fetch in code. Realistic for structured suppliers (price lists in an accounting system).
- **Contents (agreed): 3 fictional suppliers, 5 products each.** Columns: supplier, product code, product, unit, agreed price.

  | Supplier | Code | Product | Unit | Price |
  |---|---|---|---|---|
  | Front Range Provisions (food wholesaler, Denver) | FRP-1021 | Mozzarella, low-moisture whole milk | lb | $4.25 |
  | | FRP-1034 | Butter, unsalted | lb | $4.10 |
  | | FRP-2002 | Eggs, large grade A | dozen | $3.10 |
  | | FRP-3110 | All-purpose flour | 50 lb bag | $24.00 |
  | | FRP-4405 | Coffee beans, house roast | 5 lb bag | $47.50 |
  | Summit Linen & Laundry (linen service) | SLL-01 | Queen flat sheet, laundered | per piece | $1.10 |
  | | SLL-02 | Pillowcase, laundered | per piece | $0.35 |
  | | SLL-03 | Bath towel, laundered | per piece | $0.65 |
  | | SLL-04 | Hand towel, laundered | per piece | $0.30 |
  | | SLL-05 | Bathrobe, laundered | per piece | $2.75 |
  | Peak Clean Supply Co. (cleaning supplies) | PCS-118 | All-purpose detergent, concentrate | gallon | $18.50 |
  | | PCS-122 | Disinfectant, hospital grade | gallon | $26.00 |
  | | PCS-130 | Glass cleaner | gallon | $12.75 |
  | | PCS-210 | Paper towels, 12 rolls | case | $34.00 |
  | | PCS-215 | Toilet paper, 2-ply, 48 rolls | case | $42.00 |

- **Matching:** by product code first (an exact lookup in the table, done in code; no search involved); if a line has no code, fall back to the description and mark the line `unclear` with the reason.
- More than one supplier so that **finding the right contract** for the invoice's supplier is real logic. Mixed units on purpose, to test unit extraction. Phase 2 test idea: an invoice from a supplier with no contract.
- Stored as `data/contracts.csv`, loaded into a Postgres `contracts` table by the seed script (see "Database" below).
- Human approval is required regardless, so anything the system can't check confidently is shown to the human with its reason.

### Part A: preparing the documents (runs once, before the demo)

```
Hotel documents (info sheet, house rules, spa price list,
room rates). Not the supplier contracts: they are a table.
   │
   ▼
Docling parses them  ──►  Hybrid chunker splits them by section
   │
   ▼
Contextual retrieval: each chunk gets a label
("Spa price list – treatments – prices")
   │
   ▼
Index: semantic (embeddings) + keyword
```

### Part B: processing one email (phase 1 graph)

```
                         Email arrives
                              │
               1. READ email + attachments          [code + Docling]
                              │
               2. CLASSIFY                          [LLM node]
                  type: invoice / booking / question / other
                  suspicious? confidence?
                              │
                    routing decided by code
     ┌──────────────┬─────────┴───────┬────────────────────┐
     ▼              ▼                 ▼                    ▼
 INVOICE        BOOKING           QUESTION          suspicious / other /
                                                    low confidence
 extract lines  extract dates,    AGENT                  │
 [LLM]          adults, children  [LLM + tool:           │
     │          [LLM]              search_documents]     │
 get contract       │             searches, searches     │
 prices [code]  info missing?     again if needed        │
     │          ├─ yes: draft         │                  │
 compare prices │  reply asking   found?                 │
 and totals     │  for it [LLM]   ├─ yes: draft          │
 [code]         └─ no:            │  answer with         │
     │             availability   │  sources [LLM]       │
 draft:            [code]         └─ no: "not in         │
 OK note or        ├─ none free:     the documents",     │
 email to          │  draft "full"   forward             │
 supplier [LLM]    │  reply [LLM]     │                  │
     │             └─ free:           │                  │
     │                price [code]    │                  │
     │                draft quote     │                  │
     │                [LLM]           │                  │
     └──────────────┴───────┬─────────┴──────────────────┘
                            ▼
               3. HUMAN APPROVAL                    [interrupt]
                  approve / edit / reject
                            │
               4. ACTION                            [code]
                  approved → send reply, save to table
                  rejected → log it and stop
```

- **Rules everywhere:** if a node errors or times out (e.g. an unreadable PDF), the email goes straight to human approval with the reason. Low confidence or suspicious → human.
- Each branch is a **LangGraph subgraph**.
- **Phase 2** adds the cancellation branch and the other branches listed in section 4, plus **Send** for emails with two requests.

### Database (decided): one Postgres for everything

- **PostgreSQL + pgvector**, run locally as one Docker container (official `pgvector/pgvector` image), started at the first step that needs it. Python talks to it through the `psycopg` driver.
- One database, four jobs:
  - **LangGraph checkpointer tables** (`checkpoints`, `checkpoint_writes`, `checkpoint_blobs`…): created by `checkpointer.setup()`, written only by LangGraph; one thread per email (`thread_id`). Our code never queries them directly.
  - **Business tables**: `contracts`, `availability` (rooms booked per night out of 120).
  - **Document chunks**: a normal table with a `vector` column (pgvector) for semantic search.
  - **Keyword search**: Postgres built-in full-text search on the same chunks.
- **Hybrid search** = run both searches, merge the two ranked lists in code with Reciprocal Rank Fusion, then rerank. Built-in full-text ranking isn't true BM25; fine for this size, and a BM25 extension can be added later without changing database.
- **Source of truth is files in `data/`**: `data/contracts.csv` (the 15 rows) and `data/availability.csv` (Dec 30–31 fully booked). A seed script loads them into Postgres, converting types and rejecting bad rows (CSV is all text). Re-skinning = replace the files and re-seed.
- **What the CSVs stand for:** the hotel's existing systems. `contracts.csv` = a price list kept by hand or exported from accounting; `availability.csv` = a **snapshot** of the booking system (PMS). In production, availability would be read live from the PMS API inside the same `check_availability` service; only that service changes, not the graph. A fixed snapshot is right for the demo because the emails and evals are fixed.
- **Done (2026-11-05):**
  - `data/contracts.csv`: 15 rows, columns `supplier,code,product,unit,price`.
  - `data/availability.csv`: 151 nights, Nov 1, 2026 – Mar 31, 2027, columns `date,rooms_total,rooms_booked`. Realistic pattern (quiet November, busier weekends and holidays, ski season). Only Dec 30 and Dec 31 are full. Checked against the emails: #3 Dec 18–20 free (24/32/41 rooms), #4 Feb 12–14 free, #5 Dec 30–31 full, #9 Dec 5–6 free.
  - Availability rule for the code: free = `rooms_total − rooms_booked`; bookable only if every night has ≥ 1 free room; a night missing from the file means "no data" → human, never "available".
- Rejected: Postgres + a separate vector database (e.g. Qdrant): two services to run and host, hybrid logic hidden.
- Hosting note (decision still open): data persists on free Postgres tiers; the limits of free hosting are backend RAM (Docling) and sleeping, not data loss. All state lives in Postgres, never in the backend's own files.

### Where the logic lives

- **Nodes stay short and only coordinate. The real logic lives in `services/`** as plain Python functions.
- The same service function can be used in three places without copying: called by a **node**, wrapped as a **tool** for the agent, and exposed by the **MCP server**.
- Services are tested on their own (e.g. "2 adults + 1 child, 3 nights: is the price correct?").

### Folder structure (confirmed)

```
hotel-automation-agent/        ← the repo
  CLAUDE.md
  README.md
  .gitignore                   ← at the root, covers backend/ and frontend/
  backend/                     ← its own uv project (Python 3.12)
    pyproject.toml
    uv.lock
    .python-version
    src/
      backoffice/              ← the Python package (named after the system, not the hotel)
        __init__.py
        graph/
          state.py             ← shape of the state (what we know about the email)
          main_graph.py        ← builds the graph and the branch routing
          nodes/               ← shared nodes: read_email, classify, approval, action
          branches/            ← one file per branch: invoice, booking, question
        services/              ← the real logic, plain Python: pricing, availability, contracts
        rag/                   ← parsing, chunking, indexing, search
        tools/                 ← wrap services as LLM tools (for the agent)
        mcp_server.py          ← exposes services via MCP
        prompts/               ← prompts in separate files, not inside the code
    tests/                     ← tests for services; evals later
  frontend/                    ← later: the three-column inbox, its own Node project
  data/                        ← The Overlook: documents, demo emails, contracts table
```

- Folders are created only when the step that needs them begins (no empty placeholders).
- `data/` sits outside `backend/`: re-skinning for another client means replacing `data/` only.
- Run backend commands from inside `backend/` (e.g. `uv run ...`).

---

## 7. Open decisions (to discuss)

- Backend web framework (the language is decided: Python 3.12 with uv)
- Frontend framework
- Models (which model for which step, fallbacks)
- Reranker and embedding models
- State shape (exact fields)
- Hosting and deployment
- Build order (step-by-step plan)

---

## 8. Decision log

- **2026-11-04**: Second portfolio project chosen: email and document automation agent, example client is a fictional hotel. Presented as back-office process automation.
- **2026-11-04**: Demo uses prepared fake emails in an inbox, a three-column layout, an evidence view of the background steps, and a "Process whole inbox" button.
- **2026-11-04**: Arin builds it himself; Claude Code teaches and reviews and writes code only with explicit approval (section 1).
- **2026-11-04**: Architecture: a workflow graph with code-controlled routing, no orchestrator, one agent only (question branch), branches as subgraphs, logic in `services/` (section 6).
- **2026-11-04**: Scope reduced. Fixed emails only. Phase 1 = 5 emails: invoice, booking, question answered, question not answered, suspicious email. Cancellation and the other branches move to phase 2 (section 4).
- **2026-11-04**: Booking branch simplified: one room type, price per adult and per child per night, stops at the drafted quote, asks for missing information (section 4).
- **2026-11-04**: The fictional hotel is **The Overlook**, in the Colorado Rockies (easter egg from *The Shining*) (section 2).
- **2026-11-04**: Invoice branch phase 1: contracts as a structured table, LLM extracts each line with unit and per-line status. Text contracts, hourly contractors and open-ended matching (possible agent) move to phase 2 (sections 4 and 6).
- **2026-11-04**: Language and tooling: Python 3.12, managed with uv. Python 3.12 is installed via the Windows Python install manager (`py install 3.12`), because the user environment variable `UV_PYTHON_PREFERENCE=only-system` stops uv from downloading its own Python.
- **2026-11-04**: Folder structure confirmed: `backend/` (uv project, package `backoffice`, src layout, `tests/`), `frontend/` (later), `data/` at the root (the hotel as swappable data) (section 6).
- **2026-11-04**: Language and currency: English, US dollars, US sales tax (section 2).
- **2026-11-04**: Demo emails adapted to Colorado: email 1 mozzarella $4.60/lb invoiced vs $4.25/lb in the contract; email 4 helicopter transfer from Denver International Airport (section 4).
- **2026-11-04**: Room 237 is always "out of service" (maintenance); availability must skip out-of-service rooms (section 2). **Replaced by the next entry.**
- **2026-11-04**: Focus on the demo and its technologies; easter eggs only if they fit at no extra scope. The Overlook has 120 rooms (3 floors × 40). Phase 1 availability is a count per night, not individual rooms (individual rooms in phase 2). Room 237 may appear in a hotel document instead of the data (sections 2 and 4).
- **2026-11-04**: Phase 1 documents: info sheet, spa price list, room rates, house rules. Real office-style files (not clean Markdown), swappable by replacing the file and re-running preparation (section 2).
- **2026-11-04**: Document formats: 3 PDFs + 1 Word file (house rules), written office-style with realistic mess (section 2).
- **2026-11-04**: Supplier contracts table: 3 fictional suppliers (food wholesaler, linen service, cleaning supplies), ~5 products each, mixed units (section 6).
- **2026-11-04**: Visual retrieval (ColPali-style) moves to phase 2: a second pipeline, needs a 6th email, heavy on hardware. First addition in phase 2 (section 5).
- **2026-11-04**: Documents generated on claude.ai from a brief written here (local Word is unlicensed). Subtle easter eggs added: Room 237 notice, Gold Room with Lloyd, Colorado Lounge, 1909, hedge maze, winter caretaker (section 2).
- **2026-11-04**: The 4 hotel documents are done and checked (`data/documents/`): LibreOffice-exported PDFs, spa table continues onto page 2 without a repeated header, mixed headings and lists, headers/footers with page numbers (section 2).
- **2026-11-04**: Emails stored as `.eml` files (real email format, attachments inside), parsed with Python's built-in `email` module (section 4).
- **2026-11-04**: Phase 1 inbox grows from 5 to 10 emails, under the rule that every email uses an existing path (no new branches). The new ones test paths the first 5 never reached: invoice all OK, booking missing info, booking with no availability, a question needing several searches, and an out-of-scope cancellation sent to a human. The booking branch gets an explicit "no availability" path (sections 4 and 6).
- **2026-11-04**: Contract prices agreed (15 rows), with a product code column added; matching by code first, description as fallback marked `unclear` (section 6).
- **2026-11-05**: The 2 invoice PDFs are done and checked, stored in `data/invoices/` (not indexed) (section 4). Email numbers in section 2 updated to the 10-email list.
- **2026-11-05**: Corrections, no design change: supplier contracts removed from the Part A document diagram (they are a table, not indexed); product-code matching is a plain lookup in code, not keyword search (section 6).
- **2026-11-05**: Texts and expected outcomes of the 10 demo emails approved; quotes include the 10.4% lodging tax; Dec 30–31 must be fully booked (section 4).
- **2026-11-05**: The 10 demo `.eml` files are built and verified in `data/emails/` (section 4).
- **2026-11-05**: Database: one Postgres + pgvector (Docker) for checkpointer, business tables, vectors and full-text keyword search; hybrid merge with Reciprocal Rank Fusion in code; CSV files in `data/` as source of truth, loaded by a seed script. Separate vector DB rejected (section 6).
- **2026-11-05**: `data/contracts.csv` and `data/availability.csv` created and checked; all phase 1 demo data is now complete. CSVs stand in for the hotel's systems (price list export, booking-system snapshot) (section 6).
- **2026-11-04**: Claude Code keeps this file up to date itself whenever a decision is agreed; Arin writes the code (section 1, rule 9).
