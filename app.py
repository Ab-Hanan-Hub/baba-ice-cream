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

# --- NAYA DATABASE CODE YAHAN HAI ---
# --- DATABASE URL CONFIGURATION ---
database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if database_url:
    # Explicitly psycopg2 driver specify karein taake SQLAlchemy psycopg v3 na dhoonde
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///site.db"
# ----------------------------------
# -------------------------------------

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
db.init_app(app)

# Vercel par automatically tables banane ke liye:
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

@app.post("/chat")
@csrf.exempt
def chatbot_reply():
    """Simple menu-aware chatbot using current product and category data."""
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip().lower()
    if not message:
        return jsonify({"reply": "Please type a question about our menu."})

    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    available = [p for p in products if p.stock > 0]

    greetings = ("hi", "hello", "hey", "salam", "assalam")
    if any(message == word or message.startswith(word + " ") for word in greetings):
        return jsonify({"reply": "Hello! Welcome to Baba Ice Cream 🍦. Ask me about flavours, categories, prices, or products within your budget."})

    aliases = {
        "ice cream": ("ice cream", "icecream", "ice-cream", "flavour", "flavors", "flavours"),
        "coffee": ("coffee", "cappuccino", "latte", "espresso"),
        "shake": ("shake", "shakes", "milkshake", "milk shake"),
        "tea": ("tea", "chai"),
        "soda": ("soda", "sodas", "soft drink", "soft drinks"),
        "lemonade": ("lemonade", "lemonade"),
        "slush": ("slush", "slushie", "slushy"),
        "family pack": ("family pack", "family packs", "take home pack"),
        "topping": ("topping", "toppings", "sprinkles"),
    }
    category_words = {word for words in aliases.values() for word in words}
    requested_category = None
    for category in Category.query.order_by(Category.name).all():
        cname = category.name.lower()
        words = list(aliases.get(cname, (cname,)))
        for alias_key, alias_words in aliases.items():
            if alias_key in cname:
                words.extend(alias_words)
        words.append(cname)
        if any(word in message for word in words):
            requested_category = category
            break
    if requested_category:
        matches = [p for p in available if p.category_id == requested_category.id]
        if not matches:
            return jsonify({"reply": f"Sorry, there are no in-stock items in {requested_category.name} right now. Please ask about another category."})
        lines = [f"• {p.name} ({p.flavour}) — Rs. {p.price:,}" for p in matches[:12]]
        extra = f"\nAnd {len(matches) - 12} more item(s)." if len(matches) > 12 else ""
        return jsonify({"reply": f"Here are our {requested_category.name} options:\n" + "\n".join(lines) + extra})

    import re
    numbers = re.findall(r"\d+", message)
    if ("under" in message or "budget" in message or "within" in message) and numbers:
        budget = int(numbers[0])
        matches = [p for p in available if p.price <= budget]
        if matches:
            lines = [f"• {p.name} ({p.flavour}) — Rs. {p.price:,}" for p in matches[:10]]
            return jsonify({"reply": f"Available options up to Rs. {budget:,}:\n" + "\n".join(lines)})
        return jsonify({"reply": f"Sorry, no in-stock products are priced at Rs. {budget:,} or less."})

    words = [word for word in re.findall(r"[a-z0-9]+", message) if len(word) > 2 and word not in {"what", "which", "price", "cost", "show", "tell", "about", "have", "want", "like", "please", "recommend", "suggest", "much", "does", "for", "the", "and", "you", "your", "with", "can", "get", "give", "some", "item", "items"}]
    matches = [p for p in available if any(word in (p.name + " " + p.flavour + " " + (p.description or "")).lower() for word in words)]
    if matches:
        lines = [f"• {p.name} ({p.flavour}) — Rs. {p.price:,}" for p in matches[:10]]
        return jsonify({"reply": "Here are the matching available products:\n" + "\n".join(lines)})

    if "recommend" in message or "suggest" in message or "interest" in message:
        picks = available[:5]
        if picks:
            return jsonify({"reply": "Here are a few popular menu options to consider:\n" + "\n".join(f"• {p.name} ({p.flavour}) — Rs. {p.price:,}" for p in picks) + "\nTell me a category or flavour you like for a more specific suggestion."})

    categories = [c.name for c in Category.query.order_by(Category.name).all()]
    return jsonify({"reply": "I can help with menu items, prices, and budget suggestions. Try asking about: " + ", ".join(categories) + ". You can also ask, for example, 'show coffee' or 'items under 200'."})

