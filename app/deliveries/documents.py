from __future__ import annotations

import base64
import hashlib
import io
import re
import uuid
from datetime import datetime
from pathlib import Path

from flask import current_app
from PIL import Image as PILImage, ImageChops
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.localtime import format_datetime, to_local


DATA_URL_RE = re.compile(r"^data:image/png;base64,(?P<data>[A-Za-z0-9+/=\s]+)$")


def decode_signature(data_url: str) -> bytes:
    match = DATA_URL_RE.fullmatch(data_url.strip())
    if not match:
        raise ValueError("Assinatura inválida. Limpe e assine novamente.")
    try:
        raw = base64.b64decode(match.group("data"), validate=True)
    except Exception as exc:
        raise ValueError("Não foi possível ler a assinatura.") from exc
    if len(raw) > 1_500_000:
        raise ValueError("A assinatura excedeu o tamanho permitido.")

    try:
        image = PILImage.open(io.BytesIO(raw)).convert("RGBA")
        if image.width < 250 or image.height < 90:
            raise ValueError("A área da assinatura está pequena demais.")
        background = PILImage.new("RGBA", image.size, (255, 255, 255, 255))
        flattened = PILImage.alpha_composite(background, image).convert("RGB")
        difference = ImageChops.difference(flattened, PILImage.new("RGB", image.size, "white"))
        if difference.getbbox() is None:
            raise ValueError("A assinatura está em branco.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("O arquivo da assinatura não é uma imagem PNG válida.") from exc
    return raw


def save_signature(raw: bytes, delivered_at: datetime) -> tuple[str, str]:
    relative = Path("signatures") / to_local(delivered_at).strftime("%Y/%m") / f"{uuid.uuid4().hex}.png"
    absolute = Path(current_app.config["DATA_DIR"]) / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_bytes(raw)
    return relative.as_posix(), hashlib.sha256(raw).hexdigest()


def generate_receipt(delivery) -> tuple[str, str]:
    relative = Path("receipts") / to_local(delivery.delivered_at).strftime("%Y/%m") / f"{delivery.receipt_number}.pdf"
    absolute = Path(current_app.config["DATA_DIR"]) / relative
    absolute.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReceiptTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=colors.HexColor("#172A4D"), alignment=TA_CENTER, spaceAfter=12))
    styles.add(ParagraphStyle(name="ReceiptBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.3, leading=13, alignment=TA_JUSTIFY, textColor=colors.HexColor("#252C38")))
    styles.add(ParagraphStyle(name="ReceiptSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.6, leading=10, textColor=colors.HexColor("#5D6878")))

    story = [Spacer(1, 24 * mm), Paragraph("Comprovante de Entrega de EPI", styles["ReceiptTitle"])]
    metadata = [
        [Paragraph("<b>Comprovante</b>", styles["ReceiptBody"]), delivery.receipt_number],
        [Paragraph("<b>Colaborador</b>", styles["ReceiptBody"]), delivery.employee.name],
        [Paragraph("<b>Função</b>", styles["ReceiptBody"]), delivery.employee.job_title or "—"],
        [Paragraph("<b>Data e hora</b>", styles["ReceiptBody"]), format_datetime(delivery.delivered_at)],
        [Paragraph("<b>Entregue por</b>", styles["ReceiptBody"]), delivery.delivered_by.full_name],
    ]
    metadata_table = Table(metadata, colWidths=[38 * mm, 132 * mm])
    metadata_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF2F7")),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#D5DDE7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (1, 0), (1, -1), 9.3),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([metadata_table, Spacer(1, 7 * mm)])

    rows = [["Categoria", "EPI / Uniforme", "Tamanho", "Quantidade", "CA"]]
    for item in delivery.items:
        rows.append([
            item.variant.product.category.name,
            item.variant.product.name,
            item.variant.size or "Único",
            str(item.quantity),
            item.variant.product.ca_number or "—",
        ])
    item_table = Table(rows, colWidths=[28 * mm, 78 * mm, 24 * mm, 22 * mm, 20 * mm], repeatRows=1)
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#172A4D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#CCD6E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FA")]),
        ("FONTSIZE", (0, 0), (-1, -1), 8.7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.extend([item_table, Spacer(1, 6 * mm)])
    for paragraph in delivery.acknowledgement_text.split("\n\n"):
        if paragraph.strip():
            story.append(Paragraph(paragraph, styles["ReceiptBody"]))
    story.append(Spacer(1, 6 * mm))

    signature_style = ParagraphStyle(name="Signature", parent=styles["ReceiptBody"], alignment=TA_CENTER, leading=12)
    signature_block = []
    if delivery.has_digital_signature:
        signature_absolute = Path(current_app.config["DATA_DIR"]) / delivery.signature_path
        signature_block.append(Image(str(signature_absolute), width=92 * mm, height=30 * mm, kind="proportional"))
        integrity = f"Integridade da assinatura: {delivery.signature_sha256}<br/>"
    else:
        signature_block.append(Paragraph("Documento emitido sem assinatura digital. Assinar no papel no recebimento dos itens.", styles["ReceiptSmall"]))
        signature_block.append(Spacer(1, 24 * mm))
        line = Table([[""]], colWidths=[110 * mm])
        line.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), .6, colors.HexColor("#252C38"))]))
        signature_block.append(line)
        integrity = ""
    signature_block.append(Paragraph(f"<b>{delivery.employee.name}</b><br/>Assinatura do colaborador", signature_style))
    if not delivery.has_digital_signature:
        signature_block.extend([Spacer(1, 4 * mm), Paragraph("Data do recebimento e assinatura: ______ / ______ / __________", signature_style)])
    signature_block.extend([Spacer(1, 5 * mm), Paragraph(f"{integrity}Retenção prevista até {delivery.retention_until.strftime('%d/%m/%Y')}", styles["ReceiptSmall"])])
    story.append(KeepTogether(signature_block))

    document = SimpleDocTemplate(str(absolute), pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=14 * mm, bottomMargin=24 * mm, title=f"Comprovante {delivery.receipt_number}", author="Grupo Transer")
    document.build(story, onFirstPage=_draw_letterhead, onLaterPages=_draw_letterhead)
    raw = absolute.read_bytes()
    return relative.as_posix(), hashlib.sha256(raw).hexdigest()


def _draw_letterhead(canvas, document) -> None:
    width, height = A4
    base_dir = Path(current_app.root_path) / "static" / "img"
    header = base_dir / "transer-header.png"
    footer = base_dir / "transer-footer.jpg"
    if header.exists():
        canvas.drawImage(str(header), 16 * mm, height - 25 * mm, width=178 * mm, height=20 * mm, preserveAspectRatio=True, anchor="n", mask="auto")
    if footer.exists():
        canvas.drawImage(str(footer), 0, 0, width=width, height=18 * mm, preserveAspectRatio=False, mask="auto")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.white)
    canvas.drawRightString(width - 8 * mm, 6 * mm, f"Página {document.page}")
