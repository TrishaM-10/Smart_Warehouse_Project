from flask import Flask, render_template, request, redirect, url_for, flash
from database.db_connection import get_db_connection
from mysql.connector import IntegrityError

app = Flask(__name__)
app.secret_key = "warehouse-development-key"


# ---------------- DASHBOARD ----------------

@app.route('/')
def dashboard():
    return render_template('dashboard.html')


# ---------------- DEMAND PREDICTION ----------------

@app.route('/prediction')
def prediction():
    return render_template('prediction.html')


# ---------------- INVENTORY / STOCK MANAGEMENT ----------------

@app.route('/inventory', methods=['GET', 'POST'])
def inventory():

    db = get_db_connection()

    if db is None:
        return "Database connection failed!"

    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        try:
            product_id = int(request.form['product_id'])
            movement_type = request.form['movement_type']
            quantity = int(request.form['quantity'])
            remarks = request.form.get('remarks', '')

            if quantity <= 0 or movement_type not in ['IN', 'OUT']:
                raise ValueError("Enter valid stock details.")

            cursor.execute(
                "SELECT current_stock FROM products WHERE product_id=%s",
                (product_id,)
            )

            product = cursor.fetchone()

            if not product:
                raise ValueError("Product not found.")

            current_stock = product['current_stock'] or 0

            if movement_type == 'OUT':
                if quantity > current_stock:
                    raise ValueError("Insufficient stock available!")
                new_stock = current_stock - quantity
            else:
                new_stock = current_stock + quantity

            cursor.execute("""
                UPDATE products
                SET current_stock=%s
                WHERE product_id=%s
            """, (new_stock, product_id))

            cursor.execute("""
                INSERT INTO stock_movements
                (product_id, movement_type, quantity, remarks)
                VALUES (%s, %s, %s, %s)
            """, (product_id, movement_type, quantity, remarks))

            db.commit()
            flash("Stock updated successfully!", "success")

        except ValueError as error:
            db.rollback()
            flash(str(error), "error")

        except Exception as error:
            db.rollback()
            print("Stock Error:", error)
            flash("Unable to update stock.", "error")

        cursor.close()
        db.close()
        return redirect(url_for('inventory'))

    cursor.execute("""
        SELECT product_id, product_name, current_stock
        FROM products ORDER BY product_name
    """)
    products = cursor.fetchall()

    cursor.execute("""
        SELECT sm.*, p.product_name
        FROM stock_movements sm
        JOIN products p ON sm.product_id=p.product_id
        ORDER BY sm.movement_date DESC
    """)
    movements = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        'inventory.html',
        products=products,
        movements=movements
    )


# ---------------- SALES MANAGEMENT ----------------

@app.route('/sales', methods=['GET', 'POST'])
def sales():

    db = get_db_connection()

    if db is None:
        return "Database connection failed!"

    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        try:
            product_id = int(request.form['product_id'])
            quantity = int(request.form['quantity'])
            selling_price = float(request.form['selling_price'])
            sale_date = request.form['sale_date']

            if quantity <= 0 or selling_price <= 0:
                raise ValueError("Enter a valid quantity and selling price.")

            # Lock product row while processing the sale
            cursor.execute("""
                SELECT product_name, current_stock
                FROM products
                WHERE product_id=%s
                FOR UPDATE
            """, (product_id,))

            product = cursor.fetchone()

            if not product:
                raise ValueError("Product not found.")

            current_stock = product['current_stock'] or 0

            if quantity > current_stock:
                raise ValueError(
                    f"Insufficient stock! Available quantity: {current_stock}"
                )

            total_amount = quantity * selling_price
            new_stock = current_stock - quantity

            # Save sale record
            cursor.execute("""
                INSERT INTO sales
                (product_id, quantity_sold, selling_price,
                 total_amount, sale_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                product_id,
                quantity,
                selling_price,
                total_amount,
                sale_date
            ))

            # Deduct sold quantity from inventory
            cursor.execute("""
                UPDATE products
                SET current_stock=%s
                WHERE product_id=%s
            """, (new_stock, product_id))

            # Record outgoing stock movement
            cursor.execute("""
                INSERT INTO stock_movements
                (product_id, movement_type, quantity, remarks)
                VALUES (%s, 'OUT', %s, %s)
            """, (
                product_id,
                quantity,
                "Stock deducted through sales"
            ))

            db.commit()
            flash("Sale recorded and stock updated successfully!", "success")

        except ValueError as error:
            db.rollback()
            flash(str(error), "error")

        except Exception as error:
            db.rollback()
            print("Sales Error:", error)
            flash("Unable to record sale.", "error")

        cursor.close()
        db.close()

        return redirect(url_for('sales'))

    cursor.execute("""
        SELECT product_id, product_name, current_stock, unit_price
        FROM products
        ORDER BY product_name
    """)
    products = cursor.fetchall()

    cursor.execute("""
        SELECT s.*, p.product_name
        FROM sales s
        JOIN products p ON s.product_id=p.product_id
        ORDER BY s.sale_date DESC, s.sale_id DESC
    """)
    sales_history = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) AS total_transactions,
            COALESCE(SUM(quantity_sold), 0) AS total_items_sold,
            COALESCE(SUM(total_amount), 0) AS total_revenue
        FROM sales
    """)
    sales_summary = cursor.fetchone()

    cursor.close