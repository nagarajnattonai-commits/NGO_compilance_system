"""Bound the complete multipart request before it can fill temporary storage."""
from starlette.responses import JSONResponse
from fastapi import HTTPException
from .document_storage import maximum_bytes
class UploadTooLarge(HTTPException):
    def __init__(self):super().__init__(413,"Document exceeds the configured upload limit")
class DocumentUploadLimit:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope["type"]!="http" or scope.get("path")!="/api/v1/documents/upload":return await self.app(scope,receive,send)
        limit=maximum_bytes()+65536;headers=dict(scope.get("headers",[]));consumed=0
        async def reject():
            await JSONResponse({"detail":"Document exceeds the configured upload limit"},status_code=413,headers={"Cache-Control":"no-store"})(scope,receive,send)
        try:length=int(headers.get(b"content-length",b"0"))
        except ValueError:length=limit+1
        if length>limit:return await reject()
        async def bounded_receive():
            nonlocal consumed
            message=await receive();consumed+=len(message.get("body",b""))
            if consumed>limit:raise UploadTooLarge()
            return message
        try:await self.app(scope,bounded_receive,send)
        except UploadTooLarge:await reject()
