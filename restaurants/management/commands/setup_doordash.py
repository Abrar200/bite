from django.core.management.base import BaseCommand
from django.db import transaction
from restaurants.models import Restaurant
from restaurants.doordash_integration import setup_doordash_integration
import time

class Command(BaseCommand):
    help = 'Set up DoorDash integration for all existing restaurants'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run the command without making any changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        restaurants = Restaurant.objects.filter(doordash_external_business_id__isnull=True)
        total = restaurants.count()
        
        self.stdout.write(f"Found {total} restaurants to set up with DoorDash.")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: No changes will be made."))

        for index, restaurant in enumerate(restaurants, start=1):
            self.stdout.write(f"Processing restaurant {index}/{total}: {restaurant.name}")
            
            try:
                with transaction.atomic():
                    if not dry_run:
                        success = setup_doordash_integration(restaurant)
                        if success:
                            restaurant.save()  # Save the restaurant to persist the new DoorDash IDs
                            self.stdout.write(self.style.SUCCESS(f"Successfully set up DoorDash for {restaurant.name}"))
                        else:
                            self.stdout.write(self.style.ERROR(f"Failed to set up DoorDash for {restaurant.name}"))
                    else:
                        self.stdout.write(f"Would set up DoorDash for {restaurant.name}")
                    
                    # Add a small delay to avoid hitting API rate limits
                    time.sleep(1)
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing {restaurant.name}: {str(e)}"))

        if dry_run:
            self.stdout.write(self.style.SUCCESS("Dry run completed. No changes were made."))
        else:
            self.stdout.write(self.style.SUCCESS("DoorDash setup process completed."))