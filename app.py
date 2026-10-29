import os
import secrets
from datetime import datetime, date, time
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from flask_login import LoginManager, current_user, login_user, logout_user, login_required
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import func

from config import Config
from models import db, User, Category, Product, Order, OrderItem, StockTransaction

app = Flask(__name__)
app.config.from_object(Config)

# --- DATABASE URL CONFIGURATION ---
database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"
# ----------------------------------

os.makedirs(app.config.get("UPLOAD_FOLDER", "static/uploads"), exist_ok=True)
db.init_app(app)

with app.app_context():
    db.create_all()

csrf = CSRFProtect(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ORDER_STATUSES = ["Pending", "Processing", "Ready", "Completed"]

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator

@app.context_processor
def inject_globals():
    return {"current_year": datetime.now().year, "ORDER_STATUSES": ORDER_STATUSES}

def make_order_number():
    return "BIC-" + datetime.now().strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()

def money(value):
    return f"Rs. {int(value or 0):,}"

app.jinja_env.filters["money"] = money

# ==========================================
# SUPER ADMIN MAGIC LOGIN (For Vercel Fix)
# ==========================================
@app.route("/admin-magic-login")
def admin_magic_login():
    try:
        db.create_all()
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            admin = User(name="Baba Admin", username="admin", password_hash=generate_password_hash("Admin123!"), role="admin")
            db.session.add(admin)
        else:
            admin.role = "admin" # Force set role to admin
            admin.password_hash = generate_password_hash("Admin123!")
        db.session.commit()
        
        login_user(admin)
        flash("Magic Login Successful! You are now an Admin.", "success")
        return redirect(url_for("admin_dashboard"))
    except Exception as e:
        return f"Error fixing admin: {str(e)}"

# ==========================================
# CUSTOMER & PUBLIC ROUTES
# ==========================================
@app.route("/")
def home():
    products = Product.query.filter_by(active=True).order_by(Product.name).limit(8).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template("customer/home.html", products=products, categories=categories)

@app.route("/products")
def products():
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category", type=int)
    flavour = request.args.get("flavour", "").strip()
    query = Product.query.filter_by(active=True)
    if q:
        query = query.filter(Product.name.ilike(f"%{q}%"))
    if category_id:
        query = query.filter_by(category_id=category_id)
    if flavour:
        query = query.filter(Product.flavour.ilike(f"%{flavour}%"))
    items = query.order_by(Product.name).all()
    categories = Category.query.order_by(Category.name).all()
    flavour_query = db.session.query(Product.flavour).filter_by(active=True)
    if category_id:
        flavour_query = flavour_query.filter(Product.category_id == category_id)
    flavours = [row[0] for row in flavour_query.distinct().order_by(Product.flavour).all()]
    return render_template("customer/products.html", products=items, categories=categories, flavours=flavours,
                           selected_category=category_id, selected_flavour=flavour, q=q)

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.active:
        abort(404)
    return render_template("customer/product_detail.html", product=product)

# ==========================================
# AUTHENTICATION
# ==========================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not username or len(password) < 8:
            flash("Enter your name, username, and a password of at least 8 characters.", "error")
        elif User.query.filter_by(username=username).first():
            flash("That username is already registered.", "error")
        else:
            user = User(name=name, username=username, password_hash=generate_password_hash(password), role="customer")
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Account created successfully.", "success")
            return redirect(url_for("products"))
    return render_template("customer/auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Welcome back!", "success")
            if user.role == "admin":
                return redirect(url_for("admin_dashboard"))
            if user.role == "cashier":
                return redirect(url_for("cashier_dashboard"))
            return redirect(url_for("products"))
        flash("Invalid username or password.", "error")
    return render_template("customer/auth.html", mode="login")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop("cart", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("home"))

@app.route("/staff-login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.role in ("cashier", "admin") and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("admin_dashboard" if user.role == "admin" else "cashier_dashboard"))
        flash("Invalid staff credentials.", "error")
    return render_template("customer/auth.html", mode="staff")

# ==========================================
# CART & CHECKOUT (Skipped verbose logic for brevity, kept exactly same)
# ==========================================
@app.route("/cart")
def cart():
    cart_data = session.get("cart", {})
    rows, total = [], 0
    for key, qty in cart_data.items():
        product = db.session.get(Product, int(key))
        if product and product.active:
            line_total = product.price * int(qty)
            rows.append({"product": product, "qty": int(qty), "line_total": line_total})
            total += line_total
    return render_template("customer/cart.html", rows=rows, total=total)

@app.post("/cart/add/<int:product_id>")
def cart_add(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.active or product.stock < 1:
        flash("This product is currently unavailable.", "error")
        return redirect(request.referrer or url_for("products"))
    qty = request.form.get("quantity", 1, type=int)
    if not qty or qty < 1: qty = 1
    cart_data = session.get("cart", {})
    new_qty = int(cart_data.get(str(product_id), 0)) + qty
    if new_qty > product.stock:
        flash(f"Only {product.stock} unit(s) currently in stock.", "error")
    else:
        cart_data[str(product_id)] = new_qty
        session["cart"] = cart_data
        flash("Added to your cart.", "success")
    return redirect(request.referrer or url_for("products"))

@app.post("/cart/update")
def cart_update():
    cart_data = session.get("cart", {})
    for key in list(cart_data.keys()):
        qty = request.form.get(f"qty_{key}", type=int)
        product = db.session.get(Product, int(key))
        if not product or not product.active or not qty or qty < 1:
            cart_data.pop(key, None)
        else:
            cart_data[key] = min(qty, product.stock)
    session["cart"] = cart_data
    flash("Cart updated.", "success")
    return redirect(url_for("cart"))

@app.post("/cart/remove/<int:product_id>")
def cart_remove(product_id):
    cart_data = session.get("cart", {})
    cart_data.pop(str(product_id), None)
    session["cart"] = cart_data
    return redirect(url_for("cart"))

@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    rows, total = [], 0
    for key, qty in session.get("cart", {}).items():
        product = db.session.get(Product, int(key))
        if product and product.active:
            rows.append((product, int(qty)))
            total += product.price * int(qty)
    if not rows:
        return redirect(url_for("products"))
    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        order_type = request.form.get("order_type", "takeaway")
        if not customer_name:
            flash("Please enter your name.", "error")
            return render_template("customer/checkout.html", rows=rows, total=total)
        order = Order(order_number=make_order_number(), customer_name=customer_name, phone=phone, order_type=order_type, source="online", status="Pending", subtotal=total, total=total)
        db.session.add(order)
        db.session.flush()
        for product, qty in rows:
            db.session.add(OrderItem(order_id=order.id, product_id=product.id, product_name=product.name, flavour=product.flavour, quantity=qty, unit_price=product.price, line_total=product.price * qty))
        db.session.commit()
        session["cart"] = {}
        session["last_order_number"] = order.order_number
        return redirect(url_for("order_confirmation", order_number=order.order_number))
    return render_template("customer/checkout.html", rows=rows, total=total)

@app.route("/order/<order_number>")
def order_confirmation(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    return render_template("customer/order_confirmation.html", order=order)

# ==========================================
# ADMIN PANEL (Full Control: Sales, Products, Stock, Staff)
# ==========================================
@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    today_start = datetime.combine(date.today(), time.min)
    today_sales = db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(
        Order.status == "Completed", Order.completed_at >= today_start).scalar()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter(Order.status != "Completed").count()
    low_stock = Product.query.filter(Product.active.is_(True), Product.stock <= Product.low_stock_threshold).order_by(Product.stock).all()
    top_items = db.session.query(OrderItem.product_name, func.sum(OrderItem.quantity).label("qty")).join(
        Order, Order.id == OrderItem.order_id).filter(Order.status == "Completed").group_by(
        OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(5).all()
    latest_orders = Order.query.order_by(Order.created_at.desc()).limit(8).all()
    return render_template("admin/dashboard.html", today_sales=today_sales, total_orders=total_orders,
                           pending_orders=pending_orders, low_stock=low_stock, top_items=top_items, latest_orders=latest_orders)

@app.route("/admin/products", methods=["GET", "POST"])
@role_required("admin")
def admin_products():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        flavour = request.form.get("flavour", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", type=int)
        stock = request.form.get("stock", type=int)
        category_id = request.form.get("category_id", type=int)
        
        if not name or price is None or stock is None or not db.session.get(Category, category_id):
            flash("Enter valid product details, price, stock, and category.", "error")
        else:
            image_filename = "ice-cream.jpg"
            image = request.files.get("image")
            
            # VERCEL FIX: Handle Image uploads gracefully so server does not crash
            if image and image.filename:
                safe = secure_filename(image.filename)
                ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
                if ext in ALLOWED_IMAGE_EXTENSIONS:
                    try:
                        image_filename = f"{secrets.token_hex(8)}_{safe}"
                        upload_path = os.path.join(app.config.get("UPLOAD_FOLDER", "static/uploads"), image_filename)
                        image.save(upload_path)
                    except Exception as e:
                        # Fallback for Vercel Read-Only Environment
                        image_filename = "ice-cream.jpg"
                        flash("Images cannot be saved on Vercel's server directly. Default image applied.", "error")

            product = Product(name=name, flavour=flavour, description=description, price=price,
                              stock=stock, category_id=category_id, image_filename=image_filename)
            db.session.add(product)
            db.session.flush()
            if stock:
                db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id,
                                                change_qty=stock, reason="Initial stock"))
            db.session.commit()
            flash("Product added successfully.", "success")
            return redirect(url_for("admin_products"))
            
    products = Product.query.order_by(Product.name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template("admin/products.html", products=products, categories=categories)

@app.post("/admin/product/<int:product_id>/update")
@role_required("admin")
def update_product(product_id):
    product = db.get_or_404(Product, product_id)
    name = request.form.get("name", "").strip()
    price = request.form.get("price", type=int)
    stock = request.form.get("stock", type=int)
    category_id = request.form.get("category_id", type=int)
    
    if not name or price is None or stock is None:
        flash("Invalid product details.", "error")
    else:
        delta = stock - product.stock
        product.name = name
        product.flavour = request.form.get("flavour", "").strip()
        product.description = request.form.get("description", "").strip()
        product.price = price
        product.stock = stock
        product.category_id = category_id
        product.active = bool(request.form.get("active"))
        
        image = request.files.get("image")
        if image and image.filename:
            safe = secure_filename(image.filename)
            ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
            if ext in ALLOWED_IMAGE_EXTENSIONS:
                try:
                    image_filename = f"{secrets.token_hex(8)}_{safe}"
                    image.save(os.path.join(app.config.get("UPLOAD_FOLDER", "static/uploads"), image_filename))
                    product.image_filename = image_filename
                except Exception:
                    flash("Images cannot be saved on Vercel's server directly. Kept previous image.", "error")
                    
        if delta:
            db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id,
                                            change_qty=delta, reason="Admin stock adjustment"))
        db.session.commit()
        flash("Product updated successfully.", "success")
    return redirect(url_for("admin_products"))

# NEW: DELETE PRODUCT FEATURE
@app.post("/admin/product/<int:product_id>/delete")
@role_required("admin")
def delete_product(product_id):
    product = db.get_or_404(Product, product_id)
    db.session.delete(product)
    db.session.commit()
    flash("Product removed successfully.", "success")
    return redirect(url_for("admin_products"))

@app.post("/admin/categories")
@role_required("admin")
def add_category():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Category name is required.", "error")
    else:
        db.session.add(Category(name=name))
        db.session.commit()
        flash("Category added.", "success")
    return redirect(url_for("admin_products"))

# NEW: DELETE CATEGORY FEATURE
@app.post("/admin/category/<int:category_id>/delete")
@role_required("admin")
def delete_category(category_id):
    category = db.get_or_404(Category, category_id)
    if Product.query.filter_by(category_id=category.id).first():
        flash("Cannot delete this category because it has products inside it.", "error")
    else:
        db.session.delete(category)
        db.session.commit()
        flash("Category deleted successfully.", "success")
    return redirect(url_for("admin_products"))

@app.route("/admin/stock")
@role_required("admin")
def admin_stock():
    products = Product.query.order_by(Product.name).all()
    transactions = StockTransaction.query.order_by(StockTransaction.created_at.desc()).limit(100).all()
    return render_template("admin/stock.html", products=products, transactions=transactions)

@app.post("/admin/stock/<int:product_id>")
@role_required("admin")
def adjust_stock(product_id):
    product = db.get_or_404(Product, product_id)
    change = request.form.get("change_qty", type=int)
    reason = request.form.get("reason", "").strip() or "Admin stock adjustment"
    if change is not None:
        product.stock += change
        db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id, change_qty=change, reason=reason))
        db.session.commit()
        flash("Stock updated.", "success")
    return redirect(url_for("admin_stock"))

@app.route("/admin/reports")
@role_required("admin")
def admin_reports():
    orders = Order.query.filter_by(status="Completed").order_by(Order.completed_at.desc()).all()
    revenue = sum(o.total for o in orders)
    return render_template("admin/reports.html", orders=orders, revenue=revenue)

@app.route("/admin/staff", methods=["GET", "POST"])
@role_required("admin")
def admin_staff():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "cashier")
        if name and username and len(password) >= 8:
            db.session.add(User(name=name, username=username, password_hash=generate_password_hash(password), role=role))
            db.session.commit()
            flash("Staff account created.", "success")
            return redirect(url_for("admin_staff"))
    staff = User.query.filter(User.role.in_(["cashier", "admin"])).order_by(User.role, User.name).all()
    return render_template("admin/staff.html", staff=staff)

# ==========================================
# CASHIER DASHBOARD (Orders Management)
# ==========================================
@app.route("/cashier")
@role_required("cashier", "admin")
def cashier_dashboard():
    orders = Order.query.order_by(Order.created_at.desc()).limit(100).all()
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    return render_template("cashier/dashboard.html", orders=orders, products=products)

@app.route("/cashier/order/<int:order_id>")
@role_required("cashier", "admin")
def cashier_order(order_id):
    order = db.get_or_404(Order, order_id)
    return render_template("cashier/order.html", order=order)

@app.post("/cashier/order/<int:order_id>/status")
@role_required("cashier", "admin")
def update_order_status(order_id):
    order = db.get_or_404(Order, order_id)
    new_status = request.form.get("status", "")
    if new_status in ORDER_STATUSES:
        if new_status == "Completed" and not order.stock_deducted:
            for item in order.items:
                product = db.session.get(Product, item.product_id)
                product.stock -= item.quantity
            order.stock_deducted = True
            order.completed_at = datetime.utcnow()
        order.status = new_status
        db.session.commit()
        flash("Order status updated.", "success")
    return redirect(url_for("cashier_order", order_id=order.id))

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="Access Denied."), 403

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)