from rest_framework import serializers
from django.contrib.auth.models import User
from django.db import transaction # Import transaction
from .models import Order, OrderItem, Mockup, Design, InventoryProduct, InventoryItem , UserProductPrice

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "is_staff"]

class DesignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Design
        fields = ["id", "name", "file", "created_at", "updated_at"]
        read_only_fields = ["user"]

class MockupSerializer(serializers.ModelSerializer):
    # Include linked_design field
    linked_design_details = DesignSerializer(source="linked_design", read_only=True)

    class Meta:
        model = Mockup
        fields = ["id", "name", "file", "linked_design", "linked_design_details", "created_at", "updated_at"]
        read_only_fields = ["user"]
        extra_kwargs = {
            "linked_design": {"write_only": False, "required": False, "allow_null": True},
        }

class OrderItemSerializer(serializers.ModelSerializer):
    mockup_details = MockupSerializer(source="mockup", read_only=True)
    design_details = DesignSerializer(source="design", read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "mockup", "design", "type", "size", "color", "created_at", "updated_at",
                  "mockup_details", "design_details"]
        extra_kwargs = {
            "mockup": {"write_only": False, "required": False, "allow_null": True},
            "design": {"write_only": False, "required": False, "allow_null": True},
            "type": {"required": True},
        }

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, required=False)
    username = serializers.CharField(source="user.username", read_only=True)
    owner_mockups = MockupSerializer(many=True, read_only=True, required=False)
    owner_designs = DesignSerializer(many=True, read_only=True, required=False)

    class Meta:
        model = Order
        fields = ["id", "user", "username", "name", "phone", "area","areaId", "cod", "profit", "price", "status",
                  "unique_id", "created_at", "updated_at", "items",
                  "owner_mockups", "owner_designs"]
        read_only_fields = ["unique_id", "user", "owner_mockups", "owner_designs", "profit"] # 'profit' is now read-only for input, calculated internally

   
    def _calculate_total_cost_and_profit(self, order_instance, items_data_or_queryset):
        """Helper to calculate total cost of items and update order profit.
        Also applies a deduction to profit based on order_instance.areaId.
        """
        total_cost_of_items = 0

        if isinstance(items_data_or_queryset, list): # For create or pre-save update
            for item_data in items_data_or_queryset:
                product_type = item_data.get('type')
                if product_type:
                    try:
                        inventory_product = InventoryProduct.objects.get(name=product_type)
                        try:
                            custom_price_obj = UserProductPrice.objects.get(user=order_instance.user, product=inventory_product)
                            item_cost = custom_price_obj.custom_price
                        except UserProductPrice.DoesNotExist:
                            item_cost = inventory_product.price if inventory_product.price is not None else 0
                        total_cost_of_items += item_cost
                    except InventoryProduct.DoesNotExist:
                        print(f"Warning: InventoryProduct not found for type: {product_type}")
                        pass
        else: # For post-save update (using instance.items.all())
            for item in items_data_or_queryset:
                if item.type:
                    try:
                        inventory_product = InventoryProduct.objects.get(name=item.type)
                        # Use 0 if inventory_product.price is None
                        item_cost = inventory_product.price if inventory_product.price is not None else 0
                        total_cost_of_items += item_cost
                    except InventoryProduct.DoesNotExist:
                        print(f"Warning: InventoryProduct not found for type: {item.type}")
                        pass

        # Ensure profit is an integer as per your model
        # Also ensure order_instance.price is treated as a number
        order_selling_price = order_instance.price if order_instance.price is not None else 0
        order_instance.profit = int(order_selling_price - total_cost_of_items)

        # --- NEW LOGIC: Deduct from profit based on areaId ---
        area_id = order_instance.areaId # Assuming areaId exists on order_instance

        if area_id == 590:
            order_instance.profit -= 30
        elif area_id > 593:
            order_instance.profit -= 55
        else:
            order_instance.profit -= 20
        # --- END NEW LOGIC ---

        order_instance.save(update_fields=['profit']) # Only save the profit field



    def validate(self, data):
        instance = self.instance # instance will be available during update

        new_items_data = data.get("items", [])
        stock_changes = {} # { (product_name, size, color): quantity_change }
        if instance:
            current_items_map = {item.id: item for item in instance.items.all()}
            for current_item_id, current_item in current_items_map.items():
                is_removed = True
                for new_item_data in new_items_data:
                    if new_item_data.get('id') == current_item_id:
                        is_removed = False
                        # Check if item details that affect inventory have changed
                        if (current_item.type != new_item_data.get('type') or
                            current_item.size != new_item_data.get('size') or
                            current_item.color != new_item_data.get('color')):
                            # If details changed, "return" stock from old item
                            key = (current_item.type, current_item.size, current_item.color)
                            stock_changes[key] = stock_changes.get(key, 0) + 1
                        break
                if is_removed:
                    # Item was removed, return its stock
                    key = (current_item.type, current_item.size, current_item.color)
                    stock_changes[key] = stock_changes.get(key, 0) + 1

        # For new or updated items
        for item_data in new_items_data:
            item_id = item_data.get('id')
            if item_id and instance and item_id in current_items_map:
                # This is an existing item, already handled above if its details changed
                pass
            else:
                # This is a new item, or an existing item whose details changed (and was "returned" above)
                # so we need to "consume" stock for it now
                key = (item_data['type'], item_data['size'], item_data['color'])
                stock_changes[key] = stock_changes.get(key, 0) - 1

        # Now, check if there's enough stock for all proposed changes
        for (product_name, size, color), change in stock_changes.items():
            if change < 0: # If we need to consume stock (change is negative)
                try:
                    inventory_item = InventoryItem.objects.get(
                        product__name=product_name,
                        size=size,
                        color=color
                    )
                    # Check if current quantity plus the negative change (i.e., new quantity) is sufficient
                    if inventory_item.quantity + change < 0: # inventory_item.quantity - abs(change)
                        raise serializers.ValidationError(
                            f"Insufficient stock for {product_name} (Size: {size}, Color: {color}). Available: {inventory_item.quantity}"
                        )
                except InventoryItem.DoesNotExist:
                    raise serializers.ValidationError(
                        f"Inventory item not found for {product_name} (Size: {size}, Color: {color})."
                    )

        return data

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        validated_data.pop("owner_mockups", None)
        validated_data.pop("owner_designs", None)

        with transaction.atomic():
            order = Order.objects.create(**validated_data)

            for item_data in items_data:
                OrderItem.objects.create(order=order, **item_data)

                # Decrement InventoryItem quantity
                product_type = item_data.get('type')
                size = item_data.get('size')
                color = item_data.get('color')

                if product_type and size and color:
                    try:
                        inventory_item = InventoryItem.objects.get(
                            product__name=product_type,
                            size=size,
                            color=color
                        )
                        if inventory_item.quantity > 0:
                            inventory_item.quantity -= 1
                            inventory_item.save()
                        else:
                            raise serializers.ValidationError(
                                f"No stock for {product_type} (Size: {size}, Color: {color})."
                            )
                    except InventoryItem.DoesNotExist:
                        print(f"Warning: Inventory item not found for {product_type}, {size}, {color}")
                        pass # Consider raising an error here if a non-existent item should prevent order creation

            # --- Calculate and set profit after all items are created ---
            self._calculate_total_cost_and_profit(order, items_data) # Pass the created order and its raw items data

            return order

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", [])
        validated_data.pop("owner_mockups", None)
        validated_data.pop("owner_designs", None)

        with transaction.atomic():
            # Update main Order fields
            for attr, value in validated_data.items():
                setattr(instance, attr, value)
            instance.save()

            # --- Handle OrderItem updates and inventory changes ---
            current_order_items = {item.id: item for item in instance.items.all()}
            updated_item_ids = {item_data.get("id") for item_data in items_data if item_data.get("id")}

            # 1. Handle deleted items: return stock to inventory
            for item_id, item in current_order_items.items():
                if item_id not in updated_item_ids:
                    try:
                        inventory_item = InventoryItem.objects.get(
                            product__name=item.type,
                            size=item.size,
                            color=item.color
                        )
                        inventory_item.quantity += 1
                        inventory_item.save()
                    except InventoryItem.DoesNotExist:
                        print(f"Warning: Inventory item not found for deleted order item: {item.type}, {item.size}, {item.color}")
                    item.delete()

            # 2. Handle created/updated items: decrement stock
            for item_data in items_data:
                item_id = item_data.get("id")
                new_type = item_data.get("type")
                new_size = item_data.get("size")
                new_color = item_data.get("color")

                if item_id:
                    existing_item = current_order_items.get(item_id)
                    if existing_item:
                        if (existing_item.type != new_type or
                            existing_item.size != new_size or
                            existing_item.color != new_color):
                            # Item details changed, return stock for old item and consume for new
                            try:
                                old_inventory_item = InventoryItem.objects.get(
                                    product__name=existing_item.type,
                                    size=existing_item.size,
                                    color=existing_item.color
                                )
                                old_inventory_item.quantity += 1
                                old_inventory_item.save()
                            except InventoryItem.DoesNotExist:
                                print(f"Warning: Old inventory item not found during update: {existing_item.type}, {existing_item.size}, {existing_item.color}")

                            try:
                                new_inventory_item = InventoryItem.objects.get(
                                    product__name=new_type,
                                    size=new_size,
                                    color=new_color
                                )
                                if new_inventory_item.quantity > 0:
                                    new_inventory_item.quantity -= 1
                                    new_inventory_item.save()
                                else:
                                     raise serializers.ValidationError(
                                        f"No stock for {new_type} (Size: {new_size}, Color: {new_color})."
                                    )
                            except InventoryItem.DoesNotExist:
                                raise serializers.ValidationError(
                                    f"Inventory item not found for {new_type} (Size: {new_size}, Color: {new_color})."
                                )

                        OrderItem.objects.filter(id=item_id, order=instance).update(**item_data)
                else:
                    # New item - decrement stock
                    try:
                        inventory_item = InventoryItem.objects.get(
                            product__name=new_type,
                            size=new_size,
                            color=new_color
                        )
                        if inventory_item.quantity > 0:
                            inventory_item.quantity -= 1
                            inventory_item.save()
                        else:
                            raise serializers.ValidationError(
                                f"No stock for {new_type} (Size: {new_size}, Color: {new_color})."
                            )
                    except InventoryItem.DoesNotExist:
                        raise serializers.ValidationError(
                            f"Inventory item not found for {new_type} (Size: {new_size}, Color: {new_color})."
                        )
                    OrderItem.objects.create(order=instance, **item_data)

            # --- Calculate and set profit after all item modifications ---
            # Use instance.items.all() to get the final state of order items
            # after all additions, deletions, and updates are processed.
            self._calculate_total_cost_and_profit(instance, instance.items.all())
            

        return instance

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        request = self.context.get("request")

        if request and request.user and request.user.is_staff:
            owner = instance.user
            mockups = Mockup.objects.filter(user=owner)
            designs = Design.objects.filter(user=owner)
            representation["owner_mockups"] = MockupSerializer(mockups, many=True, context=self.context).data
            representation["owner_designs"] = DesignSerializer(designs, many=True, context=self.context).data
        else:
            representation.pop("owner_mockups", None)
            representation.pop("owner_designs", None)

        return representation


class InventoryItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = InventoryItem
        fields = ["id", "product", "product_name", "size", "color", "quantity", "created_at", "updated_at"]
        read_only_fields = ["product_name", "created_at", "updated_at"]
        extra_kwargs = {
            "product": {"write_only": True} # Use ID for linking on create/update
        }

class InventoryProductSerializer(serializers.ModelSerializer):
    variants = InventoryItemSerializer(many=True, read_only=True)
    price = serializers.IntegerField() # Keep as IntegerField if it's an integer in your model
    class Meta:
        model = InventoryProduct
        fields = ["id", "name","price" ,"description", "image", "variants", "created_at", "updated_at"]
        read_only_fields = ["variants", "created_at", "updated_at"]

class UserProductPriceSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = UserProductPrice
        fields = ['id', 'user', 'username', 'product', 'product_name', 'custom_price']