@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db.get_or_404(Product, product_id)
    if not product.active:
        abort(404)
    return render_template("customer/product_detail.html", product=product)

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
    if not qty or qty < 1:
        qty = 1
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
        flash("Your cart is empty.", "error")
        return redirect(url_for("products"))
    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        order_type = request.form.get("order_type", "takeaway")
        if not customer_name or order_type not in ("takeaway", "dine-in"):
            flash("Please enter your name and select a valid order type.", "error")
            return render_template("customer/checkout.html", rows=rows, total=total)
        try:
            order = Order(order_number=make_order_number(),
                          customer_id=current_user.id if current_user.is_authenticated and current_user.role == "customer" else None,
                          customer_name=customer_name, phone=phone, order_type=order_type,
                          source="online", status="Pending", subtotal=total, total=total)
            db.session.add(order)
            db.session.flush()
            for product, qty in rows:
                if qty < 1 or product.stock < qty:
                    raise ValueError(f"Not enough stock for {product.name}. Please update your cart.")
                db.session.add(OrderItem(order_id=order.id, product_id=product.id,
                                         product_name=product.name, flavour=product.flavour,
                                         quantity=qty, unit_price=product.price,
                                         line_total=product.price * qty))
            db.session.commit()
            session["cart"] = {}
            session["last_order_number"] = order.order_number
            return redirect(url_for("order_confirmation", order_number=order.order_number))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        except Exception:
            db.session.rollback()
            flash("Could not place order. Please try again.", "error")
    return render_template("customer/checkout.html", rows=rows, total=total)

@app.route("/order/<order_number>")
def order_confirmation(order_number):
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    if session.get("last_order_number") != order_number and not (current_user.is_authenticated and (current_user.role == "admin" or order.customer_id == current_user.id)):
        abort(403)
    return render_template("customer/order_confirmation.html", order=order)

@app.route("/order-status", methods=["GET", "POST"])
def order_status():
    order = None
    if request.method == "POST":
        number = request.form.get("order_number", "").strip().upper()
        order = Order.query.filter_by(order_number=number).first()
        if not order:
            flash("No order found with that number.", "error")
    return render_template("customer/order_status.html", order=order)

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

@app.route("/cashier")
@role_required("cashier", "admin")
def cashier_dashboard():
    status_filter = request.args.get("status", "")
    query = Order.query
    if status_filter in ORDER_STATUSES:
        query = query.filter_by(status=status_filter)
    orders = query.order_by(Order.created_at.desc()).limit(200).all()
    counts = {s: Order.query.filter_by(status=s).count() for s in ORDER_STATUSES}
    products = Product.query.filter_by(active=True).order_by(Product.name).all()
    return render_template("cashier/dashboard.html", orders=orders, counts=counts, products=products, status_filter=status_filter)

@app.post("/cashier/walk-in")
@role_required("cashier", "admin")
def walk_in_order():
    name = request.form.get("customer_name", "Walk-in Customer").strip() or "Walk-in Customer"
    phone = request.form.get("phone", "").strip()
    product_ids = request.form.getlist("product_id")
    quantities = request.form.getlist("quantity")
    selections = {}
    for pid, qty in zip(product_ids, quantities):
        try:
            pid, qty = int(pid), int(qty)
        except ValueError:
            continue
        if qty > 0:
            selections[pid] = selections.get(pid, 0) + qty
    if not selections:
        flash("Add at least one product to the sale.", "error")
        return redirect(url_for("cashier_dashboard"))
    try:
        order = Order(order_number=make_order_number(), customer_name=name, phone=phone,
                      order_type="takeaway", source="walk-in", status="Pending")
        db.session.add(order)
        db.session.flush()
        total = 0
        for pid, qty in selections.items():
            product = db.session.get(Product, pid)
            if not product or not product.active or product.stock < qty:
                raise ValueError(f"Insufficient stock for product ID {pid}.")
            line = product.price * qty
            total += line
            db.session.add(OrderItem(order_id=order.id, product_id=product.id,
                                     product_name=product.name, flavour=product.flavour,
                                     quantity=qty, unit_price=product.price, line_total=line))
        order.subtotal = order.total = total
        db.session.commit()
        flash("Walk-in order created. Open it to print the bill and confirm sale.", "success")
        return redirect(url_for("cashier_order", order_id=order.id))
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("cashier_dashboard"))

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
    if new_status not in ORDER_STATUSES:
        flash("Invalid order status.", "error")
        return redirect(url_for("cashier_order", order_id=order.id))
    try:
        if new_status == "Completed" and not order.stock_deducted:
            for item in order.items:
                product = db.session.get(Product, item.product_id)
                if not product or product.stock < item.quantity:
                    raise ValueError(f"Insufficient stock for {item.product_name}.")
            for item in order.items:
                product = db.session.get(Product, item.product_id)
                product.stock -= item.quantity
                db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id,
                                                order_id=order.id, change_qty=-item.quantity,
                                                reason=f"Sale {order.order_number}"))
            order.stock_deducted = True
            order.completed_at = datetime.utcnow()
            order.billed = True
        order.status = new_status
        db.session.commit()
        flash("Order status updated.", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("cashier_order", order_id=order.id))

