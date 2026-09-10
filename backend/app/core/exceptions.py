"""业务异常与全局异常处理器：所有错误统一返回 {"code", "message", "detail"} JSON。"""
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class BizError(Exception):
    """业务异常，message 面向用户可读。"""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _error_response(code: str, message: str, status_code: int, detail=None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "detail": detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def biz_error_handler(_request: Request, exc: BizError):
        return _error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException):
        return _error_response("http_error", str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        return _error_response("validation_error", "请求参数校验失败", 422, exc.errors())

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception):
        # 未捕获异常：记录日志并返回通用错误，避免内部细节泄露
        import logging

        logging.getLogger("app").exception("未捕获异常: %s", exc)
        return _error_response("internal_error", "服务器内部错误，请稍后重试", 500)
