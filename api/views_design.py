"""
API views design for:
1. Admin order status update
2. Specific date filtering
3. File upload endpoints for mockups and designs
4. Reusable assets management
"""

from rest_framework import viewsets, permissions, status, generics, filters
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.db.models import Q
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Order, OrderItem, Mockup, Design
from .serializers import (
    UserSerializer, OrderSerializer, OrderItemSerializer,
    MockupSerializer, DesignSerializer
)

# Authentication views remain the same
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    
    def create(self, request, *args, **kwargs):
        data = request.data
        
        # Check if username already exists
        if User.objects.filter(username=data.get('username')).exists():
            return Response({'error': 'Username already exists'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Create user
        user = User.objects.create(
            username=data.get('username'),
            email=data.get('email', ''),
            password=make_password(data.get('password')),
            is_staff=data.get('is_admin', False)
        )
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }, status=status.HTTP_201_CREATED)

class CustomTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        if response.status_code == 200:
            user = User.objects.get(username=request.data.get('username'))
            response.data['user'] = UserSerializer(user).data
            
        return response

@api_view(['GET'])
def get_user(request):
    return Response(UserSerializer(request.user).data)

# Enhanced Order views with specific date filtering and status update
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    
    def get_queryset(self):
        user = self.request.user
        
        # Base queryset - admins see all orders, regular users see only their orders
        if user.is_staff:
            queryset = Order.objects.all()
        else:
            queryset = Order.objects.filter(user=user)
            
        # Apply date filtering if specified
        date_filter = self.request.query_params.get('date', None)
        specific_date = self.request.query_params.get('specific_date', None)
        
        if specific_date:
            try:
                # Parse the specific date (format: YYYY-MM-DD)
                specific_date = datetime.strptime(specific_date, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date=specific_date)
            except ValueError:
                # If date format is invalid, ignore the filter
                pass
        elif date_filter:
            today = timezone.now().date()
            
            if date_filter == 'today':
                queryset = queryset.filter(created_at__date=today)
            elif date_filter == 'yesterday':
                yesterday = today - timedelta(days=1)
                queryset = queryset.filter(created_at__date=yesterday)
            elif date_filter == 'this_week':
                start_of_week = today - timedelta(days=today.weekday())
                queryset = queryset.filter(created_at__date__gte=start_of_week)
            elif date_filter == 'this_month':
                queryset = queryset.filter(created_at__month=today.month, created_at__year=today.year)
                
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    # Add a dedicated endpoint for updating order status
    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get('status')
        
        if not new_status:
            return Response({'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if new_status not in dict(Order.STATUS_CHOICES).keys():
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        
        order.status = new_status
        order.save()
        
        return Response(OrderSerializer(order).data)

# New viewsets for Mockup and Design models
class MockupViewSet(viewsets.ModelViewSet):
    serializer_class = MockupSerializer
    parser_classes = (MultiPartParser, FormParser)
    
    def get_queryset(self):
        return Mockup.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class DesignViewSet(viewsets.ModelViewSet):
    serializer_class = DesignSerializer
    parser_classes = (MultiPartParser, FormParser)
    
    def get_queryset(self):
        return Design.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
