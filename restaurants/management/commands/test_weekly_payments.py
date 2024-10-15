from django.core.management.base import BaseCommand
from restaurants.tasks import process_unpaid_sales, schedule_weekly_transfer
from django.utils import timezone
import pytz

class Command(BaseCommand):
    help = 'Test the weekly payment tasks'

    def handle(self, *args, **options):
        self.stdout.write("Running hourly check...")
        
        # Directly execute the content of hourly_check_and_schedule
        print("\n--- Hourly Check Starting ---")
        print(f"Current time: {timezone.now()}")
        process_unpaid_sales(test_mode=True)
        
        adelaide_tz = pytz.timezone('Australia/Adelaide')
        now = timezone.localtime(timezone.now(), adelaide_tz)
        
        print(f"Current day in Adelaide: {now.strftime('%A')}")
        if now.weekday() == 6:  # Sunday
            next_monday_7am = now.replace(hour=7, minute=0, second=0, microsecond=0) + timezone.timedelta(days=1)
            print(f"It's Sunday. Weekly transfer would be scheduled for {next_monday_7am}")
        else:
            print("Not Sunday, no need to schedule weekly transfer")
        print("--- Hourly Check Completed ---\n")
        
        self.stdout.write("\nRunning weekly transfer (this would normally run on Monday at 7 AM)...")
        schedule_weekly_transfer(test_mode=True)
        
        self.stdout.write(self.style.SUCCESS("\nTest completed. Check the output above for results."))