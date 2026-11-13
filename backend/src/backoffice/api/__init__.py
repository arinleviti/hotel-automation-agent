"""The backend API (step 15): the web server the frontend talks to. It sits OUTSIDE the graph and
calls the same functions as the command line (process_email's pieces, resume_email).

    app.py      FastAPI app and endpoints
    schemas.py  the shapes of requests and responses (Pydantic: "Pydantic at the edges")
    steps.py    each graph step as one line of plain text, for the UI's middle column

Run (from backend/; Postgres running):
    uv run uvicorn backoffice.api.app:app --reload --port 8000
then open http://localhost:8000/docs to try every endpoint by hand.
"""
