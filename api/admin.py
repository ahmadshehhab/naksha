from django.contrib import admin
from .models import Order, OrderItem, Mockup, Design , InventoryProduct, InventoryItem , UserProductPrice

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('unique_id', 'user', 'name', 'phone', 'area', 'cod', 'price', 'status', 'created_at')
    list_filter = ('status', 'cod', 'created_at')
    search_fields = ('unique_id', 'name', 'phone', 'user__username')
    inlines = [OrderItemInline]

@admin.register(UserProductPrice)
class UserProductPrice(admin.ModelAdmin):
    list_display = ('user', 'product', 'custom_price')
@admin.register(Mockup)
class MockupAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'user__username')

@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'user__username')


class InventoryItemInline(admin.TabularInline):
    """Allows editing inventory items directly within the product view."""
    model = InventoryItem
    extra = 1 # Show one empty row for adding new variants
    fields = ('size', 'color', 'quantity')

@admin.register(InventoryProduct)
class InventoryProductAdmin(admin.ModelAdmin):
    """Admin configuration for managing base inventory products."""
    list_display = ('name', 'description', 'created_at', 'updated_at')
    search_fields = ('name', 'description')
    inlines = [InventoryItemInline]

@admin.register(InventoryItem)
class InventoryItemAdmin(admin.ModelAdmin):
    """Admin configuration for managing specific inventory item variants (size/color)."""
    list_display = ('product', 'size', 'color', 'quantity', 'updated_at')
    list_filter = ('product', 'size', 'color')
    search_fields = ('product__name', 'size', 'color')
    list_editable = ('quantity',) # Allow quick quantity updates from the list view
    autocomplete_fields = ('product',) # Use autocomplete for product selection