@app.route("/cashier/order/<int:order_id>/bill")
@role_required("cashier", "admin")
def bill(order_id):
    order = db.get_or_404(Order, order_id)
    return render_template("cashier/bill.html", order=order)

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
        if not name or not flavour or price is None or price < 0 or stock is None or stock < 0 or not db.session.get(Category, category_id):
            flash("Enter valid product details, price, stock, and category.", "error")
        else:
            image_filename = ""
            image = request.files.get("image")
            if image and image.filename:
                safe = secure_filename(image.filename)
                ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
                if ext not in ALLOWED_IMAGE_EXTENSIONS:
                    flash("Image must be PNG, JPG, JPEG, or WEBP.", "error")
                    return redirect(url_for("admin_products"))
                image_filename = f"{secrets.token_hex(8)}_{safe}"
                image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))
            product = Product(name=name, flavour=flavour, description=description, price=price,
                              stock=stock, category_id=category_id, image_filename=image_filename)
            db.session.add(product)
            db.session.flush()
            if stock:
                db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id,
                                                change_qty=stock, reason="Initial stock"))
            db.session.commit()
            flash("Product added.", "success")
            return redirect(url_for("admin_products"))
    products = Product.query.order_by(Product.name).all()
    categories = Category.query.order_by(Category.name).all()
    return render_template("admin/products.html", products=products, categories=categories)

@app.post("/admin/product/<int:product_id>/update")
@role_required("admin")
def update_product(product_id):
    product = db.get_or_404(Product, product_id)
    name = request.form.get("name", "").strip()
    flavour = request.form.get("flavour", "").strip()
    price = request.form.get("price", type=int)
    stock = request.form.get("stock", type=int)
    category_id = request.form.get("category_id", type=int)
    if not name or not flavour or price is None or price < 0 or stock is None or stock < 0 or not db.session.get(Category, category_id):
        flash("Invalid product details.", "error")
    else:
        delta = stock - product.stock
        product.name, product.flavour, product.price = name, flavour, price
        product.stock, product.category_id = stock, category_id
        product.active = bool(request.form.get("active"))
        image = request.files.get("image")
        if image and image.filename:
            safe = secure_filename(image.filename)
            ext = safe.rsplit(".", 1)[-1].lower() if "." in safe else ""
            if ext not in ALLOWED_IMAGE_EXTENSIONS:
                db.session.rollback()
                flash("Image must be PNG, JPG, JPEG, or WEBP.", "error")
                return redirect(url_for("admin_products"))
            image_filename = f"{secrets.token_hex(8)}_{safe}"
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], image_filename))
            product.image_filename = image_filename
        if delta:
            db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id,
                                            change_qty=delta, reason="Admin stock adjustment"))
        db.session.commit()
        flash("Product updated.", "success")
    return redirect(url_for("admin_products"))

