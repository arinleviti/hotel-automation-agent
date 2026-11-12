"""The question branch (step 12): the project's one AGENT, as a loop subgraph.

    agent.py     agent (LLM: search again or answer?) and search_step (code runs the search)  (12.1)
    checks.py    check_agent_answer: the code checks (services/answer_check.py) + routing     (12.2)
    replies.py   answer_reply (LLM text inside a fixed template), not_found_note,
                 check_failed_note (both to the front desk)                                  (12.2)
    subgraph.py  build_question_graph: the loop, then checks, then a reply                   (12.1, 12.2)
"""
