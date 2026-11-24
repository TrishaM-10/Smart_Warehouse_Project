from flask import Flask, render_template, request, redirect, url_for, flash
from database.db_connection import get_db_connection
from mysql.connector import IntegrityError
from ml_model.prediction_routes import prediction_bp

app = Flask(__name__)
app.secret_key = "warehouse-development-key"

# Register ML Demand Prediction Blueprint
app.register_blueprint(prediction_bp)


# ---------------- DASHBOARD ----------------

@app.route('/')
def dashboard():
    return render_template('dashboard.html')


# ---------------- INVENTORY MANAGEMENT ----------------

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
        FROM products
        ORDER BY product_name
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
                raise ValueError("Enter valid quantity and selling price.")

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

            cursor.execute("""
                INSERT INTO sales
                (product_id, quantity_sold, selling_price,
                 total_amount, sale_date)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                product_id, quantity, selling_price,
                total_amount, sale_date
            ))

            cursor.execute("""
                UPDATE products
                SET current_stock=%s
                WHERE product_id=%s
            """, (new_stock, product_id))

            cursor.execute("""
                INSERT INTO stock_movements
                (product_id, movement_type, quantity, remarks)
                VALUES (%s, 'OUT', %s, %s)
            """, (
                product_id, quantity,
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

    cursor.close()
    db.close()

    return render_template(
        'sales.html',
        products=products,
        sales_history=sales_history,
        sales_summary=sales_summary
    )


# ---------------- REORDER MANAGEMENT ----------------

@app.route('/reorder')
def reorder():

    db = get_db_connection()
    if db is None:
        return "Database connection failed!"

    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            p.product_id,
            p.product_name,
            p.current_stock,
            p.minimum_stock,
            p.unit_price,
            s.supplier_name,
            s.phone,
            s.delivery_lead_time,

            GREATEST(
                (p.minimum_stock * 2) - p.current_stock,
                0
            ) AS suggested_quantity

        FROM products p

        LEFT JOIN suppliers s
        ON p.supplier_id = s.supplier_id

        WHERE p.current_stock <= p.minimum_stock

        ORDER BY p.current_stock ASC
    """)

    reorder_products = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(*) AS total_products,
            COALESCE(SUM(
                GREATEST((minimum_stock * 2) - current_stock, 0)
            ), 0) AS total_reorder_quantity
        FROM products
        WHERE current_stock <= minimum_stock
    """)

    reorder_summary = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template(
        'reorder.html',
        reorder_products=reorder_products,
        reorder_summary=reorder_summary
    )


# ---------------- REPORTS & ANALYTICS ----------------

@app.route('/reports')
def reports():

    db = get_db_connection()

    if db is None:
        return "Database connection failed!"

    cursor = db.cursor(dictionary=True)

    try:

        cursor.execute("""
            SELECT COUNT(*) AS total_products
            FROM products
        """)
        total_products = cursor.fetchone()['total_products']

        cursor.execute("""
            SELECT COALESCE(SUM(quantity_sold), 0) AS total_sales
            FROM sales
        """)
        total_sales = cursor.fetchone()['total_sales']

        cursor.execute("""
            SELECT COALESCE(
                SUM(current_stock * unit_price), 0
            ) AS inventory_value
            FROM products
        """)
        inventory_value = cursor.fetchone()['inventory_value']

        cursor.execute("""
            SELECT COUNT(*) AS reorder_items
            FROM products
            WHERE current_stock <= minimum_stock
        """)
        reorder_items = cursor.fetchone()['reorder_items']

        cursor.execute("""
            SELECT
                p.product_name,
                c.category_name,
                p.current_stock,
                p.minimum_stock,
                p.unit_price,
                (p.current_stock * p.unit_price) AS stock_value

            FROM products p

            LEFT JOIN categories c
            ON p.category_id = c.category_id

            ORDER BY p.product_name
        """)
        inventory_report = cursor.fetchall()

        cursor.execute("""
            SELECT
                s.sale_date,
                p.product_name,
                s.quantity_sold,
                s.selling_price,
                s.total_amount

            FROM sales s

            JOIN products p
            ON s.product_id = p.product_id

            ORDER BY s.sale_date DESC, s.sale_id DESC
        """)
        sales_report = cursor.fetchall()

        cursor.execute("""
            SELECT
                p.product_name,
                COALESCE(SUM(s.quantity_sold), 0) AS total_demand

            FROM products p

            LEFT JOIN sales s
            ON p.product_id = s.product_id

            GROUP BY p.product_id, p.product_name

            ORDER BY total_demand DESC
        """)
        demand_report = cursor.fetchall()

        cursor.execute("""
            SELECT
                COUNT(*) AS total_products,

                SUM(
                    CASE
                        WHEN current_stock = 0 THEN 1
                        ELSE 0
                    END
                ) AS out_of_stock,

                SUM(
                    CASE
                        WHEN current_stock > 0
                        AND current_stock <= minimum_stock
                        THEN 1
                        ELSE 0
                    END
                ) AS low_stock,

                SUM(
                    CASE
                        WHEN current_stock > minimum_stock
                        THEN 1
                        ELSE 0
                    END
                ) AS healthy_stock

            FROM products
        """)

        stock_summary = cursor.fetchone()

        inventory_insights = []

        out_of_stock = stock_summary['out_of_stock'] or 0
        low_stock = stock_summary['low_stock'] or 0
        healthy_stock = stock_summary['healthy_stock'] or 0

        if out_of_stock > 0:
            inventory_insights.append({
                'title': 'Out of Stock Alert',
                'message': (
                    f'{out_of_stock} product(s) have completely run out '
                    'of stock. Immediate replenishment is recommended.'
                )
            })

        if low_stock > 0:
            inventory_insights.append({
                'title': 'Low Stock Alert',
                'message': (
                    f'{low_stock} product(s) are at or below their '
                    'minimum stock level.'
                )
            })

        if healthy_stock > 0:
            inventory_insights.append({
                'title': 'Healthy Inventory',
                'message': (
                    f'{healthy_stock} product(s) currently have stock '
                    'above their minimum stock level.'
                )
            })

        if total_products == 0:
            inventory_insights.append({
                'title': 'No Products Found',
                'message': 'Add products to start tracking warehouse performance.'
            })

        return render_template(
            'reports.html',
            total_products=total_products,
            total_sales=total_sales,
            inventory_value=inventory_value,
            reorder_items=reorder_items,
            inventory_report=inventory_report,
            sales_report=sales_report,
            demand_report=demand_report,
            inventory_insights=inventory_insights
        )

    except Exception as error:
        print("Reports Error:", error)
        return "Unable to generate reports. Please check the terminal for details."

    finally:
        cursor.close()
        db.close()


# ---------------- PRODUCT MANAGEMENT ----------------

@app.route('/products', methods=['GET', 'POST'])
def products():

    db = get_db_connection()

    if db is None:
        return "Database connection failed!"

    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        cursor.execute("""
            INSERT INTO products
            (product_name, category_id, supplier_id,
             unit_price, current_stock, minimum_stock)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            request.form['product_name'],
            request.form['category_id'] or None,
            request.form['supplier_id'] or None,
            request.form['unit_price'],
            request.form['current_stock'],
            request.form['minimum_stock']
        ))

        db.commit()
        flash("Product added successfully!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('products'))

    cursor.execute("""
        SELECT p.*, c.category_name, s.supplier_name
        FROM products p
        LEFT JOIN categories c ON p.category_id=c.category_id
        LEFT JOIN suppliers s ON p.supplier_id=s.supplier_id
        ORDER BY p.product_id DESC
    """)
    product_list = cursor.fetchall()

    cursor.execute("SELECT * FROM categories ORDER BY category_name")
    categories = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers ORDER BY supplier_name")
    suppliers = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        'products.html',
        products=product_list,
        categories=categories,
        suppliers=suppliers
    )


