from django.utils import timezone
from .models import Order, WeeklySales, Restaurant
from .doordash_integration import create_doordash_order
from .sms_sender import send_order_ready_notification
from background_task import background
from django.db import transaction
import stripe
from celery import shared_task
import stripe
from django.conf import settings
import logging
from datetime import time, timedelta
import pytz

logger = logging.getLogger(__name__)


@background(schedule=60)
@shared_task
def create_delivery_task(order_id):
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order_id)
            
            if order.doordash_delivery_id or order.sms_sent:
                logger.info(f"Delivery already created or SMS already sent for order {order_id}. Skipping.")
                return

            # Create DoorDash delivery
            success, result = create_doordash_order(order)
            
            if success:
                logger.info(f"DoorDash delivery created successfully for order {order_id}")
                # If DoorDash delivery was created successfully, send SMS notification
                sms_success, sms_result = send_order_ready_notification(order)
                if sms_success:
                    order.sms_sent = True
                    order.save()
                    logger.info(f"SMS notification sent successfully for order {order_id}")
                else:
                    logger.error(f"Failed to send SMS notification for order {order_id}. Error: {sms_result}")
            else:
                logger.error(f"Failed to create DoorDash delivery for order {order_id}. Error: {result}")
                
    except Order.DoesNotExist:
        logger.error(f"Order with id {order_id} does not exist")
    except Exception as e:
        logger.error(f"Unexpected error in create_delivery_task for order {order_id}: {str(e)}")

@background(schedule=60)
def send_pickup_notification_task(order_id):
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order_id)
            if order.status == 'READY' and order.order_type in ['PICKUP', 'TAKEOUT'] and not order.sms_sent:
                success, result = send_order_ready_notification(order)
                if success:
                    order.sms_sent = True
                    order.save()
                    print(f"SMS sent successfully for Order {order.id}")
                else:
                    print(f"Failed to send SMS for Order {order.id}: {result}")
            else:
                print(f"Skipping SMS for Order {order.id}: Status={order.status}, Type={order.order_type}, SMS sent={order.sms_sent}")
    except Order.DoesNotExist:
        print(f"Order {order_id} not found")
    except Exception as e:
        print(f"Error sending pickup notification for order {order_id}: {str(e)}")


stripe.api_key = settings.STRIPE_SECRET_KEY


def process_unpaid_sales(test_mode=False):
    print("\n--- Processing Unpaid Sales ---")
    adelaide_tz = pytz.timezone('Australia/Adelaide')
    now = timezone.localtime(timezone.now(), adelaide_tz)
    print(f"Current time: {now}")
    
    # Get all unpaid weekly sales up to yesterday
    yesterday = now.date() - timedelta(days=1)
    unpaid_sales = WeeklySales.objects.filter(
        week_end__lte=yesterday,
        is_paid=False
    ).select_related('restaurant')

    print(f"Found {unpaid_sales.count()} unpaid sales")

    for sale in unpaid_sales:
        print(f"\nProcessing payment for restaurant: {sale.restaurant.name}")
        print(f"Week: {sale.week_start} to {sale.week_end}")
        print(f"Total sales: ${sale.total_sales}")
        print(f"Stripe account ID: {sale.restaurant.stripe_account_id}")

        if not sale.restaurant.stripe_account_id:
            print(f"Error: No Stripe account ID for {sale.restaurant.name}")
            continue

        if sale.total_sales <= 0:
            print(f"Skipping transfer for {sale.restaurant.name} due to zero or negative sales")
            continue

        if not test_mode:
            try:
                transfer = stripe.Transfer.create(
                    amount=int(sale.total_sales * 100),  # Convert to cents
                    currency="aud",
                    destination=sale.restaurant.stripe_account_id,
                    description=f"Weekly sales transfer for {sale.week_start} to {sale.week_end}",
                )
                sale.stripe_transfer_id = transfer.id
                sale.is_paid = True
                sale.save()
                print(f"Successfully processed payment for {sale.restaurant.name}")
            except stripe.error.StripeError as e:
                print(f"Stripe error processing payment for {sale.restaurant.name}: {str(e)}")
            except Exception as e:
                print(f"Unexpected error processing payment for {sale.restaurant.name}: {str(e)}")
        else:
            print("Test mode: Payment would be processed here")

    print("--- Finished Processing Unpaid Sales ---\n")

