from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
def user_mockup_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/mockups/user_<id>/<filename>
    return f"mockups/user_{instance.user.id}/{filename}"

def user_design_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/designs/user_<id>/<filename>
    return f"designs/user_{instance.user.id}/{filename}"

def product_image_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/products/<product_name>/<filename>
    return f"products/{instance.name}/{filename}"

class Design(models.Model):
    """Model for storing reusable design files per user"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="designs")
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to=user_design_path)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Mockup(models.Model):
    """Model for storing reusable mockup files per user, potentially linked to a design"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mockups")
    name = models.CharField(max_length=100)
    file = models.ImageField(upload_to=user_mockup_path)
    # Link to a specific design (optional)
    linked_design = models.ForeignKey(
        Design, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="linked_mockups"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.user.username})"


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
        ("returned", "Returned"),
    ]
    profit = models.IntegerField(null=True , blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="orders")
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    area = models.CharField(max_length=100)
    areaId = models.IntegerField(max_length=100 , null=True , blank=True)
    cod = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    unique_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.unique_id
    
    def save(self, *args, **kwargs):
        # Generate unique_id if not provided
        if not self.unique_id and self.user:
            latest_order = Order.objects.filter(user=self.user).order_by("-id").first()
            order_number = 1
            if latest_order:
                try:
                    last_unique_id = latest_order.unique_id
                    last_order_number = int(last_unique_id.split("-")[-1])
                    order_number = last_order_number + 1
                except:
                    order_number = latest_order.id + 1 # Fallback
            
            self.unique_id = f"{self.user.username}-{order_number}"
        
        super().save(*args, **kwargs)

class OrderItem(models.Model):
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    mockup = models.ForeignKey(Mockup, on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items")
    design = models.ForeignKey(Design, on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items")
    type = models.CharField(max_length=50, default=" ")
    size = models.CharField(max_length=50, blank=True, null=True)
    color = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Item for {self.order.unique_id}"


class InventoryProduct(models.Model):
    """Represents a base product type for inventory tracking (e.g., Lycra T-shirt)."""
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True, null=True)
    image = models.ImageField(upload_to=product_image_path, blank=True, null=True)
    # Add other base product fields if needed (e.g., material, brand)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    price = models.IntegerField(null=True , blank=True)
    def __str__(self):
        return self.name

class InventoryItem(models.Model):
    """Represents a specific variant (size/color) of an InventoryProduct with quantity."""
    product = models.ForeignKey(InventoryProduct, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField(max_length=50)
    color = models.CharField(max_length=50)
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    # Add other variant-specific fields if needed (e.g., SKU, cost_price)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (
            ("product", "size", "color"),
        ) # Ensure only one entry per product/size/color combination

    def __str__(self):
        return f"{self.product.name} - {self.size} - {self.color} ({self.quantity})"

class UserProductPrice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="custom_prices")
    product = models.ForeignKey(InventoryProduct, on_delete=models.CASCADE)
    custom_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ("user", "product")

    def __str__(self):
        return f"{self.user.username} - {self.product.name}: {self.custom_price}"