@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
def edit_product(product_id):

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        cursor.execute("""
            UPDATE products
            SET product_name=%s,
                category_id=%s,
                supplier_id=%s,
                unit_price=%s,
                current_stock=%s,
                minimum_stock=%s
            WHERE product_id=%s
        """, (
            request.form['product_name'],
            request.form['category_id'] or None,
            request.form['supplier_id'] or None,
            request.form['unit_price'],
            request.form['current_stock'],
            request.form['minimum_stock'],
            product_id
        ))

        db.commit()
        flash("Product updated successfully!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('products'))

    cursor.execute(
        "SELECT * FROM products WHERE product_id=%s",
        (product_id,)
    )
    product = cursor.fetchone()

    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        'edit_product.html',
        product=product,
        categories=categories,
        suppliers=suppliers
    )


@app.route('/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):

    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute(
            "DELETE FROM products WHERE product_id=%s",
            (product_id,)
        )
        db.commit()
        flash("Product deleted successfully!", "success")

    except IntegrityError:
        db.rollback()
        flash("Cannot delete a product with related records.", "error")

    cursor.close()
    db.close()
    return redirect(url_for('products'))


# ---------------- CATEGORY MANAGEMENT ----------------

@app.route('/categories', methods=['GET', 'POST'])
def categories():

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        cursor.execute("""
            INSERT INTO categories (category_name, description)
            VALUES (%s, %s)
        """, (
            request.form['category_name'],
            request.form['description']
        ))

        db.commit()
        flash("Category added successfully!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('categories'))

    cursor.execute("SELECT * FROM categories ORDER BY category_id DESC")
    category_list = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template('categories.html', categories=category_list)


@app.route('/categories/edit/<int:category_id>', methods=['GET', 'POST'])
def edit_category(category_id):

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        cursor.execute("""
            UPDATE categories
            SET category_name=%s, description=%s
            WHERE category_id=%s
        """, (
            request.form['category_name'],
            request.form['description'],
            category_id
        ))

        db.commit()
        flash("Category updated successfully!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('categories'))

    cursor.execute(
        "SELECT * FROM categories WHERE category_id=%s",
        (category_id,)
    )
    category = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template('edit_category.html', category=category)


@app.route('/categories/delete/<int:category_id>', methods=['POST'])
def delete_category(category_id):

    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute(
            "DELETE FROM categories WHERE category_id=%s",
            (category_id,)
        )
        db.commit()
        flash("Category deleted successfully!", "success")

    except IntegrityError:
        db.rollback()
        flash("Cannot delete a category linked to products.", "error")

    cursor.close()
    db.close()
    return redirect(url_for('categories'))


# ---------------- SUPPLIER MANAGEMENT ----------------

@app.route('/suppliers', methods=['GET', 'POST'])
def suppliers():

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        cursor.execute("""
            INSERT INTO suppliers
            (supplier_name, contact_person, phone, email,
             address, delivery_lead_time)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            request.form['supplier_name'],
            request.form['contact_person'],
            request.form['phone'],
            request.form['email'],
            request.form['address'],
            request.form['delivery_lead_time']
        ))

        db.commit()
        flash("Supplier added successfully!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('suppliers'))

    cursor.execute("SELECT * FROM suppliers ORDER BY supplier_id DESC")
    supplier_list = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template('suppliers.html', suppliers=supplier_list)


@app.route('/suppliers/edit/<int:supplier_id>', methods=['GET', 'POST'])
def edit_supplier(supplier_id):

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == 'POST':

        cursor.execute("""
            UPDATE suppliers
            SET supplier_name=%s,
                contact_person=%s,
                phone=%s,
                email=%s,
                address=%s,
                delivery_lead_time=%s
            WHERE supplier_id=%s
        """, (
            request.form['supplier_name'],
            request.form['contact_person'],
            request.form['phone'],
            request.form['email'],
            request.form['address'],
            request.form['delivery_lead_time'],
            supplier_id
        ))

        db.commit()
        flash("Supplier updated successfully!", "success")

        cursor.close()
        db.close()
        return redirect(url_for('suppliers'))

    cursor.execute(
        "SELECT * FROM suppliers WHERE supplier_id=%s",
        (supplier_id,)
    )
    supplier = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template('edit_supplier.html', supplier=supplier)


@app.route('/suppliers/delete/<int:supplier_id>', methods=['POST'])
def delete_supplier(supplier_id):

    db = get_db_connection()
    cursor = db.cursor()

    try:
        cursor.execute(
            "DELETE FROM suppliers WHERE supplier_id=%s",
            (supplier_id,)
        )
        db.commit()
        flash("Supplier deleted successfully!", "success")

    except IntegrityError:
        db.rollback()
        flash("Cannot delete a supplier linked to products.", "error")

    cursor.close()
    db.close()
    return redirect(url_for('suppliers'))


# ---------------- RUN APPLICATION ----------------

if __name__ == '__main__':
    app.run(debug=True)