import shutil
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from oauth2client.service_account import ServiceAccountCredentials 
import json
import requests
import json
from django.conf import settings
from .models import Order, OrderItem, Mockup, Design , InventoryItem, InventoryProduct ,  UserProductPrice
from .serializers import OrderSerializer, OrderItemSerializer, MockupSerializer, DesignSerializer, UserSerializer , InventoryItemSerializer, InventoryProductSerializer, UserProductPriceSerializer

class IsOwnerOrAdmin(permissions.BasePermission):
    
    def has_object_permission(self, request, view, obj):
        # Admin permissions
        if request.user.is_staff:
            return True

        # Check if the object has a user field directly
        if hasattr(obj, 'user'):
            return obj.user == request.user

        # For OrderItem, check the parent Order
        if isinstance(obj, OrderItem):
            return obj.order.user == request.user

        return False

class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAdminUser]

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def current(self, request):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

import django_filters
class OrderFilter(django_filters.FilterSet):
    user = django_filters.CharFilter(field_name='user__username', lookup_expr='icontains', label='Username')
    name = django_filters.CharFilter(lookup_expr='icontains')
    phone = django_filters.CharFilter(lookup_expr='icontains')
    status = django_filters.CharFilter(lookup_expr='iexact')
    unique_id = django_filters.CharFilter(lookup_expr='icontains')
    month = django_filters.CharFilter(method='filter_month')

    # NEW: Custom filter for 'month'
    def filter_month(self, queryset, name, value):
        today = timezone.now().date()
        print(int(value))
        if value:
            try:
                # Convert value to integer as month numbers are integers
                month_num = int(value)
                return queryset.filter(
                    created_at__year=today.year,
                    created_at__month=month_num
                )
            except ValueError:
                # Handle cases where value is not a valid integer (e.g., empty string)
                pass
        return queryset


    class Meta:
        model = Order
        fields = [
            'user',
            'name',
            'phone',
            'status',
            'unique_id'
            # Custom filter methods are automatically discovered,
            # so no need to list 'order_start_date', 'order_end_date', or 'month' here.
        ]

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    filter_backends = [filters.OrderingFilter , DjangoFilterBackend]
    filterset_class = OrderFilter # Ensure this is set
    ordering_fields = ['created_at', 'status', 'name', 'phone', 'unique_id']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        queryset = Order.objects.all()

        if not user.is_staff:
            queryset = queryset.filter(user=user)

        # KEEP this block if you still want the 'date' and 'specific_date' shortcuts
        # (e.g., 'today', 'yesterday', 'this_week', 'this_month').
        # These operate *before* django-filter's filters are applied.
        date_filter = self.request.query_params.get('date')
        specific_date = self.request.query_params.get('specific_date')

        if specific_date:
            try:
                date_obj = datetime.strptime(specific_date, '%Y-%m-%d').date()
                print(specific_date)
                queryset = queryset.filter(created_at__date=date_obj)
            except ValueError:
                pass
        elif date_filter:
            today = timezone.now().date()
            if date_filter == 'today':
                queryset = queryset.filter(created_at__date=today)
            elif date_filter == 'yesterday':
                queryset = queryset.filter(created_at__date=today - timedelta(days=1))
            elif date_filter == 'this_week':
                start_of_week = today - timedelta(days=today.weekday())
                queryset = queryset.filter(
                    created_at__date__gte=start_of_week,
                    created_at__date__lte=today
                )
            elif date_filter == 'this_month':
                queryset = queryset.filter(
                    created_at__year=today.year,
                    created_at__month=today.month
                )

        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        
    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAuthenticated, IsOwnerOrAdmin])
    def update_status(self, request, pk=None):
        order = self.get_object()
        new_status = request.data.get('status')
        old_status = order.status

        if not new_status:
            return Response({'error': 'Status is required'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            order.status = new_status
            order.save()

            if old_status != 'cancelled' and new_status == 'cancelled':
                order.price = 0
                order.profit = 0
                order.save()
                # If order is being cancelled, return items to inventory
                for item in order.items.all():
                    print(item)
                    try:
                        inventory_item = InventoryItem.objects.get(
                            product__name=item.type,
                            size=item.size,
                            color=item.color
                        )
                        inventory_item.quantity += 1
                        inventory_item.save()
                    except InventoryItem.DoesNotExist:
                        print(f"Warning: Inventory item not found for cancelled order item: {item.type}, {item.size}, {item.color}")

        serializer = self.get_serializer(order)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAdminUser])
    def export(self, request):
        try:
            today = datetime.now().strftime('%d-%m-%Y')
            sheet_name = f"{today}-orders"

            orders = self.get_queryset()
            exported_count = 0
            rows_to_append = []

            shipping_orders = []

            for order in orders:
                # Only process if status is 'shipped' and it hasn't been exported yet (by unique_id)
                if order.status == "shipped":
                    # Prepare order for shipping API
                    shipping_order = {
                        "note": None,  # Can be customized if needed
                        "product_note": None,  # Can be customized if needed
                        "reference_id": order.unique_id,  # Using unique_id as reference
                        "customer_area": order.areaId,
                        "customer_name": order.name,
                        "copy_total_cost": int(order.price),  # Convert to string if needed
                        "customer_mobile": order.phone,
                        "customer_address": order.area,  # Add if available in your order model
                        "customer_sub_area": None,  # Add if available in your order model
                        "second_mobile_number": None  # Add if available in your order model
                    }
                    shipping_orders.append(shipping_order)
                    order.status = "delivered"  # Change status to delivered after preparing for export
                    order.save()  # Save the status change
                    exported_count += 1

          
            # ===== SHIPPING API SUBMISSION =====
            shipping_api_success = False
            shipping_api_message = "No orders to submit to shipping company"

            if shipping_orders:
                # Prepare payload for shipping API
                payload = {
                    "context": "{\"lang\":\"en_US\",\"uid\":2}",
                    "password": "12345678",
                    "sessionId": "b59c61dea31e1f626436c91e2afe56c6272c3d3f",
                    "orders_list": shipping_orders
                }
                json_output = json.dumps(payload, indent=4)

                print(json_output)
                # Set headers for the API request
                headers = {
                    'Cookie': 'session_id=b59c61dea31e1f626436c91e2afe56c6272c3d3f; fileToken=dummy-because-api-expects-one; frontend_lang=en_US',
                    'Content-Type': 'application/json'
                }

                # Make the API request
                try:
                    shipping_api_url = "https://111hiexpress.ps/create_super_multi_orders"
                    response = requests.post(shipping_api_url, json=json_output, headers=headers)
                    # Check if the request was successful
                    if response.status_code == 200:
                        
                        shipping_api_success = True
                        shipping_api_message = f"Successfully submitted {len(shipping_orders)} orders to shipping company"

                        # You might want to parse the response for more details
                        try:
                            shipping_response_data = response.json()
                            shipping_api_message += f". Response: {shipping_response_data}"
                        except:
                            shipping_api_message += f". Raw response: {response.text[:100]}..."
                    else:
                        shipping_api_message = f"Failed to submit orders to shipping company. Status code: {response.status_code}. Response: {response.text[:100]}..."
                except Exception as e:
                    shipping_api_message = f"Error submitting orders to shipping company: {str(e)}"

            # Return combined response
            return Response({
                'success': True,
                'shipping_api': {
                    'success': shipping_api_success,
                    'message': shipping_api_message,
                    'orders_submitted': len(shipping_orders) if shipping_orders else 0
                }
            })

        except gspread.exceptions.APIError as e:
            error_message = f"Google Sheets API Error: {e.args[0].get('message', str(e))}"
            if 'PERMISSION_DENIED' in str(e):
                 error_message += ". Ensure the service account has editor access to the target Google Drive folder or spreadsheet."
            return Response({
                'success': False,
                'message': f'Failed to export orders: {error_message}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Failed to export orders: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAdminUser])
    def export_designs_by_order_date(self, request):
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')

        if not start_date_str or not end_date_str:
            return Response({'error': 'start_date and end_date are required query parameters.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({'error': 'Date format should be YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure end_date includes the entire day
        end_date = end_date + timedelta(days=1)

        # Filter orders by created_at date range
        orders = Order.objects.filter(created_at__date__gte=start_date, created_at__date__lt=end_date)

        # Create a unique folder for this export
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        export_folder_name = f"order_designs_{start_date_str}_to_{end_date_str}_{timestamp}"
        base_export_dir = os.path.join(settings.MEDIA_ROOT, 'exported_order_designs')
        destination_folder = os.path.join(base_export_dir, export_folder_name)

        os.makedirs(destination_folder, exist_ok=True)

        copied_count = 0
        for order in orders:
            for item in order.items.all():
                if item.design and item.design.file and os.path.isfile(item.design.file.path):
                    design = item.design
                    
                    # Original filename and extension
                    filename_without_ext, extension = os.path.splitext(os.path.basename(design.file.name))
                    
                    # Construct initial destination path
                    dest_path = os.path.join(destination_folder, os.path.basename(design.file.name))
                    
                    # Check if file exists and create a unique name if it does
                    counter = 1
                    while os.path.exists(dest_path):
                        new_filename = f"{filename_without_ext}_copy{counter}{extension}"
                        dest_path = os.path.join(destination_folder, new_filename)
                        counter += 1

                    try:
                        shutil.copy(design.file.path, dest_path)
                        copied_count += 1
                    except Exception as e:
                        print(f"Error copying file {filename_without_ext}{extension} for order {order.unique_id}: {str(e)}")

        if copied_count == 0:
            shutil.rmtree(destination_folder) # Clean up empty folder
            return Response({
                'success': False,
                'message': 'No designs found for the specified date range.'
            }, status=status.HTTP_404_NOT_FOUND)

        # Zip the collected designs
        zip_base_name = os.path.join(base_export_dir, export_folder_name)
        shutil.make_archive(zip_base_name, 'zip', destination_folder)

        # Clean up the unzipped folder
        shutil.rmtree(destination_folder)

        zip_url = f"{settings.MEDIA_URL}exported_order_designs/{export_folder_name}.zip"

        return Response({
            'success': True,
            'message': f'{copied_count} designs collected and zipped.',
            'zip_url': zip_url
        })

    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAdminUser])
    def sync_returns(self, request):
        
        external_api_url = "https://hiexpress.ps/web/dataset/search_read" # <--- IMPORTANT: Replace with the actual API URL
        payload = {
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "model": "rb_delivery.order",
        "domain": [
            [
                "state",
                "=",
                "completed_returned"
            ]
        ],
        "fields": [
            "web_color",
            "is_block_delivery_fee",
            "is_data_entry",
            "delivery_profit",
            "note",
            "sequence_related",
            "reference_id",
            "assign_to_business",
            "state",
            "customer_name",
            "customer_mobile",
            "assign_to_agent",
            "customer_area",
            "customer_address",
            "create_date",
            "first_delivery_attempt_date",
            "write_date",
            "required_from_business",
            "required_to_company",
            "delivery_cost",
            "money_collection_cost",
            "business_state"
        ],
        
        "sort": "",
        "context": {
            "lang": "ar_SY",
            "tz": "Asia/Jerusalem",
            "uid": 7227
        }
    },
    "id": 69987485
}
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Cookie': 'session_id=b59c61dea31e1f626436c91e2afe56c6272c3d3f; Expires=Mon, 08-Sep-2025 14:03:53 GMT; Max-Age=7776000; HttpOnly; Path=/;SameSite=None; Secure',
        }
        
        try:
            response = requests.post(external_api_url, json=payload, headers=headers)
            response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
            external_api_response_data = response.json()
            external_returns_data = external_api_response_data.get('result', {}).get('records', [])
            print(external_returns_data)
        except requests.exceptions.RequestException as e:
            return Response(
                {'error': f"Failed to fetch return data from external API: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except ValueError: # Catches JSONDecodeError if response is not valid JSON
            return Response(
                {'error': "External API returned invalid JSON."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        updated_count = 0
        skipped_count = 0
        errors_during_update = []

        if not isinstance(external_returns_data, list):
            return Response(
                {'error': "Expected a list of returns from external API, but got a different format."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Get all unique_ids from your database for efficient lookup
        # This prevents N+1 queries inside the loop
        existing_order_unique_ids = set(Order.objects.values_list('unique_id', flat=True))

        for return_entry in external_returns_data:
            external_order_unique_id = return_entry.get('reference_id')
            print(external_order_unique_id)
            if not external_order_unique_id:
                errors_during_update.append(f"Skipped return entry due to missing 'unique_id': {return_entry}")
                skipped_count += 1
                continue

            # Check if this unique_id actually exists in your system to avoid unnecessary DB calls
            if external_order_unique_id not in existing_order_unique_ids:
                skipped_count += 1
                continue # No matching order in our database

            try:
                # Use select_for_update to lock the row during the transaction
                # if you expect concurrent updates.
                with transaction.atomic():
                    order = Order.objects.select_for_update().get(unique_id=external_order_unique_id)
                    
                  
                    if order.status != 'returned':
                        old_status = order.status
                        order.profit = 0
                        new_profit = 0
                        order.status = 'returned'
                        for item in order.items.all():
                            inventory_Product = InventoryProduct.objects.get(name=item.type,)
                            try:
                                inventory_product2 = UserProductPrice.objects.get(user=order.user, product=inventory_Product)
                                new_profit -= inventory_product2.custom_price
                            except UserProductPrice.DoesNotExist:
                            
                                try:
                                    
                                    new_profit-= inventory_Product.price
                                except InventoryProduct.DoesNotExist:
                                    print(f"Warning: Inventory item not found for cancelled order item: {item.type}, {item.size}, {item.color}")

                        order.profit = new_profit
                        order.price = 0
                        order.save()
                        updated_count += 1

                    else:
                        skipped_count += 1 # Already returned, no update needed

            except Order.DoesNotExist:
                # This case should be mostly covered by the initial unique_id check,
                # but good to keep for robustness (e.g., race conditions).
                errors_during_update.append(f"Order with unique_id {external_order_unique_id} not found in database.")
                skipped_count += 1
            except Exception as e:
                errors_during_update.append(f"Error updating order {external_order_unique_id}: {str(e)}")
                skipped_count += 1

        return Response({
            'message': 'Return synchronization process completed.',
            'updated_orders': updated_count,
            'skipped_orders': skipped_count,
            'errors': errors_during_update,
            'total_external_returns_processed': len(external_returns_data)
        }, status=status.HTTP_200_OK)





class OrderItemViewSet(viewsets.ModelViewSet):
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user

        if user.is_staff:
            return OrderItem.objects.all()

        return OrderItem.objects.filter(order__user=user)

class MockupViewSet(viewsets.ModelViewSet):
    serializer_class = MockupSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user

        if user.is_staff:
            return Mockup.objects.all()

        return Mockup.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class DesignViewSet(viewsets.ModelViewSet):
    serializer_class = DesignSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user

        if user.is_staff:
            return Design.objects.all()

        return Design.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
    
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def collect_designs(self, request):
        today_str = timezone.now().strftime('%Y-%m-%d')
        base_folder = os.path.join(settings.MEDIA_ROOT, 'collected_designs')
        destination_folder = os.path.join(base_folder, today_str)

        os.makedirs(destination_folder, exist_ok=True)

        # Filter designs for the current day
        designs = Design.objects.filter(created_at__date=timezone.now().date())
        print(timezone.now().date())
        copied_count = 0
        for design in designs:
            if design.file and os.path.isfile(design.file.path):
                filename = os.path.basename(design.file.name)
                dest_path = os.path.join(destination_folder, filename)

                try:
                    shutil.copy(design.file.path, dest_path)
                    copied_count += 1
                except Exception as e:
                    print(f"Error copying file {filename}: {str(e)}")
        zip_filename = f"{destination_folder}.zip"
        shutil.make_archive(destination_folder, 'zip', destination_folder)
        return Response({
            'success': True,
            'message': f'{copied_count} designs copied to {destination_folder}',
            'zip_url': f"http://localhost:8000/media/collected_designs/{today_str}.zip"
        })

class InventoryProductViewSet(viewsets.ModelViewSet):
    queryset = InventoryProduct.objects.all()
    serializer_class = InventoryProductSerializer
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.AllowAny]
        else:
            permission_classes = [permissions.IsAdminUser]
        return [permission() for permission in permission_classes]
    
class InventoryItemViewSet(viewsets.ModelViewSet):
    queryset = InventoryItem.objects.all()
    serializer_class = InventoryItemSerializer
    permission_classes = [permissions.IsAdminUser] # Only admin can manage inventory items
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['product__name', 'size', 'color']
    ordering_fields = ['product__name', 'size', 'color', 'quantity', 'updated_at']
    ordering = ['product__name', 'size', 'color']

    

class UserProductPriceViewSet(viewsets.ModelViewSet):
    queryset = UserProductPrice.objects.all()
    serializer_class = UserProductPriceSerializer
    permission_classes = [permissions.IsAdminUser]  
