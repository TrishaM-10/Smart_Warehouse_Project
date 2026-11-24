from flask import Blueprint, render_template, request
from database.db_connection import get_db_connection
from ml_model.prediction import forecast_product

prediction_bp = Blueprint('prediction_module', __name__)


@prediction_bp.route('/prediction', methods=['GET', 'POST'])
def prediction_page():

    db = get_db_connection()

    if db is None:
        return "Database connection failed!"

    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT product_id, product_name
        FROM products
        ORDER BY product_name
    """)

    products = cursor.fetchall()

    cursor.close()
    db.close()

    prediction = None
    selected_product = None

    if request.method == 'POST':

        selected_product = int(request.form['product_id'])

        prediction = forecast_product(selected_product)

    return render_template(
        'prediction.html',
        products=products,
        prediction=prediction,
        selected_product=selected_product
    )