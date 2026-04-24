from fastapi import APIRouter, Request

router = APIRouter()


@router.get("")
async def demo_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        request=request, name="demo.html", context={},
    )
