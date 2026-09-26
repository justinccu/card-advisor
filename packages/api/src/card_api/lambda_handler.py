"""API Lambda entry point (Cognito triggers live in card_api.triggers); local and cloud run the
same app code."""

from mangum import Mangum

from card_api.app import app

# API Gateway HTTP API -> FastAPI. The JWT authorizer runs before this; auth.py reads its claims.
handler = Mangum(app, lifespan="off")
