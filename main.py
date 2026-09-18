#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Official competition runtime entrypoint for MSB Credit Proposal Copilot.

GreenNode AgentBase Custom Agent entrypoint.
Launches the HTTP server on port 8080 hosting:
- GET /health -> 200 OK
- GET / -> Copilot Web RM Interface
- GET /api/case -> Active customer case data
- POST /api/preview_legal_pdf -> Evidence-backed legal facts extraction
- POST /api/confirm_legal_preview -> Commit verified legal facts to Section A
- POST /api/preview_financial_pdf -> Multi-year BCTC facts extraction
- POST /api/confirm_financial_preview -> Commit verified BCTC facts to Section D
- POST /api/generate_docx -> Assemble and render complete MB07 credit proposal
"""

import os
import sys

# Import canonical server runner and handler from web_copilot_app
from web_copilot_app import run_server, CopilotHTTPHandler, PORT


def main() -> None:
    """Entrypoint function for GreenNode AgentBase runtime."""
    run_server()


if __name__ == "__main__":
    main()
