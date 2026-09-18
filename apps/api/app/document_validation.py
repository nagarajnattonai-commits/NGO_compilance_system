"""Format validation does not claim malware scanning or legal-content verification."""
import io
import re
import warnings
import zipfile
from pathlib import PurePath
from PIL import Image
MIMES={".pdf":"application/pdf",".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp",".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",".xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
def validate_file(filename,mime,content):
    original=re.sub(r"[\x00-\x1f\x7f]","",(filename or "").replace("\\","/").split("/")[-1])[:255]
    extension=PurePath(original).suffix.lower()
    if extension not in MIMES or mime!=MIMES[extension]:raise ValueError("File extension and MIME type must match PDF, PNG, JPG, WEBP, DOCX or XLSX")
    if not content:raise ValueError("Empty files are not accepted")
    if extension==".pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]:raise ValueError("Invalid PDF content")
        if re.search(rb"/(?:JavaScript|JS|Launch|EmbeddedFile|RichMedia)\b",content):raise ValueError("Active or embedded PDF content is not accepted")
    elif mime.startswith("image/"):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error",Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    if image.format!={"image/png":"PNG","image/jpeg":"JPEG","image/webp":"WEBP"}[mime] or image.width*image.height>16_000_000 or getattr(image,"n_frames",1)!=1:raise ValueError()
                    image.verify()
        except Exception:raise ValueError("Image content is invalid or does not match its MIME type") from None
    else:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries=archive.infolist()
                if len(entries)>2000 or sum(e.file_size for e in entries)>100*1024*1024:raise ValueError()
                names={e.filename for e in entries};expected="word/document.xml" if extension==".docx" else "xl/workbook.xml"
                if expected not in names or "[Content_Types].xml" not in names or any(".." in PurePath(n).parts or n.startswith(("/","\\")) or "vba" in n.lower() or n.lower().endswith((".exe",".js",".vbs")) for n in names) or archive.testzip():raise ValueError()
        except Exception:raise ValueError("Office file must be a valid bounded macro-free DOCX or XLSX archive") from None
    safe=re.sub(r"[^A-Za-z0-9_.-]","_",original)[:100]
    return original,safe or "document"+extension
