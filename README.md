# Coupon Management System - XAMPP / MySQL - Final Coupon Flow Fix v2

A Django + MySQL/MariaDB (XAMPP) coupon management website with working sidebar navigation and functional booking, coupon, redemption, ledger, rules, settings, customer, client portal and Excel upload flows.

## Admin login

- Username: `admin`
- Password: `admin123`

The admin account is created automatically by `python manage.py migrate`.

## XAMPP setup on Windows

### 1. Start MySQL in XAMPP

Open **XAMPP Control Panel** and click **Start** next to **MySQL**.

Default configuration:
- Host: `127.0.0.1`
- Port: `3306`
- User: `root`
- Password: blank

If your XAMPP MySQL root account has a password, put that password in `.env`.

### 2. Create the database

You can use phpMyAdmin:

1. Open `http://localhost/phpmyadmin/`
2. Import `database/xampp_coupon_management.sql`

Or open MySQL/phpMyAdmin SQL and run the same file.

The SQL file creates only the database. Django creates the application table safely through migrations.

### 3. Open the project in VS Code

Open this project folder (the folder containing `manage.py`).

### 4. Create and activate the virtual environment

PowerShell:

```powershell
python -m venv venv
.env\Scripts\Activate.ps1
```

If the virtual environment already exists:

```powershell
.env\Scripts\Activate.ps1
```

### 5. Install packages

```powershell
python -m pip install -r requirements.txt
```

### 6. Create `.env`

Copy `.env.example` to `.env`.

For normal XAMPP MySQL with root and no password:

```env
MYSQL_DATABASE=coupon_management
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
```

If your MySQL root user has a password, enter it after `MYSQL_PASSWORD=`.

### 7. Create Django tables and admin user

```powershell
python manage.py migrate
```

Expected result includes:

```text
Applying core.0001_initial... OK
Applying core.0002_seed_admin... OK
```

### 8. Optional: import old JSON backup data

The project keeps the old JSON files in `legacy_json_backup/`.

If you want to import them:

```powershell
python manage.py import_json_data --path legacy_json_backup
```

This is optional. A fresh database can be used without this step.

### 9. Run the website

```powershell
python manage.py runserver
```

Open:

`http://127.0.0.1:8000/`

## Deploy to Render

This app uses MySQL, so Render needs a reachable external MySQL-compatible
database (for example, TiDB Cloud); Render's managed database offering is
PostgreSQL, which this project is not configured to use.

1. Push the project to GitHub. Do not upload `.env` or the local `venv/`.
2. Create the external database and its database/schema. Keep its host, port,
   database name, username, and password available for Render's environment
   variables.
3. In Render, create a **Blueprint** from the GitHub repository and select
   `render.yaml`.
4. When prompted, enter the database values for `MYSQL_DATABASE`,
   `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, and `MYSQL_PORT`. Render
   generates `SECRET_KEY`; keep all secrets in Render, not in GitHub.
5. Deploy. The start command applies Django migrations before starting Gunicorn.

Render provides the public hostname automatically. The app uses it for allowed
hosts and HTTPS/CSRF handling. For local XAMPP, continue using `.env` and
`127.0.0.1:3306`; the local database connection does not require TLS.

## Sidebar pages

All sidebar links are connected to Django routes:

- Dashboard
- Client Portal
- Customers
- Coupons
- Bookings
- Redemptions
- Ledger
- Excel Upload
- Rules
- Settings
- Sign Out / Logout

## Main business flow

1. Add a Customer.
2. Add a Booking for an existing Client.
3. An active coupon rule automatically creates the coupon for a new booking.
4. Before the unlock date the coupon is `PENDING`.
5. After the unlock date it becomes `AVAILABLE`.
6. `Earn Coupon` can be used only when that booking does not already have a coupon.
7. Redeem an available coupon.
8. The redemption is automatically written to Redemptions.
9. The transaction is automatically written to Ledger.
10. Reverse Coupon restores the redeemed amount and records a reversal in Ledger.
11. Client Portal shows the customer's booking and coupon balance.
12. Rules and Settings control coupon calculation/redemption configuration.
13. Excel Upload can add multiple bookings and create their coupon/ledger records.

## Important data-integrity changes

- Duplicate coupon creation for the same customer + booking is prevented.
- Reverse Coupon now performs a real reversal instead of only displaying a message.
- Automatic redemption records cannot be casually deleted; use Reverse Coupon.
- Customers with no bookings are still displayed.
- Ledger fields now match the backend data returned by the Django view.
- Dashboard earned/redeemed values are calculated from ledger transactions.
- XAMPP/MySQL default blank root password is supported.
- MySQL strict mode is enabled for the Django connection.
- PyMySQL is already connected to Django's MySQL backend.


## Compatibility note

This fixed package targets XAMPP's MariaDB 10.4.x. Django's supported
MariaDB range changes over time; the project includes a small compatibility
patch so the installed Django 5.2 environment can work with the MariaDB 10.4
server used by this XAMPP setup.

The requirements file uses `mysqlclient` directly. If an older virtual
environment contains PyMySQL or a different Django version, recreate the
virtual environment from this package before running migrations.


## IMPORTANT: use the final fixed build

If you previously extracted a folder named `Coupon_Management_XAMPP_Fixed` or `Coupon_Management_XAMPP_Fixed(1)`, do not run that old copy. The final build is the ZIP containing `VERSION.txt` with `Final Coupon Flow Fix v2`.

The `is_released` fix is now applied at two levels: the database default is repaired by migration `core.0007_coupon_is_released_db_default`, and the coupon flow explicitly writes `is_released` using Django ORM transactions.

After extracting the final ZIP, run:

```powershell
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Do not manually delete the existing `coupon_management` database.

### Coupon test data

1. Create a customer, for example `CL-1003`.
2. Create a booking belonging to that customer, for example `BK-2026-001`.
3. Set a positive `Net Amount`, for example `10000`.
4. Set a travel start date.
5. In Coupons -> Earn Coupon enter the exact Customer ID and S PNR.
6. `10000 / 100 = 100` coupon points.
7. Before the travel date the coupon is `PENDING` and `is_released=0`. On/after the travel date it is `AVAILABLE` and `is_released=1`.
8. Redeem from an available balance. The system writes Redemptions, Redemption Allocations, and Ledger rows.
9. Reverse the redemption to restore the coupon balance and create a reversal Ledger row.
