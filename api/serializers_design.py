"""
Serializers design for:
1. File uploads for mockups and designs
2. Enhanced order items with references to uploaded files
"""

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Order, OrderItem, Mockup, Design

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'is_staff']

class MockupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mockup
        fields = ['id', 'name', 'file', 'created_at', 'updated_at']
        read_only_fields = ['user']

class DesignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Design
        fields = ['id', 'name', 'file', 'created_at', 'updated_at']
        read_only_fields = ['user']

class OrderItemSerializer(serializers.ModelSerializer):
    # Add fields to display mockup and design information
    mockup_details = MockupSerializer(source='mockup', read_only=True)
    design_details = DesignSerializer(source='design', read_only=True)
    
    class Meta:
        model = OrderItem
        fields = ['id', 'mockup', 'design', 'size', 'color', 'created_at', 'updated_at', 
                 'mockup_details', 'design_details']

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, required=False)
    username = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = Order
        fields = ['id', 'user', 'username', 'name', 'phone', 'area', 'cod', 'price', 'status', 
                 'unique_id', 'created_at', 'updated_at', 'items']
        read_only_fields = ['unique_id', 'user']
        
    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        order = Order.objects.create(**validated_data)
        
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
            
        return order
    
    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', [])
        
        # Update order fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Handle items - this is a simple implementation
        # In a real app, you might want to handle updates more carefully
        if items_data:
            instance.items.all().delete()  # Remove existing items
            for item_data in items_data:
                OrderItem.objects.create(order=instance, **item_data)
                
        return instance
