from django.db import models


# ============================================================
# 1. USERS
# ============================================================

class User(models.Model):
    user_id = models.CharField(
        max_length=50,
        primary_key=True
    )

    username = models.CharField(
        max_length=100,
        unique=True
    )

    password = models.CharField(
        max_length=255
    )

    name = models.CharField(
        max_length=100
    )

    role = models.CharField(
        max_length=50,
        default="USER"
    )

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.username


# ============================================================
# 2. CUSTOMERS
# ============================================================

class Customer(models.Model):
    id = models.CharField(
        max_length=50,
        primary_key=True
    )

    passenger_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    name = models.CharField(
        max_length=150
    )

    email = models.EmailField(
        max_length=254,
        null=True,
        blank=True
    )

    phone = models.CharField(
        max_length=30,
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        default="ACTIVE"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = "customers"

    def __str__(self):
        return self.name


# ============================================================
# 3. BOOKINGS
# ============================================================

class Booking(models.Model):

    pnr = models.CharField(
        max_length=50,
        primary_key=True
    )

    client = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        db_column="client_id",
        related_name="bookings"
    )

    passenger_name = models.CharField(
        max_length=150
    )

    passenger_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    sector = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    travel_date = models.DateField(
        null=True,
        blank=True
    )

    end_date = models.DateField(
        null=True,
        blank=True
    )

    booked_date = models.DateField(
        null=True,
        blank=True
    )

    net_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    email = models.EmailField(
        max_length=254,
        null=True,
        blank=True
    )

    mobile = models.CharField(
        max_length=30,
        null=True,
        blank=True
    )

    airline_pnr = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=30,
        default="Confirmed"
    )

    booking_type = models.CharField(
        max_length=50,
        default="Web Booking"
    )

    travel_type = models.CharField(
        max_length=50,
        default="One Way"
    )

    username = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    office_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    supplier = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    airline = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    fare_type = models.CharField(
        max_length=50,
        default="Net Fare"
    )

    parent_pnr = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = "bookings"

        indexes = [
            models.Index(fields=["client"]),
            models.Index(fields=["travel_date"]),
            models.Index(fields=["passenger_name"]),
            models.Index(fields=["airline"]),
        ]

    def __str__(self):
        return self.pnr


# ============================================================
# 4. COUPONS
# ============================================================

class Coupon(models.Model):

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("AVAILABLE", "Available"),
        ("REDEEMED", "Redeemed"),
        ("EXPIRED", "Expired"),
    ]

    id = models.CharField(
        max_length=60,
        primary_key=True
    )

    coupon_code = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="coupons"
    )

    booking = models.OneToOneField(
        Booking,
        on_delete=models.SET_NULL,
        db_column="booking_id",
        related_name="coupon",
        null=True,
        blank=True
    )

    booking_ref = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    customer_name = models.CharField(
        max_length=150,
        null=True,
        blank=True
    )

    passenger_name = models.CharField(
        max_length=150,
        null=True,
        blank=True
    )

    travel_date = models.DateField(
        null=True,
        blank=True
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING"
    )

    # Existing XAMPP/MariaDB `coupons` table contains this column.
    # Keep it in Django state and always provide a value on INSERT.
    is_released = models.BooleanField(
        db_column="is_released",
        default=False,
        db_default=False,
    )

    unlock_date = models.DateField(
        null=True,
        blank=True
    )

    available_date = models.DateField(
        null=True,
        blank=True
    )

    expiry_date = models.DateField(
        null=True,
        blank=True
    )

    redeemed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        db_table = "coupons"

        indexes = [
            models.Index(fields=["customer"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return self.id


# ============================================================
# 5. REDEMPTIONS
# ============================================================

class Redemption(models.Model):

    STATUS_CHOICES = [
        ("SUCCESS", "Success"),
        ("FAILED", "Failed"),
        ("PENDING", "Pending"),
        ("COMPLETED", "Completed"),
        ("REVERSED", "Reversed"),
    ]

    id = models.CharField(
        max_length=60,
        primary_key=True
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        related_name="redemptions",
        null=True,
        blank=True
    )

    customer_name = models.CharField(
        max_length=150,
        null=True,
        blank=True
    )

    booking_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    booking_ref = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    coupon_code = models.CharField(
        max_length=500,
        null=True,
        blank=True
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    redeemed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="SUCCESS"
    )

    redemption_type = models.CharField(
        max_length=50,
        default="Coupon Redemption"
    )

    date = models.DateTimeField(
        auto_now_add=True
    )

    time = models.CharField(
        max_length=10,
        null=True,
        blank=True
    )

    notes = models.CharField(
        max_length=500,
        null=True,
        blank=True
    )

    reversed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    reversed_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    class Meta:
        db_table = "redemptions"

        indexes = [
            models.Index(fields=["customer"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return self.id


# ============================================================
# 6. REDEMPTION ALLOCATIONS
# ============================================================

class RedemptionAllocation(models.Model):

    id = models.BigAutoField(
        primary_key=True
    )

    redemption = models.ForeignKey(
        Redemption,
        on_delete=models.CASCADE,
        related_name="allocations"
    )

    coupon_code = models.CharField(
        max_length=100
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    class Meta:
        db_table = "redemption_allocations"

    def __str__(self):
        return f"{self.redemption_id} - {self.coupon_code}"


# ============================================================
# 7. LEDGER
# ============================================================

class Ledger(models.Model):

    id = models.CharField(
        max_length=60,
        primary_key=True
    )

    txn_id = models.CharField(
        max_length=60,
        unique=True,
        null=True,
        blank=True
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        related_name="ledger_entries",
        null=True,
        blank=True
    )

    customer_name = models.CharField(
        max_length=150,
        null=True,
        blank=True
    )

    booking = models.ForeignKey(
        Booking,
        on_delete=models.SET_NULL,
        db_column="booking_id",
        related_name="ledger_entries",
        null=True,
        blank=True
    )

    booking_ref = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    coupon_code = models.CharField(
        max_length=500,
        null=True,
        blank=True
    )

    type = models.CharField(
        max_length=50
    )

    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    status = models.CharField(
        max_length=30,
        default="PENDING"
    )

    date = models.DateField()

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = "ledger"

        indexes = [
            models.Index(fields=["customer"]),
            models.Index(fields=["date"]),
        ]

    def __str__(self):
        return self.id


# ============================================================
# 8. RULES
# ============================================================

class Rule(models.Model):

    id = models.CharField(
        max_length=60,
        primary_key=True
    )

    office_id = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    booking_type = models.CharField(
        max_length=50,
        default="Any Booking Type"
    )

    supplier = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    airline = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    fare_type = models.CharField(
        max_length=50,
        default="Any Fare Type"
    )

    percentage = models.DecimalField(
        max_digits=7,
        decimal_places=4,
        default=0
    )

    status = models.CharField(
        max_length=20,
        default="Active"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        db_table = "rules"

        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["airline"]),
        ]

    def __str__(self):
        return self.id


# ============================================================
# 9. SETTINGS
# ============================================================

class Setting(models.Model):

    id = models.PositiveSmallIntegerField(
        primary_key=True,
        default=1
    )

    min_redemption_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=100
    )

    max_redemption_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=50000
    )

    coupon_expiry_days = models.IntegerField(
        default=365
    )

    allow_partial_redemption = models.BooleanField(
        default=True
    )

    allow_combined_offers = models.BooleanField(
        default=False
    )

    class Meta:
        db_table = "settings"

    def __str__(self):
        return "Application Settings"