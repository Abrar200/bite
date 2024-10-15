from twilio.rest import Client
from django.conf import settings
import re
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

def format_phone_number(phone_number):
    # Remove any non-digit characters
    digits_only = re.sub(r'\D', '', phone_number)
    
    # Check if it's an Australian number
    if len(digits_only) == 10 and digits_only.startswith('0'):
        # Convert to international format
        return '+61' + digits_only[1:]
    elif len(digits_only) == 9:
        # Assume it's an Australian number without the leading 0
        return '+61' + digits_only
    elif digits_only.startswith('61'):
        # Already in international format
        return '+' + digits_only
    else:
        # If it doesn't match expected formats, return as is
        return phone_number

def send_sms(to_number, message):
    client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    
    # Format the phone number
    formatted_number = format_phone_number(to_number)
    
    try:
        message = client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=formatted_number
        )
        return True, message.sid
    except Exception as e:
        return False, str(e)


def send_order_ready_notification(order):
    with transaction.atomic():
        # Refresh the order from the database to get the latest state
        order.refresh_from_db()
        
        # Check if SMS has already been sent
        if order.sms_sent:
            logger.info(f"SMS already sent for order {order.id}. Skipping.")
            return False, "SMS already sent"

        phone_number = order.user.phone if order.user else order.guest_phone
        restaurant_name = order.restaurant.name
        order_type = order.get_order_type_display()
        
        message = f"Your {order_type} order from {restaurant_name} is ready! "
        
        if order.order_type == 'PICKUP':
            message += "Please come and collect it at your convenience."
        elif order.order_type == 'DELIVERY':
            message += "Our delivery partner will pick it up shortly and bring it to you."
        
        success, result = send_sms(phone_number, message)
        
        if success:
            logger.info(f"SMS sent successfully to {phone_number}. Message SID: {result}")
            # Update the sms_sent flag only if SMS was actually sent
            order.sms_sent = True
            order.save()
        else:
            logger.error(f"Failed to send SMS to {phone_number}. Error: {result}")

        return success, result