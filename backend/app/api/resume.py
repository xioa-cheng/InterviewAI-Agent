"""简历 API：上传 / 保存 / 删除简历文本"""
import re
import sys
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models.interview import Interview
from app.models.resume import Resume
from app.models.user import User

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"])

# 上传安全限制
MAX_UPLOAD_BYTES = 10 * 1024 * 1024       # 上传文件大小上限 10MB
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024    # docx 解压后总大小上限 50MB
MAX_PDF_PAGES = 100                        # PDF 页数上限
MAX_IMAGE_PIXELS = 30_000_000              # 图片像素上限（约 1.2 亿字节 RGBA）


def _log(msg: str):
    print(f"[resume-parser] {msg}", file=sys.stderr, flush=True)


def _decode_text(data: bytes) -> str:
    """按常见编码尝试解码文本（中文 txt 常为 GBK 编码）"""
    for enc in ("utf-8", "gb18030", "gbk", "big5"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")


def _ocr_image(img_bytes: bytes) -> str:
    """用 tesseract OCR 识别图片文字（支持中文 + 英文）"""
    try:
        import pytesseract
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        img = Image.open(BytesIO(img_bytes))
        _log(f"OCR 图片尺寸={img.size} 模式={img.mode}")
        return pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception as e:  # noqa: BLE001
        _log(f"OCR 失败: {type(e).__name__}: {e}")
        return ""


def _extract_pdf(data: bytes) -> str:
    _log(f"PDF 文件大小={len(data)} 字节")
    # 优先 pypdf
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ValueError(f"PDF 页数过多（上限 {MAX_PDF_PAGES} 页）")
        _log(f"pypdf 打开成功，页数={len(reader.pages)}，加密={reader.is_encrypted}")
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                _log("pypdf 解密失败（加密 PDF）")
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        _log(f"pypdf 提取文字长度={len(text)}")
        if text:
            return text
    except Exception as e:  # noqa: BLE001
        _log(f"pypdf 失败: {type(e).__name__}: {e}")
    # 回退 pymupdf（对部分 PDF 提取更稳）
    try:
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="pdf")
        if doc.page_count > MAX_PDF_PAGES:
            doc.close()
            raise ValueError(f"PDF 页数过多（上限 {MAX_PDF_PAGES} 页）")
        _log(f"pymupdf 打开成功，页数={doc.page_count}，需密码={doc.needs_pass}")
        if doc.needs_pass:
            doc.authenticate("")
        text = "\n".join(page.get_text() for page in doc).strip()
        _log(f"pymupdf 提取文字长度={len(text)}")
        if text:
            doc.close()
            return text
        # 无文字层（扫描件）→ 逐页转图片做 OCR
        texts = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=200)
            _log(f"第{i+1}页转图：{pix.width}x{pix.height}")
            t = _ocr_image(pix.tobytes("png"))
            _log(f"第{i+1}页 OCR 文字长度={len(t.strip())}")
            if t.strip():
                texts.append(t.strip())
        doc.close()
        if texts:
            return "\n".join(texts)
    except Exception as e:  # noqa: BLE001
        _log(f"pymupdf 失败: {type(e).__name__}: {e}")
    return ""


