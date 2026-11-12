"""The invoice branch (step 11): a LangGraph subgraph, built from the nodes in this folder.

    extract.py   extract_invoice: the ONLY LLM call (copy the invoice into a form), then code turns
                 the printed amounts into exact Decimals                                     (11.1)
    checks.py    check_invoice: which supplier, every line ✓/⚠/✗, totals, one outcome     (11.2)
    replies.py   ok_to_pay_note, correction_request, needs_check_note, unknown_supplier_note:
                 fixed templates filled by code; invoice_evidence for the approval screen    (11.3, 11.4)
    subgraph.py  build_invoice_graph: the nodes above, connected                             (11.4)
"""
