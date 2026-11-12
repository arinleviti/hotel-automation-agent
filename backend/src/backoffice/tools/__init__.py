"""Services wrapped as TOOLS: functions an LLM may choose to call (step 12, the question agent).

A tool = (1) a description + input schema sent to the model, so it knows the tool exists and how to
call it, and (2) the code that runs when the model calls it. The logic itself stays in services/ or
rag/; these files only adapt it. The MCP server (step 17) will expose the same functions.

    search_documents.py   the agent's search tool (your step-7 search: Voyage + pgvector + reranker)
"""