def _extract_docx(data: bytes) -> str:
    """解析 docx，直读 XML 以兼容文本框（text box）排版。

    python-docx 只读正文段落和表格，读不到放在「文本框」里的文字；
    而大量简历模板（尤其 WPS 生成）整份简历都放在文本框里，导致解析为空。
    这里用 lxml 直接遍历所有 <w:p>，文本框、表格、页眉页脚都能取到。
    """
    import zipfile

    from lxml import etree

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

    _log(f"DOCX 文件大小={len(data)} 字节")
    z = zipfile.ZipFile(BytesIO(data))
    # zip 炸弹防护：限制解压后总大小
    if sum(i.file_size for i in z.infolist()) > MAX_EXTRACTED_BYTES:
        raise ValueError("文件解压后过大，疑似压缩炸弹")
    names = ["word/document.xml"] + sorted(
        n for n in z.namelist() if n.startswith("word/header") or n.startswith("word/footer")
    )
    lines: list[str] = []
    for name in names:
        try:
            root = etree.fromstring(z.read(name))
        except (KeyError, etree.XMLSyntaxError):
            continue
        for p in root.iter(W + "p"):
            # 跳过 WPS 专用分支 mc:Choice，只保留标准 mc:Fallback，避免整段重复
            if any(a.tag == MC + "Choice" for a in p.iterancestors()):
                continue
            line = "".join((t.text or "") for t in p.iter(W + "t"))
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            # 过滤 WPS 分节符产生的 "<" 行
            if set(line) <= {"<", ">", " "}:
                continue
            # 去掉「某某某某」式的整行二倍重复（WPS 文本框常把标题存两遍）
            half = len(line) // 2
            if half >= 2 and line[:half] == line[half:]:
                line = line[:half]
            if lines and lines[-1] == line:
                continue
            lines.append(line)
    result = "\n".join(lines)
    _log(f"DOCX 提取行数={len(lines)} 文字长度={len(result)}")
    return result


async def _extract_file_text(file: UploadFile) -> str:
    """按扩展名解析上传文件，返回纯文本"""
    # 只读取上限 + 1 字节，超过上限直接拒绝，避免大文件读入内存
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件过大，请上传 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 以内的文件",
        )
    name = (file.filename or "").lower()
    _log(f"收到文件: {file.filename!r} 大小={len(data)} 字节 content_type={file.content_type}")
    try:
        if name.endswith((".txt", ".md", ".text")):
            result = _decode_text(data)
            _log(f"TXT 解码文字长度={len(result)}")
            return result
        if name.endswith(".pdf"):
            return _extract_pdf(data)
        if name.endswith(".docx"):
            return _extract_docx(data)
        if name.endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
            result = _ocr_image(data)
            _log(f"图片 OCR 文字长度={len(result)}")
            return result
        if name.endswith(".doc"):
            _log("检测到旧版 .doc 格式，不支持")
    except Exception as e:  # noqa: BLE001
        _log(f"文件解析异常: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=f"文件解析失败（{type(e).__name__}），文件可能已损坏，请换一个文件重试")
    raise HTTPException(status_code=400, detail="不支持的文件格式，请上传 txt / md / docx / pdf / jpg / png 等")


async def _create_resume(db: AsyncSession, user_id, title: str, content: str) -> Resume:
    resume = Resume(user_id=user_id, title=title, content=content)
    db.add(resume)
    await db.commit()
    await db.refresh(resume)
    return resume


@router.get("")
async def list_resumes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
    )
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "content": r.content,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in result.scalars().all()
    ]


@router.post("")
async def create_resume(data: dict, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    content = data.get("content", "")
    title = data.get("title", "我的简历")

    resume = await _create_resume(db, user.id, title, content)
    return {"id": str(resume.id), "title": title}


@router.post("/upload")
async def upload_resume(
    file: UploadFile = File(...),
    title: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """上传 Word/PDF/txt 文件，服务端解析文本后创建简历"""
    content = (await _extract_file_text(file)).strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail="未能从文件中解析出文本内容。若上传的是 PDF，可能是扫描件/图片型 PDF（无文字层），请改用文字版 PDF、Word(.docx) 或 txt 文件。",
        )

    fallback_title = (file.filename or "我的简历").rsplit(".", 1)[0]
    title = (title or "").strip() or fallback_title

    resume = await _create_resume(db, user.id, title, content)
    return {"id": str(resume.id), "title": title, "content": content}


@router.delete("/{resume_id}")
async def delete_resume(resume_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    try:
        rid = uuid.UUID(resume_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的简历 ID")

    resume = (await db.execute(select(Resume).where(Resume.id == rid))).scalar_one_or_none()
    if resume is None:
        raise HTTPException(status_code=404, detail="简历不存在")
    if resume.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权删除该简历")

    # 解除面试与简历的关联，避免外键冲突
    await db.execute(update(Interview).where(Interview.resume_id == rid).values(resume_id=None))
    await db.delete(resume)
    await db.commit()
    return {"deleted": True}
