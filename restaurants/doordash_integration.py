import base64
import jwt
import time
import logging
from django.conf import settings
import requests
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

logger = logging.getLogger(__name__)

def check_delivery_distance(restaurant_address, delivery_address, max_retries=3, timeout=5):
    geolocator = Nominatim(user_agent="restaurants", timeout=timeout)
    
    def do_geocode(address):
        for _ in range(max_retries):
            try:
                return geolocator.geocode(address)
            except GeocoderTimedOut:
                logger.warning(f"Geocoding request timed out. Retrying...")
            except Exception as e:
                logger.error(f"Error in geocoding: {e}")
                return None
        logger.error(f"Failed to geocode after {max_retries} attempts")
        return None

    try:
        restaurant_location = do_geocode(restaurant_address)
        delivery_location = do_geocode(delivery_address)
        
        if restaurant_location and delivery_location:
            restaurant_coords = (restaurant_location.latitude, restaurant_location.longitude)
            delivery_coords = (delivery_location.latitude, delivery_location.longitude)
            
            distance = geodesic(restaurant_coords, delivery_coords).miles
            
            max_distance = 10  # DoorDash's official 10-mile limit
            within_range = distance <= max_distance
            
            logger.info(f"Distance: {distance:.2f} miles, Within range: {within_range}")
            return distance, within_range
        else:
            logger.error("Could not geocode one or both addresses")
            return None, False
    except Exception as e:
        logger.error(f"Error in distance check: {e}")
        return None, False


def generate_doordash_jwt():
    current_time = int(time.time())
    payload = {
        'aud': 'doordash',
        'iat': current_time,
        'exp': current_time + 30 * 60,
        'iss': settings.DOORDASH_DEVELOPER_ID,
        'kid': settings.DOORDASH_KEY_ID,
    }
    signing_secret = base64.urlsafe_b64decode(settings.DOORDASH_SIGNING_SECRET_KEY + '==')
    headers = {'dd-ver': 'DD-JWT-V1'}
    return jwt.encode(payload, signing_secret, algorithm='HS256', headers=headers)



def create_doordash_business(restaurant):
    jwt_token = generate_doordash_jwt()
    url = "https://openapi.doordash.com/developer/v1/businesses"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "external_business_id": f"restaurant-{restaurant.id}",
        "name": restaurant.name,
        "description": restaurant.description[:100] if restaurant.description else None,  # Truncate to 100 chars if needed
        "activation_status": "active"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        business_data = response.json()
        logger.info(f"DoorDash business created successfully for restaurant {restaurant.id}")
        return True, business_data
    except requests.exceptions.RequestException as e:
        error_msg = f"DoorDash API error creating business: {str(e)}"
        if e.response is not None:
            error_msg += f" Response: {e.response.text}"
        logger.error(error_msg)
        return False, error_msg

def create_doordash_store(restaurant):
    jwt_token = generate_doordash_jwt()
    url = f"https://openapi.doordash.com/developer/v1/businesses/restaurant-{restaurant.id}/stores"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "external_store_id": f"store-{restaurant.id}",
        "name": restaurant.name,
        "phone_number": restaurant.phone,
        "address": restaurant.address
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        store_data = response.json()
        logger.info(f"DoorDash store created successfully for restaurant {restaurant.id}")
        return True, store_data
    except requests.exceptions.RequestException as e:
        error_msg = f"DoorDash API error creating store: {str(e)}"
        if e.response is not None:
            error_msg += f" Response: {e.response.text}"
        logger.error(error_msg)
        return False, error_msg

def create_doordash_order(order):
    if not check_delivery_distance(order.restaurant.address, order.delivery_location):
        logger.error(f"Delivery distance exceeds limit or could not be determined for order {order.id}")
        return False, "Delivery distance exceeds limit or could not be determined"

    if order.doordash_delivery_id:
        logger.info(f"DoorDash delivery already exists for order {order.id}")
        return False, f"Delivery already exists with ID: {order.doordash_delivery_id}"
    
    restaurant_address = order.restaurant.address
    delivery_address = order.delivery_location
    
    distance, within_range = check_delivery_distance(restaurant_address, delivery_address)
    
    logger.info(f"Order {order.id}: Distance = {distance:.2f} miles, Within range: {within_range}")
    
    if not within_range:
        logger.error(f"Delivery distance ({distance:.2f} miles) exceeds DoorDash's 10-mile limit for order {order.id}")
        return False, "Delivery distance exceeds DoorDash's 10-mile limit"

    jwt_token = generate_doordash_jwt()
    url = "https://openapi.doordash.com/drive/v2/deliveries"
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json"
    }

    items = []
    for order_item in order.items.all():
        item = {
            "name": order_item.menu_item.name,
            "quantity": order_item.quantity,
            "description": order_item.menu_item.description[:50] if order_item.menu_item.description else None,
            "price": int(order_item.price * 100)  # Convert to cents
        }
        items.append(item)

    payload = {
        "external_delivery_id": str(order.id),
        "pickup_address": order.restaurant.address,
        "pickup_business_name": order.restaurant.name,
        "pickup_phone_number": order.restaurant.phone,
        "pickup_external_business_id": f"restaurant-{order.restaurant.id}",
        "pickup_external_store_id": f"store-{order.restaurant.id}",
        "dropoff_address": order.delivery_location,
        "dropoff_business_name": order.user.get_full_name() if order.user else "Guest",
        "dropoff_phone_number": order.user.phone if order.user else order.guest_phone,
        "order_value": int(order.total_price * 100),
        "items": items
    }

    logger.info(f"Sending request to DoorDash API: {url}")
    logger.debug(f"Payload: {payload}")

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        doordash_data = response.json()
        logger.info(f"DoorDash delivery created successfully. Delivery ID: {doordash_data.get('external_delivery_id')}")
        
        # Update the order with the DoorDash delivery ID
        order.doordash_delivery_id = doordash_data.get('external_delivery_id')
        order.save()
        
        return True, doordash_data
    except requests.exceptions.RequestException as e:
        error_msg = f"DoorDash API error: {str(e)}"
        if e.response is not None:
            error_msg += f" Response: {e.response.text}"
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error in create_doordash_order: {str(e)}"
        logger.error(error_msg)
        return False, error_msg

def setup_doordash_integration(restaurant):
    # Create business
    business_success, business_result = create_doordash_business(restaurant)
    if not business_success:
        logger.error(f"Failed to create DoorDash business for restaurant {restaurant.id}: {business_result}")
        return False

    # Create store
    store_success, store_result = create_doordash_store(restaurant)
    if not store_success:
        logger.error(f"Failed to create DoorDash store for restaurant {restaurant.id}: {store_result}")
        return False

    logger.info(f"DoorDash integration setup completed successfully for restaurant {restaurant.id}")
    return True