@background(schedule=60*60)  # Run every hour
def hourly_check_and_schedule(test_mode=False):
    print("\n--- Hourly Check Starting ---")
    print(f"Current time: {timezone.now()}")
    process_unpaid_sales(test_mode)  # Process any unpaid sales immediately
    
    adelaide_tz = pytz.timezone('Australia/Adelaide')
    now = timezone.localtime(timezone.now(), adelaide_tz)
    
    print(f"Current day in Adelaide: {now.strftime('%A')}")
    # If it's Sunday, schedule the transfer for tomorrow (Monday) at 7 AM
    if now.weekday() == 6:  # Sunday
        next_monday_7am = now.replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if not test_mode:
            schedule_weekly_transfer(schedule=next_monday_7am)
        print(f"Scheduled weekly transfer for {next_monday_7am}")
    else:
        print("Not Sunday, no need to schedule weekly transfer")
    print("--- Hourly Check Completed ---\n")

@background(schedule=60*60*24*7)  # Run weekly
def schedule_weekly_transfer(test_mode=False):
    print("\n--- Weekly Transfer Starting ---")
    adelaide_tz = pytz.timezone('Australia/Adelaide')
    now = timezone.localtime(timezone.now(), adelaide_tz)
    print(f"Current time: {now}")
    
    # Process last week's sales
    last_week_end = now.date() - timedelta(days=1)
    last_week_start = last_week_end - timedelta(days=6)
    
    print(f"Processing sales for week: {last_week_start} to {last_week_end}")
    
    weekly_sales = WeeklySales.objects.filter(
        week_start=last_week_start,
        week_end=last_week_end,
        is_paid=False
    ).select_related('restaurant')

    print(f"Found {weekly_sales.count()} unpaid weekly sales")

    for sale in weekly_sales:
        print(f"\nProcessing scheduled payment for restaurant: {sale.restaurant.name}")
        print(f"Total sales: ${sale.total_sales}")
        print(f"Stripe account ID: {sale.restaurant.stripe_account_id}")

        if not sale.restaurant.stripe_account_id:
            print(f"Error: No Stripe account ID for {sale.restaurant.name}")
            continue

        if sale.total_sales <= 0:
            print(f"Skipping transfer for {sale.restaurant.name} due to zero or negative sales")
            continue

        if not test_mode:
            try:
                transfer = stripe.Transfer.create(
                    amount=int(sale.total_sales * 100),  # Convert to cents
                    currency="aud",
                    destination=sale.restaurant.stripe_account_id,
                    description=f"Weekly sales transfer for {sale.week_start} to {sale.week_end}",
                )
                sale.stripe_transfer_id = transfer.id
                sale.is_paid = True
                sale.save()
                print(f"Successfully processed scheduled payment for {sale.restaurant.name}")
            except stripe.error.StripeError as e:
                print(f"Stripe error processing scheduled payment for {sale.restaurant.name}: {str(e)}")
            except Exception as e:
                print(f"Unexpected error processing scheduled payment for {sale.restaurant.name}: {str(e)}")
        else:
            print("Test mode: Payment would be processed here")

    # Create new WeeklySales objects for the current week
    current_week_start = now.date() - timedelta(days=now.weekday())
    current_week_end = current_week_start + timedelta(days=6)
    new_sales_created = 0
    for restaurant in Restaurant.objects.all():
        _, created = WeeklySales.objects.get_or_create(
            restaurant=restaurant,
            week_start=current_week_start,
            week_end=current_week_end
        )
        if created:
            new_sales_created += 1
    print(f"Created {new_sales_created} new WeeklySales objects for the current week")
    print("--- Weekly Transfer Completed ---\n")