@app.post("/admin/categories")
@role_required("admin")
def add_category():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Category name is required.", "error")
    elif Category.query.filter_by(name=name).first():
        flash("Category already exists.", "error")
    else:
        db.session.add(Category(name=name))
        db.session.commit()
        flash("Category added.", "success")
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
    if change is None or product.stock + change < 0:
        flash("Invalid stock adjustment; stock cannot become negative.", "error")
    else:
        product.stock += change
        db.session.add(StockTransaction(product_id=product.id, user_id=current_user.id,
                                        change_qty=change, reason=reason))
        db.session.commit()
        flash("Stock updated.", "success")
    return redirect(url_for("admin_stock"))

@app.route("/admin/reports")
@role_required("admin")
def admin_reports():
    start_text = request.args.get("start", "")
    end_text = request.args.get("end", "")
    query = Order.query.filter_by(status="Completed")
    try:
        if start_text:
            start_date = datetime.strptime(start_text, "%Y-%m-%d")
            query = query.filter(Order.completed_at >= start_date)
        if end_text:
            end_date = datetime.strptime(end_text, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            query = query.filter(Order.completed_at <= end_date)
    except ValueError:
        flash("Invalid date range.", "error")
    orders = query.order_by(Order.completed_at.desc()).all()
    revenue = sum(o.total for o in orders)
    chart_rows = db.session.query(func.date(Order.completed_at), func.sum(Order.total)).filter(
        Order.status == "Completed", Order.completed_at.isnot(None)).group_by(func.date(Order.completed_at)).order_by(
        func.date(Order.completed_at).desc()).limit(14).all()
    chart_rows.reverse()
    return render_template("admin/reports.html", orders=orders, revenue=revenue, start_text=start_text,
                           end_text=end_text, chart_labels=[r[0] for r in chart_rows],
                           chart_values=[int(r[1]) for r in chart_rows])

@app.route("/admin/staff", methods=["GET", "POST"])
@role_required("admin")
def admin_staff():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "cashier")
        if not name or not username or len(password) < 8 or role not in ("cashier", "admin"):
            flash("Provide valid details and a password of at least 8 characters.", "error")
        elif User.query.filter_by(username=username).first():
            flash("Username already exists.", "error")
        else:
            db.session.add(User(name=name, username=username, password_hash=generate_password_hash(password), role=role))
            db.session.commit()
            flash("Staff account created.", "success")
            return redirect(url_for("admin_staff"))
    staff = User.query.filter(User.role.in_(["cashier", "admin"])).order_by(User.role, User.name).all()
    return render_template("admin/staff.html", staff=staff)

@app.errorhandler(403)
def forbidden(_):
    return render_template("error.html", code=403, message="You do not have permission to access this page."), 403

@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="The requested page could not be found."), 404

@app.cli.command("init-db")
def init_db():
    db.create_all()
    for name in ["Cone", "Scoop", "Cup Ice Cream", "Sundae", "Ice Cream Bar", "Family Pack", "Ice Cream Flavours", "Ice Cream Shakes", "Cold Coffee", "Cold Beverages", "Lemonade", "Slush", "Hot Coffee", "Hot Tea", "Toppings", "Sodas"]:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
    if not User.query.filter_by(username="admin").first():
        db.session.add(User(name="Baba Admin", username="admin",
                            password_hash=generate_password_hash("Admin123!"), role="admin"))
    if not User.query.filter_by(username="cashier").first():
        db.session.add(User(name="Baba Cashier", username="cashier",
                            password_hash=generate_password_hash("Cashier123!"), role="cashier"))
    db.session.commit()
    print("Database initialized.")

