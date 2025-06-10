from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import views_design
router = DefaultRouter()
router.register(r'orders', views.OrderViewSet, basename='order')
router.register(r'mockups', views.MockupViewSet, basename='mockup')
router.register(r'designs', views.DesignViewSet, basename='design')
router.register(r'inventory-products', views.InventoryProductViewSet, basename='inventoryproduct')
router.register(r'inventory-items', views.InventoryItemViewSet, basename='inventoryitem')
# router.register(r'users', views.UserViewSet, basename='user') # Optional: If admin needs user management via API

urlpatterns = [
    path('', include(router.urls)),
    # Commenting out potentially unimplemented auth views to fix migration error
    path('auth/register/', views_design.RegisterView.as_view(), name='register'),
    path('auth/login/', views_design.CustomTokenObtainPairView.as_view(), name='login'),
    path('auth/user/', views_design.get_user, name='user'),
    # Assuming default DRF token auth or session auth is handled elsewhere
]
