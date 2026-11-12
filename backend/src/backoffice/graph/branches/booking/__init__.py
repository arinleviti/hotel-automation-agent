"""The booking branch (step 10): a LangGraph subgraph, built in 10.5 from the nodes in this folder.

    extract.py   extract_request: the ONLY LLM call (read the request), then code validation   (10.2)
    checks.py    check_availability, price_stay, find_alternatives + the routing decisions  (10.3)
    replies.py   quote_reply, full_reply, ask_for_missing_info, no_data_reply: fixed templates
                 (data/reply_templates/) filled by code, no LLM                             (10.4)
"""