@app.cli.command("seed-products")
def seed_products():
    db.create_all()
    menu = []

    for flavour in ["Pista Badam", "Kulfa Khoya", "Mango", "Vanilla", "Strawberry", "Chocolate",
                    "Kaju Akhrot", "Cheeko", "Date", "Caramel", "Sugar Free", "Pineapple",
                    "Chocolate Chip", "Blue Berry", "Tutti Frutti"]:
        for size, price in [("Small", 200), ("Medium", 280), ("Large", 400)]:
            menu.append((f"{flavour} Ice Cream - {size}", flavour,
                         f"{size} serving of {flavour} ice cream.", price, "Ice Cream Flavours"))
    for name, price, desc in [
        ("Half Liter Ice Cream Pack", 720, "Half-litre family ice cream pack."),
        ("Three-Quarter Liter Ice Cream Pack", 1080, "Three-quarter-litre family ice cream pack."),
        ("One Liter Ice Cream Pack", 1440, "One-litre family ice cream pack."),
        ("Full Liter Special Ice Cream Pack", 1800, "Full-litre special family pack, as listed on the menu."),
        ("Sprinkles Topping", 30, "Extra sprinkles topping."),
        ("Nuts Topping", 30, "Extra nuts topping."),
        ("Extra Jelly Topping", 30, "Extra jelly topping."),
    ]:
        menu.append((name, name, desc, price, "Toppings" if "Topping" in name else "Family Pack"))

    for flavour in ["Mango", "Banana", "Vanilla", "Strawberry", "Pista Badam", "Kulfa Khoya",
                    "Oreo", "Chocolate", "Cheeku", "Caramel", "KitKat", "Blue Berry"]:
        menu.append((f"{flavour} Shake", flavour, f"Baba Cafe {flavour.lower()} ice cream shake.", 420, "Ice Cream Shakes"))
    for flavour in ["Bounty", "Power", "Pineapple"]:
        menu.append((f"{flavour} Shake", flavour, f"Baba Cafe {flavour.lower()} shake.", 450, "Ice Cream Shakes"))
    for flavour in ["Vanilla", "Chocolate", "Caramel"]:
        menu.append((f"{flavour} Cold Coffee", flavour, f"Chilled {flavour.lower()} cold coffee.", 420, "Cold Coffee"))

    for name, price in [
        ("Berry Neval", 250), ("Strawberry Shake", 230), ("Mango Shake", 230),
        ("Banana Shake", 230), ("Ice Cream Shake", 230), ("Chocolate Shake", 230),
        ("Oreo Shake", 230), ("Cold Coffee", 200), ("Mocca Cold Coffee", 230),
        ("Fruit & Fiber", 220), ("Baba Special Blue Lagoon", 180), ("Pina Colada", 210),
        ("Blue Colada", 210), ("Red Colada", 210), ("Fresh Lime", 100),
        ("Pinacolada", 450), ("Blue Lagoon", 450), ("Mint Margarita", 330),
    ]:
        menu.append((name, name.replace(" Shake", ""), f"{name} from the Baba Cafe cold beverages menu.", price, "Cold Beverages"))
    for flavour in ["Mango", "Bubblegum", "Peach", "Green Apple", "Orange", "Kiwi", "Rass Berry", "Strawberry", "Lichi"]:
        menu.append((f"{flavour} Lemonade", flavour, f"Refreshing {flavour.lower()} lemonade.", 180, "Lemonade"))
    menu.append(("Classic Lemonade", "Classic", "Classic fresh lemonade.", 180, "Lemonade"))
    for flavour in ["Mango", "Bubblegum", "Peach", "Green Apple", "Orange", "Kiwi", "Rass Berry", "Strawberry", "Lichi"]:
        menu.append((f"{flavour} Slush", flavour, f"Chilled {flavour.lower()} slush.", 100, "Slush"))
    for name, price in [
        ("Cappuccino", 200), ("Irish Cappuccino", 220), ("Vanilla Cappuccino", 220),
        ("Hazelnut Cappuccino", 220), ("Caramel Cappuccino", 220), ("Chocolate Cappuccino", 220),
        ("Latte Coffee", 220), ("Irish Latte", 240), ("Vanilla Latte", 240),
        ("Hazelnut Latte", 240), ("Caramel Latte", 240), ("Chocolate Latte", 240),
        ("Americano Coffee", 240), ("Espresso Single", 180), ("Black Coffee", 170),
        ("Hot Chocolate", 170),
    ]:
        menu.append((name, name, f"Freshly prepared {name.lower()}.", price, "Hot Coffee"))
    for name, price in [
        ("Pink Tea", 150), ("SP Tea", 120), ("Irish Tea", 120), ("Coconut Tea", 120),
        ("Cardamom Tea", 120), ("Mix Tea", 100), ("Black Tea", 100), ("Green Tea", 100),
        ("Lemon Tea", 100), ("Peach Tea", 100), ("Doodh Patti", 160),
        ("Cardamom Patti", 170), ("Kashmiri Chaye", 180),
    ]:
        menu.append((name, name, f"Freshly prepared {name.lower()}.", price, "Hot Tea"))

    for name, price in [
        ("Cola Soda", 100), ("Lemon-Lime Soda", 100), ("Orange Soda", 100),
        ("Blueberry Soda", 150), ("Strawberry Soda", 150), ("Mint Soda", 150),
        ("Baba Special Soda", 180),
    ]:
        menu.append((name, name.replace(" Soda", ""), f"Chilled {name.lower()}.", price, "Sodas"))

    for category_name in sorted({row[4] for row in menu}):
        if not Category.query.filter_by(name=category_name).first():
            db.session.add(Category(name=category_name))
    db.session.commit()

    added = updated = 0
    image_by_category = {
        "Ice Cream Flavours": "https://www.thedailymeal.com/img/gallery/the-ultimate-ice-cream-brands-ranked/intro-1660338932.jpg",
        "Cone": "https://www.tourismeregionsoreltracy.com/_next/image?q=75&url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Fhzynoggk%2Fproduction%2Fd936163a2de7eb7455f848e2b11228d0ef48e811-1310x1310.jpg&w=1920",
        "Scoop": "https://www.thedailymeal.com/img/gallery/the-ultimate-ice-cream-brands-ranked/intro-1660338932.jpg",
        "Cup Ice Cream": "https://www.thedailymeal.com/img/gallery/the-ultimate-ice-cream-brands-ranked/intro-1660338932.jpg",
        "Sundae": "https://www.tourismeregionsoreltracy.com/_next/image?q=75&url=https%3A%2F%2Fcdn.sanity.io%2Fimages%2Fhzynoggk%2Fproduction%2Fd936163a2de7eb7455f848e2b11228d0ef48e811-1310x1310.jpg&w=1920",
        "Ice Cream Bar": "https://www.thedailymeal.com/img/gallery/the-ultimate-ice-cream-brands-ranked/intro-1660338932.jpg",
        "Ice Cream Shakes": "shake.jpg",
        "Cold Coffee": "https://mir-s3-cdn-cf.behance.net/project_modules/max_1200/996c6973260883.5c0410f93fe97.jpg",
        "Hot Coffee": "https://vstatic.vietnam.vn/vietnam/resource/IMAGE/2026/05/12/1778558197817_kingcoffee-com-vn-wp-content-uploads-2026-02-_cac-loai-thuc-uong-ca-phe.jpeg",
        "Cold Beverages": "https://vstatic.vietnam.vn/vietnam/resource/IMAGE/2026/05/12/1778558197817_kingcoffee-com-vn-wp-content-uploads-2026-02-_cac-loai-thuc-uong-ca-phe.jpeg",
        "Lemonade": "https://milex.co.za/cdn/shop/articles/Classic_Frozen_Lemonade_1024x.png?v=1757064284",
        "Slush": "https://milex.co.za/cdn/shop/articles/Classic_Frozen_Lemonade_1024x.png?v=1757064284",
        "Sodas": "cold-beverage.jpg",
        "Hot Tea": "tea.jpg",
        "Toppings": "https://snapcalorie-webflow-website.s3.us-east-2.amazonaws.com/media/food_pics_v2/medium/ice_cream_toppings.jpg",
        "Family Pack": "https://digitalcontent.api.tesco.com/v2/media/ghs/2ebb0ab2-657d-40f5-91e0-4d31ce1b9e41/e1c05692-504d-4f93-91a2-698cd37b0290_1751870300.jpeg"
    }
    for name, flavour, desc, price, category_name in menu:
        category = Category.query.filter_by(name=category_name).first()
        product = Product.query.filter_by(name=name, category_id=category.id).first()
        image_filename = image_by_category.get(category_name, "ice-cream.jpg")
        if product:
            product.flavour = flavour
            product.description = desc
            product.price = price
            product.image_filename = image_filename
            product.active = True
            updated += 1
        else:
            product = Product(name=name, flavour=flavour, description=desc, price=price,
                              image_filename=image_filename, stock=20, low_stock_threshold=5, category_id=category.id)
            db.session.add(product)
            db.session.flush()
            db.session.add(StockTransaction(product_id=product.id, change_qty=20,
                                            reason="Opening stock from menu import"))
            added += 1
    db.session.commit()
    print(f"Baba Cafe menu import complete.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)