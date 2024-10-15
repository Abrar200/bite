# In a new file: restaurants/management/commands/update_menu_item_points.py

from django.core.management.base import BaseCommand
from restaurants.models import MenuItem

class Command(BaseCommand):
    help = 'Updates points prices for all menu items based on their restaurant\'s loyalty program'

    def handle(self, *args, **options):
        menu_items = MenuItem.objects.all()
        updated_count = 0

        for item in menu_items:
            old_points_price = item.points_price
            item.points_price = item.calculate_points_price()
            if item.points_price != old_points_price:
                item.save()
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} menu items'))