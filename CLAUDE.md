# Project: Hotel Email & Document Automation Agent

> Working document. Updated in conversation every time a decision is agreed.
> Last updated: 2026-11-06

---

## 1. Working rules for Claude Code (read first, always follow)

I (Arin) own this project and its design. I'm job hunting and interviews focus on **architecture**, so my time goes into understanding and deciding the design; **Claude Code writes the code** (changed 2026-11-06; until then I wrote it myself).

1. **Agree the design before writing code.** Explain what the next piece does, why, and how it fits the architecture; once I agree, write it. Don't ask whether I want to write it myself.
2. **Do only what was agreed.** If you notice something else that should change, tell me and wait.
3. **Explain everything you write so I can defend it in an interview:**
   - What each function/module does, its inputs and outputs, and why it's designed that way (trade-offs, alternatives rejected).
   - A concrete example from the demo data.
   - Keep my names and style when editing code I wrote; only change what's needed, and say why.
   - Write tests for what you build, and run them.
4. **Ask before running any command with lasting side effects outside the code**: installing packages, deleting files or folders, database migrations, git commits. Creating and editing code and test files for an agreed piece is fine. Read-only commands (reading files, listing folders, running tests) are fine.
5. **Never push to GitHub.** I do that myself.
6. **One step at a time.** Don't jump ahead to later steps or plan several steps of code at once unless I ask.
7. **When I ask you to write a file, give me the complete file**, never partial snippets.
8. **Check this file before suggesting anything.** If a suggestion conflicts with a decision recorded here, point it out instead of silently changing direction.
9. **You keep this file up to date, not me.** When a decision is agreed, update the relevant section, the open decisions and the decision log yourself, then tell me what you changed.

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
| 5 | Priya Patel | Nov 3 | New Year's Eve at The Overlook | 2 adults, Dec 30 – Jan 1: fully booked (Dec 30, 31) → reply saying so and suggesting the 3 closest 2-night alternatives found in code: **Dec 28–30, Jan 1–3, Dec 27–29**; no prices invented |
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
- **Alternative dates (code, not the model):** a service tries stays of the **same length** starting 1 to 7 days earlier or later, closest first (−1, +1, −2, +2 … −7, +7), checks each with `check_availability`, and keeps only `AVAILABLE` ones (a candidate with any full or missing night is simply skipped). At most 3 suggestions; never a start before today (today is passed in). None found → "please contact our reservations team". The LLM only writes the reply from this list, so it can't invent dates.

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
| **Vector search + reranking** | Semantic (vector) search on label + text, then a reranker. Keyword/hybrid search dropped 2026-11-10 (see decision log) | 1 |
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
- Stored as `data/supplier_prices.csv` (named for what it is: agreed prices per supplier and product, not the contract documents), loaded into a Postgres `supplier_prices` table by the seed script (see "Database" below). Checked by `services/invoice_check.py` (dataclass `SupplierPrice`).
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

