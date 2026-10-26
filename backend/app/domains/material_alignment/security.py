from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader


ALLOWED_MIME_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".txt": {"text/plain", "text/markdown"},
}
DETECTED_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
}


class UploadPolicyError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SecurityInspection:
    extension: str
    detected_mime: str
    byte_size: int
    sha256: str
    warnings: list[dict[str, str]] = field(default_factory=list)


def validate_upload_metadata(
    filename: str,
    declared_mime: str,
    byte_size: int,
    max_bytes: int,
    expected_sha256: str | None = None,
) -> str:
    if not filename or Path(filename).name != filename or "\x00" in filename:
        raise UploadPolicyError("unsafe_filename", "文件名不得包含路径或控制字符")
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_MIME_TYPES:
        raise UploadPolicyError("unsupported_extension", "仅支持PDF、DOCX、PPTX和TXT文件")
    normalized_mime = declared_mime.split(";", 1)[0].strip().lower()
    if normalized_mime not in ALLOWED_MIME_TYPES[extension]:
        raise UploadPolicyError("declared_mime_mismatch", "文件扩展名与声明的内容类型不一致")
    if byte_size <= 0:
        raise UploadPolicyError("empty_file", "文件不能为空")
    if byte_size > max_bytes:
        raise UploadPolicyError("file_too_large", f"单个文件不得超过{max_bytes // (1024 * 1024)}MB")
    if expected_sha256 is not None:
        candidate = expected_sha256.strip().lower()
        if len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
            raise UploadPolicyError("invalid_sha256", "SHA-256必须是64位十六进制字符串")
    return extension


def _inspect_office_zip(path: Path, extension: str, max_bytes: int) -> list[dict[str, str]]:
    expected_member = "word/document.xml" if extension == ".docx" else "ppt/presentation.xml"
    warnings: list[dict[str, str]] = []
    try:
        with ZipFile(path) as archive:
            infos = archive.infolist()
            names = {item.filename for item in infos}
            if "[Content_Types].xml" not in names or expected_member not in names:
                raise UploadPolicyError("office_signature_mismatch", "压缩容器不是有效的Office开放文档")
            if len(infos) > 3000:
                raise UploadPolicyError("archive_entry_limit", "Office文件包含过多内部条目")
            unpacked = sum(item.file_size for item in infos)
            packed = max(1, sum(item.compress_size for item in infos))
            if unpacked > max(100 * 1024 * 1024, max_bytes * 5) or unpacked / packed > 250:
                raise UploadPolicyError("archive_expansion_limit", "Office文件的解压规模异常")
            lowered = {name.lower() for name in names}
            if any(name.endswith("vbaproject.bin") or "/embeddings/" in name for name in lowered):
                raise UploadPolicyError("active_content_rejected", "不接收包含宏或嵌入对象的Office文件")
            relationship_files = [name for name in names if name.lower().endswith(".rels")]
            if any(b'TargetMode="External"' in archive.read(name) for name in relationship_files):
                warnings.append({
                    "code": "external_relationship_ignored",
                    "message": "文件包含外部链接；解析过程不会访问这些地址",
                })
    except BadZipFile as exc:
        raise UploadPolicyError("invalid_office_container", "Office文件容器已损坏") from exc
    return warnings


def _validate_text(path: Path) -> None:
    content = path.read_bytes()
    if b"\x00" in content:
        raise UploadPolicyError("binary_text_rejected", "TXT文件包含二进制空字符")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            content.decode(encoding)
            return
        except UnicodeDecodeError:
            continue
    raise UploadPolicyError("text_encoding_unsupported", "TXT文件应使用UTF-8或GB18030编码")


def inspect_upload(
    path: Path,
    *,
    filename: str,
    declared_mime: str,
    expected_size: int,
    max_bytes: int,
    expected_sha256: str | None = None,
) -> SecurityInspection:
    extension = validate_upload_metadata(
        filename, declared_mime, expected_size, max_bytes, expected_sha256
    )
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise UploadPolicyError("size_mismatch", "实际上传大小与预申请大小不一致")
    if actual_size > max_bytes:
        raise UploadPolicyError("file_too_large", "实际上传文件超过大小限制")
    digest = sha256(path.read_bytes()).hexdigest()
    if expected_sha256 and digest != expected_sha256.strip().lower():
        raise UploadPolicyError("sha256_mismatch", "上传文件的SHA-256与预申请值不一致")

    prefix = path.read_bytes()[:8]
    warnings: list[dict[str, str]] = []
    if extension == ".pdf":
        if not prefix.startswith(b"%PDF-"):
            raise UploadPolicyError("file_signature_mismatch", "文件签名与PDF扩展名不一致")
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise UploadPolicyError("encrypted_document", "暂不接收加密PDF")
        except UploadPolicyError:
            raise
        except Exception as exc:
            raise UploadPolicyError("invalid_pdf", "PDF结构无法安全解析") from exc
    elif extension in {".docx", ".pptx"}:
        if not prefix.startswith(b"PK"):
            raise UploadPolicyError("file_signature_mismatch", "文件签名与Office扩展名不一致")
        warnings.extend(_inspect_office_zip(path, extension, max_bytes))
    else:
        _validate_text(path)

    return SecurityInspection(
        extension=extension,
        detected_mime=DETECTED_MIME_TYPES[extension],
        byte_size=actual_size,
        sha256=digest,
        warnings=warnings,
    )


def resolve_storage_path(root: Path, area: str, asset_id: str) -> Path:
    if area not in {"quarantine", "accepted"}:
        raise ValueError("未知资产存储区")
    target = (root / area / f"{asset_id}.blob").resolve()
    resolved_root = root.resolve()
    if not target.is_relative_to(resolved_root):
        raise ValueError("资产路径越界")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
