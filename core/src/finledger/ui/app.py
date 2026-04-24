from pathlib import Path
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from finledger.ui.routes.inbox import router as inbox_router
from finledger.ui.routes.journal import router as journal_router
from finledger.ui.routes.recon import router as recon_router
from finledger.ui.routes.flow import router as flow_router
from finledger.ui.routes.revrec import router as revrec_router
from finledger.ui.routes.demo import router as demo_router


TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app() -> FastAPI:
    app = FastAPI(title="FinLedger")
    app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.include_router(inbox_router, prefix="")
    app.include_router(journal_router, prefix="/journal")
    app.include_router(recon_router, prefix="/recon")
    app.include_router(flow_router, prefix="/flow")
    app.include_router(revrec_router, prefix="/revrec")
    app.include_router(demo_router, prefix="/demo")
    return app


app = create_app()