- **Embeddings: Voyage AI, model `voyage-4`** (1024 dimensions; $0.06 per 1M tokens, 200M free tokens for new accounts; the balanced option between `voyage-4-large` and `voyage-4-lite`, all three compatible; decided 2026-11-10). `input_type="document"` for chunks, `"query"` for questions. API; Anthropic's recommended embedding provider. Called in two moments only: (1) **preparation**, once per run, to embed every chunk (re-run only when a document changes); (2) **each search** (step 7 onward), to embed the question, one small call, so it can be compared with the stored chunk vectors. Documents are never re-embedded per question. Chosen over a local open-source model to keep the backend light for hosting; Voyage also offers rerankers (candidate for step 7).
- **Parsing (6.1, `backoffice/rag/parsing.py`)**: one Docling `DocumentConverter` for all files (`parse_documents`). First run ~5 min (downloads layout/table models), later runs seconds. What Docling made of the messy documents:
  - ✓ Page headers/footers recognised as "furniture" and kept out of the body (won't pollute chunks).
  - ✓ In PDFs, bold-text headings ("Getting here", "The Gold Room", "Hedge maze") are detected as headings, like real ones.
  - ⚠ PDFs lose heading **levels**: every heading is level 1 ("Indoor pool" is not nested under "Facilities").
  - ⚠ In the Word file, the hand-numbered bold sections ("1. Smoking" … "9. Children") are plain text, not headings; only "5. Cancellation policy" (a real Heading 1) and "Fees at a glance" are headings. Sections 6–9 therefore sit under "5. Cancellation policy" structurally.
  - ⚠ The spa table that continues onto page 2 comes out as **two tables**; the second has no column headers (its first row, "BODY TREATMENTS", acts as header).
  - Word files have no pages: chunks from the `.docx` can cite their section, not a page number.
  - These are exactly the realistic problems the documents were built to have; how far to fix them in code is decided in 6.2, after seeing the chunks. Contextual labels (below) are the main answer to missing structure.
- **Chunking (6.2, `backoffice/rag/chunking.py`)**: Docling `HybridChunker`, 256-token limit (tokenizer `sentence-transformers/all-MiniLM-L6-v2`, used only to measure length), `merge_peers=True`. Output converted to our own `Chunk` dataclass (document, index, headings, text, pages): the adapter pattern, so only this file depends on Docling. First run: 21 chunks. Findings: guest information perfect (one chunk per section, so the flattened heading levels don't matter → LLM heading-level fix skipped); house rules mixed (sections 6–9 inside "Cancellation policy"); spa table chunks broken (second table with anonymous "1 =" / "2 =" columns; a row cut mid-way, orphaning "$135").
- **Cleanup before chunking (`backoffice/rag/cleanup.py`)**, rules that change structure only, never text:
  - **Fix 1 (done):** `promote_numbered_headings`: a plain paragraph that is bold, under 60 characters and starts with "N. " becomes a level-1 heading. House rules: 8 headings promoted, 3 mixed chunks → 11 clean ones ("7. Transportation" is its own chunk). Known side-effect: the "Fees at a glance" table (a real level-2 heading) now sits under "9. Children"; left for the contextual labels to describe correctly.
    - **Limitation (kept on purpose, decided 2026-11-10):** the rule encodes one way of faking headings (bold + numbered). It misses unbolded/unnumbered headings and can misfire on bold numbered lines that aren't headings. Fine for the demo (fixed documents, deterministic, tested). **Production alternatives, for the README/interviews:** (a) Arin's more general rule: a standalone item that is short (≤ ~6 words), doesn't end with a full stop, and is followed by a longer paragraph; (b) an LLM structure pass: the model gets the short lines and returns which are headings and their level (structured output), code applies it, text never rewritten ("model judges, code applies"). Safety nets either way: contextual labels + retrieval evals.
  - **Fix 2 (done):** `stitch_continued_tables`: table B is the continuation of table A when B directly follows A in reading order, starts on the next page, has the same number of columns and no header row; B's cells are appended below A's (row numbers shifted), A's provenance gains B's page, B is deleted. Spa list: 2 tables → 1 table of 27 rows on pages [1, 2]; the second half now reads "Rocky Mountain clay wrap, Duration = 80 min" instead of "1 = 80 min". Same limitation style as fix 1 (a rule for a known pattern).
  - **Fix 3 (done, in `chunking.py`):** tables written as compact Markdown rows (`MarkdownTablesProvider` → `MarkdownTableSerializer`, `compact_tables=True`) instead of Docling's default `TripletTableSerializer` ("Swedish massage, Duration = 50 min. Swedish massage, Price = $145."); `repeat_table_header=True`. The spa table (27 rows, ~330 tokens) is now cut between rows into 2 pieces, each starting with "| Treatment | Duration | Price |"; no orphaned prices.
  - **Result after all three fixes: 28 chunks** (guest information 10, house rules 11, room rates 2, spa 5), 81 tests passing. Small leftovers, left for the labels / not worth rules: PDF text keeps HTML escapes ("House Rules &amp; Policies"); the EXTRAS section of the spa table is split across the 2 pieces ("Private sauna" sits in the second piece without its "EXTRAS" row).
- **Contextual labels: Claude Haiku 5.5** (`claude-haiku-5-5`, $0.10 / $0.50 per 1M tokens; decided 2026-11-10). A simple, one-off task (~50 short labels): "right model for the job" rather than the most capable one. Each document is sent once per chunk with prompt caching, as in Anthropic's contextual-retrieval recipe.
- **Labels (6.3, `backoffice/rag/contextual_chunk_labels.py`)**: official Anthropic SDK; `ANTHROPIC_API_KEY` read via `config.py` (`SecretStr`, optional so DB-only code works without it). One call per chunk: system prompt (rules: one line ≤ 30 words, start with the document kind, name the section and topic, use guest search words, no prices/numbers, no new facts) + `<document>` block marked `cache_control` + `<chunk>` block; `effort: low`, `max_tokens` 1024. `Chunk` gained `label: str = ""` (filled via `dataclasses.replace`, the text never changes). Tests use a fake client (no cost).
  - **First real run (28 chunks):** prompt caching worked for all 4 documents (1 cache write per document, then reads; the 646-token rate card is above Haiku's 512-token minimum). Total cost ≈ **$0.002**. Labels are good, e.g. "House rules: section 7 Transportation … hotel offers no shuttle service, front desk provides local taxi numbers"; "Spa price list 2026, Treatments table: extras such as private sauna and spa packages …"; the fees table is correctly described as "following the Children section". Minor rule slips: some labels keep small numbers ("minimum age 16", "under-14s") and one adds a word not in the chunk ("airport shuttle"). Acceptable for search; the agent answers from the chunk text, never from the label.
  - Labels are stored in 6.4 (with the embeddings). They are non-deterministic: each indexing run may word them slightly differently.
- **Embeddings + saving (6.4)**:
  - `backoffice/rag/embeddings.py`: `make_voyage_client()` (`VOYAGE_API_KEY` via `config.py`), `embedding_input(chunk)` = label + headings + text, `embed_documents()` (`input_type="document"`, batches of 64), `embed_query()` (`input_type="query"`, for step 7).
  - `schema.sql`: table `chunks` (id, document, chunk_index, headings `TEXT[]`, text, pages `INTEGER[]`, label, embedding `vector(1024)`, `search_text tsvector GENERATED ALWAYS AS (to_tsvector('english', label || ' ' || text)) STORED`, unique (document, chunk_index)); HNSW index (cosine) on embedding, GIN index on search_text.
  - `backoffice/rag/index_documents.py`: the whole preparation in one command, `uv run python -m backoffice.rag.index_documents` (parse → cleanup → chunk → label → embed → save; one transaction: TRUNCATE + insert; idempotent). Re-run after changing a document.
  - **Result:** 28 chunks indexed (10 + 11 + 2 + 5), all 1024-dim. First taste of search: the email #7 question ("Is the hedge maze open in August, and can kids use the pool alone?") returns Hedge maze (0.53), 9. Children (0.40), Indoor pool (0.39) as the top 3 by vector similarity; keyword search finds "shuttle" in "7. Transportation" and finds no chunk at all for "helicopter" (email #8's signal).
  - Tests: fake Voyage client; database test inside `conn.transaction(force_rollback=True)` so the real index is never touched. 90 tests pass.

### Search (step 7, `backoffice/rag/search.py`)

- `search_documents(conn, voyage, question, candidates=8, keep=4) -> list[SearchResult]`: (a) `embed_query` (Voyage, `input_type="query"`) → (b) `vector_candidates`: `ORDER BY embedding <=> %s::vector LIMIT 8` (pgvector cosine distance; similarity reported as 1 − distance) → (c) `rerank`: Voyage `rerank-3-lite` on label + headings + text of the 8, keeps 4, best first. Connection and client passed in (testable, reusable by the agent).
- `SearchResult`: chunk_id, document, headings, pages, label, text, vector_similarity, rerank_score: everything the evidence view needs.
- **Real results:** #6 → Access to spa facilities 0.77, Indoor pool 0.66, Treatments 0.57, Spa 0.54. #7 → Hedge maze 0.66, 9. Children 0.64, Indoor pool 0.58 (then a clear drop to 0.39). #8 (helicopter) → best only 0.42 (Getting here, 7. Transportation): the "probably not in the documents" signal for the agent.
- Tests: fake Voyage + fake chunks in a rolled-back transaction (proves vector search shortlists and the reranker can overturn the vector order); live tests on the real index run only with `RUN_LIVE_TESTS=1` (paid API).

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
  - **Business tables**: `supplier_prices`, `availability` (rooms booked per night out of 120).
  - **Document chunks**: a normal table with a `vector` column (pgvector) for semantic search.
  - **Keyword search**: Postgres built-in full-text search on the same chunks.
- **Hybrid search** = run both searches, merge the two ranked lists in code with Reciprocal Rank Fusion, then rerank. Built-in full-text ranking isn't true BM25; fine for this size, and a BM25 extension can be added later without changing database.
- **Source of truth is files in `data/`**: `data/supplier_prices.csv` (the 15 rows) and `data/availability.csv` (Dec 30–31 fully booked). A seed script loads them into Postgres, converting types and rejecting bad rows (CSV is all text). Re-skinning = replace the files and re-seed.
- **What the CSVs stand for:** the hotel's existing systems. `supplier_prices.csv` = a price list kept by hand or exported from accounting; `availability.csv` = a **snapshot** of the booking system (PMS). In production, availability would be read live from the PMS API inside the same `check_availability` service; only that service changes, not the graph. A fixed snapshot is right for the demo because the emails and evals are fixed.
- **Done (2026-11-05):**
  - `data/supplier_prices.csv` (originally `contracts.csv`): 15 rows, columns `supplier,code,product,unit,price`.
  - `data/availability.csv`: 151 nights, Nov 1, 2026 – Mar 31, 2027, columns `date,rooms_total,rooms_booked`. Realistic pattern (quiet November, busier weekends and holidays, ski season). Only Dec 30 and Dec 31 are full. Checked against the emails: #3 Dec 18–20 free (24/32/41 rooms), #4 Feb 12–14 free, #5 Dec 30–31 full, #9 Dec 5–6 free.
  - Availability rule for the code: free = `rooms_total − rooms_booked`; bookable only if every night has ≥ 1 free room; a night missing from the file means "no data" → human, never "available".
- **How it's built (step 5):**
  - `docker-compose.yml`: image `pgvector/pgvector:pg17`, container `overlook-db`, named volume `overlook-db-data`, healthcheck. **Host port 5433** (5432 is used by another local project, `polyant-postgres`). Credentials in `.env` (random local password, git-ignored); `.env.example` is the template.
  - `backoffice/config.py`: `Settings` (pydantic-settings) reads `DATABASE_URL` from the environment or `.env` (works from the repo root and from `backend/`).
  - `backoffice/db/connection.py`: `connect()`, used in a `with` block (commit / rollback / close); `connect_timeout=5` so a stopped database fails fast instead of hanging (Windows).
  - `backoffice/db/schema.sql` + `schema.py`: `CREATE EXTENSION vector`, tables `supplier_prices` (PK supplier+code, `NUMERIC(10,2)`, price ≥ 0) and `availability` (PK night, counts ≥ 0; overbooking allowed). Idempotent (`IF NOT EXISTS`). No migrations tool (Alembic) yet: overkill for two tables.
  - `backoffice/db/seed.py`: reads the CSVs (`utf-8-sig`, so Excel files with a BOM work), validates every row and collects **all** problems with line numbers (missing values, bad numbers/dates, negative prices, > 2 decimals, duplicates, gaps; overbooking = warning), then loads in **one transaction** (schema, `TRUNCATE`, inserts). Idempotent. Run: `uv run python -m backoffice.db.seed`.
  - `backoffice/db/queries.py`: `load_supplier_prices(conn, supplier=None) -> list[SupplierPrice]`, `load_nights(conn, start, end) -> dict[date, NightAvailability]` (start included, end excluded). `%s` placeholders only (no SQL injection). **The services are unchanged**: this data-access layer produces exactly their input types.
  - Rows come back from psycopg as a list of tuples by default (`NUMERIC` → `Decimal`, `DATE` → `date`).
- Rejected: Postgres + a separate vector database (e.g. Qdrant): two services to run and host, hybrid logic hidden.
- Hosting note (decision still open): data persists on free Postgres tiers; the limits of free hosting are backend RAM (Docling) and sleeping, not data loss. All state lives in Postgres, never in the backend's own files.

### Where the logic lives

- **Nodes stay short and only coordinate. The real logic lives in `services/`** as plain Python functions.
- The same service function can be used in three places without copying: called by a **node**, wrapped as a **tool** for the agent, and exposed by the **MCP server**.
- Services are tested on their own (e.g. "2 adults + 1 child, 3 nights: is the price correct?").

### Code conventions (agreed)

- **Types live next to the function that produces them** (e.g. `StayPrice` in `pricing.py`, `AvailabilityResult` in `availability.py`), not in one big `models.py`. Move a type to a shared module only when a second module needs it (e.g. the graph state in `graph/state.py`, LLM answer formats). `services/__init__.py` may re-export names for shorter imports.
- **Pydantic at the edges, dataclasses inside.** Data from outside (LLM structured output from step 8, API requests and responses from step 15, config) uses Pydantic models: validation and JSON. Data passed between our own functions uses plain `dataclass`es: already checked at the edge, no silent conversion.
- **Money is `Decimal`**, created from strings, rounded to cents with `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`; never `float`.
- **Fixed sets of values are `StrEnum`s** (e.g. `AvailabilityStatus`), not loose strings.
- **`ValueError` for impossible input** (e.g. check-out before check-in); **a status for real-world outcomes** the graph routes on (e.g. `full`, `no_data`).
- Services receive their data as arguments (no file or database reads inside), so tests build small inputs by hand. Function and variable names in snake_case.
- **Shape comments (requested by Arin, 2026-11-06):** whenever code builds or returns a non-trivial structure (lists of tuples, dicts of objects, nested data), add a comment just before it showing its shape with a short concrete example from the demo data, e.g. `# Shape returned: dict, key = date, value = NightAvailability` followed by 2–3 example entries and `...`. Applies to all new code; older files get them when they are next edited. **This includes objects that come IN from libraries**, not just what our functions return: e.g. a `DoclingDocument` (`doc.texts`, `doc.tables`, cells), what `enumerate(...)` / `zip(...)` / `iterate_items()` produce, and `model_dump()` dictionaries, shown with real values from the demo data. A module working on a library object starts with a reference block showing that object's shape (see `rag/cleanup.py`).
- **Explain library terms in the code (requested by Arin, 2026-11-10):** every class, method or parameter that comes from a library (e.g. Docling's `HybridChunker`, `chunk(dl_doc=...)`, `DocChunk`, Pydantic's `model_validate`) gets a plain-language comment saying what it is and why it's used. In chat, explain each such term before using it; never leave `(...)` placeholders or vague phrases like "plus tables". Go one concept at a time.

### Folder structure (confirmed)

```
hotel-automation-agent/        ← the repo
  CLAUDE.md
  README.md
  .gitignore                   ← at the root, covers backend/ and frontend/
  docker-compose.yml           ← local Postgres + pgvector (container overlook-db, host port 5433)
  .env.example                 ← template for .env (real .env is git-ignored)
  backend/                     ← its own uv project (Python 3.12)
    pyproject.toml
    uv.lock
    .python-version
    src/
      backoffice/              ← the Python package (named after the system, not the hotel)
        __init__.py
        graph/
          state.py             ← shape of the state (EmailState, ParsedEmail, Attachment, Classification)
          main_graph.py        ← builds and runs the graph (START HERE to read the flow)
          nodes/               ← shared nodes: read_email, classify, decide_route; approval, action (step 9)
          branches/            ← placeholders.py now; one file per branch from steps 10–12
        config.py              ← settings (DATABASE_URL, API keys) read from .env with pydantic-settings
        llm.py                 ← the shared Anthropic client
        db/                    ← connection, schema.sql + schema.py, seed.py (CSV → tables), queries.py (tables → service types)
        services/              ← the real logic, plain Python: pricing, availability, invoice_check
        rag/                   ← parsing.py, cleanup.py, chunking.py, contextual_chunk_labels.py, embeddings.py, index_documents.py; search (step 7)
        tools/                 ← wrap services as LLM tools (for the agent)
        mcp_server.py          ← exposes services via MCP
        prompts/               ← prompts in separate files, not inside the code (classify_system.md)
    tests/                     ← tests for services; evals later
  frontend/                    ← later: the three-column inbox, its own Node project
  data/                        ← The Overlook: documents, invoices, demo emails, supplier prices, availability
```

- Folders are created only when the step that needs them begins (no empty placeholders).
- `data/` sits outside `backend/`: re-skinning for another client means replacing `data/` only.
- Run backend commands from inside `backend/` (e.g. `uv run ...`).

---

## 7. Build order (phase 1)

Rules: inside out (plain logic → graph → interface); every step ends with something runnable and tested, and is a natural commit point; each open decision is made at the step that first needs it; each branch is tested on its own demo emails as it's built.

| # | Step | What gets built | Decision made here | Demo emails |
|---|---|---|---|---|
| 1 | ✅ Setup | Python 3.12 + uv, `backend/` package, Git | | |
| 2 | ✅ Demo-data decisions | Language, hotel, documents, suppliers, emails, database | | |
| 3 | ✅ Demo data | 4 documents, 2 invoices, 10 `.eml`, 2 CSVs | | |
| 4 | ✅ Services + tests | `services/pricing.py` (stay price with tax), `services/availability.py` (availability + alternative stays), `services/invoice_check.py` (unit normalisation, lookup by code / description, line check, totals check); 45 `pytest` tests. No AI, no database (data passed in) | | numbers behind #1–#5 |
| 5 | ✅ Postgres + seed | Postgres + pgvector in Docker (port 5433), `config.py`, `db/` (connection, schema, seed with validation, queries); services unchanged, fed by the data-access layer; 69 tests (8 need the database, skipped when Docker is off) | | |
| 6 | ✅ Document preparation (Part A) | `rag/`: parsing (Docling), cleanup (2 rules), chunking (HybridChunker, Markdown tables), contextual labels (Haiku 5.5), embeddings (Voyage `voyage-4`), `index_documents.py` → `chunks` table (vector + full-text). 28 chunks; 90 tests | Embedding model (Voyage `voyage-4`); labels (Haiku 5.5) | |
| 7 | ✅ Search | `rag/search.py`: `search_documents(conn, voyage, question)` = embed question (Voyage) → pgvector top 8 (cosine) → rerank (Voyage `rerank-3-lite`) → best 4, each a `SearchResult` with document, headings, pages, label, text, vector_similarity, rerank_score. No keyword search (dropped). 92 tests + 3 live tests (`RUN_LIVE_TESTS=1`) | Reranker: `rerank-3-lite` ✅ | #6–#8 (search only) |
| **8** | **Graph skeleton + tracing** ← **next** | State, read node (`.eml` + attachments), classify node, code routing, empty branches; Langfuse from here on | State shape; models | all 10 (classification) |
| 9 | Human approval + checkpointer | `interrupt()` approve / edit / reject, Postgres checkpointer, action node; before the branches so each ends properly | | #9, #10 |
| 10 | Booking branch | Subgraph: extract → missing info → availability → price → quote or "full" reply | | #3, #4, #5 |
| 11 | Invoice branch | Subgraph: extract lines → contract lookup → compare → draft | | #1, #2 |
| 12 | Question branch (the agent) | Agentic RAG: search tool, search again, "not in the documents" | | #6, #7, #8 |
| 13 | Robustness | Per-node timeouts, error handlers, retry once on bad format → human | | broken-input tests |
| 14 | Evals | All 10 emails automatically against expected outcomes, score report | | all 10 |
| 15 | Backend API | List emails, process one, stream steps, approve | Backend web framework | |
| 16 | Frontend | Three-column inbox, evidence view, "Process whole inbox" | Frontend framework | all 10 |
| 17 | MCP server | Exposes the services (search, availability, supplier prices) | | |
| 18 | Deploy + README | Hosting, README, GIF | Hosting | |

**Deadline: Sunday 15 or Monday 16 November 2026**: everything on GitHub and on Arin's portfolio website. Full scope kept (decided 2026-11-10, after a proposal to cut Langfuse, MCP, FastAPI + React and hosting was rejected: Claude Code writes the frontend, a Langfuse account already exists). Only hybrid search is dropped.

Why this order: search (6–7) is tested on its own before the graph, because RAG is the hardest part to debug; approval (9) comes before the branches so each branch is complete when written; Langfuse comes in at 8, as soon as LLM calls exist.

---

## 8. Open decisions (to discuss)

Each is made at its step in section 7.

- Models for the later LLM nodes (extraction, drafting) and the question agent: decide at their steps (10–12). Arin's leaning: Haiku 5.5 wherever it's good enough. Classify is decided (Haiku 5.5).
- Backend web framework (step 15; the language is decided: Python 3.12 with uv)
- Frontend framework (step 16)
- Hosting and deployment (step 18)

---

## 9. Decision log

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
- **2026-11-05**: Build order agreed (18 steps, steps 1–3 done, next is step 4: services + tests). Open decisions each tied to the step that needs them. New section 7; open decisions and decision log renumbered to 8 and 9.
- **2026-11-06**: Code conventions agreed: types next to the function that produces them; Pydantic at the edges, dataclasses inside; `Decimal` for money; `StrEnum` for fixed values; `ValueError` for impossible input vs a status for real-world outcomes (section 6). Step 4 progress: pricing and availability services done with 12 passing tests.
- **2026-11-06**: "No availability" replies suggest up to 3 alternative stays of the same length within ±7 days, closest first, found in code by reusing `check_availability`; otherwise "contact reservations". Email #5's expected outcome updated (section 4).
- **2026-11-06**: `data/contracts.csv` renamed to `data/supplier_prices.csv` (and the future table to `supplier_prices`): it holds agreed prices, not contracts. Invoice line checks go in `services/invoice_check.py`; skeleton created, Arin completes it (section 6).
- **2026-11-06**: Working mode changed: Arin focuses on architecture and design decisions (job hunting, interviews are architecture-heavy); Claude Code writes the code after the design is agreed, explains it at interview level, and writes and runs the tests (section 1).
- **2026-11-06**: Step 4 done: pricing, availability (with alternative stays) and invoice checks (lines + totals) in `services/`, 45 passing tests. Next: step 5, Postgres + seed (section 7).
- **2026-11-06**: New convention: shape comments with concrete examples before non-trivial returns and structures (section 6, code conventions). Added to `db/queries.py`.
- **2026-11-09**: Step 5 done: Postgres + pgvector in Docker (host port 5433), schema, validated seed (one transaction, idempotent, Excel BOM handled), data-access queries; `connect_timeout=5` added after tests showed a stopped database hung forever on Windows. 69 tests pass (8 database tests skip when Docker is off). Next: step 6, document preparation (section 7).
- **2026-11-10**: Embeddings: Voyage AI API (option A) rather than a local open-source model: Anthropic-recommended, keeps the backend light for hosting, same provider can rerank in step 7 (section 6, Part A).
- **2026-11-10**: Contextual labels written by Claude Haiku 5.5: simple one-off task, fixed demo data, cost of larger models not justified. Models for the graph's LLM nodes and the agent still decided at step 8 (Arin leans towards Haiku where it's good enough) (section 6, Part A).
- **2026-11-10**: Step 6.3 done (Haiku contextual labels, ≈ $0.002 for 28 chunks, caching verified). 6.4 design agreed: Voyage `voyage-4` (1024 dims), a `chunks` table (arrays for headings/pages, `vector(1024)`, generated `tsvector` for keyword search, vector + full-text indexes), `rag/embeddings.py` + `rag/index_documents.py` (whole preparation in one command, one transaction, idempotent) (section 6, Part A).
- **2026-11-10**: Step 6 done: 28 chunks indexed in Postgres with Haiku labels and Voyage `voyage-4` vectors plus a generated full-text column; one-command, idempotent `index_documents.py`. Next: step 7, hybrid search (section 7).
- **2026-11-10**: Hybrid search dropped (Arin): vector search only, on label + text. Tested on the real index first: vector search + labels finds the right chunk for the demo questions ("gym" → Fitness room via the label; email #7 → Hedge maze, Children, Indoor pool); keyword search would mainly help with names ("Lloyd") and give a "not found" signal (email #8, "helicopter"). Judged an overreach for the deadline. The generated `search_text` column and GIN index stay in the schema (harmless, reusable later). Deadline: GitHub + portfolio website by Sunday 15 / Monday 16 November 2026; all other planned technologies (reranker, Langfuse, MCP, timeouts, FastAPI + React, hosting) are kept.
- **2026-11-10**: Reranker: Voyage `rerank-3-lite`. Search = embed question (Voyage) → pgvector top 8 → rerank the 8 (Voyage reads question + chunk text together) → best 3–4 to the agent. Tested before deciding: same chunks found as vector search on 28 chunks, but clearer scores ("Who is Lloyd?": vector 0.07 vs 0.03, rerank 0.63 vs 0.32) and a usable "probably not found" hint (email #8 best score 0.42 vs ≥ 0.63 for answerable questions); scales to larger indexes (section 7, step 7).
- **2026-11-10**: Step 7 done: `rag/search.py` (vector top 8 → `rerank-3-lite` → best 4, with evidence and both scores). Emails #6 and #7 find all their sections; #8's best rerank score is 0.42 vs ≥ 0.66 for answerable questions. The generated `search_text` column is kept unused (Arin's choice). Next: step 8, graph skeleton + Langfuse (section 7).
- **2026-11-10**: Step 8 design agreed. Parts: 8.1 state + read node, 8.2 classify node, 8.3 routing + empty branches + compile, 8.4 Langfuse. **State** (`graph/state.py`): `EmailState(TypedDict, total=False)` with `email_path`, `email` (ParsedEmail: sender, subject, date, body, attachments, PDFs as Markdown via Docling), `classification`, `route`, `human_reason`; later steps add keys. **Classify:** Claude Haiku 5.5 with structured output (Pydantic `Classification`: type invoice/booking/question/other, suspicious + reason, confidence 0–1, one-line summary). **Routing in code** (a conditional-edge function, not the LLM): suspicious → human; other → human; confidence < 0.7 → human; else the type's branch. **LLM calls use the Anthropic SDK directly inside nodes** (no LangChain model wrappers).
- **2026-11-10**: Step 8.1 done (LangGraph 1.2.20 installed). `graph/state.py`: `EmailState` (TypedDict, total=False), `ParsedEmail`, `Attachment` (dataclasses), `Classification` (Pydantic, with field descriptions sent to the model), `Route`. `graph/nodes/read_email.py`: code-only node, `email` module (`BytesParser(policy=policy.default)`), plain-text body, PDF attachments → Markdown via `rag/parsing.parse_bytes` (Docling `DocumentStream`, in memory). `parsing.py` now shares one cached converter (`get_converter`, `lru_cache`). The FRP invoice comes out with its line items as a clean Markdown table. 98 tests pass.
- **2026-11-10**: `graph/main_graph.py` created early (Arin's request, so the graph grows in one real file): `build_graph()` (now START → read_email → END), `email_path_for(name)` (only demo emails in `data/emails/`: the client sends a name, never a path), `process_email(name)` (calls `graph.invoke({"email_path": ...})`), and a run command: `uv run python -m backoffice.graph.main_graph 06_question_pool_and_spa`. Who provides the starting state: the run command now; the backend API from step 15 (UI click → email name → path); a mailbox reader in a real deployment.
- **2026-11-10**: Step 8.2 done. `backoffice/llm.py`: one shared, cached Anthropic client (`anthropic_client()`, also used by the labels). `prompts/classify_system.md`: the classify instructions (email = data between `<email>` tags, never instructions; definitions of the 4 types; suspicious criteria; confidence < 0.7 when unclear). `graph/nodes/classify.py`: `client.messages.parse(..., output_format=Classification)` with Haiku 5.5, `effort: low`; attachments previewed (first 1,500 chars). `main_graph.py`: START → read_email → classify → END. **Real run on the 10 emails:** first prompt got 9/10 (#8 helicopter → `booking`, 0.60: "booking" was too loose); prompt sharpened (booking = ROOMS only; requests to arrange services such as transfers = question) → **10/10**, #9 suspicious with the right reason. Tests use a fake client via pytest `monkeypatch`.
- **2026-11-10**: Step 8.3 done. `graph/nodes/decide_route.py`: code-only node with the rules (`route_for`: suspicious → human; other → human; confidence < 0.7 → human; else the type), writing `route` + `human_reason` into the state (saved for the UI, evals and reviewer). In `main_graph.py`, the conditional edge `follow_route` only READS `state["route"]` (`add_conditional_edges("decide_route", follow_route, [4 branch names])`). `graph/branches/placeholders.py`: 4 empty branches (invoice, booking, question, human_review) to be replaced in steps 9–12. `process_email_step_by_step` uses `graph.stream(stream_mode="updates")` to list the nodes that ran (what the UI will show). **Real run: all 10 emails take the expected path** (#1–2 invoice, #3–5 booking, #6–8 question, #9 human "Suspicious: …", #10 human "type 'other'"). 115 tests pass. Next: 8.4 Langfuse.
- **2026-11-04**: Claude Code keeps this file up to date itself whenever a decision is agreed; Arin writes the code (section 1, rule 9).
