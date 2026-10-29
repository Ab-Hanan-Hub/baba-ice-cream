# Baba Ice Cream — Web-Based Ordering & Management System

A beginner-friendly Flask + SQLite starter application with three role-based panels:
- Customer: browse catalogue, cart, checkout, order tracking
- Cashier: receive orders, create walk-in sales, update statuses, print bills
- Admin: products, prices, categories, inventory movements, staff, sales reports

## Requirements
- Python 3.10 or newer
- VS Code (recommended)
- Internet connection for Bootstrap and Chart.js CDN assets (the backend itself runs locally)

## Windows setup (PowerShell)
Open VS Code terminal in the extracted `Baba_IceCream` folder:

```powershell
py -m venv venv
```

Activate the virtual environment. If PowerShell blocks scripts, use the one-session workaround:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.env\Scripts\Activate.ps1
```
Or use Command Prompt instead:
```bat
venv\Scripts\activate.bat
```

Install packages:
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Initialize the database, default categories, and demo staff:
```powershell
flask --app app init-db
```

Import the photographed Baba Cafe menu (ice-cream flavours, shakes, cold beverages, lemonade, slush, hot coffee, tea, toppings, and family packs). This can be run again safely; it updates menu names/prices while preserving existing stock:
```powershell
flask --app app seed-products
```

Run:
```powershell
python app.py
```
Open http://127.0.0.1:5000 in your browser.

## Open on a phone over the shop Wi-Fi
1. Connect the laptop and phone to the same Wi-Fi network.
2. Run `ipconfig` in a second Windows terminal and find the laptop's Wi-Fi IPv4 Address (for example `192.168.1.8`).
3. Start the app with `python app.py`. The server listens on `0.0.0.0:5000` for local-network access.
4. On the phone, open `http://YOUR-LAPTOP-IP:5000` (example: `http://192.168.1.8:5000`).
5. If it does not load, allow TCP port 5000 through Windows Firewall for a Private network.

This works on the same local Wi-Fi only. For customers using mobile data or another network, deploy the app to a secure hosting service; do not expose Flask's development server directly to the public internet.

## Demo accounts
- Admin: `admin` / `Admin123!`
- Cashier: `cashier` / `Cashier123!`

Sign in to staff pages using **Staff login** at `/staff-login`. Change demo passwords and set a strong `SECRET_KEY` before any non-local use. Demo accounts are for local development only.

## Main URLs
- Customer home: `/`
- Catalogue: `/products`
- Cart: `/cart`
- Order status: `/order-status`
- Staff login: `/staff-login`
- Cashier dashboard: `/cashier`
- Admin dashboard: `/admin`
- Admin products and prices: `/admin/products`
- Admin stock: `/admin/stock`
- Sales reports: `/admin/reports`
- Staff accounts: `/admin/staff`

## Important workflow notes
- New online orders are created as Pending and shown to the cashier.
- A cashier creates a bill from an order and can print it.
- When a cashier changes an order to **Completed**, the app validates stock and deducts it once.
- Reports include completed orders only.
- Historical order items retain their original price even after product prices change.
- Product images are optional; without an image the UI displays an ice-cream emoji placeholder.
- SQLite database file `baba_icecream.db` is created in the project folder.

## Troubleshooting
- `flask` not found: activate the venv and run `python -m pip install -r requirements.txt`; alternatively use `python -m flask --app app init-db`.
- PowerShell activation blocked: use the temporary Process-scope command above, or activate with `venv\Scripts\activate.bat` in Command Prompt.
- Port 5000 already in use: close the other app or change `app.run(debug=True, port=5001)` in `app.py`.
- Database schema changes during development: back up any needed data, then delete `baba_icecream.db` and rerun `flask --app app init-db`. This deletes local database records, so do not do it if you need to keep them.
- Images must be PNG, JPG, JPEG, or WEBP and at most 4 MB.

## Production note
This is intended as a local learning/semester project starter, not an internet-facing production deployment. Before public hosting, set a strong secret key, disable debug mode, configure HTTPS, review upload handling and rate limiting, and add proper payment integration only if required.


## Menu photos and category filtering update
- The customer menu now has clickable category buttons. Selecting a category displays only products in that category.
- The flavour dropdown is limited to the selected category.
- The seed command assigns web-hosted food photos for categories with suitable matching images; some categories use bundled local images. Internet access is required to load web-hosted photos.
- Product names and menu prices are kept from the supplied menu list. Run `python -m flask --app app seed-products` after starting the updated project to refresh existing product records and assign the updated images.

## Customer chatbot

A floating **Chat with Baba** assistant is included on the website. It reads active, in-stock products and current prices from the database and can answer category, product/flavour, and budget questions. It is a simple rule-based chatbot and does not require an external AI API. The chat endpoint is `/chat`.

To use it, install dependencies and start the app as described above, then open the website and click **Chat with Baba** in the bottom-right corner.
