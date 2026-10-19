import csv
import io
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, render_template
from flask_login import login_required

from app.extensions import db
from app.localtime import format_datetime
from app.models import Delivery, Employee, Solicitation, StockMovement, StockVariant


bp = Blueprint("main", __name__)


@bp.get("/")
@login_required
def dashboard():
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    metrics = {
        "pending_requests": db.session.scalar(db.select(db.func.count()).select_from(Solicitation).where(Solicitation.status.in_(["pending", "separated", "partial"]))),
        "deliveries_30_days": db.session.scalar(db.select(db.func.count()).select_from(Delivery).where(Delivery.status == "completed", Delivery.delivered_at >= thirty_days_ago)),
        "low_stock": db.session.scalar(db.select(db.func.count()).select_from(StockVariant).where(StockVariant.current_quantity > 0, StockVariant.minimum_quantity.is_not(None), StockVariant.current_quantity <= StockVariant.minimum_quantity)),
        "zero_stock": db.session.scalar(db.select(db.func.count()).select_from(StockVariant).where(StockVariant.current_quantity <= 0)),
    }
    alerts = db.session.scalars(db.select(StockVariant).where(StockVariant.active.is_(True), StockVariant.minimum_quantity.is_not(None), StockVariant.current_quantity <= StockVariant.minimum_quantity).order_by(StockVariant.current_quantity).limit(8)).all()
    recent_deliveries = db.session.scalars(db.select(Delivery).order_by(Delivery.delivered_at.desc()).limit(6)).all()
    return render_template("main/dashboard.html", metrics=metrics, alerts=alerts, recent_deliveries=recent_deliveries)


@bp.get("/relatorios")
@login_required
def reports():
    movements = db.session.scalars(db.select(StockMovement).order_by(StockMovement.created_at.desc()).limit(200)).all()
    deliveries = db.session.scalars(db.select(Delivery).order_by(Delivery.delivered_at.desc()).limit(100)).all()
    return render_template("main/reports.html", movements=movements, deliveries=deliveries)


@bp.get("/relatorios/<string:report_name>.csv")
@login_required
def report_csv(report_name: str):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    if report_name == "estoque":
        writer.writerow(["Categoria", "EPI", "Tamanho", "CA", "Saldo", "Estoque minimo", "Situacao"])
        for item in db.session.scalars(db.select(StockVariant).order_by(StockVariant.product_id, StockVariant.size)):
            writer.writerow([item.product.category.name, item.product.name, item.size or "Unico", item.product.ca_number or "", item.current_quantity, item.minimum_quantity if item.minimum_quantity is not None else "", item.stock_level])
    elif report_name == "entregas":
        writer.writerow(["Comprovante", "Data", "Colaborador", "Funcao", "EPI", "Tamanho", "CA", "Quantidade", "Situacao", "Entregue por"])
        for delivery in db.session.scalars(db.select(Delivery).order_by(Delivery.delivered_at.desc())):
            for item in delivery.items:
                writer.writerow([delivery.receipt_number, format_datetime(delivery.delivered_at), delivery.employee.name, delivery.employee.job_title or "", item.variant.product.name, item.variant.size or "Unico", item.variant.product.ca_number or "", item.quantity, delivery.status, delivery.delivered_by.full_name])
    elif report_name == "colaboradores":
        writer.writerow(["Nome", "Funcao", "Camisa", "Calca", "Calcado", "Ativo"])
        for item in db.session.scalars(db.select(Employee).order_by(Employee.name)):
            writer.writerow([item.name, item.job_title or "", item.shirt_size or "", item.pants_size or "", item.shoe_size or "", "Sim" if item.active else "Nao"])
    else:
        return Response("Relatório inexistente.", status=404, content_type="text/plain; charset=utf-8")
    data = "\ufeff" + output.getvalue()
    return Response(data, headers={"Content-Disposition": f'attachment; filename="relatorio-{report_name}.csv"'}, content_type="text/csv; charset=utf-8")
