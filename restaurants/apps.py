from django.apps import AppConfig


class RestaurantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'restaurants'

    def ready(self):
        from .tasks import hourly_check_and_schedule
        print("Scheduling hourly check for weekly payments")
        hourly_check_and_schedule(repeat=60*60)  # Repeat every hour
        print("Hourly check for weekly payments scheduled")