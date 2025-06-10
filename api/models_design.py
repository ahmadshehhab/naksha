"""
Design for new models to support:
1. File uploads for mockups and designs
2. Reusable mockups and designs per user
3. Enhanced order items with references to uploaded files
"""

from django.db import models
from django.contrib.auth.models import User

def user_mockup_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/mockups/user_<id>/<filename>
    return f'mockups/user_{instance.user.id}/{filename}'

def user_design_path(instance, filename):
    # File will be uploaded to MEDIA_ROOT/designs/user_<id>/<filename>
    return f'designs/user_{instance.user.id}/{filename}'

class Mockup(models.Model):
    """Model for storing reusable mockup files per user"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mockups')
    name = models.CharField(max_length=100)
    file = models.ImageField(upload_to=user_mockup_path)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Design(models.Model):
    """Model for storing reusable design files per user"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='designs')
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to=user_design_path)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.name} ({self.user.username})"

class Order(models.Model):
    """Updated Order model with same fields as before"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    area = models.CharField(max_length=100)
    cod = models.BooleanField(default=False)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    unique_id = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.unique_id
    
    def save(self, *args, **kwargs):
        # Generate unique_id if not provided
        if not self.unique_id and self.user:
            # Get the latest order number for this user
            latest_order = Order.objects.filter(user=self.user).order_by('-id').first()
            order_number = 1
            if latest_order:
                # Try to extract the order number from the unique_id
                try:
                    last_unique_id = latest_order.unique_id
                    last_order_number = int(last_unique_id.split('-')[-1])
                    order_number = last_order_number + 1
                except:
                    # If extraction fails, just increment by 1
                    order_number = latest_order.id + 1
            
            self.unique_id = f"{self.user.username}-{order_number}"
        
        super().save(*args, **kwargs)

class OrderItem(models.Model):
    """Updated OrderItem model with references to Mockup and Design models"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    mockup = models.ForeignKey(Mockup, on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    design = models.ForeignKey(Design, on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    size = models.CharField(max_length=50, blank=True, null=True)
    color = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Item for {self.order.unique_id}"
