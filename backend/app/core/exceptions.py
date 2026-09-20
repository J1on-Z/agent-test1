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


# 常见 pydantic 校验错误类型 → 用户可读文案（{} 占位符取 errors[i].ctx 的键）
_VALIDATION_HINTS = {
    "string_too_short": "长度不能少于 {min_length} 位",
    "string_too_long": "长度不能超过 {max_length} 位",
    "string_pattern_mismatch": "格式不符合要求（仅支持字母/数字/中文/短横线）",
    "missing": "缺少必填参数",
}


def _friendly_validation_message(errors: list) -> str:
    """把 pydantic 校验错误列表转成用户可读的一句话（取第一个错误）。"""
    if not errors:
        return "请求参数校验失败"
    e = errors[0]
    field = ".".join(str(p) for p in e.get("loc", []) if p not in ("body",))
    tpl = _VALIDATION_HINTS.get(e.get("type", ""))
    if tpl:
        try:
            reason = tpl.format(**e.get("ctx", {}))
        except (KeyError, IndexError, ValueError):
            reason = e.get("msg", "格式不正确")
    else:
        reason = e.get("msg", "格式不正确")
    return f"参数 {field} 校验失败：{reason}" if field else f"请求参数校验失败：{reason}"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def biz_error_handler(_request: Request, exc: BizError):
        return _error_response(exc.code, exc.message, exc.status_code)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException):
        return _error_response("http_error", str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, exc: RequestValidationError):
        return _error_response(
            "validation_error", _friendly_validation_message(exc.errors()), 422, exc.errors()
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception):
        # 未捕获异常：记录日志并返回通用错误，避免内部细节泄露
        import logging

        logging.getLogger("app").exception("未捕获异常: %s", exc)
        return _error_response("internal_error", "服务器内部错误，请稍后重试", 500)
