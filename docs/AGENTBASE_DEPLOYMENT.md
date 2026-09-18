# GreenNode AgentBase Deployment Guide

## Overview

- **Deployment Type**: Custom Agent (`/agent-runtimes`)
- **Application**: MSB Credit Proposal Copilot (MSB Enterprise Banking AI Credit Proposal Copilot)
- **Target Audience**: Relationship Managers (RM) and Credit Approvers at MSB

## Architecture

$$\text{Local Docker Image} \longrightarrow \text{GreenNode AgentBase Container Registry (CR)} \longrightarrow \text{Custom Agent Runtime} \longrightarrow \text{Public HTTPS Endpoint}$$

1. **Docker Container**: Packages Python runtime, `pypdfium2`, `python-docx`, `pypdf`, `pydantic`, canonical core engine, and HTTP server.
2. **Container Registry**: GreenNode AgentBase managed Container Registry (`vcr`).
3. **Agent Runtime**: Custom Agent hosting container on port `8080` with auto-restart, autoscaling (1 to N replicas), and integrated monitoring.
4. **Public Endpoint**: Provides direct HTTPS URL to access Web UI and REST API.

## Environment & Credential Contract

### Mandatory Credential Names (NO VALUES TO BE STORED IN REPO)

- `GREENNODE_CLIENT_ID`: Service account client ID for AgentBase platform access and Container Registry authentication.
- `GREENNODE_CLIENT_SECRET`: Service account secret key for AgentBase platform authentication.
- `LLM_API_KEY`: API key for GreenNode MaaS LLM / Vision inference.

### Standardized Public Runtime Variables

| Variable Name | Required | Default / Recommended Value | Description |
| :--- | :--- | :--- | :--- |
| `APP_MODE` | Yes | `hackathon` | Execution mode (enforces strict GreenNode-only validation). |
| `PORT` | Yes | `8080` | HTTP port exposed by the container. |
| `LLM_BASE_URL` | Yes | `https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1` | Proven GreenNode MaaS OpenAI-compatible endpoint. |
| `LLM_MODEL` | Yes | `z-ai/glm-5.2-hackathon` | GreenNode reasoning & text extraction model. |
| `VISION_MODEL` | Yes | `qwen/qwen3.6-flash` | GreenNode Vision OCR model for scanned documents. |

*(Backwards-compatible aliases `GREENNODE_API_KEY`, `GREENNODE_BASE_URL`, `GREENNODE_MODEL` remain supported in code).*

### Platform Auto-Injected Variables (Runtime Only)

When deployed on AgentBase, the platform automatically injects:
- `GREENNODE_CLIENT_ID`
- `GREENNODE_CLIENT_SECRET`
- `GREENNODE_AGENT_IDENTITY`
- `GREENNODE_ENDPOINT_URL`

Do NOT duplicate or hardcode these into static env files.

## Health Check Contract

- **Method**: `GET /health`
- **Port**: `8080`
- **Expected Status**: `HTTP 200`
- **Response Format**: `{"status": "ok", "app": "msb-credit-proposal-copilot"}`
- **Latency**: `< 10ms` (zero LLM token consumption, zero external network dependency, zero credentials leaked).

## Runtime Sizing Guidance

Based on organizer guidelines for the AI Hackathon, candidate resource allocations for the Custom Agent runtime are:

1. **Baseline / Standard**: `2 CPU / 4 GB RAM`
   - Suitable for digital PDF processing, deterministic financial analysis, and proposal rendering.
2. **High Performance**: `4 CPU / 8 GB RAM`
   - Recommended if handling high-volume concurrent multi-page scanned PDF rasterization via PDFium.

> **Note**: A final cloud flavor must NOT be hardcoded in advance. Actual flavor availability must be queried live from the AgentBase Runtime service via `runtime.sh flavors` during deployment.

## Security Policies

- **Zero Secret Commits**: Never commit `.env`, API keys, or client secrets to git.
- **No Secrets in Docker Images**: Never use `ENV` in Dockerfile for credentials. Pass all secrets at runtime via `--env-file` or AgentBase runtime secret injection.
- **Safe Logging**: Telemetry logs record latency, token counts, and model names only; secret values are masked or omitted.