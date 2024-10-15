import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.apps import apps
from channels.layers import get_channel_layer
from channels.db import database_sync_to_async

class OrderNotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.restaurant_slug = self.scope['url_route']['kwargs']['restaurant_slug']
        self.user = self.scope["user"]
        
        if not self.user.is_authenticated or not await self.is_restaurant_admin():
            await self.close()
            return

        self.room_group_name = f'orders_{self.restaurant_slug}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    @database_sync_to_async
    def is_restaurant_admin(self):
        return self.user.is_restaurant_admin and self.user.restaurant.slug == self.restaurant_slug

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        text_data_json = json.loads(text_data)
        message = text_data_json['message']

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'order_notification',
                'message': message
            }
        )

    async def order_notification(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'message': message
        }))

    async def new_order_notification(self, event):
        order_id = event['order_id']
        await self.send(text_data=json.dumps({
            'message': {
                'status': 'new_order',
                'order_id': order_id
            }
        }))

    @property
    def Restaurant(self):
        return apps.get_model('restaurants', 'Restaurant')

    @property
    def Order(self):
        return apps.get_model('restaurants', 'Order')

    @property
    def OrderNotification(self):
        return apps.get_model('restaurants', 'OrderNotification')

async def send_order_notification(order):
    channel_layer = get_channel_layer()
    await channel_layer.group_send(
        f'orders_{order.restaurant.slug}',
        {
            'type': 'new_order_notification',
            'order_id': order.id,
        }
    )