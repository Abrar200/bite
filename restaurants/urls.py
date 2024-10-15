from django.urls import path
from . import views
from .views import (
    restaurant_registration_view, user_registration_view, login_view, logout_view, 
    email_verification_view, stripe_payment_view, CustomPasswordResetView, CustomPasswordResetConfirmView,
    restaurant_dashboard, add_menu, add_menu_item, add_modifier
)
from django.contrib.auth import views as auth_views
from .stripe_webhook import stripe_webhook
from .consumers import OrderNotificationConsumer
from django.urls import re_path


urlpatterns = [
    path('register/restaurant/', restaurant_registration_view, name='restaurant_registration'),
    path('register/user/<slug:restaurant_slug>/', user_registration_view, name='user_registration'),
    path('login/<slug:restaurant_slug>/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('verify-email/<uidb64>/<token>/', email_verification_view, name='email_verification'),
    path('stripe-payment/<int:restaurant_id>/', stripe_payment_view, name='stripe_payment'),
    path('restaurant/<slug:slug>/', views.restaurant_landing_page_view, name='restaurant_landing_page'),
    path('password-reset/<slug:restaurant_slug>/', CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset-done/<slug:restaurant_slug>/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset-confirm/<slug:restaurant_slug>/<uidb64>/<token>/', CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset-complete/<slug:restaurant_slug>/', auth_views.PasswordResetCompleteView.as_view(template_name='restaurants/password_reset_complete.html'), name='password_reset_complete'),
    path('restaurant/<slug:slug>/', views.restaurant_landing_page_view, name='restaurant_landing_page'),
    path('restaurant/<slug:slug>/dashboard/', restaurant_dashboard, name='restaurant_dashboard'),
    path('restaurant/<slug:slug>/add-menu/', add_menu, name='add_menu'),
    path('restaurant/<slug:slug>/add-menu-item/<int:menu_id>/', add_menu_item, name='add_menu_item'),
    path('restaurant/<slug:slug>/add-modifier/<int:menu_item_id>/', add_modifier, name='add_modifier'),
    path('restaurant/<slug:restaurant_slug>/menu-item/<int:item_id>/', views.menu_item_detail, name='menu_item_detail'),
    path('restaurant/<slug:slug>/add-to-cart/<int:menu_item_id>/', views.add_to_cart_view, name='add_to_cart'),
    path('restaurant/<slug:slug>/guest-checkout/', views.guest_checkout_view, name='guest_checkout'),
    path('restaurant/<slug:slug>/cart/', views.cart_view, name='cart_view'),
    path('post-subscription/<slug:slug>/', views.post_subscription, name='post_subscription'),
    path('restaurant/<slug:slug>/create-checkout-session/', views.create_checkout_session, name='create_checkout_session'),
    path('restaurant/<slug:slug>/payment-success/', views.payment_success, name='payment_success'),
    path('restaurant/<slug:slug>/payment-cancel/', views.payment_cancel, name='payment_cancel'),
    path('order-confirmation/<int:order_id>/', views.order_confirmation, name='order_confirmation'),
    path('restaurant/<slug:slug>/dashboard/', views.restaurant_dashboard, name='restaurant_dashboard'),
    path('restaurant/<slug:slug>/order/<int:order_id>/', views.order_detail, name='order_detail'),
    path('restaurant/<slug:slug>/order/<int:order_id>/accept/', views.accept_order, name='accept_order'),
    path('restaurant/<slug:slug>/order/<int:order_id>/mark-as-ready/', views.mark_order_as_ready, name='mark_order_as_ready'),
    path('restaurant/<slug:slug>/check-delivery-distance/', views.check_delivery_distance_view, name='check_delivery_distance'),
    path('restaurant/<slug:slug>/order-partial/<int:order_id>/', views.order_partial_view, name='order_partial'),
    path('restaurant/<slug:slug>/loyalty-program-setup/', views.loyalty_program_setup, name='loyalty_program_setup'),
    path('restaurant/<slug:slug>/digital-loyalty-card-setup/', views.digital_loyalty_card_setup, name='digital_loyalty_card_setup'),
    path('restaurant/<slug:slug>/user-rewards/', views.user_rewards, name='user_rewards'),
    path('restaurant/<slug:slug>/redeem-points/', views.redeem_points, name='redeem_points'),
    path('restaurant/<slug:slug>/redeem-digital-card/', views.redeem_digital_card, name='redeem_digital_card'),
    path('restaurant/<slug:slug>/redeem-free-item/<int:digital_card_id>/', views.redeem_free_item, name='redeem_free_item'),
    path('restaurant/<slug:slug>/confirm-redeem-digital-card/', views.confirm_redeem_digital_card, name='confirm_redeem_digital_card'),
    path('restaurant/<slug:slug>/redeem-free-item-by-points/<int:menu_item_id>/', views.redeem_free_item_by_menu_item, name='redeem_free_item_by_menu_item'),
    path('restaurant/<slug:slug>/confirm-redeem-by-points/', views.confirm_redeem_by_points, name='confirm_redeem_by_points'),
    path('restaurant/<slug:slug>/order/<int:order_id>/receipt/', views.generate_order_receipt_pdf, name='order_receipt_pdf'),
    path('restaurant/<slug:slug>/weekly-sales-report/<str:week_start>/', views.weekly_sales_report, name='weekly_sales_report'),
    path('restaurant/<slug:slug>/send-sms/', views.send_sms_to_subscribers, name='send_sms_to_subscribers'),
    path('restaurant/<slug:slug>/check-availability/', views.check_restaurant_availability, name='check_restaurant_availability'),
]

websocket_urlpatterns = [
    re_path(r'ws/orders/(?P<restaurant_slug>[\w-]+)/$', OrderNotificationConsumer.as_asgi()),
]