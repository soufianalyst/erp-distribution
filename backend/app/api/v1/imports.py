"""Legacy data import — admin only.

Two endpoints do the work: one hands out the template, the other takes files back.
Uploading is split into a dry run and a real run by a single flag, and the screen
is built so the dry run is the obvious first step.
"""

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permissions
from app.api.schemas.common import APIResponse
from app.api.schemas.imports import (
    ImportColumnInfoOut,
    ImportGuideOut,
    ImportReportOut,
    ImportSheetInfoOut,
)
from app.core.exceptions import AppException
from app.db.session import get_db
from app.domain.models.user import User
from app.services.imports import template
from app.services.imports.import_service import ImportService
from app.services.imports.spec import GUIDE_RULES, SHEETS, SHEETS_BY_NAME

router = APIRouter(prefix="/imports", tags=["Data import"])

# One permission for the whole module, granted to admins only. Importing rewrites
# the opening position of the entire business; there is no meaningful half of it to
# delegate.
require_importer = require_permissions("data.import")
importer = Depends(require_importer)

# A migration file is big — a year of invoice lines for a distributor runs to tens of
# megabytes — but not unbounded, because the whole upload is held in memory to be
# validated before anything is written.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FILES = 10


@router.get(
    "/guide", response_model=APIResponse[ImportGuideOut], dependencies=[importer]
)
async def import_guide() -> APIResponse[ImportGuideOut]:
    """شرح الأوراق والأعمدة المطلوبة للاستيراد، كما يولّدها القالب نفسه."""
    return APIResponse(
        data=ImportGuideOut(
            rules=list(GUIDE_RULES),
            sheets=[
                ImportSheetInfoOut(
                    name=sheet.name,
                    title=sheet.title,
                    purpose=sheet.purpose,
                    columns=[
                        ImportColumnInfoOut(
                            name=column.name,
                            label=column.label,
                            kind=column.kind,
                            required=column.required,
                            choices=list(column.choices),
                            note=column.note,
                        )
                        for column in sheet.columns
                    ],
                )
                for sheet in SHEETS
            ],
        )
    )


@router.get("/template.xlsx", dependencies=[importer])
async def download_template() -> Response:
    """تنزيل قالب Excel يحتوي كل الأوراق مع أمثلة وشرح لكل عمود."""
    return Response(
        content=template.build_workbook(),
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="erp-import-template.xlsx"'
        },
    )


@router.get("/template.zip", dependencies=[importer])
async def download_csv_bundle() -> Response:
    """تنزيل القالب كملفات CSV منفصلة مضغوطة، لمن لا يستخدم Excel."""
    return Response(
        content=template.build_csv_bundle(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="erp-import-template-csv.zip"'
        },
    )


@router.post("/run", response_model=APIResponse[ImportReportOut])
async def run_import(
    files: list[UploadFile] = File(..., description="ملف Excel واحد أو عدة ملفات CSV"),
    dry_run: bool = Query(default=True, description="فحص فقط دون حفظ"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_importer),
) -> APIResponse[ImportReportOut]:
    """فحص أو تنفيذ استيراد بيانات النظام القديم.

    الوضع الافتراضي هو الفحص فقط: يُقرأ الملف بالكامل ويُتحقق منه دون كتابة أي سطر.
    التنفيذ الفعلي يتم بتمرير `dry_run=false`، وحينها إمّا أن تُحفظ كل الأسطر أو لا
    يُحفظ أي منها.
    """
    if len(files) > MAX_FILES:
        raise AppException(400, f"الحد الأقصى {MAX_FILES} ملفات في المرة الواحدة.")

    payload: dict[str, bytes] = {}
    total = 0
    for upload in files:
        content = await upload.read()
        total += len(content)
        if total > MAX_UPLOAD_BYTES:
            raise AppException(
                400,
                f"حجم الملفات يتجاوز {MAX_UPLOAD_BYTES // (1024 * 1024)} ميغابايت. "
                "قسّم البيانات على دفعات.",
            )
        if not content:
            raise AppException(400, f"الملف «{upload.filename}» فارغ.")
        payload[upload.filename or "unnamed"] = content

    report = await ImportService(db).run(payload, dry_run=dry_run, user=current_user)
    return APIResponse(data=report, message=report.message)


@router.get(
    "/template/{sheet_name}.csv",
    dependencies=[importer],
)
async def download_sheet_csv(sheet_name: str) -> Response:
    """تنزيل ورقة واحدة كملف CSV."""
    sheet = SHEETS_BY_NAME.get(sheet_name)
    if sheet is None:
        raise AppException(404, "لا توجد ورقة بهذا الاسم في القالب.")
    return Response(
        content=template.build_csv(sheet),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{sheet.name}.csv"'},
    )
